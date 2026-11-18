"""nous.services.sandbox_manager の unit テスト。

docker は実行しない。``_docker`` を FakeDocker に差し替えて引数組み立てと
エラー経路だけを見る。
"""

from __future__ import annotations

import os
import stat
import subprocess
import time
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient

from nous.services import sandbox_manager as sm

if TYPE_CHECKING:
    from pathlib import Path

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
        code, out, err = cast("tuple[int, str, str]", spec)
        return subprocess.CompletedProcess(["docker", *args], code, out, err)


@pytest.fixture
def fake(monkeypatch, tmp_path) -> FakeDocker:
    # manager コンテナ内の /data と、bind mount の source（ホスト絶対パス）は別物。
    monkeypatch.setenv("NOUS_DATA_ROOT", str(tmp_path / "container"))
    monkeypatch.setenv("SANDBOX_HOST_DATA_ROOT", str(tmp_path / "host"))
    monkeypatch.setattr(sm, "_last_used", {})
    monkeypatch.setattr(sm, "_idle_override", {})
    monkeypatch.setattr(sm, "_in_flight", {})
    # $HOME の chown は 1 回だけ。テスト間で持ち越さない。
    monkeypatch.setattr(sm, "_home_fixed", set())
    monkeypatch.setattr(sm, "_home_warned", set())
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
    assert (
        "exec",
        "alice-sandbox",
        "timeout",
        "-k",
        "5",
        str(int(sm.EXEC_TIMEOUT_SECONDS)),
        "bash",
        "-lc",
        "echo hi; ls -1",
    ) in fake.calls
    assert res.json() == {
        "status": "ok",
        "exit_code": 0,
        "stdout_tail": "ok\n",
        "stderr_tail": "",
        "truncated": False,
        "log_path": res.json()["log_path"],
    }


def test_exec_with_cwd_adds_workdir(client, fake) -> None:
    client.post("/exec", json={"persona": "alice", "command": "pwd", "cwd": "/home/agent/workspace"})
    assert (
        "exec",
        "-w",
        "/home/agent/workspace",
        "alice-sandbox",
        "timeout",
        "-k",
        "5",
        str(int(sm.EXEC_TIMEOUT_SECONDS)),
        "bash",
        "-lc",
        "pwd",
    ) in fake.calls


def test_exec_runs_container_when_missing(client, fake, tmp_path: Path) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "--name" in run and "alice-sandbox" in run
    assert "com.docker.compose.project=nous-sandbox" in run
    assert "com.docker.compose.service=sbx-alice" in run
    assert "com.nous.sandbox=1" in run
    assert f"{tmp_path}/host/persona/alice/workspace:/home/agent/workspace" in run
    assert f"{tmp_path}/host/persona/alice/wiki:/home/agent/wiki" in run
    assert f"{tmp_path}/host/persona/alice/uploads:/home/agent/uploads" in run
    # media は nous が書く生成物なので読み取り専用。
    assert f"{tmp_path}/host/persona/alice/media:/home/agent/media:ro" in run
    assert "--user" in run
    # _fix_home は sandbox の既定 caps（CAP_CHOWN）で exec する。ここで cap を
    # 落とすと $HOME の chown が静かに効かなくなる（tests/unit/test_sandbox_manager.py の
    # test_fix_home_* が前提にしている）。
    assert not any(a.startswith("--cap-drop") for a in run)
    assert f"{tmp_path}/host/persona/alice/skills:/home/agent/.agents/skills" in run
    assert f"{tmp_path}/host/skills:/home/agent/.agents/global-skills:ro" in run
    assert run[-2:] == ("sleep", "infinity")
    # mkdir は manager から見えるパス（NOUS_DATA_ROOT）に行う。
    # -v に渡すのはホスト名前空間のパスで、コンテナからは触れない。
    assert (tmp_path / "container" / "persona" / "alice" / "workspace").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "wiki").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "uploads").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "media").is_dir()
    # sandbox は非 root（既定 1026:100）で走る。manager は root なので
    # mkdir しただけだと書けない。rw のマウント先は 777 にしておく。
    mode = (tmp_path / "container" / "persona" / "alice" / "workspace").stat().st_mode
    assert stat.S_IMODE(mode) == 0o777


def test_run_uses_cpu_shares_because_the_kernel_has_no_cfs(client, fake) -> None:
    """Synology の 4.4 カーネルは CFS quota 非対応で --cpus だと run が失敗する。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "--cpus" not in run
    assert run[run.index("--cpu-shares") + 1] == "512"


def test_run_inherits_the_parent_tz_and_forces_utf8(client, fake, monkeypatch) -> None:
    """persona 側は Asia/Tokyo。UTC のままだとログが 9 時間ずれる。"""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=Asia/Tokyo" in run
    assert "LANG=C.UTF-8" in run
    assert "LC_ALL=C.UTF-8" in run


def test_sandbox_tz_overrides_the_parent_tz(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    monkeypatch.setenv("SANDBOX_TZ", "UTC")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    client.post("/exec", json={"persona": "alice", "command": "id"})

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=UTC" in run


def test_run_lets_env_override_the_git_identity(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_GIT_USER_NAME", "herta")
    monkeypatch.setenv("SANDBOX_GIT_USER_EMAIL", "herta@nous.local")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    client.post("/exec", json={"persona": "alice", "command": "id"})

    run = next(c for c in fake.calls if c[0] == "run")
    assert "GIT_AUTHOR_NAME=herta" in run and "GIT_COMMITTER_NAME=herta" in run
    assert "GIT_AUTHOR_EMAIL=herta@nous.local" in run and "GIT_COMMITTER_EMAIL=herta@nous.local" in run


def test_dns_check_is_quiet_when_nous_resolves(fake) -> None:
    fake.by_subcommand["exec"] = (0, "172.18.0.2\tnous\n", "")
    assert sm._check_dns("alice-sandbox") is None
    assert ("exec", "alice-sandbox", "getent", "hosts", "nous") in fake.calls


def test_dns_check_reports_the_first_stderr_line(fake) -> None:
    fake.by_subcommand["exec"] = (2, "", "getent: nous: Name or service not known\nsecond\n")
    err = sm._check_dns("alice-sandbox")
    assert err is not None
    assert "Name or service not known" in err and "second" not in err


def test_dns_failure_fails_the_ensure(client, fake) -> None:
    """名前解決できないコンテナを静かに使い始めない。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    fake.by_subcommand["exec"] = (2, "", "getent: nous: Name or service not known\n")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "名前解決" in body["stderr_tail"]


def test_dns_check_can_be_skipped(fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")
    fake.by_subcommand["exec"] = (2, "", "getent: nous: Name or service not known\n")
    assert sm._post_start_check("alice-sandbox") is None
    assert fake.calls == []


def test_fix_mount_perms_opens_rw_mounts_only(fake, tmp_path: Path) -> None:
    """既存コンテナの start 経路は run の chmod を通らない。掛け直す。"""
    rw = tmp_path / "container" / "persona" / "alice" / "wiki"
    ro = tmp_path / "container" / "persona" / "alice" / "media"
    for d in (rw, ro):
        d.mkdir(parents=True)
        os.chmod(d, 0o755)

    sm._fix_mount_perms("alice")

    assert stat.S_IMODE(rw.stat().st_mode) == 0o777
    assert stat.S_IMODE(ro.stat().st_mode) == 0o755


def test_apt_extra_skips_apt_when_everything_is_installed(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_APT_EXTRA", "jq,tree")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    seen = _docker_spy(fake, installed={"jq", "tree"}, apt=(0, "", ""))
    monkeypatch.setattr(sm, "_docker", seen.fn)

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"
    assert [c for c in seen.calls if c[:4] == ("exec", "alice-sandbox", "dpkg", "-s")] == [
        ("exec", "alice-sandbox", "dpkg", "-s", "jq"),
        ("exec", "alice-sandbox", "dpkg", "-s", "tree"),
    ]
    assert not any("apt-get" in " ".join(c) for c in seen.calls)


def test_apt_extra_installs_only_the_missing_packages(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_APT_EXTRA", "jq, tree ,htop")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    seen = _docker_spy(fake, installed={"tree"}, apt=(0, "", ""))
    monkeypatch.setattr(sm, "_docker", seen.fn)

    client.post("/exec", json={"persona": "alice", "command": "id"})

    installs = [c for c in seen.calls if "apt-get install" in " ".join(c)]
    assert len(installs) == 1
    # コンテナは --user 1026:100 で走るので、apt は root で打たないと必ず失敗する。
    assert installs[0][1:4] == ("-u", "0", "alice-sandbox")
    script = installs[0][-1]
    assert "DEBIAN_FRONTEND=noninteractive" in script
    assert "--no-install-recommends" in script
    assert "apt-get update" in script
    assert script.endswith("jq htop")


def test_apt_extra_failure_is_a_warning_not_an_error(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_APT_EXTRA", "nope")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    seen = _docker_spy(fake, installed=set(), apt=(100, "", "E: Unable to locate package nope\nmore\n"))
    monkeypatch.setattr(sm, "_docker", seen.fn)

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "ok"
    assert "E: Unable" not in body["stderr_tail"]


class _DockerSpy:
    def __init__(self, fake: FakeDocker, installed: set[str], apt: tuple[int, str, str]) -> None:
        self.fake = fake
        self.installed = installed
        self.apt = apt
        self.calls: list[tuple[str, ...]] = []

    def fn(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:4] == ("exec", "alice-sandbox", "dpkg", "-s"):
            missing = args[4] not in self.installed
            return subprocess.CompletedProcess(["docker", *args], 1 if missing else 0, "", "")
        if args[:4] == ("exec", "alice-sandbox", "bash", "-lc") and "apt-get install" in args[4]:
            return subprocess.CompletedProcess(["docker", *args], *self.apt)
        return self.fake(*args, timeout=timeout)


def _docker_spy(fake: FakeDocker, installed: set[str], apt: tuple[int, str, str]) -> _DockerSpy:
    return _DockerSpy(fake, installed, apt)


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


def test_tail_truncates_to_120_lines_and_full_log_is_saved(client, fake, tmp_path: Path) -> None:
    stdout = "".join(f"line{i}\n" for i in range(200))
    fake.by_subcommand["exec"] = (0, stdout, "")

    body = client.post("/exec", json={"persona": "alice", "command": "seq 200"}).json()
    assert body["truncated"] is True
    assert len(body["stdout_tail"].splitlines()) == sm.TAIL_LINES
    assert body["stdout_tail"].startswith("line80")

    # 返るのはコンテナ内から読めるパス（read_file の境界内）。実体は workspace の下。
    assert body["log_path"].startswith(f"{sm.CONTAINER_WORKSPACE}/{sm.LOG_DIR}/")
    rel = body["log_path"].removeprefix(f"{sm.CONTAINER_WORKSPACE}/")
    log_path = tmp_path / "container" / "persona" / "alice" / "workspace" / rel
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
        return cast("subprocess.CompletedProcess[str]", fake(*args, timeout=timeout))

    monkeypatch.setattr(sm, "_docker", spy)
    client.post("/exec", json={"persona": "alice", "command": "id", "timeout_seconds": 9999})
    assert seen[-1] == sm.EXEC_TIMEOUT_MAX + 10.0


def test_exec_marks_last_used_before_the_command_runs(client, fake, monkeypatch) -> None:
    observed: list[float] = []

    def spy(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        if args[0] == "exec":
            observed.append(sm._last_used.get("alice", 0.0))
        return cast("subprocess.CompletedProcess[str]", fake(*args, timeout=timeout))

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
    monkeypatch.setenv("SANDBOX_ALLOWED_NETWORKS", "sbx-net")
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


def test_reset_uses_request_options(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_ALLOWED_NETWORKS", "sbx-net")
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
    # $HOME の chown は 1 回だけ。テスト間で持ち越さない。
    monkeypatch.setattr(sm, "_home_fixed", set())
    monkeypatch.setattr(sm, "_home_warned", set())
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


def test_exec_rejects_a_network_outside_the_allowlist(client, fake, monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_ALLOWED_NETWORKS", raising=False)
    body = client.post("/exec", json={"persona": "alice", "command": "id", "network": "custom-net"}).json()
    assert body["status"] == "error" and "network" in body["stderr_tail"]
    assert not any(call[0] == "run" for call in fake.calls)


def test_exec_wraps_the_command_in_timeout(client, fake) -> None:
    fake.by_subcommand["inspect"] = (0, "true 1", "")
    client.post("/exec", json={"persona": "alice", "command": "sleep 999", "timeout_seconds": 7})
    # _fix_home も exec を打つので、timeout ラッパーを含む exec を選ぶ。
    exec_call = next(c for c in fake.calls if c[0] == "exec" and "timeout" in c)
    assert exec_call[exec_call.index("-k") + 1] == "5"
    assert tuple(exec_call[exec_call.index("timeout") + 1 :])[:4] == ("-k", "5", "7", "bash")


def test_load_existing_starts_the_idle_clock_after_a_grace(fake, monkeypatch) -> None:
    """再起動直後に idle 30 分が丸ごと戻らないこと。"""
    monkeypatch.setattr(sm, "_last_used", {})
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    fake.by_subcommand["ps"] = (0, "alice-sandbox bob-sandbox\n", "")
    before = time.time()
    sm._load_existing()
    last = sm._last_used["alice"]
    assert before - sm._idle_minutes() * 60.0 + sm.RESTART_GRACE_SECONDS - 2 <= last
    assert last <= before - sm._idle_minutes() * 60.0 + sm.RESTART_GRACE_SECONDS + 2


def test_fix_home_chowns_home_and_agents_as_root(fake, monkeypatch) -> None:
    """$HOME はイメージ側で root 所有になり得る（WORKDIR が useradd より先）。

    実機で `ls -ld /home/agent` が root:root 0755 になり、$HOME に書けなかった。
    run / start の後に uid へ寄せ直す（manager は cap_drop: ALL で chown できない）。
    """
    monkeypatch.setattr(sm, "_home_fixed", set())
    monkeypatch.setenv("SANDBOX_UID", "1026")
    monkeypatch.setenv("SANDBOX_GID", "100")

    sm._fix_home("alice-sandbox")

    assert fake.calls == [
        ("exec", "-u", "0", "alice-sandbox", "chown", "1026:100", "/home/agent"),
        ("exec", "-u", "0", "alice-sandbox", "chown", "1026:100", "/home/agent/.agents"),
    ]


def test_fix_home_uses_configured_uid(fake, monkeypatch) -> None:
    """SANDBOX_UID を変えている環境では、その uid に合わせる（1026 決め打ちにしない）。"""
    monkeypatch.setattr(sm, "_home_fixed", set())
    monkeypatch.setenv("SANDBOX_UID", "1000")
    monkeypatch.setenv("SANDBOX_GID", "1000")

    sm._fix_home("alice-sandbox")

    assert fake.calls[0][-2] == "1000:1000"


def test_ensure_fixes_home_on_existing_container(fake, tmp_path: Path, monkeypatch) -> None:
    """running の経路（毎 exec）でも HOME を直す。start 済みだと run の chmod を通らない。"""
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")

    assert sm._ensure("alice") is None

    assert ("exec", "-u", "0", "alice-sandbox", "chown", "1026:100", "/home/agent") in fake.calls


def test_fix_home_prefers_container_user(fake, monkeypatch) -> None:
    """chown 先は env ではなく既存コンテナの .Config.User を信じる。

    SANDBOX_UID を後から変えたとき、動いていない uid へ $HOME を寄せると
    二度と書けないコンテナになる。
    """
    monkeypatch.setenv("SANDBOX_UID", "1026")
    monkeypatch.setenv("SANDBOX_GID", "100")
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")
    fake.by_subcommand["inspect"] = (0, "true 1 1000:1000\n", "")

    assert sm._ensure("alice") is None

    assert ("exec", "-u", "0", "alice-sandbox", "chown", "1000:1000", "/home/agent") in fake.calls
    assert ("exec", "-u", "0", "alice-sandbox", "chown", "1026:100", "/home/agent") not in fake.calls


def test_write_log_is_writable_by_persona(fake, tmp_path: Path, monkeypatch) -> None:
    """ログは root 所有で置かれるので、ペルソナが消せる/書き換えられる状態にする。"""
    rel = sm._write_log("alice", "id", "out", "err")

    assert rel is not None
    log = tmp_path / "container" / "persona" / "alice" / "workspace" / rel.split("/workspace/", 1)[1]
    assert stat.S_IMODE(log.stat().st_mode) == 0o666
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o777
