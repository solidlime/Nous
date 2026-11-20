"""nous.services.sandbox_manager の unit テスト。

docker は実行しない。``_docker`` を FakeDocker に差し替えて引数組み立てと
エラー経路だけを見る。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi.testclient import TestClient

from nous.services import sandbox_manager as sm


@pytest.fixture(autouse=True)
def _settings_cache():
    """テストごとに get_settings の lru_cache を潰す — NOUS_TIMEZONE を触る
    テストの Europe/Berlin が次のテストに残留しないように（テスト順非依存化）。
    yield 前にも潰す — 先行テストファイルが cache を汚したままでもここから始める。"""
    from nous.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


if TYPE_CHECKING:
    from collections.abc import Callable
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
        id_error: str = "",
        **by_subcommand: object,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.by_subcommand = by_subcommand
        self.mount = mount
        self.label = label
        self.container_id = container_id
        self.not_found = not_found
        # /restore の事後検証が返す .Config.Image を差し替えるための器。
        self.running_image: str | None = None
        self.id_error = id_error
        self.last_run_image: str | None = None
        # /restore の rm が ensure ロックの内側で走っているか（lock 保持の直接証拠）。
        self.rm_lock_held: list[bool] = []
        # /restore の事後検証（{{.Config.Image}}）を失敗させるための器。
        self.verify_error = ""
        # stop の実行中に走らせるフック（stop の 10 秒の隙間で exec が始まる状況を作る）。
        self.on_stop: Callable[[], None] | None = None

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args and args[0] == "rm":
            self.rm_lock_held.append(sm._ensure_lock("alice").locked())
        if args[0] == "run" and "sleep" in args:
            self.last_run_image = args[args.index("sleep") - 1]
        if args[0] == "stop" and self.on_stop is not None:
            self.on_stop()
        inspected = self._inspect(args)
        if inspected is not None:
            return inspected
        spec = self.by_subcommand.get(args[0] if args else "", (0, "", ""))
        if isinstance(spec, BaseException):
            raise spec
        code, out, err = cast("tuple[int, str, str]", spec)
        return subprocess.CompletedProcess(["docker", *args], code, out, err)

    def _inspect(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
        """inspect は format 文字列でどの問い合わせか見分ける（inspect 以外は None）。"""
        if args[0] != "inspect":
            return None
        joined = " ".join(args)
        if "{{range .Mounts}}" in joined:
            return subprocess.CompletedProcess(["docker", *args], 0, self.mount, "")
        if "{{.Id}}" in joined and "com.nous.sandbox" in joined:
            if self.id_error:
                return subprocess.CompletedProcess(["docker", *args], 1, "", self.id_error)
            if self.not_found:
                return subprocess.CompletedProcess(["docker", *args], 1, "", "No such object")
            return subprocess.CompletedProcess(["docker", *args], 0, f"{self.container_id} {self.label}", "")
        if "{{.Config.Image}}" in joined:
            if self.verify_error:
                return subprocess.CompletedProcess(["docker", *args], 1, "", self.verify_error)
            image = self.running_image or self.last_run_image or ""
            return subprocess.CompletedProcess(["docker", *args], 0, f"{image} {self.label}", "")
        return None


@pytest.fixture
def fake(monkeypatch, tmp_path) -> FakeDocker:
    # manager コンテナ内の /data と、bind mount の source（ホスト絶対パス）は別物。
    monkeypatch.setenv("NOUS_DATA_ROOT", str(tmp_path / "container"))
    monkeypatch.setenv("SANDBOX_HOST_DATA_ROOT", str(tmp_path / "host"))
    monkeypatch.setattr(sm, "_last_used", {})
    monkeypatch.setattr(sm, "_idle_override", {})
    monkeypatch.setattr(sm, "_in_flight", {})
    # root 以外の警告はコンテナごとに 1 回。テスト間で持ち越さない。
    monkeypatch.setattr(sm, "_user_warned", set())
    monkeypatch.setattr(sm, "_host_root", None)
    # HOSTNAME は自分自身のコンテナ ID（短縮形）と一致していなければならない。
    monkeypatch.setenv("HOSTNAME", "0123456789ab")
    monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", TOKEN)
    # 開発 shell の SANDBOX_* で挙動が変わらないようにする（差し替えるテストだけが setenv する）。
    for name in (
        "SANDBOX_IMAGE",
        "SANDBOX_NETWORK",
        "SANDBOX_MEMORY",
        "SANDBOX_IDLE_MINUTES",
        "SANDBOX_ALLOWED_NETWORKS",
        "SANDBOX_APT_EXTRA",
        "SANDBOX_TZ",
        "SANDBOX_DNS_CHECK",
        "SANDBOX_GIT_USER_NAME",
        "SANDBOX_GIT_USER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
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
    assert anonymous.post("/reset", json={"persona": "alice"}).status_code == 404
    assert anonymous.post("/snapshot", json={"persona": "alice"}).status_code == 401
    assert anonymous.post("/restore", json={"persona": "alice", "image": "ubuntu:24.04"}).status_code == 401


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
    client.post("/exec", json={"persona": "alice", "command": "pwd", "cwd": "/root/workspace"})
    assert (
        "exec",
        "-w",
        "/root/workspace",
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
    assert f"{tmp_path}/host/persona/alice/root:/root" in run
    assert f"{tmp_path}/host/persona/alice/workspace:/mnt/nous/workspace" in run
    assert f"{tmp_path}/host/persona/alice/wiki:/mnt/nous/wiki" in run
    assert f"{tmp_path}/host/persona/alice/uploads:/mnt/nous/uploads" in run
    # media は nous が書く生成物なので読み取り専用。
    assert f"{tmp_path}/host/persona/alice/media:/mnt/nous/media:ro" in run
    assert "--user" in run
    # ペルソナ専用マシンなので root で走らせる。
    assert run[run.index("--user") + 1] == "0:0"
    assert run[run.index("--pids-limit") + 1] == "1024"
    assert run[run.index("--memory") + 1] == "4g"
    # no-new-privileges は廃止（root 前提の運用に合わせる）。
    assert "no-new-privileges" not in run
    assert not any(a.startswith("--cap-drop") for a in run)
    assert f"{tmp_path}/host/persona/alice/skills:/mnt/nous/skills" in run
    assert f"{tmp_path}/host/skills:/mnt/nous/global-skills:ro" in run
    # /root 集約: HOME も workdir も /root。日常ディレクトリは symlink で見せる。
    assert "HOME=/root" in run
    assert run[run.index("--workdir") + 1] == "/root"
    assert run[-2:] == ("sleep", "infinity")
    # mkdir は manager から見えるパス（NOUS_DATA_ROOT）に行う。
    # -v に渡すのはホスト名前空間のパスで、コンテナからは触れない。
    assert (tmp_path / "container" / "persona" / "alice" / "root").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "workspace").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "wiki").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "uploads").is_dir()
    assert (tmp_path / "container" / "persona" / "alice" / "media").is_dir()


def test_run_links_home_dirs_and_checks_the_mounts(client, fake) -> None:
    """run 直後は symlink を張り直して、対象は _SANDBOX_LINKS から導く。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    link_call = next(c for c in fake.calls if c[0] == "exec" and "ln -sfn" in " ".join(c))
    # root 権限で実行し、/root/.agents の親も作る。profile 読み込みは無し。
    assert link_call[link_call.index("-u") + 1] == "0"
    assert "--noprofile" in link_call and "--norc" in link_call
    script = link_call[link_call.index("-c") + 1]
    assert "mkdir -p /root/.agents" in script
    # 検査が mutate に先立つ（マウント漏れなら 1 本も触らない）。
    # MISS は 1 本で即抜けせず全本数を積んでから非 0 で落とす。
    assert script.index("MISS:$t") < script.index("mkdir -p")
    assert '[ "$miss" -eq 0 ]' in script
    for link, target in sm._SANDBOX_LINKS:
        assert f'ln -sfn {target} "{link}"' in script
        # ln -sfn は実ディレクトリに負けるので退避する。衝突で止めると恒久
        # 故障になるので .pre-link.1, .pre-link.2 … と追い番にし、MOVED: で
        # host 側に知らせる。
        assert f'while [ -e "$d" ] || [ -L "$d" ]; do i=$((i+1)); d="{link}.pre-link.$i"; done' in script
        assert f'mv -- "{link}" "$d" && echo "MOVED:$d"' in script
    # dangling チェックの対象は _SANDBOX_LINKS から導く（二重管理しない）。
    derived = " ".join(sorted({t.rsplit("/", 1)[-1] for _, t in sm._SANDBOX_LINKS}))
    assert f"for t in {derived}; do" in script
    assert "MISS:$t" in script
    # post_run の最初に走る（tz より先）。
    execs = [c for c in fake.calls if c[0] == "exec"]
    assert execs.index(link_call) == 0
    # /etc/passwd のパッチは廃止済み（復活したらここで落ちる）。
    assert all("/etc/passwd" not in " ".join(c) for c in fake.calls)


def test_ensure_relinks_even_when_already_running(client, fake) -> None:
    """start を挟がない経路（既に running）でも symlink は張り直す。"""
    fake.by_subcommand["inspect"] = (0, "true 1 0\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    # run は叩かないが、link の exec は走る（手で壊された symlink の修復）。
    assert not any(c[0] == "run" for c in fake.calls)
    assert any(c[0] == "exec" and "ln -sfn" in " ".join(c) for c in fake.calls)


def test_run_fails_when_a_mount_is_invisible(client, fake) -> None:
    """dangling symlink は「ファイルが無い」に化けるので、run を殺して status=error。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    fake.by_subcommand["exec"] = (1, "MISS:workspace\nMISS:media\n", "")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "workspace" in body["stderr_tail"] and "media" in body["stderr_tail"]
    # 検査が 2 本まとめて報告する（1 本で即抜けすると残りが静かに漏れる）。
    assert "workspace, media" in body["stderr_tail"]
    # dangling が見つかったら tz も DNS チェックも走らせない。
    assert not any("zoneinfo" in " ".join(c) or "getent" in " ".join(c) for c in fake.calls if c[0] == "exec")
    # 壊れた新規コンテナを残さない（running 短絡による再入を防ぐ）。
    # /restore と同じ「ID で消す」規約（run -d の stdout = コンテナ ID）。
    assert any(c[0] == "rm" and "abc123" in c for c in fake.calls)


def test_run_fails_when_linking_itself_fails(client, fake) -> None:
    """ln 自体が失敗したら（シェル不在など）run を殺す。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    fake.by_subcommand["exec"] = (127, "", "bash: ln: command not found\n")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "symlink" in body["stderr_tail"]


def test_ensure_miss_leaves_running_container_alone(client, fake) -> None:
    """running 短絡での dangling は error を返すだけで、既存コンテナは rm しない。

    rm は「run 直後に失敗した新規コンテナ」専用。この釘が無いと将来の
    経路統合で他人の running マシンを消す変更が緑のまま通る。
    """
    fake.by_subcommand["inspect"] = (0, "true 1 0\n", "")
    fake.by_subcommand["exec"] = (1, "MISS:workspace\n", "")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "workspace" in body["stderr_tail"]
    assert not any(c[0] == "rm" for c in fake.calls)


def test_run_reports_moved_directories(client, fake, caplog) -> None:
    """退避が起きたら（MOVED:）host 側に warning を出す（サイレント統合を防ぐ）。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    fake.by_subcommand["exec"] = (0, "MOVED:/root/workspace.pre-link\n", "")

    with caplog.at_level(logging.WARNING, logger="nous.services.sandbox_manager"):
        body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    # 退避はエラーではない: リンクは張れており、データは .pre-link 側に生きる。
    assert body["status"] == "ok"
    assert "workspace.pre-link" in caplog.text
    assert "退避" in caplog.text


def test_run_uses_cpu_shares_because_the_kernel_has_no_cfs(client, fake) -> None:
    """Synology の 4.4 カーネルは CFS quota 非対応で --cpus だと run が失敗する。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "--cpus" not in run
    assert run[run.index("--cpu-shares") + 1] == "512"


def test_run_uses_the_nous_setting_for_tz_and_forces_utf8(client, fake, monkeypatch) -> None:
    """sandbox の TZ は Nous 設定（Asia/Tokyo）から。親プロセスの TZ はもう継承しない。"""
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    # .env の NOUS_TIMEZONE は delenv で消えないので、明示して既定に頼らない
    monkeypatch.setenv("NOUS_TIMEZONE", "Asia/Tokyo")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=Asia/Tokyo" in run
    assert "LANG=C.UTF-8" in run
    assert "LC_ALL=C.UTF-8" in run


def test_tz_follows_the_nous_timezone_env(client, fake, monkeypatch) -> None:
    """NOUS_TIMEZONE を変えれば sandbox の TZ も付いてくる（設定が 1 本化）。"""
    monkeypatch.setenv("NOUS_TIMEZONE", "Europe/Berlin")
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=Europe/Berlin" in run


def test_sandbox_tz_overrides_the_nous_setting(client, fake, monkeypatch) -> None:
    """SANDBOX_TZ は Nous 設定より優先（1 台だけ変えたいとき用）。"""
    monkeypatch.setenv("NOUS_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("SANDBOX_TZ", "UTC")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    client.post("/exec", json={"persona": "alice", "command": "id"})

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=UTC" in run


def test_sandbox_tz_malformed_falls_back_to_the_nous_setting(client, fake, monkeypatch) -> None:
    """SANDBOX_TZ がゾーン名の形でなければ警告のうえ Nous 設定に落とす（bash 埋め込み前の防衛）。"""
    monkeypatch.setenv("NOUS_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("SANDBOX_TZ", "Asia/Tokyo; rm -rf /")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=Europe/Berlin" in run
    # 不正値がどこかの argv 要素に紛れ込んでいないか（TZ=Europe/Berlin だけでは足りない）
    assert not any("rm -rf" in a for a in run)


def test_tz_falls_back_to_utc_when_settings_is_mutated_at_runtime(client, fake, monkeypatch) -> None:
    """RCM の setattr が field_validator を通らず settings.timezone を汚染していても、
    _tz() の出口検証が bash スクリプトへの注入を防ぐ（settings 由来も無条件に刈る）。"""
    from nous.config.settings import get_settings

    monkeypatch.setenv("NOUS_TIMEZONE", "Europe/Berlin")
    settings = get_settings()
    # RCM（admin API）と同じ setattr — validate_assignment が無いので素通りする
    settings.timezone = 'Asia/Tokyo"; touch /tmp/pwned; "'
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    run = next(c for c in fake.calls if c[0] == "run")
    assert "TZ=UTC" in run
    # sink の手前（run argv）だけではなく、全 docker 呼び出し（tz の exec スクリプト込み）に漏れがないこと
    assert not any("pwned" in " ".join(c) for c in fake.calls)
    # tz の exec が初期られた zone（UTC）で動いていること — 汚染値が /etc/timezone に書かれていない
    assert any(c[0] == "exec" and "/usr/share/zoneinfo/UTC" in " ".join(c) for c in fake.calls)


def test_apply_timezone_writes_etc_timezone_before_the_dns_check(client, fake, monkeypatch) -> None:
    """新規作成直後に /etc/timezone と /etc/localtime を書く。DNS チェックより先。"""
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    # .env の NOUS_TIMEZONE は delenv で消えないので、明示して既定に頼らない
    monkeypatch.setenv("NOUS_TIMEZONE", "Asia/Tokyo")
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).json()["status"] == "ok"

    execs = [c for c in fake.calls if c[0] == "exec"]
    assert execs, "run 直後の後処理 exec が無い"
    tz_call = next(c for c in execs if "/etc/timezone" in " ".join(c))
    script = tz_call[tz_call.index("-c") + 1]
    assert 'printf "%s\\n" "Asia/Tokyo" > /etc/timezone' in script
    assert 'ln -sf "/usr/share/zoneinfo/Asia/Tokyo" /etc/localtime' in script
    # DNS チェック（getent）より先に書く — DNS 失敗コンテナにも tz が付く。
    getent_index = next(i for i, c in enumerate(execs) if "getent" in " ".join(c))
    assert execs.index(tz_call) < getent_index


def test_apply_timezone_failure_does_not_kill_the_run(client, fake, monkeypatch) -> None:
    """tz の exec が失敗しても警告だけ。run を殺さない（apt と同じ方針）。"""
    monkeypatch.setenv("NOUS_TIMEZONE", "Europe/Berlin")
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    # exec は tz スクリプトも DNS チェックもユーザーコマンドも同じ by_subcommand 応答を
    # 共有する。tz だけ失敗させるため docker を wrapper クラスで置き換える。
    real_docker = fake

    class TZFailDocker:
        def __init__(self, inner: FakeDocker) -> None:
            self.inner = inner
            self.calls = inner.calls

        def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "exec" and "/etc/timezone" in " ".join(args):
                self.calls.append(args)
                return subprocess.CompletedProcess(["docker", *args], 2, "", "zoneinfo missing")
            return self.inner(*args, timeout=timeout)

    monkeypatch.setattr(sm, "_docker", TZFailDocker(real_docker))

    body = client.post("/exec", json={"persona": "alice", "command": "true"}).json()
    assert body["status"] == "ok", body
    assert any(
        args[0] == "exec"
        and "/etc/timezone" in " ".join(args)
        and "/usr/share/zoneinfo/Europe/Berlin" in " ".join(args)
        for args in fake.calls
    )


def test_apply_timezone_is_skipped_when_the_container_already_exists(client, fake, monkeypatch) -> None:
    """既存コンテナの start 経路では書かない（エージェントが変えた /etc/timezone を尊重）。"""
    monkeypatch.delenv("SANDBOX_TZ", raising=False)
    fake.by_subcommand["inspect"] = (0, "false 1\n", "")
    fake.by_subcommand["start"] = (0, "", "")
    fake.by_subcommand["exec"] = (0, "ok\n", "")

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "ok", body
    assert ("start", "alice-sandbox") in fake.calls
    assert not any(c[0] == "exec" and "/etc/timezone" in " ".join(c) for c in fake.calls)


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


def test_dns_failure_fails_the_ensure(client, fake, monkeypatch) -> None:
    """名前解決できないコンテナを静かに使い始めない。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object: alice-sandbox")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    # exec の応答は symlink 張り・tz・DNS チェックで共有される。DNS だけを
    # 失敗させるため、getent を含む呼び出しだけを攔む wrapper にする（TZFailDocker と同型）。
    real_docker = fake

    class DNSFailDocker:
        def __init__(self, inner: FakeDocker) -> None:
            self.inner = inner
            self.calls = inner.calls

        def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "exec" and "getent" in " ".join(args):
                self.calls.append(args)
                return subprocess.CompletedProcess(
                    ["docker", *args], 2, "", "getent: nous: Name or service not known\n"
                )
            return self.inner(*args, timeout=timeout)

    monkeypatch.setattr(sm, "_docker", DNSFailDocker(real_docker))

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()
    assert body["status"] == "error"
    assert "名前解決" in body["stderr_tail"]


def test_dns_check_can_be_skipped(fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")
    fake.by_subcommand["exec"] = (2, "", "getent: nous: Name or service not known\n")
    assert sm._post_start_check("alice-sandbox") is None
    assert fake.calls == []


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
    # 旧 1026 コンテナも動くので、apt は uid に依らず root で打つ。
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
        if args[0] == "exec" and "apt-get install" in " ".join(args):
            return subprocess.CompletedProcess(["docker", *args], *self.apt)
        return self.fake(*args, timeout=timeout)


def _docker_spy(fake: FakeDocker, installed: set[str], apt: tuple[int, str, str]) -> _DockerSpy:
    return _DockerSpy(fake, installed, apt)


def test_exec_starts_stopped_container(client, fake) -> None:
    fake.by_subcommand["inspect"] = (0, "false 1\n", "")

    assert client.post("/exec", json={"persona": "alice", "command": "id"}).status_code == 200
    assert ("start", "alice-sandbox") in fake.calls
    assert not any(c[0] == "run" for c in fake.calls)


def test_exec_nonzero_exit_is_error(client, fake, monkeypatch) -> None:
    """ユーザーコマンドの非零終了は status=error + exit_code で返す。"""
    # link 張り直し・tz・DNS の exec は成功させ、ユーザーコマンドだけ失敗させる。
    real_docker = fake

    class UserCmdFailDocker:
        def __init__(self, inner: FakeDocker) -> None:
            self.inner = inner
            self.calls = inner.calls

        def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "exec":
                self.calls.append(args)
                if args[-1] == "nope":
                    return subprocess.CompletedProcess(["docker", *args], 2, "", "bash: nope: command not found\n")
                return subprocess.CompletedProcess(["docker", *args], 0, "", "")
            return self.inner(*args, timeout=timeout)

    monkeypatch.setattr(sm, "_docker", UserCmdFailDocker(real_docker))

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


def test_reset_is_gone(client) -> None:
    """全消去 API は廃止。壊れたら snapshot から /restore で戻す。"""
    assert client.post("/reset", json={"persona": "alice"}).status_code == 404


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


def test_snapshot_commits_the_container_to_a_timestamped_image(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_IMAGE", "ghcr.io/solidlime/nous-sandbox:latest")

    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["status"] == "ok"
    commit = next(c for c in fake.calls if c[0] == "commit")
    assert commit[1] == "--pause=false"
    assert commit[2] == "abc123def456"
    repo, _, tag = commit[3].rpartition(":")
    assert repo == "ghcr.io/solidlime/nous-sandbox"
    # %f が無いと同一秒の 2 回目が既存タグを黙って上書きする。
    assert re.fullmatch(r"alice-snap-\d{8}-\d{6}-\d{6}", tag)
    assert body["image"] == commit[3]


def test_snapshot_uses_the_requested_image_as_repository(client, fake) -> None:
    body = client.post("/snapshot", json={"persona": "alice", "image": "ubuntu:24.04"}).json()

    assert body["image"].startswith("ubuntu:alice-snap-")


def test_snapshot_gives_commit_a_long_timeout(client, fake, monkeypatch) -> None:
    """writable layer が数 GB でも 60 秒既定で落ちないように。"""
    seen: list[tuple[str, float]] = []

    def spy(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        seen.append((args[0], timeout))
        return cast("subprocess.CompletedProcess[str]", fake(*args, timeout=timeout))

    monkeypatch.setattr(sm, "_docker", spy)
    client.post("/snapshot", json={"persona": "alice"})

    commit = [timeout for name, timeout in seen if name == "commit"]
    assert commit == [sm.SNAPSHOT_TIMEOUT_SECONDS] and commit[0] == 300.0


def test_snapshot_repo_falls_back_to_the_code_default(client, fake) -> None:
    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["image"].startswith("ubuntu:alice-snap-")


def test_snapshot_refuses_a_bare_registry_repository(client, fake) -> None:
    """repo が空 or 末尾 / だとタグを付けられない。"""
    body = client.post("/snapshot", json={"persona": "alice", "image": "host:5000/"}).json()

    assert body["status"] == "error" and "repository" in body["stderr_tail"]
    assert not any(c[0] == "commit" for c in fake.calls)


def test_snapshot_stops_on_an_inspect_error(client, fake) -> None:
    fake.id_error = "permission denied while trying to connect to the Docker daemon socket"

    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["status"] == "error" and "permission denied" in body["stderr_tail"]
    assert not any(c[0] == "commit" for c in fake.calls)


def test_snapshot_without_a_container_is_an_error(client, fake) -> None:
    """snapshot は実在するマシンの状態保存。無ければ作らない。"""
    fake.not_found = True

    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["status"] == "error"
    assert not any(c[0] in {"commit", "run"} for c in fake.calls)


def test_snapshot_refuses_a_container_we_did_not_create(client, fake) -> None:
    fake.label = "<no value>"

    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["status"] == "error" and "sandbox" in body["stderr_tail"]
    assert not any(c[0] == "commit" for c in fake.calls)


def test_snapshot_commit_failure_is_an_error(client, fake) -> None:
    fake.by_subcommand["commit"] = (1, "", "no space left on device")

    body = client.post("/snapshot", json={"persona": "alice"}).json()

    assert body["status"] == "error" and "no space" in body["stderr_tail"]


@pytest.mark.parametrize(
    ("image", "repo"),
    [
        ("ubuntu:24.04", "ubuntu"),
        ("ghcr.io/solidlime/nous-sandbox:latest", "ghcr.io/solidlime/nous-sandbox"),
        ("host:5000/foo", "host:5000/foo"),
        ("host:5000/foo:1.0", "host:5000/foo"),
        ("ubuntu@sha256:abc", "ubuntu"),
    ],
)
def test_image_repo_strips_only_the_tag(image: str, repo: str) -> None:
    assert sm._image_repo(image) == repo


def test_restore_removes_the_container_and_recreates_it_from_the_image(client, fake) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json() == {"status": "ok"}
    # ID 指定で消す（inspect と rm の間に同名で作り直されても他人を消さない）。
    assert ("rm", "-f", "abc123def456") in fake.calls
    assert not any(c == ("rm", "-f", "alice-sandbox") for c in fake.calls)
    # rm の後に、要求された image で run する（既存 running を見て素通りしない）。
    names = [c[0] for c in fake.calls]
    assert names.index("rm") < names.index("run")
    assert next(c for c in fake.calls if c[0] == "run")[-3] == "alice-snap-1"


def test_restore_holds_the_ensure_lock_while_removing(client, fake) -> None:
    """rm と run の間に exec が差し込まれないこと（ensure ロックが復元中ずっと保持される）。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json() == {"status": "ok"}

    assert fake.rm_lock_held == [True]


def test_restore_passes_network_and_memory_to_run(client, fake, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_ALLOWED_NETWORKS", "sbx-net")
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    body = client.post(
        "/restore",
        json={"persona": "alice", "image": "alice-snap-1", "network": "sbx-net", "memory": "2g"},
    ).json()

    assert body == {"status": "ok"}
    run = next(c for c in fake.calls if c[0] == "run")
    assert run[run.index("--network") + 1] == "sbx-net"
    assert run[run.index("--memory") + 1] == "2g"


def test_restore_verifies_the_image_that_is_actually_running(client, fake) -> None:
    """run が古い running を掴んだ場合に ok を返さない。"""
    fake.by_subcommand["inspect"] = (0, "true 1\n", "")
    fake.running_image = "ubuntu:22.04"

    body = client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json()

    assert body["status"] == "error" and "ubuntu:22.04" in body["stderr_tail"]
    assert sm._in_flight == {}


def test_restore_without_an_image_keeps_the_error_contract(client, fake) -> None:
    """422 にすると {status:error} 契約が崩れるので、空 image は自分で弾く。"""
    res = client.post("/restore", json={"persona": "alice"})

    assert res.status_code == 200
    assert res.json()["status"] == "error"
    assert fake.calls == []


def test_restore_stops_on_an_inspect_error(client, fake) -> None:
    fake.id_error = "permission denied while trying to connect to the Docker daemon socket"

    body = client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json()

    assert body["status"] == "error" and "permission denied" in body["stderr_tail"]
    assert not any(c[0] in {"rm", "run"} for c in fake.calls)


def test_restore_reports_a_failed_recreate(client, fake) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (1, "", "pull access denied\n")

    body = client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json()

    assert body["status"] == "error" and "pull access denied" in body["stderr_tail"]
    assert any(c[0] == "rm" for c in fake.calls)


def test_restore_marks_last_used(client, fake) -> None:
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json() == {"status": "ok"}
    assert sm._last_used["alice"] > 0


def test_restore_without_a_container_only_creates_it(client, fake) -> None:
    fake.not_found = True
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")

    assert client.post("/restore", json={"persona": "alice", "image": "ubuntu:22.04"}).json() == {"status": "ok"}
    assert not any(c[0] == "rm" for c in fake.calls)
    assert "ubuntu:22.04" in next(c for c in fake.calls if c[0] == "run")


def test_restore_refuses_while_exec_runs(client, fake, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_in_flight", {})
    sm._enter("alice")

    body = client.post("/restore", json={"persona": "alice", "image": "ubuntu:24.04"}).json()

    assert body["status"] == "error" and "実行中" in body["stderr_tail"]
    assert not any(c[0] == "rm" for c in fake.calls)
    # 拒否経路で restore 自身が in_flight を足していない（exec の 1 本だけのまま）。
    assert sm._in_flight == {"alice": 1}
    sm._leave("alice")
    assert sm._in_flight == {}


def test_restore_refuses_a_container_we_did_not_create(client, fake) -> None:
    fake.label = "<no value>"

    body = client.post("/restore", json={"persona": "alice", "image": "ubuntu:24.04"}).json()

    assert body["status"] == "error" and "sandbox" in body["stderr_tail"]
    assert not any(c[0] == "rm" for c in fake.calls)


def test_restore_fails_when_rm_fails(client, fake) -> None:
    fake.by_subcommand["rm"] = (1, "", "cannot remove alice-sandbox")

    body = client.post("/restore", json={"persona": "alice", "image": "ubuntu:24.04"}).json()

    assert body["status"] == "error" and "cannot remove" in body["stderr_tail"]
    assert not any(c[0] == "run" for c in fake.calls)
    assert sm._in_flight == {}


def test_restore_reports_an_inspect_failure_after_run(client, fake) -> None:
    """事後検証の inspect が失敗したとき「ラベルが無い」と誤診しない。"""
    fake.by_subcommand["inspect"] = (1, "", "No such object")
    fake.by_subcommand["run"] = (0, "abc123\n", "")
    fake.verify_error = "permission denied while trying to connect to the Docker daemon socket"

    body = client.post("/restore", json={"persona": "alice", "image": "alice-snap-1"}).json()

    assert body["status"] == "error" and "inspect 失敗" in body["stderr_tail"]


@pytest.mark.parametrize("image", ["", "--privileged"])
def test_restore_requires_a_valid_image(client, fake, image: str) -> None:
    body = client.post("/restore", json={"persona": "alice", "image": image}).json()

    assert body["status"] == "error" and "image" in body["stderr_tail"]
    assert fake.calls == []


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


def test_idle_stop_skips_a_persona_with_a_running_exec(fake, monkeypatch) -> None:
    """exec 実行中に stop が着地すると、走り出したコンテナを止めて exec が失敗する。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    monkeypatch.setattr(sm, "_in_flight", {})
    now = time.time()
    sm._last_used["alice"] = now - 31 * 60
    sm._enter("alice")

    assert sm._stop_idle(now=now) == []
    assert not any(c[0] == "stop" for c in fake.calls)
    assert "alice" in sm._last_used


class _ProbedLastUsed(dict[str, float]):
    """``_last_used`` の読みが guard の内側で起きたかを記録する dict。"""

    def __init__(self, data: dict[str, float], reads: list[bool]) -> None:
        super().__init__(data)
        self.reads = reads

    def get(self, key: str, default: Any = None) -> Any:
        self.reads.append(sm._in_flight_guard.locked())
        return super().get(key, default)

    def setdefault(self, key: str, default: float = 0.0) -> float:
        self.reads.append(sm._in_flight_guard.locked())
        return super().setdefault(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        self.reads.append(sm._in_flight_guard.locked())
        return super().pop(key, default)


def test_idle_stop_reads_last_used_under_the_guard(fake, monkeypatch) -> None:
    """判定をループ入口のスナップショットへ戻すと、この assert が落ちる。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    reads: list[bool] = []
    monkeypatch.setattr(sm, "_last_used", _ProbedLastUsed({"alice": now - 31 * 60}, reads))
    fake.by_subcommand["stop"] = (0, "alice-sandbox\n", "")

    assert sm._stop_idle(now=now) == ["alice"]
    # 判定と compare-and-pop の両方。1 つでも guard の外なら False が混ざる。
    assert reads and all(reads)


def test_idle_stop_restarts_when_an_exec_starts_during_the_stop(fake, monkeypatch) -> None:
    """stop の隙間に始まった exec の記録を消すと、誰も idle 判定を持たない running が残る。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    reads: list[bool] = []
    monkeypatch.setattr(sm, "_last_used", _ProbedLastUsed({"alice": now - 31 * 60}, reads))
    fake.by_subcommand["stop"] = (0, "alice-sandbox\n", "")

    def _exec_starts() -> None:
        sm._last_used["alice"] = now

    fake.on_stop = _exec_starts

    assert sm._stop_idle(now=now) == []
    assert sm._last_used["alice"] == now
    # restart 分岐の setdefault も guard の内側。外へ動くと False が混ざる。
    assert reads and all(reads)
    assert ("start", "alice-sandbox") in fake.calls


def test_idle_stop_keeps_a_record_when_the_pop_already_happened(fake, monkeypatch) -> None:
    """並行スイープが記録を消し終えていた場合も、start で戻したコンテナを idle 判定に残す。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {"alice": now - 31 * 60})
    fake.by_subcommand["stop"] = (0, "alice-sandbox\n", "")
    fake.on_stop = lambda: sm._last_used.pop("alice", None)  # 並行スイープが pop し終えていた相当

    assert sm._stop_idle(now=now) == []
    assert sm._last_used["alice"] == now - 31 * 60  # setdefault が last に戻した値そのもの
    assert ("start", "alice-sandbox") in fake.calls


def test_missing_container_keeps_a_record_when_an_exec_starts_during_the_stop(fake, monkeypatch) -> None:
    """幽霊経路も、stop 中に使い始めた exec がいたら記録は消さず start もしない。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {"ghost": now - 31 * 60})
    fake.by_subcommand["stop"] = (1, "", "Error: No such container: ghost-sandbox")

    def _exec_starts() -> None:
        sm._last_used["ghost"] = now

    fake.on_stop = _exec_starts

    assert sm._stop_idle(now=now) == []
    assert sm._last_used["ghost"] == now
    assert not any(c[0] == "start" for c in fake.calls)


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


def test_exec_failure_expires_the_record_instead_of_dropping_it(client, fake, monkeypatch) -> None:
    """ensure 失敗で記録を消すと stop との交差で idle 判定から外れる。期限切れ 0.0 を残す。"""
    monkeypatch.setattr(sm, "_last_used", {})

    body = client.post("/exec", json={"persona": "alice", "command": "id", "network": "host"}).json()

    assert body["status"] == "error" and "network" in body["stderr_tail"]
    assert sm._last_used["alice"] == 0.0


def test_the_expired_record_is_collected_by_the_next_sweep(fake, monkeypatch) -> None:
    """exec 失敗が残した 0.0 は、次スイープが stop → pop で回収する。"""
    monkeypatch.setenv("SANDBOX_IDLE_MINUTES", "30")
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {"alice": 0.0})
    fake.by_subcommand["stop"] = (0, "alice-sandbox\n", "")

    assert sm._stop_idle(now=now) == ["alice"]
    assert "alice" not in sm._last_used


def test_exec_failure_keeps_a_newer_record_written_in_parallel(client, fake, monkeypatch) -> None:
    """ensure の遅い間に並行 exec が書いた新値を、0.0 の期限切れで上書きしない。"""
    now = time.time()
    monkeypatch.setattr(sm, "_last_used", {})

    def _slow_ensure(persona: str, **kwargs: Any) -> str:
        # 並行 exec が ensure の途中で成功し、新しい時刻を書いた状況の再現。
        sm._last_used[persona] = now + 1.0
        return "boom"

    monkeypatch.setattr(sm, "_ensure", _slow_ensure)

    body = client.post("/exec", json={"persona": "alice", "command": "id"}).json()

    assert body["status"] == "error"
    assert sm._last_used["alice"] == now + 1.0  # 0.0 で上書きされない


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


def test_old_non_root_container_warns_once(fake, monkeypatch) -> None:
    """旧 uid 運用（1026:100）のコンテナは root 前提の操作で書けない場所がある。"""
    warnings: list[str] = []
    monkeypatch.setattr(sm.logger, "warning", lambda fmt, *a: warnings.append(fmt % a))
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")
    fake.by_subcommand["inspect"] = (0, "true 1 1026:100\n", "")

    assert sm._ensure("alice") is None
    assert sm._ensure("alice") is None

    assert len(warnings) == 1 and "1026:100" in warnings[0]


def test_root_container_does_not_warn(fake, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(sm.logger, "warning", lambda fmt, *a: warnings.append(fmt % a))
    monkeypatch.setenv("SANDBOX_DNS_CHECK", "0")
    fake.by_subcommand["inspect"] = (0, "true 1 0:0\n", "")

    assert sm._ensure("alice") is None
    assert warnings == []


def test_write_log_is_left_at_the_default_mode(fake, monkeypatch, tmp_path: Path) -> None:
    """sandbox は root なので 0644 のまま読める。chmod は呼ばない。"""
    chmods: list[tuple] = []
    monkeypatch.setattr(sm.os, "chmod", lambda *a, **k: chmods.append(a))

    rel = sm._write_log("alice", "id", "out", "err")

    assert rel is not None
    assert chmods == []
    log = tmp_path / "container" / "persona" / "alice" / "workspace" / rel.split("/workspace/", 1)[1]
    assert log.is_file()
    assert os.access(log, os.R_OK) and os.access(log.parent, os.R_OK)
