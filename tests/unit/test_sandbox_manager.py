"""nous.services.sandbox_manager の unit テスト。

docker は実行しない。``_docker`` を FakeDocker に差し替えて引数組み立てと
エラー経路だけを見る。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nous.services import sandbox_manager as sm

TOKEN = "test-token"

pytestmark = pytest.mark.unit


class FakeDocker:
    """``_docker`` の代役。subcommand ごとに (returncode, stdout, stderr) を返す。"""

    def __init__(
        self,
        mount: str = "",
        label: str = "1",
        container_id: str = "abc123def456",
        not_found: bool = False,
        **by_subcommand: object,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.by_subcommand = by_subcommand
        self.mount = mount
        self.label = label
        self.container_id = container_id
        self.not_found = not_found

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        # /data のマウント元とラベルは format で見分ける
        if args[0] == "inspect" and any("{{range .Mounts}}" in a for a in args):
            return subprocess.CompletedProcess(["docker", *args], 0, self.mount, "")
        if args[0] == "inspect" and any("com.nous.sandbox" in a and "{{.Id}}" in a for a in args):
            if self.not_found:
                return subprocess.CompletedProcess(["docker", *args], 1, "", "No such object")
            return subprocess.CompletedProcess(["docker", *args], 0, f"{self.container_id} {self.label}", "")
        spec = self.by_subcommand.get(args[0], (0, "", ""))
        if isinstance(spec, BaseException):
            raise spec
        code, out, err = spec  # type: ignore[misc]
        return subprocess.CompletedProcess(["docker", *args], code, out, err)


@pytest.fixture
def fake(monkeypatch, tmp_path) -> FakeDocker:
    # manager コンテナ内の /data と、bind mount の source（ホスト絶対パス）は別物。
    monkeypatch.setenv("NOUS_DATA_ROOT", str(tmp_path / "container"))
    monkeypatch.setenv("SANDBOX_HOST_DATA_ROOT", str(tmp_path / "host"))
    monkeypatch.setattr(sm, "_last_used", {})
    monkeypatch.setattr(sm, "_idle_override", {})
    monkeypatch.setattr(sm, "_in_flight", {})
    monkeypatch.setattr(sm, "_host_root", None)
    # HOSTNAME は自分自身のコンテナ ID（短縮形）と一致していなければならない。
    monkeypatch.setenv("HOSTNAME", "0123456789ab")
    monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", TOKEN)
    docker = FakeDocker(mount=f"0123456789abff {tmp_path / 'host'}", inspect=(0, "true 1\n", ""), exec=(0, "ok\n", ""))
    monkeypatch.setattr(sm, "_docker", docker)
    return docker


@pytest.fixture
def client(fake) -> TestClient:
    # with を使わない = lifespan（起動時 docker ps）を走らせない
    return TestClient(sm.app, headers={sm.TOKEN_HEADER: TOKEN})


def test_auth_requires_the_shared_token(fake) -> None:
    anonymous = TestClient(sm.app)
    assert anonymous.post("/exec", json={"persona": "alice", "command": "id"}).status_code == 401
    assert anonymous.get("/list").status_code == 401
    assert anonymous.post("/reset", json={"persona": "alice"}).status_code == 401


def test_auth_refuses_a_wrong_token(fake) -> None:
    wrong = TestClient(sm.app, headers={sm.TOKEN_HEADER: "nope"})
    assert wrong.get("/list").status_code == 401


def test_auth_fails_closed_without_configured_token(fake, monkeypatch) -> None:
    monkeypatch.delenv("NOUS_SANDBOX_MANAGER_TOKEN")
    anonymous = TestClient(sm.app)
    assert anonymous.get("/list").status_code == 503
    # health は compose の healthcheck 用に開けておく
    assert anonymous.get("/health").status_code == 200


@pytest.mark.parametrize("persona", ["Alice", "a b", "../x", ""])
def test_invalid_persona_is_400(client, fake, persona: str) -> None:
    assert client.post("/exec", json={"persona": persona, "command": "id"}).status_code == 400
    assert client.post("/touch", json={"persona": persona}).status_code == 400
    assert fake.calls == []


def test_exec_builds_docker_exec_args(client, fake) -> None:
    res = client.post("/exec", json={"persona": "alice", "command": "echo hi; ls -1"})
    assert res.status_code == 200
    assert ("exec", "alice-sandbox", "bash", "-lc", "echo hi; ls -1") in fake.calls
    assert res.json() == {
        "status": "ok",
        "exit_code": 0,
        "stdout_tail": "ok\n",
        "stderr_tail": "",
        "truncated": False,
        "log_path": res.json()["log_path"],
    }


def test_exec_with_cwd_adds_workdir(client, fake) -> None:
    client.post("/exec", json={"persona": "alice", "command": "pwd", "cwd": "/home/alice/workspace"})
    assert ("exec", "-w", "/home/alice/workspace", "alice-sandbox", "bash", "-lc", "pwd") in fake.calls


def test_exec_runs_container_when_missing(client, fake, tmp_path: Path) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "--name" in run and "alice-sandbox" in run
    assert "com.docker.compose.project=nous-sandbox" in run
    assert "com.docker.compose.service=sbx-alice" in run
    assert "com.nous.sandbox=1" in run
    assert f"{tmp_path}/host/persona/alice/workspace:/home/alice/workspace" in run
    assert f"{tmp_path}/host/persona/alice/skills:/home/alice/.agents/skills" in run
    assert f"{tmp_path}/host/skills:/home/alice/.agents/global-skills:ro" in run
    assert run[-2:] == ("sleep", "infinity")
    assert (tmp_path / "host" / "persona" / "alice" / "workspace").is_dir()


def test_run_uses_cpu_shares_because_the_kernel_has_no_cfs(client, fake) -> None:
    """Synology の 4.4 カーネルは CFS quota 非対応で --cpus だと run が失敗する。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "--cpus" not in run
    assert run[run.index("--cpu-shares") + 1] == "512"


def test_exec_starts_stopped_container(client, fake) -> None:
    fake.by_subcommand["inspect"] = (0, "false 1\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).status_code == 200
    assert ("start", "alice-sandbox") in fake.calls
    assert not any(c[0] == "run" for c in fake.calls)


def test_exec_nonzero_exit_is_error(client, fake) -> None:
    fake.by_subcommand["exec"] = (2, "", "bash: nope: command not found\n")

    body = client.post("/exec", json={"persona": "alice", "command": "nope"}).json()
    assert body["status"] == "error"
    assert body["exit_code"] == 2
    assert body["stderr_tail"].strip() == "bash: nope: command not found"


def test_docker_missing_is_error_not_500(client, fake) -> None:
    fake.by_subcommand["inspect"] = FileNotFoundError("docker")

    res = client.post("/exec", json={"persona": "alice", "command": "id"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "error"
    assert body["exit_code"] is None
    assert "docker" in body["stderr_tail"]


def test_tail_truncates_to_120_lines_and_full_log_is_saved(client, fake) -> None:
    stdout = "".join(f"line{i}\n" for i in range(200))
    fake.by_subcommand["exec"] = (0, stdout, "")

    body = client.post("/exec", json={"persona": "alice", "command": "seq 200"}).json()
    assert body["truncated"] is True
    assert len(body["stdout_tail"].splitlines()) == sm.TAIL_LINES
    assert body["stdout_tail"].startswith("line80")

    log_path = Path(body["log_path"])
    assert log_path.is_file()
    assert "line0" in log_path.read_text(encoding="utf-8")


def test_reset_creates_dir_when_container_absent(client, fake, monkeypatch, tmp_path: Path) -> None:
    removed: list[str] = []
    monkeypatch.setattr(sm.shutil, "rmtree", lambda p, **kw: removed.append(str(p)))
    fake.not_found = True
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    (tmp_path / "container" / "persona" / "alice" / "workspace").mkdir(parents=True)

    assert client.post("/reset", json={"persona": "alice"}).json() == {"status": "ok"}
    # 存在しないのに名前で rm しない（同名の他人を消さない）。
    assert not any(c[0] == "rm" for c in fake.calls)
    assert removed == [str(tmp_path / "container" / "persona" / "alice" / "workspace")]
    assert any(c[0] == "run" for c in fake.calls)


def test_reset_removes_by_id_not_name(client, fake, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sm.shutil, "rmtree", lambda p, **kw: None)
    (tmp_path / "container" / "persona" / "alice" / "workspace").mkdir(parents=True)

    assert client.post("/reset", json={"persona": "alice"}).json() == {"status": "ok"}
    assert ("rm", "-f", "abc123def456") in fake.calls
    assert not any(c == ("rm", "-f", "alice-sandbox") for c in fake.calls)


def test_idle_stop_only_hits_old_sandboxes(fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {"old": now - 31 * 60, "new": now})
    fake.by_subcommand["stop"] = (0, "old-sandbox\n", "")

    assert sm._stop_idle(now=now) == ["old"]
    assert ("stop", "old-sandbox") in fake.calls
    assert not any(c == ("stop", "new-sandbox") for c in fake.calls)
    assert "old" not in sm._last_used


def test_list_shape(client, fake) -> None:
    fake.by_subcommand["ps"] = (0, "alice-sandbox\trunning\nbob-sandbox\texited\n", "")
    sm._last_used["alice"] = 1_700_000_000.0

    body = client.get("/list").json()
    assert [s["persona"] for s in body["sandboxes"]] == ["alice", "bob"]
    assert body["sandboxes"][0] == {
        "persona": "alice",
        "container": "alice-sandbox",
        "running": True,
        "last_used": "2023-11-14T22:13:20+00:00",
    }
    assert body["sandboxes"][1]["running"] is False
    assert body["sandboxes"][1]["last_used"] is None


@pytest.mark.parametrize("persona", ["-it", "a" * 64])
def test_persona_must_start_alnum_and_be_bounded(client, fake, persona: str) -> None:
    assert client.post("/exec", json={"persona": persona, "command": "id"}).status_code == 400
    assert fake.calls == []


def test_reset_fails_when_rm_fails(client, fake) -> None:
    fake.by_subcommand["rm"] = (1, "", "cannot remove alice-sandbox")

    body = client.post("/reset", json={"persona": "alice"}).json()
    assert body["status"] == "error"
    assert "cannot remove" in body["stderr_tail"]
    assert not any(c[0] == "run" for c in fake.calls)


def test_container_without_our_label_is_refused(client, fake) -> None:
    fake.by_subcommand["inspect"] = (0, "true  <no value>\n", "")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "sandbox" in body["stderr_tail"]
    assert not any(c[0] == "exec" for c in fake.calls)


def test_inspect_permission_error_is_not_treated_as_missing(client, fake) -> None:
    fake.by_subcommand["inspect"] = (1, "", "permission denied while trying to connect to the Docker daemon socket")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "permission denied" in body["stderr_tail"]
    assert not any(c[0] == "run" for c in fake.calls)


def test_exec_timeout_is_clamped(client, fake, monkeypatch) -> None:
    seen: list[float] = []

    def spy(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        seen.append(timeout)
        return fake(*args, timeout=timeout)

    monkeypatch.setattr(sm, "_docker", spy)
    client.post("/exec", json={"persona": "alice", "command": "id", "timeout_seconds": 9999})
    assert seen[-1] == sm.EXEC_TIMEOUT_MAX


def test_exec_marks_last_used_before_the_command_runs(client, fake, monkeypatch) -> None:
    observed: list[float] = []

    def spy(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        if args[0] == "exec":
            observed.append(sm._last_used.get("alice", 0.0))
        return fake(*args, timeout=timeout)

    monkeypatch.setattr(sm, "_docker", spy)
    client.post("/exec", json={"persona": "alice", "command": "sleep 60"})
    assert observed and observed[0] > 0, "idle sweep must see the sandbox as busy while exec runs"


def test_health_reports_degraded_when_docker_is_down(client, fake) -> None:
    fake.by_subcommand["version"] = FileNotFoundError("docker")

    assert client.get("/health").json()["status"] == "degraded"


def test_request_options_override_env_defaults(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_IMAGE", "debian:12")
    monkeypatch.setenv("SANDBOX_NETWORK", "none")
    monkeypatch.setenv("SANDBOX_MEMORY", "1g")
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    client.post(
        "/exec",
        json={
            "persona": "alice",
            "command": "id",
            "image": "ubuntu:22.04",
            "network": "sbx-net",
            "memory": "2g",
        },
    )
    run = next(c for c in fake.calls if c[0] == "run")
    assert "ubuntu:22.04" in run and "debian:12" not in run
    assert run[run.index("--network") + 1] == "sbx-net"
    assert run[run.index("--memory") + 1] == "2g"


def test_host_data_root_unresolved_fails_closed(client, fake, monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_HOST_DATA_ROOT")
    fake.mount = ""
    fake.by_subcommand["inspect"] = (1, "", "No such object")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "data root" in body["stderr_tail"]
    assert not any(c[0] == "run" for c in fake.calls)


def test_host_data_root_env_mismatch_is_refused(client, fake, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX_HOST_DATA_ROOT", str(tmp_path / "other"))
    fake.mount = f"0123456789abff {tmp_path / 'host'}"
    monkeypatch.setattr(sm, "_host_root", None)
    fake.by_subcommand["inspect"] = (1, "", "No such object")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert not any(c[0] == "run" for c in fake.calls)


def test_host_data_root_ignores_a_foreign_container(fake, monkeypatch, tmp_path: Path) -> None:
    # ホスト直起動で HOSTNAME がホスト名のとき、同名の他人のコンテナを inspect しうる。
    monkeypatch.delenv("SANDBOX_HOST_DATA_ROOT", raising=False)
    monkeypatch.setenv("HOSTNAME", "buildhost")
    fake.mount = f"bbbbbbbbbbbbffff {tmp_path / 'host'}"
    monkeypatch.setattr(sm, "_host_root", None)

    assert sm._host_data_root() is None


def test_reset_refuses_a_container_we_did_not_create(client, fake) -> None:
    fake.label = "<no value>"

    body = client.post("/reset", json={"persona": "alice"}).json()
    assert body["status"] == "error"
    assert "sandbox" in body["stderr_tail"]
    assert not any(c[0] == "rm" for c in fake.calls)


def test_reset_refuses_while_exec_runs(client, fake, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_in_flight", {"alice": 1})

    body = client.post("/reset", json={"persona": "alice"}).json()
    assert body["status"] == "error"
    assert "実行中" in body["stderr_tail"]
    assert not any(c[0] == "rm" for c in fake.calls)


def test_reset_uses_request_options(client, fake) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/reset", json={"persona": "alice", "image": "ubuntu:22.04", "network": "sbx-net"}).json() == {
        "status": "ok"
    }
    run = next(c for c in fake.calls if c[0] == "run")
    assert "ubuntu:22.04" in run
    assert run[run.index("--network") + 1] == "sbx-net"


def test_in_flight_counts_concurrent_execs(monkeypatch) -> None:
    monkeypatch.setattr(sm, "_in_flight", {})
    sm._enter("alice")
    sm._enter("alice")
    assert sm._in_flight == {"alice": 2}
    sm._leave("alice")
    assert sm._in_flight == {"alice": 1}
    sm._leave("alice")
    assert sm._in_flight == {}


def test_idle_stop_forgets_a_missing_container(fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {"ghost": now - 31 * 60})
    fake.by_subcommand["stop"] = (1, "", "Error: No such container: ghost-sandbox")

    assert sm._stop_idle(now=now) == []
    assert "ghost" not in sm._last_used


def test_reset_fails_when_workspace_cannot_be_removed(client, fake, monkeypatch, tmp_path: Path) -> None:
    def deny(path, *args, **kwargs):  # noqa: ANN001, ARG001
        raise PermissionError("denied")

    monkeypatch.setattr(sm.shutil, "rmtree", deny)
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    (tmp_path / "container" / "persona" / "alice" / "workspace").mkdir(parents=True)

    body = client.post("/reset", json={"persona": "alice"}).json()
    assert body["status"] == "error"
    assert "workspace" in body["stderr_tail"]
    assert not any(c[0] == "run" for c in fake.calls)


def test_reset_fails_closed_without_host_root(client, fake, monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_HOST_DATA_ROOT")
    fake.mount = ""

    body = client.post("/reset", json={"persona": "alice"}).json()
    assert body["status"] == "error"
    assert "data root" in body["stderr_tail"]
    assert not any(c[0] in {"rm", "run"} for c in fake.calls)


def test_named_volume_mount_is_refused(fake, monkeypatch) -> None:
    """named volume の Source は絶対パスでない。そのまま -v に渡すと別ボリュームになる。"""
    fake.mount = "0123456789abff nous-data"
    monkeypatch.setattr(sm, "_host_root", None)
    monkeypatch.delenv("SANDBOX_HOST_DATA_ROOT", raising=False)
    assert sm._host_data_root() is None


def test_exec_rejects_a_host_network(client, fake) -> None:
    body = client.post("/exec", json={"persona": "alice", "command": "id", "network": "host"}).json()
    assert body["status"] == "error" and "network" in body["stderr_tail"]
    assert not any(call[0] == "run" for call in fake.calls)


def test_exec_rejects_a_flag_like_image(client, fake) -> None:
    body = client.post("/exec", json={"persona": "alice", "command": "id", "image": "--privileged"}).json()
    assert body["status"] == "error" and "image" in body["stderr_tail"]
    assert not any(call[0] == "run" for call in fake.calls)
