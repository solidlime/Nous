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
# IANA ゾーン名（Asia/Tokyo, UTC, Etc/GMT-9 など）。bash スクリプトに埋め込む前に通す。
_TZ_RE = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _tz() -> str:
    """sandbox に渡す TZ。個別上書き（SANDBOX_TZ）→ Nous 設定の timezone。

    Nous 設定（``NOUS_TIMEZONE`` env / ``.env``、既定 Asia/Tokyo）がそのまま
    sandbox に引き継がれる。settings の import は _tz() 内 — 循環回避と、
    TZ が不要な経路（status / stop / exec）での起動コストのため。
    SANDBOX_TZ は bash スクリプトに埋め込む前ここで形状検証する（settings 側は
    available_timezones() 検証済み・SANDBOX_IMAGE は _IMAGE_RE 検証済みと対称に）。
    値は bash スクリプトに埋め込むので、生成元に関係なく**出口で**も同じ検証を通す
    — settings は RCM の setattr で field_validator を通らずに書き換わり得るため
    （manager プロセスに現状 RCM は無いが、_tz() は汎用なので defense in depth）。
    """
    zone = _env("SANDBOX_TZ", "")
    if zone and not _TZ_RE.fullmatch(zone):
        # 不正値を渡すと /etc/timezone 未書き込み＋glibc が TZ を捨てて UTC に
        # 落ちる — まさに潰したい「静かに壊れる」なので、警告して設定側に落とす。
        logger.warning("SANDBOX_TZ %r はゾーン名の形ではない。Nous 設定側を使う", zone)
        zone = ""
    if not zone:
        try:
            from nous.config.settings import get_settings

            zone = get_settings().timezone or "UTC"
        except Exception:  # 設定不備で /exec を 500 にしない — 文字列エラー契約を守る
            logger.warning("settings の読み込みに失敗。sandbox の TZ は UTC に落ちる", exc_info=True)
            zone = "UTC"
    if not isinstance(zone, str) or not _TZ_RE.fullmatch(zone):
        logger.warning("sandbox TZ %r は不正な形。UTC に落とす", zone)
        return "UTC"
    return zone


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


_in_flight_guard = threading.Lock()


def _enter(persona: str) -> None:
    # _enter_exclusive の排他判定と同じ dict を触るので、guard 内で加算する。
    with _in_flight_guard:
        _in_flight[persona] = _in_flight.get(persona, 0) + 1


def _leave(persona: str) -> None:
    with _in_flight_guard:
        left = _in_flight.get(persona, 0) - 1
        if left > 0:
            _in_flight[persona] = left
        else:
            _in_flight.pop(persona, None)


def _enter_exclusive(persona: str) -> bool:
    """in_flight が空でなければ False。空なら自分が 1 として入って True。"""
    with _in_flight_guard:
        if _in_flight.get(persona, 0) > 0:
            return False
        _in_flight[persona] = 1
        return True


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


def _mount_specs(root: Path, persona: str) -> list[tuple[Path, str, bool]]:
    """sandbox に見せるディレクトリ。(host, target, read_only)

    ペルソナが読める場所だけを見せる。memory.sqlite や config.json は見せない
    （壊されると復旧できない）。media は nous が書く生成物なので ro。
    """
    home = "/home/agent"
    return [
        (root / "persona" / persona / "workspace", f"{home}/workspace", False),
        (root / "persona" / persona / "wiki", f"{home}/wiki", False),
        (root / "persona" / persona / "uploads", f"{home}/uploads", False),
        (root / "persona" / persona / "media", f"{home}/media", True),
        (root / "persona" / persona / "skills", f"{home}/.agents/skills", False),
        (root / "skills", f"{home}/.agents/global-skills", True),
    ]


# 旧 uid 運用（1026:100）のコンテナは root 前提の操作で書けない場所がある。
# 毎 exec ではなく、コンテナごとに 1 回だけ警告する。
_user_warned: set[str] = set()


def _warn_non_root(container: str, user: str | None) -> None:
    spec = (user or "").strip()
    if not spec or spec in {"0", "0:0"} or container in _user_warned:
        return
    _user_warned.add(container)
    logger.warning(
        "sandbox が root で動いていない（root 前提の運用では書けない場所がある）: %s user=%s", container, spec
    )


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
    # 旧 1026 コンテナも動くので、apt は uid に依らず root で打つ。
    proc, err = _call("exec", "-u", "0", container, "bash", "-lc", script, timeout=APT_EXTRA_TIMEOUT_SECONDS)
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


def _apply_timezone(container: str) -> None:
    """/etc/timezone と /etc/localtime を Nous 設定の TZ に揃える（新規作成時のみ）。

    ``-e TZ=`` だけだと /etc/timezone を読む物が Etc/UTC 扱いになる
    （requirements-herta §3 の「静かに壊れる」系）。zoneinfo が無ければ
    silent skip — 失敗は警告で済み、run は殺さない（_install_missing と同じ方針）。
    """
    zone = _tz()
    script = (
        f'[ -f "/usr/share/zoneinfo/{zone}" ] '
        rf'&& printf "%s\n" "{zone}" > /etc/timezone '
        f'&& ln -sf "/usr/share/zoneinfo/{zone}" /etc/localtime'
    )
    proc, err = _call("exec", "-u", "0", container, "bash", "-lc", script, timeout=15.0)
    if proc is None:
        logger.warning("sandbox tz setup failed (%s): %s", container, err)
        return
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:300]
        logger.warning("sandbox tz setup failed (%s): %s", container, detail or f"exit {proc.returncode}")


def _post_run(container: str) -> str | None:
    """run 直後の面倒。戻り値に載るのは DNS の失敗だけ（tz・apt は警告で済ませる）。"""
    # run 直後は必ず新規コンテナ。外部の docker rm で作り直された場合も
    # ここを通るので、root 以外の警告キャッシュはここで捨てる。
    _user_warned.discard(container)
    # DNS 失敗でも tz は付けておく（新規作成はここを 1 回しか通らない）。
    _apply_timezone(container)
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


def _container_id(name: str) -> tuple[str | None, str | None]:
    """既存コンテナの ID とラベルを inspect で確かめる。(ID, エラー)。両方 None は不在。"""
    fmt = '{{.Id}} {{index .Config.Labels "com.nous.sandbox"}}'
    state, err = _call("inspect", "--format", fmt, name, timeout=30.0)
    if state is None:
        return None, err or "docker inspect failed"
    if state.returncode != 0:
        if _missing(state.stderr):
            return None, None
        # sock の権限エラーなど。「無い」と決めつけると原因が隠れる。
        return None, f"docker inspect 失敗: {state.stderr.strip() or 'unknown error'}"
    cid, _, label = state.stdout.strip().partition(" ")
    if not cid:
        return None, f"{name} の ID が取れない"
    # 名前だけ一致する他人のコンテナを掴まない。
    if label.strip() != "1":
        return None, f"{name} は nous の sandbox ではない（com.nous.sandbox ラベルが無い）"
    return cid, None


def _image_repo(image: str) -> str:
    """tag と digest を剥がして repository 部だけ残す（port 付き registry 対応）。"""
    repo = image.split("@", 1)[0]
    head, sep, tail = repo.rpartition("/")
    # host:5000/foo の ``:`` を剥がすと repository でなくなるので、``/`` 以降だけ見る。
    return head + sep + tail.rsplit(":", 1)[0]


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
        '{{.State.Running}} {{index .Config.Labels "com.nous.sandbox"}} {{.Config.User}}',
        name,
        timeout=30.0,
    )
    if inspected is None:
        return err or "docker inspect failed"
    if inspected.returncode == 0:
        running, _, rest = inspected.stdout.strip().partition(" ")
        label, _, user = rest.partition(" ")
        # 名前だけで他人のコンテナを exec しない。自分が作ったものだけ触る。
        if label.strip() != "1":
            return f"{name} は nous の sandbox ではない（com.nous.sandbox ラベルが無い）"
        _warn_non_root(name, user)
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

    home = "/home/agent"
    root = _host_data_root()
    if root is None:
        return "host data root が解決できない（SANDBOX_HOST_DATA_ROOT に絶対パスを設定する）"
    # ペルソナが読める場所だけを見せる。memory.sqlite や config.json は
    # 見せない（壊されると復旧できない）。media は nous が書く生成物なので ro。
    mounts = _mount_specs(root, persona)
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
        # root で走らせる（ペルソナ専用マシン）。apt / mount 不可の制限は docs/sandbox.md 参照。
        "--user",
        "0:0",
        "--network",
        net,
    ]
    local = _data_root()
    for host, target, read_only in mounts:
        # mkdir は自分のマウントから見えるパスで行う。host 側の絶対パスは
        # ホストの名前空間のもので、このコンテナからは触れない。
        try:
            target_dir = local / host.relative_to(root)
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"ホスト側ディレクトリを作れない: {host}: {e}"
        args += ["-v", f"{host}:{target}" + (":ro" if read_only else "")]
    args += [
        "-e",
        f"HOME={home}",
        "-e",
        f"TZ={_tz()}",
        # persona 側は UTF-8 前提。POSIX に落ちると Python が ASCII になる。
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "LC_ALL=C.UTF-8",
    ]
    # git identity の上書き（SANDBOX_GIT_USER_NAME / _EMAIL）。素 ubuntu には git 自体
    # 無い — ペルソナが自分で入れた git が commit 時にこの GIT_AUTHOR_*/COMMITTER_* を拾う。
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


CONTAINER_WORKSPACE = "/home/agent/workspace"
LOG_DIR = ".nous/logs"


def _write_log(persona: str, command: str, stdout: str, stderr: str) -> str | None:
    """全文ログをワークスペース内に落とし、コンテナから読めるパスを返す。

    マウント外（旧 ``{DATA_ROOT}/sandbox/<persona>/logs``）に置くと ``read_file``
    の境界（``resolve_in_workspace``）の外なので、``log_path`` が空約束になる。
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = _data_root() / "persona" / persona / "workspace" / LOG_DIR / f"{stamp}.log"
    body = f"$ {command}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # sandbox は root なので 0644 のまま読める。world-writable を残す理由が無い。
        path.write_text(body, encoding="utf-8")
    except OSError:
        logger.warning("sandbox log write failed: %s", path, exc_info=True)
        return None
    return f"{CONTAINER_WORKSPACE}/{LOG_DIR}/{stamp}.log"


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


def _forget_stopped(persona: str, last: float, restart: bool = True) -> bool:
    """stop 後の compare-and-pop。記録を消したら True を返す。

    stop の実行中（最大 10 秒）に exec が ``_last_used`` を上げていたら、その記録は
    消さない。消すと誰も idle 判定を持たない running コンテナが残る。ensure 失敗の
    exec は記録を消さず 0.0（期限切れセンチネル）を書くので、ここは stop 自身の
    pop とだけ compare する。``last`` への setdefault は、この窓で記録が消えて
    しまっていた場合の防御。使い始めた exec は ensure を通過済みで拾い直せない
    ので、``restart=True`` のときは ``start`` で戻す。幽霊（missing）経路は
    コンテナが無いので ``restart=False``。
    """
    with _in_flight_guard:
        if _in_flight.get(persona, 0) > 0 or _last_used.get(persona) != last:
            # 記録が消えていたら ``last`` で復元する（無いと idle 判定から永久に外れる）。
            _last_used.setdefault(persona, last)
        else:
            _last_used.pop(persona, None)
            return True
    if not restart:
        return False
    # 戻しに失敗しても warning だけ。exec の次回 ensure が start する。
    proc, err = _call("start", _container(persona))
    if proc is None:
        logger.warning("sandbox restart after stop failed: %s %s", persona, err)
    elif proc.returncode != 0:
        logger.warning("sandbox restart after stop failed: %s %s", persona, proc.stderr.strip())
    return False


def _stop_idle(now: float | None = None) -> list[str]:
    """アイドル超過のコンテナを stop する（rm しない）。停止した persona を返す。"""
    now = time.time() if now is None else now
    stopped: list[str] = []
    for persona in list(_last_used):
        # 判定と _in_flight / _last_used の読みを同じ guard で行う。ループ入口の
        # last を使い回すと、exec が _last_used を上げた直後に stop を着地させてしまう。
        with _in_flight_guard:
            if _in_flight.get(persona, 0) > 0:
                continue
            last = _last_used.get(persona)
            if last is None or last >= now - _idle_override.get(persona, _idle_minutes()) * 60.0:
                continue
        # shortcut: stop 自体は guard の外（最大 10 秒）。その隙間に始まった exec は
        #           下の compare-and-pop で検出して start で戻す。取りこぼすのは
        #           この判定〜pop の間に始まり、かつ stop が成功しなかった場合だけ
        #           （exec 側の次回 ensure が拾う）。
        proc, err = _call("stop", _container(persona))
        if proc is None:
            logger.warning("sandbox stop failed: %s %s", persona, err)
            continue
        if proc.returncode != 0:
            if _missing(proc.stderr):
                # 運用者が手で消した等。幽霊を毎回 stop しに行かない（コンテナが無いので
                # start 戻しはしない）。
                _forget_stopped(persona, last, restart=False)
                continue
            logger.warning("sandbox stop failed: %s %s", persona, proc.stderr.strip())
            continue
        # compare-and-pop。stop 中に誰かが使い始めていたら記録は消さず start で戻す。
        if _forget_stopped(persona, last):
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


class RestoreRequest(BaseModel):
    persona: str
    # 必須にすると FastAPI が 422 を返し {status:"error"} 契約を破る。空は _IMAGE_RE が弾く。
    image: str = ""
    # 消す前の network/memory を引き継がないと、復元直後に既定値で run し直すことになる。
    network: str | None = None
    memory: str | None = None


@app.post("/exec", dependencies=[Depends(_auth)])
def exec_in_sandbox(req: ExecRequest) -> dict:
    persona = _persona(req.persona)
    if not req.command.strip():
        raise HTTPException(status_code=400, detail="command が空")
    # 実行中に idle 掃除が SIGTERM を打たないよう、ensure より先に印を付ける。
    if req.idle_minutes and req.idle_minutes > 0:
        _idle_override[persona] = max(1.0, min(600.0, req.idle_minutes))
    mine = time.time()
    _last_used[persona] = mine
    _enter(persona)
    try:
        err = _ensure(persona, image=req.image, network=req.network, memory=req.memory)
        if err:
            # 記録は消さず期限切れ扱いにする。消すと stop と交差した際に、
            # start で戻したコンテナが idle 判定から外れる（次スイープが stop → pop）。
            # 0.0 は mine がまだ現値のときだけ書く。ensure の遅い間に並行 exec が
            # 新しい時刻を書いていたら、そちらを壊さない。
            # shortcut: compare と代入は不可分でない。潰れるのは並行 exec の新値だが、
            # stop/start 1回で済むので全永続運用では無害。厳密に守るなら全 writer を lock する。
            if _last_used.get(persona) == mine:
                _last_used[persona] = 0.0
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


SNAPSHOT_TIMEOUT_SECONDS = 300.0


@app.post("/snapshot", dependencies=[Depends(_auth)])
def snapshot_sandbox(req: PersonaRequest) -> dict:
    persona = _persona(req.persona)
    name = _container(persona)
    cid, err = _container_id(name)
    if err:
        return _failure(err)
    if cid is None:
        # snapshot は「実在するマシンの状態保存」。無ければ作らない。
        return _failure(f"{name} が無い（snapshot は実在するコンテナにだけ取れる）")
    base = req.image or _env("SANDBOX_IMAGE", "ubuntu:24.04")
    if not _IMAGE_RE.fullmatch(base):
        return _failure(f"image {base!r} が不正")
    repo = _image_repo(base)
    # repo が空・末尾 / だと commit は失敗する方向にしか倒れないので、ここで止める。
    if not repo or repo.endswith("/"):
        return _failure(f"image {base!r} の repository 部が不正")
    image = f"{repo}:{persona}-snap-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
    # --pause=false: commit 中も exec を止めない。瞬間の整合性は保証しない（docs 参照）。
    proc, err = _call("commit", "--pause=false", cid, image, timeout=SNAPSHOT_TIMEOUT_SECONDS)
    if proc is None:
        return _failure(err or "docker commit failed")
    if proc.returncode != 0:
        return _failure(proc.stderr.strip() or "docker commit failed")
    return {"status": "ok", "image": image}


@app.post("/restore", dependencies=[Depends(_auth)])
def restore_sandbox(req: RestoreRequest) -> dict:
    persona = _persona(req.persona)
    if not _IMAGE_RE.fullmatch(req.image or ""):
        return _failure(f"image {req.image!r} が不正")
    name = _container(persona)
    # idle 掃除が復元途中のコンテナを stop しに来ないよう、先に利用時刻を入れる。
    _last_used[persona] = time.time()
    # restore は rm と run をまたぐので、exec のような並行実行を原子に拒否する必要がある。
    if not _enter_exclusive(persona):
        return _failure(f"{persona} は実行中（exec の終了後に restore する）")
    try:
        with _ensure_lock(persona):
            cid, err = _container_id(name)
            if err:
                return _failure(err)
            if cid is not None:
                # 名前でなく ID で消す（inspect と rm の間に同名で作り直されても消さない）。
                removed, rerr = _call("rm", "-f", cid)
                if removed is None:
                    return _failure(rerr or "docker rm failed")
                if removed.returncode != 0 and not _missing(removed.stderr):
                    return _failure(removed.stderr.strip() or "docker rm failed")
            # _ensure だとロックを二重取得するので _ensure_inner を直に呼ぶ。
            eerr = _ensure_inner(persona, image=req.image, network=req.network, memory=req.memory)
            if eerr:
                return _failure(eerr)
            # 事後検証: 実際に要求イメージで動いているか（既存 running を掴む競合の保険）。
            state, ierr = _call(
                "inspect",
                "--format",
                '{{.Config.Image}} {{index .Config.Labels "com.nous.sandbox"}}',
                name,
                timeout=30.0,
            )
            if state is None:
                return _failure(ierr or "docker inspect failed")
            if state.returncode != 0:
                # コンテナ消滅 / sock の権限エラーを「ラベルが無い」と誤診しない。
                return _failure(f"inspect 失敗: {state.stderr.strip()[:200]}")
            actual, _, label = state.stdout.strip().partition(" ")
            if label.strip() != "1":
                return _failure(f"{name} は nous の sandbox ではない（com.nous.sandbox ラベルが無い）")
            if actual != req.image:
                return _failure(f"復元できなかった（{actual} で稼働中）")
        _last_used[persona] = time.time()
        return {"status": "ok"}
    finally:
        _leave(persona)


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
    uvicorn.run(
        app,
        host=os.environ.get("SANDBOX_MANAGER_HOST", "0.0.0.0"),  # nosec B104 - コンテナ内待ち受け。ホスト公開はしない。
        port=8080,
    )
