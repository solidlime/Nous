"""ペルソナ専用サンドボックスコンテナの管理サービス。

docker sock を持つのはこのプロセスのみ。nous 本体は HTTP でここに exec を依頼する。
コンテナ名は必ず ``<persona>-sandbox``（素の persona はホストの他コンテナと衝突する）。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)

TAIL_LINES = 120
IDLE_CHECK_SECONDS = 30.0
EXEC_TIMEOUT_SECONDS = 60.0
EXEC_TIMEOUT_MAX = 600.0
# manager 再起動後、既存コンテナを idle 判定に載せるまでの猶予。
# now で初期化すると再起動のたびに idle が丸ごと延びる。
RESTART_GRACE_SECONDS = 300.0
PERSONA_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

# persona -> 最終利用 epoch 秒。idle 判定と /list の材料。
# shortcut: プロセス内メモリなので manager を複数レプリカにすると idle 判定が割れる。
#           1 レプリカ前提（compose も 1 サービス）。増やすなら外部ストアに置くこと。
_last_used: dict[str, float] = {}
# exec 実行中の persona と本数。idle 掃除が実行中のコンテナを止めないようにする。
_in_flight: dict[str, int] = {}
# persona -> idle 分（nous がペルソナ設定で上書きしたときだけ入る）
_idle_override: dict[str, float] = {}


TOKEN_HEADER = "X-Sandbox-Token"
# host / container: に繋ぐと nous の loopback や他コンテナへ抜けられる。
# 既定は none / bridge だけ。それ以外は SANDBOX_ALLOWED_NETWORKS に列挙する
# （カンマ区切り）。sandbox 間通信が要る環境だけ足す。
_FORBIDDEN_NETWORKS = frozenset({"host"})
_DEFAULT_NETWORKS = frozenset({"none", "bridge"})
_IMAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*")


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _allowed_networks() -> frozenset[str]:
    extra = {n.strip() for n in _env("SANDBOX_ALLOWED_NETWORKS", "").split(",") if n.strip()}
    return _DEFAULT_NETWORKS | extra


def _auth(x_sandbox_token: str = Header(default="")) -> None:
    """共有トークンを照合する。未設定なら 503（無認証で動かさない）。"""
    expected = _env("NOUS_SANDBOX_MANAGER_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="NOUS_SANDBOX_MANAGER_TOKEN is not set")
    if not secrets.compare_digest(x_sandbox_token, expected):
        raise HTTPException(status_code=401, detail="sandbox token mismatch")


def _enter(persona: str) -> None:
    _in_flight[persona] = _in_flight.get(persona, 0) + 1


def _leave(persona: str) -> None:
    left = _in_flight.get(persona, 0) - 1
    if left > 0:
        _in_flight[persona] = left
    else:
        _in_flight.pop(persona, None)


def _data_root() -> Path:
    """manager コンテナ内から見た /data。ログと rmtree に使う。"""
    return Path(_env("NOUS_DATA_ROOT", "/data"))


_host_root: Path | None = None


def _host_data_root() -> Path | None:
    """bind mount の source をホスト絶対パスで返す。解決できなければ None。

    ``docker run -v`` の source はデーモン（ホスト）側で解決されるので、
    コンテナ内の ``/data`` をそのまま渡すとホストの ``/data`` を指してしまう。
    自分の ``/data`` の実際のマウント元を docker に聞いて使う。

    解決できないまま ``-v /data/...`` を渡すと、デーモンがホスト直下に
    ``/data/persona/<p>/workspace`` を作り、sandbox は空の workspace を見る。
    警告1行では気づけないので fail closed にし、呼び出し側がエラーを返す。
    """
    global _host_root
    if _host_root is not None:
        return _host_root
    from_env = None
    env = _env("SANDBOX_HOST_DATA_ROOT", "").strip()
    # 相対パスを -v に渡すと docker は名前付きボリュームとして扱うので、絶対だけ採用する。
    if env and os.path.isabs(env):
        from_env = Path(env)
    from_inspect = _inspect_data_mount()
    # named volume の Source は絶対パスでなくボリューム名。そのまま -v に渡すと
    # デーモンが別の named volume として扱い、空の workspace を作ってしまう。
    if from_inspect is not None and not from_inspect.is_absolute():
        from_inspect = None
    if from_env and from_inspect and from_env.resolve() != from_inspect.resolve():
        logger.error(
            "SANDBOX_HOST_DATA_ROOT (%s) と /data のマウント元 (%s) が違う。mount を作らない",
            from_env,
            from_inspect,
        )
        return None
    chosen = from_env or from_inspect
    if chosen is None:
        logger.error(
            "host data root が解決できない。bind mount を作らない"
            "（SANDBOX_HOST_DATA_ROOT に絶対パスを設定するか、/data をマウントしたコンテナで動かす）",
        )
        return None
    _host_root = chosen
    return chosen


def _inspect_data_mount() -> Path | None:
    """自分のコンテナの /data のマウント元を docker に聞く。"""
    name = os.environ.get("HOSTNAME", "")
    if not name:
        return None
    proc, _ = _call(
        "inspect",
        "--format",
        '{{.Id}} {{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}',
        name,
        timeout=15.0,
    )
    if proc is None or proc.returncode != 0:
        return None
    cid, _, source = proc.stdout.strip().partition(" ")
    # HOSTNAME が自分を指していない（ホスト直起動で同名コンテナがある等）なら採用しない。
    if not source or not cid.startswith(name):
        return None
    return Path(source)


def _container(persona: str) -> str:
    return f"{persona}-sandbox"


# shell.py と同じ切り詰め。あちらの _tail を import すると chat ツール一式
# （builtin/definitions 経由で約 2.6 秒）をこのサービスに引き込むので写している。
def _tail(text: str, limit: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text, False
    return "\n".join(lines[-limit:]), True


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)


def _call(*args: str, timeout: float = 60.0) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """_docker を包んで、docker 未導入 / タイムアウトをエラーメッセージに落とす。"""
    try:
        return _docker(*args, timeout=timeout), None
    except FileNotFoundError:
        return None, "docker が見つからない（未導入、または PATH に無い）"
    except OSError as exc:
        return None, f"docker を実行できない: {exc}"
    except subprocess.TimeoutExpired:
        return None, f"docker {args[0]} が {timeout:.0f} 秒でタイムアウトした"


def _missing(stderr: str) -> bool:
    """docker が「そのコンテナは無い」と言っているか（権限エラーと混ぜない）。"""
    text = stderr.lower()
    return "no such object" in text or "no such container" in text


DNS_CHECK_TIMEOUT_SECONDS = 10.0


def _check_dns(container: str, timeout: float = DNS_CHECK_TIMEOUT_SECONDS) -> str | None:
    """コンテナ内から nous を名前解決できるか。できなければ理由を返す。

    既定 bridge では Docker の埋め込み DNS が効かず、nous は引けない。
    引けないまま exec を返すと「繋がらない」だけの静かな壊れ方になるので、
    ensure の段階で理由を返す（``SANDBOX_DNS_CHECK=0`` で skip）。
    """
    proc, err = _call("exec", container, "getent", "hosts", "nous", timeout=timeout)
    if proc is None:
        return err or "docker exec failed"
    if proc.returncode == 0:
        return None
    detail = (proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}").splitlines()[0]
    return f"{container} から nous を名前解決できない（SANDBOX_NETWORK を確認する）: {detail}"


def _post_start_check(container: str) -> str | None:
    if _env("SANDBOX_DNS_CHECK", "1") in {"0", "false", "no"}:
        return None
    return _check_dns(container)


APT_EXTRA_TIMEOUT_SECONDS = 300.0
_PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9+.-]{0,63}")


def _apt_extra() -> list[str]:
    """イメージに焼いていないパッケージ（``SANDBOX_APT_EXTRA``、カンマ区切り）。"""
    raw = os.environ.get("SANDBOX_APT_EXTRA", "")
    names = [p.strip() for p in raw.split(",") if p.strip()]
    valid = [p for p in names if _PACKAGE_RE.fullmatch(p)]
    if len(valid) != len(names):
        # apt に余計な引数を解釈させない（オプションを紛れ込ませない）。
        logger.warning("SANDBOX_APT_EXTRA に不正なパッケージ名: %s", [p for p in names if p not in valid])
    return valid


def _install_missing(container: str, packages: list[str]) -> list[str]:
    """コンテナに無いパッケージだけ apt で足す。失敗は警告に落とす（run は殺さない）。

    全部を焼くとイメージの rebuild が重くなるので、変化の速いものだけ起動時に足す。
    全部入っていれば dpkg を叩くだけで終わる。
    """
    missing: list[str] = []
    for pkg in packages:
        proc, err = _call("exec", container, "dpkg", "-s", pkg, timeout=15.0)
        if proc is not None and proc.returncode == 0:
            continue
        if proc is None:
            logger.warning("dpkg -s %s in %s failed: %s", pkg, container, err)
        missing.append(pkg)
    if not missing:
        return []
    script = (
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update && apt-get install -y --no-install-recommends " + " ".join(missing)
    )
    proc, err = _call("exec", container, "bash", "-lc", script, timeout=APT_EXTRA_TIMEOUT_SECONDS)
    if proc is None:
        logger.warning("sandbox apt install failed (%s): %s", container, err)
        return []
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        detail = lines[0] if lines else f"exit {proc.returncode}"
        logger.warning("sandbox apt install failed (%s): %s", container, detail[:300])
        return []
    logger.info("sandbox apt install (%s): %s", container, ", ".join(missing))
    return missing


def _post_run(container: str) -> str | None:
    """run 直後の面倒。戻り値に載るのは DNS の失敗だけ（apt は警告で済ませる）。"""
    dns_err = _post_start_check(container)
    if dns_err:
        return dns_err
    extra = _apt_extra()
    if extra:
        _install_missing(container, extra)
    return None


def _persona(raw: str) -> str:
    if not PERSONA_RE.fullmatch(raw):
        raise HTTPException(status_code=400, detail=f"invalid persona: {raw!r}")
    return raw


def _failure(message: str) -> dict:
    return {
        "status": "error",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": message,
        "truncated": False,
        "log_path": None,
    }


_ensure_locks: dict[str, threading.Lock] = {}
_ensure_locks_guard = threading.Lock()


def _ensure_lock(persona: str) -> threading.Lock:
    with _ensure_locks_guard:
        return _ensure_locks.setdefault(persona, threading.Lock())


def _ensure(
    persona: str,
    image: str | None = None,
    network: str | None = None,
    memory: str | None = None,
) -> str | None:
    """同じ persona の同時 ensure を直列化する（初回 run の名前衝突を防ぐ）。"""
    with _ensure_lock(persona):
        return _ensure_inner(persona, image=image, network=network, memory=memory)


def _ensure_inner(
    persona: str,
    image: str | None = None,
    network: str | None = None,
    memory: str | None = None,
) -> str | None:
    """コンテナを running にする。失敗理由を返す（成功なら None）。"""
    net = network or _env("SANDBOX_NETWORK", "bridge")
    if net in _FORBIDDEN_NETWORKS or net.startswith("container:"):
        return f"network {net!r} は使えない（host / container: は拒否）"
    if net not in _allowed_networks():
        return f"network {net!r} は許可されていない（SANDBOX_ALLOWED_NETWORKS で追加する）"
    img = image or _env("SANDBOX_IMAGE", "ubuntu:24.04")
    if not _IMAGE_RE.fullmatch(img):
        return f"image {img!r} が不正"
    name = _container(persona)
    inspected, err = _call(
        "inspect",
        "--format",
        '{{.State.Running}} {{index .Config.Labels "com.nous.sandbox"}}',
        name,
        timeout=30.0,
    )
    if inspected is None:
        return err or "docker inspect failed"
    if inspected.returncode == 0:
        running, _, label = inspected.stdout.strip().partition(" ")
        # 名前だけで他人のコンテナを exec しない。自分が作ったものだけ触る。
        if label.strip() != "1":
            return f"{name} は nous の sandbox ではない（com.nous.sandbox ラベルが無い）"
        if running == "true":
            return None
        started, err = _call("start", name)
        if started is None:
            return err or "docker start failed"
        if started.returncode != 0:
            return started.stderr.strip() or "docker start failed"
        return _post_start_check(name)

    detail = inspected.stderr.strip()
    if not _missing(detail):
        # sock の権限エラーなど。「無い」と決めつけて run すると原因が隠れる。
        return f"docker inspect 失敗: {detail or 'unknown error'}"

    home = f"/home/{persona}"
    root = _host_data_root()
    if root is None:
        return "host data root が解決できない（SANDBOX_HOST_DATA_ROOT に絶対パスを設定する）"
    mounts = [
        (root / "persona" / persona / "workspace", f"{home}/workspace", False),
        (root / "persona" / persona / "skills", f"{home}/.agents/skills", False),
        (root / "skills", f"{home}/.agents/global-skills", True),
    ]
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "com.docker.compose.project=nous-sandbox",
        "--label",
        f"com.docker.compose.service=sbx-{persona}",
        "--label",
        "com.nous.sandbox=1",
        "--memory",
        memory or _env("SANDBOX_MEMORY", "4g"),
        # Synology の 4.4 カーネルには CFS quota が無く、--cpus で run が失敗する。
        # cpu-shares は重み付け（制限ではない）で旧カーネルでも通る。
        "--cpu-shares",
        "512",
        "--pids-limit",
        "1024",
        "--security-opt",
        "no-new-privileges",
        "--network",
        net,
    ]
    local = _data_root()
    for host, target, read_only in mounts:
        # mkdir は自分のマウントから見えるパスで行う。host 側の絶対パスは
        # ホストの名前空間のもので、このコンテナからは触れない。
        try:
            (local / host.relative_to(root)).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"ホスト側ディレクトリを作れない: {host}: {e}"
        args += ["-v", f"{host}:{target}" + (":ro" if read_only else "")]
    args += [
        "-e",
        f"HOME={home}",
        "-e",
        f"TZ={os.environ.get('SANDBOX_TZ') or os.environ.get('TZ') or 'UTC'}",
        # persona 側は UTF-8 前提。POSIX に落ちると Python が ASCII になる。
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "LC_ALL=C.UTF-8",
    ]
    # イメージの git config --system は persona / persona@nous.local。
    # commit の author と committer を両方 env で上書きしないと片方だけ残る。
    for env_name, git_key in (("SANDBOX_GIT_USER_NAME", "NAME"), ("SANDBOX_GIT_USER_EMAIL", "EMAIL")):
        value = os.environ.get(env_name, "").strip()
        if value:
            args += [
                "-e",
                f"GIT_AUTHOR_{git_key}={value}",
                "-e",
                f"GIT_COMMITTER_{git_key}={value}",
            ]
    args += [
        "--workdir",
        home,
        img,
        "sleep",
        "infinity",
    ]

    ran, err = _call(*args, timeout=180.0)
    if ran is None:
        return err or "docker run failed"
    if ran.returncode != 0:
        return ran.stderr.strip() or "docker run failed"
    return _post_run(name)


def _write_log(persona: str, command: str, stdout: str, stderr: str) -> str | None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = _data_root() / "sandbox" / persona / "logs" / f"{stamp}.log"
    body = f"$ {command}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError:
        logger.warning("sandbox log write failed: %s", path, exc_info=True)
        return None
    return str(path)


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, UTC).isoformat()


def _idle_minutes() -> float:
    try:
        return max(1.0, float(_env("SANDBOX_IDLE_MINUTES", "30")))
    except ValueError:
        return 30.0


def _exec_timeout(seconds: float | None, idle_minutes: float) -> float:
    # idle 掃除が exec の途中で SIGTERM を打たないよう、idle より短く抑える。
    limit = min(EXEC_TIMEOUT_MAX, max(1.0, idle_minutes * 60.0 - 1.0))
    if seconds is None:
        return min(EXEC_TIMEOUT_SECONDS, limit)
    return max(1.0, min(limit, seconds))


def _stop_idle(now: float | None = None) -> list[str]:
    """アイドル超過のコンテナを stop する（rm しない）。停止した persona を返す。"""
    now = time.time() if now is None else now
    stopped: list[str] = []
    for persona, last in list(_last_used.items()):
        if persona in _in_flight:
            continue
        minutes = _idle_override.get(persona, _idle_minutes())
        if last >= now - minutes * 60.0:
            continue
        proc, err = _call("stop", _container(persona))
        if proc is None:
            logger.warning("sandbox stop failed: %s %s", persona, err)
            continue
        if proc.returncode != 0:
            if _missing(proc.stderr):
                # 運用者が手で消した等。幽霊を毎回 stop しに行かない。
                _last_used.pop(persona, None)
                continue
            logger.warning("sandbox stop failed: %s %s", persona, proc.stderr.strip())
            continue
        _last_used.pop(persona, None)
        stopped.append(persona)
    return stopped


def _load_existing() -> None:
    """起動時に既存の running コンテナを拾って last_used を now で初期化する。"""
    proc, err = _call("ps", "--filter", "label=com.nous.sandbox=1", "--format", "{{.Names}}")
    if proc is None:
        logger.warning("sandbox initial scan skipped: %s", err)
        return
    if proc.returncode != 0:
        logger.warning("sandbox initial scan skipped: %s", proc.stderr.strip())
        return
    now = time.time()
    # 再起動のたびに idle を持ち越さないよう、「grace 秒後に idle 判定へ入る」時刻を入れる。
    grace = min(RESTART_GRACE_SECONDS, _idle_minutes() * 30.0)
    for name in proc.stdout.split():
        if name.endswith("-sandbox"):
            _last_used[name[: -len("-sandbox")]] = now - _idle_minutes() * 60.0 + grace


async def _idle_loop() -> None:
    while True:
        await asyncio.sleep(IDLE_CHECK_SECONDS)
        try:
            await asyncio.to_thread(_stop_idle)
        except Exception:
            logger.warning("sandbox idle sweep failed", exc_info=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(_load_existing)
    task = asyncio.create_task(_idle_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="nous-sandbox-manager", lifespan=lifespan)


class ExecRequest(BaseModel):
    persona: str
    command: str
    cwd: str | None = None
    timeout_seconds: float | None = None
    image: str | None = None
    network: str | None = None
    memory: str | None = None
    idle_minutes: float | None = None


class PersonaRequest(BaseModel):
    persona: str
    image: str | None = None
    network: str | None = None
    memory: str | None = None
    idle_minutes: float | None = None


@app.post("/exec", dependencies=[Depends(_auth)])
def exec_in_sandbox(req: ExecRequest) -> dict:
    persona = _persona(req.persona)
    if not req.command.strip():
        raise HTTPException(status_code=400, detail="command が空")
    # 実行中に idle 掃除が SIGTERM を打たないよう、ensure より先に印を付ける。
    if req.idle_minutes and req.idle_minutes > 0:
        _idle_override[persona] = max(1.0, min(600.0, req.idle_minutes))
    _last_used[persona] = time.time()
    _enter(persona)
    try:
        err = _ensure(persona, image=req.image, network=req.network, memory=req.memory)
        if err:
            # 失敗したコンテナを idle 掃除が stop し続けないよう、記録も消す。
            _last_used.pop(persona, None)
            return _failure(err)
        args = ["exec"]
        if req.cwd:
            args += ["-w", req.cwd]
        limit = _exec_timeout(req.timeout_seconds, _idle_override.get(persona, _idle_minutes()))
        # 外側の subprocess timeout だけだとコンテナ内のプロセスが残る。
        # 内側で timeout(1) を噛ませ、打ち切ったら exit 124 で返す。
        args += [
            _container(persona),
            "timeout",
            "-k",
            "5",
            str(max(1, int(limit))),
            "bash",
            "-lc",
            req.command,
        ]
        proc, err = _call(*args, timeout=limit + 10.0)
    finally:
        _leave(persona)
    if proc is None:
        return _failure(f"{err or 'docker exec failed'}（コンテナ内では継続中の可能性がある）")

    stdout_tail, out_cut = _tail(proc.stdout, TAIL_LINES)
    stderr_tail, err_cut = _tail(proc.stderr, TAIL_LINES)
    _last_used[persona] = time.time()
    return {
        "status": "ok" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "truncated": out_cut or err_cut,
        "log_path": _write_log(persona, req.command, proc.stdout, proc.stderr),
    }


@app.post("/reset", dependencies=[Depends(_auth)])
def reset_sandbox(req: PersonaRequest) -> dict:
    persona = _persona(req.persona)
    if persona in _in_flight:
        return _failure(f"{persona} は実行中（exec の終了後に reset する）")
    # 消す前に、_ensure と同じ「マウント元が解決できるか」を確かめる。
    if _host_data_root() is None:
        return _failure("host data root が解決できない（SANDBOX_HOST_DATA_ROOT に絶対パスを設定する）")
    name = _container(persona)
    fmt = '{{.Id}} {{index .Config.Labels "com.nous.sandbox"}}'
    state, err = _call("inspect", "--format", fmt, name, timeout=30.0)
    if state is None:
        return _failure(err or "docker inspect failed")
    if state.returncode == 0:
        # 名前でなく ID で消す（inspect と rm の間に同名で作り直されても消さない）。
        cid, _, label = state.stdout.strip().partition(" ")
        if not cid:
            return _failure(f"{name} の ID が取れない")
        # 名前だけ一致する他人のコンテナを消さない。
        if label.strip() != "1":
            return _failure(f"{name} は nous の sandbox ではない（com.nous.sandbox ラベルが無い）")
        removed, err = _call("rm", "-f", cid)
        if removed is None:
            return _failure(err or "docker rm failed")
        if removed.returncode != 0 and not _missing(removed.stderr):
            return _failure(removed.stderr.strip() or "docker rm failed")
    elif not _missing(state.stderr):
        return _failure(f"docker inspect 失敗: {state.stderr.strip() or 'unknown error'}")
    # 消すのはマウント元の workspace。ログと資材は残す。
    workspace = _data_root() / "persona" / persona / "workspace"
    if workspace.exists():
        try:
            shutil.rmtree(workspace)
        except OSError:
            # 消せていないのに ok を返さない（旧 workspace が残ったまま「リセット済み」にしない）。
            logger.warning("sandbox workspace reset failed: %s", workspace, exc_info=True)
            return _failure(f"workspace を消せない: {workspace}")
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _failure(f"workspace を作れない: {workspace}: {exc}")
    _last_used.pop(persona, None)
    if req.idle_minutes and req.idle_minutes > 0:
        _idle_override[persona] = max(1.0, min(600.0, req.idle_minutes))

    err = _ensure(persona, image=req.image, network=req.network, memory=req.memory)
    if err:
        return _failure(err)
    _last_used[persona] = time.time()
    return {"status": "ok"}


@app.get("/list", dependencies=[Depends(_auth)])
def list_sandboxes() -> dict:
    proc, err = _call("ps", "-a", "--filter", "label=com.nous.sandbox=1", "--format", "{{.Names}}\t{{.State}}")
    if proc is None or proc.returncode != 0:
        return {"sandboxes": [], "error": err or (proc.stderr.strip() if proc else "docker ps failed")}
    sandboxes = []
    for line in proc.stdout.splitlines():
        name, _, state = line.partition("\t")
        if not name.endswith("-sandbox"):
            continue
        persona = name[: -len("-sandbox")]
        sandboxes.append(
            {
                "persona": persona,
                "container": name,
                "running": state.strip() == "running",
                "last_used": _iso(_last_used.get(persona)),
            }
        )
    return {"sandboxes": sandboxes}


@app.post("/touch", dependencies=[Depends(_auth)])
def touch_sandbox(req: PersonaRequest) -> dict:
    _last_used[_persona(req.persona)] = time.time()
    return {"status": "ok"}


@app.get("/health")
def health() -> dict:
    # HTTP が上がっているだけでは意味がない。sock が死んでいれば degraded を返す。
    proc, err = _call("version", "--format", "{{.Server.Version}}", timeout=5.0)
    if proc is None or proc.returncode != 0:
        return {"status": "degraded", "docker": err or (proc.stderr.strip() if proc else "unavailable")}
    return {"status": "ok", "docker": proc.stdout.strip()}


if __name__ == "__main__":
    import uvicorn

    # compose ネットワーク内にだけ出す（host 公開はしない）。ホストで直接動かすなら
    # SANDBOX_MANAGER_HOST=127.0.0.1 を渡す。
    uvicorn.run(app, host=os.environ.get("SANDBOX_MANAGER_HOST", "0.0.0.0"), port=8080)
