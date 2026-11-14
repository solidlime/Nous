# Nous: 単一サンドボックスコンテナ + ペルソナ別ユーザー分離 実装計画

> **For agentic workers:** Use subagents to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MemoryMCP → Nous へ改名。ペルソナ毎にDockerコンテナを生成する方式をやめ、単一のsandboxコンテナ内でLinuxユーザー分離する方式に変更。リソース効率10倍以上、イメージを言語非依存に。

**Architecture:** `llm_sandbox` ライブラリ依存を廃止し、`docker exec` による直接コード実行に置き換え。ペルソナ名がそのままLinuxユーザー名（プレフィックスなし）。全コード実行はファイル経由（シェルエスケープ不要）。言語ランタイムのみDockerfileにプリインストール、ライブラリは `pip install --user` 等でペルソナ別に永続化。新言語追加はルーティングテーブル+1行。

**Tech Stack:** Python 3.12+, Docker SDK (docker-py), ubuntu:22.04, プロジェクト名: Nous

---

## ファイル構造

| 操作 | ファイル | 責任 |
|------|----------|------|
| **書換** | `Dockerfile.sandbox` | 言語非依存の最小Ubuntuイメージに全面書換 |
| **書換** | `memory_mcp/application/sandbox/service.py` | `llm_sandbox` 依存廃止、`docker exec` ベース実行に変更、ペルソナ別ユーザー管理追加 |
| **修正** | `docker-compose.yml` | sandboxコンテナを常駐サービスとして追加 |
| **修正** | `memory_mcp/config/settings.py` | `SandboxConfig` 更新（image名、新プロパティ） |
| **修正** | `memory_mcp/api/mcp/_tools_sandbox.py` | インターフェース変更に対応 |
| **修正** | `memory_mcp/application/chat/tools/builtin.py` | sandbox呼出し更新 |
| **修正** | `memory_mcp/api/http/routers/chat.py` | sandbox API 更新 |
| **修正** | `memory_mcp/main.py` | 起動時sandboxコンテナ管理 |
| **新規** | `memory_mcp/application/sandbox/user_manager.py` | ペルソナ別Linuxユーザー作成・管理（コンテナ内で実行するコマンド群） |
| **修正** | `tests/` 配下のsandbox関連テスト | 新方式に合わせて全更新 |

---

## Chunk 0: プロジェクト改名 MemoryMCP → Nous

### Task 0.1: プロジェクト名の一括変更

**Files:** プロジェクト全体

**変更内容:**

| 旧 | 新 | 対象 |
|----|----|------|
| `MemoryMCP` | `Nous` | README, ドキュメント, 表示名 |
| `memory_mcp` | `nous` | Pythonパッケージ名, 全import |
| `memory-mcp` | `nous` | docker-compose service名, コンテナ名 |
| `memorymcp` | `nous` | Dockerイメージ名, kebab-case識別子 |
| `MEMORY_MCP_` | `NOUS_` | 環境変数プレフィックス |
| `memory.mcp` | `nous` | ロガー名 |

- [ ] **Step 1: pyproject.toml 更新**
  ```toml
  [project]
  name = "nous"
  # ... scripts entry point → nous
  
  [tool.setuptools.packages.find]
  include = ["nous*"]  # was memory_mcp*
  ```

- [ ] **Step 2: ディレクトリ名変更**
  ```bash
  mv memory_mcp nous
  ```

- [ ] **Step 3: 全ファイルのimportパス更新**
  ```bash
  # 全 .py ファイルの import memory_mcp → import nous に置換
  find nous/ tests/ -name "*.py" -exec sed -i 's/from memory_mcp/from nous/g; s/import memory_mcp/import nous/g' {} +
  ```

- [ ] **Step 4: 設定ファイル更新**
  ```python
  # config/settings.py
  class Settings(BaseSettings):
      model_config = SettingsConfigDict(env_prefix="NOUS__")  # was MEMORY_MCP__
  ```

- [ ] **Step 5: Docker関連更新**
  ```yaml
  # docker-compose.yml
  services:
    nous:  # was memory-mcp
      image: nous:latest  # was memorymcp:latest
      container_name: nous
      environment:
        - NOUS__QDRAFT_URL=...  # was MEMORY_MCP__QDRAFT_URL
  ```
  ```dockerfile
  # Dockerfile.sandbox
   LABEL org.opencontainers.image.title="Nous Sandbox"  # was Nous Sandbox
  ```

- [ ] **Step 6: ドキュメント更新**
  ```bash
  # README.md, AGENTS.md, .spec/*.md 内の MemoryMCP → Nous 置換
  ```

- [ ] **Step 7: 動作確認**
  ```bash
  pytest tests/ -x --ignore=tests/benchmark -q
  # 1337+ tests 全件パスを確認
  python -m nous.main  # 起動確認
  curl http://localhost:26262/health
  ```

- [ ] **Step 8: コミット**
  ```bash
  git add -A
  git commit -m "rename: MemoryMCP → Nous"
  ```

---

## Chunk 1: Dockerfile.sandbox 書換 + docker-compose 追加

### Task 1.1: Dockerfile.sandbox を言語非依存に書換

**Files:**
- Modify: `Dockerfile.sandbox`
- Modify: `docker-compose.yml`

**要件:**
- ベース: `ubuntu:22.04`
- プリインストール: 言語ランタイムのみ（ライブラリは含まない）
  - `python3`, `python3-pip`, `python3-venv`
  - `nodejs`, `npm` (NodeSource 22.x or apt default)
  - `golang-go` (Go 1.18+ from apt)
  - `curl`, `git` (Rustインストール用 + 汎用)
- Rust: `rustup` 経由でインストール（コンテナビルド時）
  ```dockerfile
  RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  ENV PATH="/root/.cargo/bin:${PATH}"
  ```
- `/sandbox` ワークスペース作成 (`chmod 777` で全ユーザー書き込み可)
- エントリポイント: ユーザー管理スクリプトを配置しつつ `tail -f /dev/null` で常駐

- [ ] **Step 1: Dockerfile.sandbox を書換**

```dockerfile
# 言語非依存 sandbox イメージ
# ライブラリは含まず、ランタイムのみプリインストール
FROM ubuntu:22.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# 言語ランタイム（ライブラリは含まない）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    nodejs npm \
    golang-go \
    gcc g++ \
    curl git ca-certificates \
    bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Rust（rustup 経由、イメージサイズ最小化のため）
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# 共有ワークスペース（全ユーザー書き込み可）
RUN mkdir -p /sandbox/uploads /sandbox/output && chmod 777 /sandbox

WORKDIR /sandbox
CMD ["tail", "-f", "/dev/null"]
```

- [ ] **Step 2: docker-compose.yml に sandbox サービス追加**

`docker-compose.yml` に追加（qdrant, searxng と同じレベル）:

```yaml
  sandbox:
    build:
      context: .
      dockerfile: Dockerfile.sandbox
    image: nous-sandbox:latest
    container_name: sandbox
    restart: unless-stopped
    volumes:
      # 各ペルソナのデータをコンテナ内の /home/ にマウント
      - ./data/persona/default/sandbox:/home/default
      - ./data/persona/config/sandbox:/home/config
      # 追加ペルソナは動的に docker cp で対応（静的マウントは代表のみ）
    cap_drop:
      - ALL
    cap_add:
      - DAC_OVERRIDE  # ファイル読み取りのみ
    security_opt:
      - no-new-privileges:true
    read_only: false  # /home への書き込みが必要なため
```

> **注意**: docker-compose の volumes は静的なので、新規ペルソナ追加時は `docker cp` または `docker exec` で対応する。頻繁にペルソナが増える場合は別途管理方式を検討。

- [ ] **Step 3: ビルド確認**

```bash
docker build -f Dockerfile.sandbox -t nous-sandbox:latest .
# ビルド成功を確認
docker run --rm nous-sandbox:latest python3 --version
# Python 3.x と表示されること
```

- [ ] **Step 4: コミット**

```bash
git add Dockerfile.sandbox docker-compose.yml
git commit -m "feat(sandbox): language-agnostic Dockerfile + compose service"
```

---

## Chunk 2: ユーザー管理モジュール + サービス層書換

### Task 2.1: ペルソナ別ユーザー管理モジュール新規作成

**Files:**
- Create: `memory_mcp/application/sandbox/user_manager.py`
- Test: `tests/unit/test_sandbox_user_manager.py`

このモジュールはコンテナ内で実行するコマンドを生成する。実際のユーザー作成は `docker exec` 経由。

```python
"""Per-persona Linux user management inside sandbox container."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SANDBOX_CONTAINER_NAME = "sandbox"


def make_username(persona: str) -> str:
    """Convert persona name to sandbox username.
    
    Persona name IS the Linux username. Sanitize if needed.
    Maps: persona="default" → username="default"
    """
    return persona  # そのまま。問題ある文字が入ったらサニタイズ


def user_create_commands(persona: str) -> list[str]:
    """Generate shell commands to create a persona user inside sandbox.
    
    Creates user if not exists, ensures home directory, sets up pip user dir.
    Idempotent — safe to run multiple times.
    Username = persona name (no prefix).
    """
    username = persona
    home = f"/home/{username}"
    return [
        # Create user if not exists (idempotent via id check)
        f'id -u {username} &>/dev/null || useradd -m -d {home} -s /bin/bash {username}',
        # Set pip to install packages to user home (persistent via volume)
        f'mkdir -p {home}/.local {home}/.cache/pip {home}/.config/pip',
        f'chown -R {username}:{username} {home}',
        # Set PIP_USER=1 for the user so pip install goes to ~/.local
        f'echo "export PIP_USER=1" >> {home}/.bashrc',
        # Set npm prefix for user-local installs
        f'mkdir -p {home}/.npm-global',
        f'echo "export PATH={home}/.npm-global/bin:\\$PATH" >> {home}/.bashrc',
        f'chown -R {username}:{username} {home}/.npm-global',
        # Rust cargo bin for user
        f'echo "export PATH={home}/.cargo/bin:\\$PATH" >> {home}/.bashrc',
    ]


def user_delete_commands(persona: str) -> list[str]:
    """Generate commands to delete a persona user (cleanup on persona deletion)."""
    username = make_username(persona)
    return [
        f'id -u {username} &>/dev/null && userdel -r {username} || true',
    ]


def user_exists_commands(persona: str) -> list[str]:
    """Generate command to check if user exists (exit code 0 = exists)."""
    username = make_username(persona)
    return [f'id -u {username}']
```

- [ ] **Step 1: user_manager.py 作成**

上記コードを `memory_mcp/application/sandbox/user_manager.py` に配置。

- [ ] **Step 2: ユニットテスト作成**

```python
"""Tests for sandbox user manager."""

import pytest
from memory_mcp.application.sandbox.user_manager import (
    make_username,
    user_create_commands,
    user_delete_commands,
    USER_PREFIX,
)


class TestMakeUsername:
    def test_default_persona(self):
        assert make_username("default") == "default"

    def test_custom_persona(self):
        assert make_username("my-persona") == "my-persona"


class TestUserCreateCommands:
    def test_generates_idempotent_commands(self):
        cmds = user_create_commands("default")
        assert len(cmds) > 0
        assert any("useradd" in c for c in cmds)
        assert "id -u default" in cmds[0] or "useradd" in cmds[0]

    def test_generates_pip_user_setup(self):
        cmds = user_create_commands("default")
        text = " ".join(cmds)
        assert "PIP_USER=1" in text

    def test_generates_npm_global_setup(self):
        cmds = user_create_commands("default")
        text = " ".join(cmds)
        assert ".npm-global" in text


class TestUserDeleteCommands:
    def test_generates_delete_command(self):
        cmds = user_delete_commands("default")
        text = " ".join(cmds)
        assert "userdel" in text

    def test_safe_for_missing_user(self):
        cmds = user_delete_commands("nonexistent")
        text = " ".join(cmds)
        assert "|| true" in text
```

- [ ] **Step 3: テスト実行確認**

```bash
pytest tests/unit/test_sandbox_user_manager.py -v
# Expected: 全テストPASS
```

- [ ] **Step 4: コミット**

```bash
git add memory_mcp/application/sandbox/user_manager.py tests/unit/test_sandbox_user_manager.py
git commit -m "feat(sandbox): per-persona user management module"
```

---

### Task 2.2: SandboxSession を docker exec ベースに書換

**Files:**
- Modify: `memory_mcp/application/sandbox/service.py`
- Test: `tests/unit/test_sandbox_service.py` (更新)
- Test: `tests/integration/test_sandbox_service.py` (更新)

**変更内容:**

`llm_sandbox` 依存を完全廃止し、`docker` Python SDK (`docker-py`) を使用して `docker exec` 経由でコード実行する。

```python
# 新しい SandboxSession（概要）
import asyncio
import docker
from docker.errors import NotFound

class SandboxSession:
    """Single sandbox container execution via docker exec.
    
    No longer per-persona container. All personas share the same container,
    isolated by Linux user accounts.
    """
    
    def __init__(self, persona: str):
        self.persona = persona
        self.username = persona  # ユーザー名 = persona名
        self._docker = docker.from_env()
        self._container = None
        self._last_access = None
    
    async def _ensure_user(self) -> None:
        """Create Linux user for this persona if not exists."""
        cmds = user_create_commands(self.persona)
        script = " && ".join(cmds)
        await self._exec_root(f"bash -c '{script}'")
    
    async def _ensure_container(self) -> None:
        """Ensure sandbox container is running."""
        try:
            self._container = self._docker.containers.get("sandbox")
            if self._container.status != "running":
                self._container.start()
        except NotFound:
            raise RuntimeError("sandbox container not found. Run docker compose up -d sandbox")
    
    async def _exec_root(self, cmd: str, timeout: int = 60) -> tuple[str, str, int]:
        """Execute command as root in sandbox container."""
        await self._ensure_container()
        result = self._container.exec_run(
            cmd, user="root", demux=True
        )
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return stdout, stderr, result.exit_code
    
    async def _exec_user(self, cmd: str, timeout: int = 60) -> tuple[str, str, int]:
        """Execute command as persona user in sandbox container."""
        await self._ensure_container()
        result = self._container.exec_run(
            cmd, user=self.username, demux=True, environment={
                "HOME": f"/home/{self.username}",
                "USER": self.username,
                "PATH": f"/home/{self.username}/.local/bin:/home/{self.username}/.npm-global/bin:/home/{self.username}/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "PIP_USER": "1",
            }
        )
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return stdout, stderr, result.exit_code
    
    async def execute(self, code: str, language: str = "python", 
                      libraries: list[str] | None = None) -> ExecResult:
        """Execute code in sandbox as the persona user."""
        await self._ensure_user()
        self._last_access = asyncio.get_event_loop().time()
        
        # Install libraries if specified
        if libraries:
            await self.install_packages(libraries)
        
        # Route by language
        if language in ("python", "py"):
            return await self._execute_python(code)
        elif language in ("javascript", "js", "node"):
            return await self._execute_javascript(code)
        elif language in ("bash", "sh"):
            return await self._execute_bash(code)
        elif language == "go":
            return await self._execute_go(code)
        elif language == "rust":
            return await self._execute_rust(code)
        else:
            return ExecResult(stderr=f"Unsupported language: {language}", exit_code=1, language=language)
    
    async def _execute_python(self, code: str) -> ExecResult:
        """Execute Python code. Use script file for multi-line."""
        # Escape for shell
        escaped = code.replace("'", "'\"'\"'")
        stdout, stderr, exit_code = await self._exec_user(
            f"python3 -c '{escaped}'"
        )
        return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, language="python")
    
    async def _execute_javascript(self, code: str) -> ExecResult:
        ... # 同様に node -e で実行
    
    async def _execute_bash(self, code: str) -> ExecResult:
        # '!' プレフィックス除去
        if code.startswith("!"):
            code = code[1:]
        stdout, stderr, exit_code = await self._exec_user(f"bash -c '{code}'")
        return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, language="bash")
    
    # ... 他のメソッドも同様に docker exec ベースで書き換え
    
    async def install_packages(self, packages: list[str]) -> str:
        """Install Python packages as persona user."""
        await self._ensure_user()
        cmd = f"python3 -m pip install --user {' '.join(packages)}"
        stdout, stderr, exit_code = await self._exec_user(cmd)
        return stdout if exit_code == 0 else stderr
    
    async def read_file_text(self, remote_path: str) -> str:
        """Read a file from sandbox container (as persona user)."""
        await self._ensure_user()
        # Use docker exec cat
        stdout, stderr, exit_code = await self._exec_user(f"cat {remote_path}")
        if exit_code != 0:
            raise FileNotFoundError(stderr)
        return stdout
    
    async def write_file_text(self, remote_path: str, content: str) -> None:
        """Write text to sandbox container (as persona user)."""
        await self._ensure_user()
        escaped = content.replace("'", "'\"'\"'")
        stdout, stderr, exit_code = await self._exec_user(
            f"bash -c 'cat > {remote_path} << \"HEREDOC_END\"\n{content}\nHEREDOC_END'"
        )
        if exit_code != 0:
            raise IOError(stderr)
    
    # list_files, read_file (binary), delete_file も同様に docker exec で実装
    
    async def close(self) -> None:
        """Release Docker client connection. Container stays running for other personas."""
        if self._docker:
            self._docker.close()
            self._docker = None
```

- [ ] **Step 1: サービス層テストを先に書く**

```python
# tests/unit/test_sandbox_service.py (新規追加分)

class TestSandboxSessionUnit:
    """Unit tests for SandboxSession without Docker dependency."""
    
    def test_language_routing_python(self):
        """execute() routes 'python' to Python executor."""
        session = _make_mock_session("default")
        # Mock _exec_user to verify correct command
        ...
    
    def test_language_routing_javascript(self):
        """execute() routes 'js' to Node executor."""
        ...
    
    def test_language_routing_bash(self):
        """execute() routes 'sh' to Bash executor."""
        ...
    
    def test_unsupported_language(self):
        """Unsupported language returns error ExecResult."""
        ...
    
    def test_bash_strips_exclamation_prefix(self):
        """'!' prefix is stripped before bash execution."""
        ...
    
    def test_install_packages_as_user(self):
        """install_packages uses pip install --user."""
        ...
    
    def test_user_auto_created(self):
        """_ensure_user creates user on first execution."""
        ...
    
    def test_cross_persona_isolation(self):
        """Different personas get different usernames."""
        session_a = SandboxSession("alice")
        session_b = SandboxSession("bob")
        assert session_a.username != session_b.username
```

- [ ] **Step 2: service.py を書換**

上記の設計に基づいて `memory_mcp/application/sandbox/service.py` を全面書換。
`llm_sandbox` インポートを全削除し、`docker` SDK インポートに置き換え。

保持する公開API:
- `SandboxSession` クラス（全メソッド）
- `ExecResult` データクラス
- `SandboxFileInfo` データクラス
- グローバル関数: `get_sandbox_session(persona) -> SandboxSession`
- グローバル関数: `close_sandbox_session(persona) -> None`

破棄する内部実装:
- `_ensure_sandbox_image` 関数
- `_get_own_container_id` 関数
- `_auto_detect_host_data_root` 関数（不要に）
- `_build_container_configs` 関数
- `_cleanup_stale_sandbox_container` 関数
- `ArtifactSandboxSession` / `InteractiveSandboxSession` / `LlmStatelessSession` インポート

- [ ] **Step 3: 単体テスト実行**

```bash
pytest tests/unit/test_sandbox_service.py -v
# Expected: Docker非依存の単体テストがPASS
```

- [ ] **Step 4: コミット**

```bash
git add memory_mcp/application/sandbox/service.py tests/unit/test_sandbox_service.py
git commit -m "refactor(sandbox): replace llm_sandbox with docker exec, single container"
```

---

### Task 2.3: LLM向けツール説明 + 環境自動設定 + sandbox_reset

**Files:**
- Modify: `memory_mcp/application/sandbox/service.py` — `_exec_user` に環境自動注入
- Modify: `memory_mcp/api/mcp/_tools_sandbox.py` — sandbox_reset ツール追加
- Modify: `memory_mcp/application/chat/tools/definitions.py` — ツール説明をLLMフレンドリーに

**設計方針:**
LLMはコードと「どの言語か」だけ指定すればよい。ユーザー名、パス、環境変数はツール側が自動注入する。

**1. `_exec_user` に作業ディレクトリ自動設定 + 環境変数注入**

```python
def _build_env(self) -> dict[str, str]:
    """Build environment for persona user execution.
    
    LLM never needs to know these values — they are injected automatically.
    """
    home = f"/home/{self.username}"
    return {
        "HOME": home,
        "USER": self.username,
        "LOGNAME": self.username,
        "PATH": f"{home}/.local/bin:{home}/.cargo/bin:{home}/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PIP_USER": "1",
        "SANDBOX_WORKDIR": home,
        "SANDBOX_PERSONA": self.persona,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
```

```python
async def _exec_user(self, cmd: str, workdir: str | None = None, timeout: int = 60) -> tuple[str, str, int]:
    """Execute command as persona user. Automatically sets HOME, USER, PATH, PIP_USER.
    
    Args:
        cmd: Shell command to execute
        workdir: Working directory (defaults to persona home)
    """
    await self._ensure_container()
    if workdir is None:
        workdir = f"/home/{self.username}"
    
    # Auto-cd to workdir
    wrapped = f"cd {workdir} && {cmd}"
    
    result = self._container.exec_run(
        ["bash", "-c", wrapped],
        user=self.username,
        environment=self._build_env(),
    )
    stdout = result.output[0].decode() if result.output[0] else ""
    stderr = result.output[1].decode() if result.output[1] else ""
    return stdout, stderr, result.exit_code
```

**2. ファイルベース安全実行（全言語共通）**

シェルエスケープを避けるため、コードは一時ファイルに書き込んでから実行：

```python
async def _execute_via_file(self, code: str, language: str, 
                             run_cmd: str, ext: str) -> ExecResult:
    """Safe execution: write code → temp file → run → cleanup."""
    import uuid
    filepath = f"/home/{self.username}/._sandbox_{uuid.uuid4().hex[:8]}{ext}"
    binpath = f"{filepath}.bin"  # for compiled langs
    
    # Write code via heredoc (safe — no shell escaping needed)
    await self._exec_root(
        f"cat > {filepath} << 'SANDBOX_END'\n{code}\nSANDBOX_END"
    )
    # Fix ownership
    await self._exec_root(f"chown {self.username}:{self.username} {filepath}")
    
    # Execute
    stdout, stderr, exit_code = await self._exec_user(
        run_cmd.format(file=filepath, bin=binpath)
    )
    
    # Cleanup
    await self._exec_root(f"rm -f {filepath} {binpath} 2>/dev/null")
    
    return ExecResult(
        stdout=stdout, stderr=stderr, exit_code=exit_code, language=language
    )
```

| 言語 | ext | run_cmd |
|------|-----|---------|
| python | `.py` | `python3 {file}` |
| javascript | `.js` | `node {file}` |
| bash | `.sh` | `bash {file}` |
| go | `.go` | `go run {file}` |
| rust | `.rs` | `rustc {file} -o {bin} && {bin}` |

#### 新しい言語の追加方法

言語追加は3ステップだけで済む：

1. **Dockerfile.sandbox** にランタイム追加（1行）:
   ```dockerfile
   RUN apt-get install -y ruby lua5.4  # 例
   ```

2. **service.py** のルーティングテーブルに追加（1行）:
   ```python
   _LANG_ROUTING = {
       ...
       "ruby": ("ruby", ".rb"),
       "lua": ("lua", ".lua"),
       "php": ("php", ".php"),
       "perl": ("perl", ".pl"),
       "zig": ("zig run", ".zig"),
       # なんでも入る
   }
   ```

3. **`allowed_languages`** 設定に追加:
   ```python
   allowed_languages: list[str] = [
       "python", "javascript", "bash", "go", "rust", "ruby", "lua", "php", "perl", "zig"
   ]
   ```

LLM側は変更不要。`sandbox_execute(language="ruby")` で自動ルーティングされる。
ツール説明は `get_sandbox_context` が動的に利用可能言語を返すので、LLMは常に最新の言語一覧を知ることができる。

**3. `sandbox_reset` ツール追加（LLMがリセット可能）**

```python
# _tools_sandbox.py に追加
@mcp.tool()
async def sandbox_reset(
    ctx: Context,
    persona: str | None = None,
    level: str = "files",  # "files" | "packages" | "full"
) -> str:
    """サンドボックス環境をリセットします。
    
    level:
      - "files": 作業ディレクトリ内の全ファイルを削除
      - "packages": pip/npmでインストールしたパッケージも削除
      - "full": ユーザーごと再作成（完全リセット）
    """
    persona = _resolve_persona(ctx, persona)
    session = get_sandbox_session(persona)
    
    await session._ensure_user()
    home = f"/home/{session.username}"
    
    if level == "files":
        await session._exec_root(f"find {home} -type f ! -path '{home}/.local/*' ! -path '{home}/.cargo/*' ! -path '{home}/.npm-global/*' -delete 2>/dev/null")
        return f"Sandbox files reset for {persona}"
    
    elif level == "packages":
        # Clear pip user packages
        await session._exec_root(f"rm -rf {home}/.local/lib/python*/site-packages/* 2>/dev/null")
        await session._exec_root(f"rm -rf {home}/.npm-global/lib/node_modules/* 2>/dev/null")
        await session._exec_root(f"rm -rf {home}/.cargo/registry/* 2>/dev/null")
        return f"Sandbox packages reset for {persona}"
    
    elif level == "full":
        # Delete and recreate user
        await session._exec_root(f"id -u {session.username} &>/dev/null && userdel -r {session.username} || true")
        await session._ensure_user()
        return f"Sandbox fully reset for {persona} (user recreated)"
    
    return f"Unknown reset level: {level}"
```

**4. ツール説明のLLMフレンドリー化**

```python
# definitions.py の sandbox ToolDefinition 更新
ToolDefinition(
    name="sandbox_execute",
    description=(
        "サンドボックス環境でコードを実行します。"
        "あなたは sandbox コンテナ内の専用ユーザーとして実行されます。"
        "ホームディレクトリは自動設定され、pip install --user で"
        "インストールしたパッケージは次回以降も利用可能です。\n"
        "対応言語: python, javascript, bash, go, rust\n"
        "ファイル操作は sandbox_files ツールを使ってください。\n"
        "コードの内容だけ書いてください。環境設定（cd, export等）は不要です。"
    ),
    parameters={
        "code": {"type": "string", "description": "実行するコード"},
        "language": {"type": "string", "description": "プログラミング言語 (python/js/bash/go/rust)", "default": "python"},
        "libraries": {"type": "array", "items": {"type": "string"}, "description": "事前インストールするpipパッケージ（初回のみ）", "default": []},
    },
)

ToolDefinition(
    name="sandbox_reset",
    description=(
        "サンドボックス環境をリセットします。\n"
        "files: 作業ファイルのみ削除\n"
        "packages: pip/npmパッケージも削除\n"
        "full: ユーザーごと再作成（完全初期化）"
    ),
    parameters={
        "level": {"type": "string", "description": "リセットレベル (files/packages/full)", "default": "files"},
    },
)
```

**5. (オプション) `get_sandbox_context` ツール**

LLMが現在のサンドボックス状態を確認したい時に使う：

```python
@mcp.tool()
async def get_sandbox_context(ctx: Context, persona: str | None = None) -> dict:
    """サンドボックスの現在の環境情報を返します。
    
    Returns: {user, home, languages, python_version, installed_packages}
    """
    persona = _resolve_persona(ctx, persona)
    session = get_sandbox_session(persona)
    await session._ensure_user()
    
    # Check installed languages
    langs = {}
    for lang, check_cmd in [("python3", "--version"), ("node", "--version"), ("go", "version"), ("rustc", "--version"), ("bash", "--version")]:
        stdout, _, exit_code = await session._exec_user(f"{lang} {check_cmd}")
        if exit_code == 0:
            langs[lang] = stdout.strip().split("\n")[0]
    
    # Check pip packages
    stdout, _, _ = await session._exec_user("pip3 list --user --format=json 2>/dev/null || echo '[]'")
    try:
        packages = json.loads(stdout)
    except Exception:
        packages = []
    
    return {
        "user": session.username,
        "home": f"/home/{session.username}",
        "languages": langs,
        "pip_packages": [p["name"] for p in packages] if isinstance(packages, list) else [],
    }
```

- [ ] **Step 1: service.pyに `_build_env`, `_execute_via_file`, `reset` 追加**

- [ ] **Step 2: _tools_sandbox.pyに `sandbox_reset`, `get_sandbox_context` 追加**

- [ ] **Step 3: definitions.pyのツール説明更新**

- [ ] **Step 4: 単体テスト追加**

```python
class TestLLM_FriendlySandbox:
    def test_env_includes_home_and_user(self):
        session = SandboxSession("test-env")
        env = session._build_env()
        assert env["HOME"] == "/home/test-env"
        assert env["USER"] == "test-env"
        assert env["PIP_USER"] == "1"
        assert "/home/test-env/.local/bin" in env["PATH"]
    
    def test_exec_user_cd_to_home(self):
        """_exec_user auto-cds to home directory."""
        session = _make_mock_session("test-cd")
        mock_container = Mock()
        session._container = mock_container
        session._exec_user("ls")
        # Verify command includes cd
        cmd = mock_container.exec_run.call_args[0][0]
        assert "cd /home/test-cd" in " ".join(cmd)
    
    def test_reset_files_level(self):
        session = _make_mock_session("test-reset")
        # Mock _exec_root
        ...
    
    def test_reset_full_level_recreates_user(self):
        ...
    
    def test_execute_via_file_cleanup(self):
        """Temporary files are cleaned up after execution."""
        ...
```

- [ ] **Step 5: コミット**

```bash
git add memory_mcp/application/sandbox/service.py \
        memory_mcp/api/mcp/_tools_sandbox.py \
        memory_mcp/application/chat/tools/definitions.py \
        tests/
git commit -m "feat(sandbox): LLM-friendly auto-env, sandbox_reset, sandbox_context"
```

---

### Task 2.4: ペルソナ作成/削除時のsandboxユーザー自動連動

**Files:**
- Modify: `memory_mcp/main.py` — ペルソナ作成/削除フックにsandbox処理追加
- Modify: `memory_mcp/api/http/routers/persona.py` — ペルソナAPI削除時にsandboxクリーンアップ
- Modify: `memory_mcp/application/persona/service.py` — ペルソナ作成時にsandboxユーザー作成

**設計:**
- ペルソナ作成時: `SandboxSession._ensure_user()` を呼ぶ → Linuxユーザー自動作成
- ペルソナ削除時: `close_sandbox_session(persona)` + `userdel -r {persona}`
- 既に `main.py:206` にペルソナ削除時のsandboxクリーンアップがある → このパスを更新

```python
# main.py または persona service に追加
async def _on_persona_created(persona: str) -> None:
    """Create sandbox Linux user when a new persona is created."""
    if not get_settings().sandbox.enabled:
        return
    try:
        session = get_sandbox_session(persona)
        await session._ensure_user()
        logger.info(f"Sandbox user created for persona: {persona}")
    except Exception as e:
        logger.warning(f"Failed to create sandbox user for {persona}: {e}")

async def _on_persona_deleted(persona: str) -> None:
    """Delete sandbox Linux user when a persona is deleted."""
    # Existing cleanup from close_sandbox_session
    await close_sandbox_session(persona)
    # Additionally delete the Linux user
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get("sandbox")
        container.exec_run(f"id -u {persona} &>/dev/null && userdel -r {persona} || true")
        client.close()
        logger.info(f"Sandbox user deleted for persona: {persona}")
    except Exception as e:
        logger.warning(f"Failed to delete sandbox user for {persona}: {e}")
```

- [ ] **Step 1: persona service/routers に sandbox フック追加**

- [ ] **Step 2: main.py の既存 sandbox cleanup を更新**

- [ ] **Step 3: テスト追加**

```python
class TestPersonaSandboxLifecycle:
    @pytest.mark.integration
    async def test_persona_creation_creates_sandbox_user(self):
        """New persona → sandbox Linux user auto-created."""
        ...
    
    @pytest.mark.integration
    async def test_persona_deletion_removes_sandbox_user(self):
        """Deleted persona → sandbox Linux user removed."""
        ...
    
    @pytest.mark.integration
    async def test_persona_deletion_cleans_up_files(self):
        """Deleted persona → sandbox home directory cleaned."""
        ...
```

- [ ] **Step 4: コミット**

```bash
git add memory_mcp/main.py \
        memory_mcp/api/http/routers/persona.py \
        memory_mcp/application/persona/service.py \
        tests/
git commit -m "feat(sandbox): auto-manage sandbox users on persona create/delete"
```

---

### Task 2.5: 呼出し側の修正

**Files:**
- Modify: `memory_mcp/api/mcp/_tools_sandbox.py` — `get_sandbox_session()` の呼出し方が変わるか確認
- Modify: `memory_mcp/application/chat/tools/builtin.py` — `_handle_execute_code` のアダプト
- Modify: `memory_mcp/api/http/routers/chat.py` — sandbox API エンドポイント更新
- Modify: `memory_mcp/config/settings.py` — `SandboxConfig` 更新

**確認ポイント:**
- `_tools_sandbox.py`: `get_sandbox_session(persona)` の戻り値が `SandboxSession` のままなら変更不要（インターフェースは維持）
- `builtin.py`: 同上
- `chat.py`: sandbox URL 関連のコードがあれば修正

- [ ] **Step 1: 全呼出し側を確認し、必要な修正を適用**

```bash
grep -rn "sandbox_session\|llm_sandbox\|ArtifactSandbox\|InteractiveSandbox" memory_mcp/ --include="*.py"
# 残存している llm_sandbox 参照を全削除
```

- [ ] **Step 2: 設定更新**

```python
# settings.py SandboxConfig 更新
class SandboxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOUS_SANDBOX__")
    
    enabled: bool = True
    container_name: str = "sandbox"  # 新: 単一コンテナ名
    image: str = "nous-sandbox:latest"
    # session_idle_timeout は残す（将来の状態管理用）
    session_idle_timeout: int = 1800
    allowed_languages: list[str] = ["python", "javascript", "bash", "go", "rust"]
```

- [ ] **Step 3: コミット**

```bash
git add -A
git commit -m "fix(sandbox): update callers and config for single-container model"
```

---

## Chunk 3: main.py 起動時管理 + 統合テスト

### Task 3.1: main.py に sandbox コンテナ起動管理追加

**Files:**
- Modify: `memory_mcp/main.py`

- [ ] **Step 1: 起動時に sandbox コンテナの存在確認・起動**

```python
# main.py 起動シーケンスに追加
async def _ensure_sandbox_container():
    """Ensure single sandbox container is running at startup."""
    import docker
    client = docker.from_env()
    try:
        container = client.containers.get("sandbox")
        if container.status != "running":
            logger.info("Starting existing sandbox container...")
            container.start()
        else:
            logger.info("Sandbox container already running")
    except docker.errors.NotFound:
        logger.warning(
            "Sandbox container not found. "
            "Run 'docker compose up -d sandbox' or ensure it's started separately."
        )
    finally:
        client.close()
```

- [ ] **Step 2: コミット**

```bash
git add memory_mcp/main.py
git commit -m "feat(sandbox): auto-detect sandbox container on startup"
```

---

### Task 3.2: 統合テスト

**Files:**
- Create/Modify: `tests/integration/test_sandbox_integration.py`
- Modify: `tests/unit/test_builtin_handlers.py` (sandbox関連テスト更新)

**シナリオ:**

- [ ] **Step 1: 単一コンテナ内で複数ペルソナの隔離テスト**

```python
@pytest.mark.integration
class TestSandboxMultiPersonaIntegration:
    """Integration tests requiring running sandbox container."""
    
    @pytest.mark.asyncio
    async def test_personas_have_separate_users(self):
        """Each persona gets a unique Linux user inside sandbox."""
        session_a = get_sandbox_session("alice")
        session_b = get_sandbox_session("bob")
        
        assert session_a.username != session_b.username
        # Verify users exist in container
        ...
    
    @pytest.mark.asyncio
    async def test_data_isolation_between_personas(self):
        """Persona A cannot read Persona B's files."""
        session_a = get_sandbox_session("alice")
        session_b = get_sandbox_session("bob")
        
        # Alice writes a file
        await session_a.write_file_text("/home/alice/secret.txt", "alice data")
        
        # Bob cannot read it
        with pytest.raises(Exception):
            await session_b.read_file_text("/home/alice/secret.txt")
    
    @pytest.mark.asyncio
    async def test_pip_install_persistence(self):
        """pip installed packages survive across sessions."""
        session = get_sandbox_session("test_pkg")
        await session.install_packages(["six"])
        
        # New session for same persona
        session2 = get_sandbox_session("test_pkg")
        result = await session2.execute("import six; print(six.__version__)", "python")
        assert result.exit_code == 0
    
    @pytest.mark.asyncio
    async def test_python_execution_basic(self):
        session = get_sandbox_session("test_py")
        result = await session.execute("print(1+1)", "python")
        assert result.exit_code == 0
        assert "2" in result.stdout
    
    @pytest.mark.asyncio
    async def test_javascript_execution_basic(self):
        session = get_sandbox_session("test_js")
        result = await session.execute("console.log('hello')", "javascript")
        assert result.exit_code == 0
        assert "hello" in result.stdout
    
    @pytest.mark.asyncio
    async def test_bash_execution_basic(self):
        session = get_sandbox_session("test_sh")
        result = await session.execute("echo hello", "bash")
        assert result.exit_code == 0
        assert "hello" in result.stdout
    
    @pytest.mark.asyncio
    async def test_write_and_read_file(self):
        session = get_sandbox_session("test_file")
        await session.write_file_text("/home/test_file/test.txt", "content")
        text = await session.read_file_text("/home/test_file/test.txt")
        assert text == "content"
    
    @pytest.mark.asyncio
    async def test_list_files(self):
        session = get_sandbox_session("test_list")
        files = await session.list_files("/home/test_list")
        assert isinstance(files, list)
    
    @pytest.mark.asyncio
    async def test_delete_file(self):
        session = get_sandbox_session("test_del")
        await session.write_file_text("/home/test_del/tmp.txt", "data")
        result = await session.delete_file("/home/test_del/tmp.txt")
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cleanup_on_persona_delete(self):
        """User is removed when persona is deleted."""
        session = get_sandbox_session("test_cleanup")
        await session._ensure_user()  # Create user
        close_sandbox_session("test_cleanup")  # Should trigger user cleanup
        # Verify user no longer exists
        ...
```

- [ ] **Step 2: builtinハンドラテスト更新**

```python
# test_builtin_handlers.py の sandbox 関連テスト更新
# _handle_execute_code のモックを docker exec モデルに対応
```

- [ ] **Step 3: 全テスト実行**

```bash
# 統合テスト（sandboxコンテナ要）
docker compose up -d sandbox
pytest tests/ -x --ignore=tests/benchmark -q
# Expected: 1337+ tests, all passing
```

- [ ] **Step 4: コミット**

```bash
git add tests/
git commit -m "test(sandbox): integration tests for single-container model"
```

---

## Chunk 4: データ移行 + .spec 更新

### Task 4.1: データ移行スクリプト

既存の `data/persona/{persona}/sandbox/` を新しい `/home/{persona}/` にマウントし直すだけなので、データ移行は不要。既存の sandbox データはそのまま使える。

- [ ] **Step 1: 確認のみ。データ移行が不要であることを確認してスキップ。**

### Task 4.2: .spec ファイル更新

- [ ] **Step 1: PLAN.md 更新**

PLAN.md の柱A-2, 柱C を新しい方針で置き換える。

- [ ] **Step 2: SPEC.md 更新**

```markdown
### 柱A: Docker Compose 完全自動デプロイ (更新)

- [x] **A-2 (改)**: 単一sandboxコンテナ + 言語非依存イメージ
  - ベース: ubuntu:22.04
  - プリインストール: python3, nodejs, golang-go, rust (ランタイムのみ、ライブラリなし)
  - 単一コンテナ内でペルソナ別Linuxユーザー分離
  - `llm_sandbox` 依存廃止、`docker exec` ベース実行

### 柱C: sandbox マルチ言語対応 (更新)

- [x] **C-1 (改)**: 単一コンテナ sandbox 方式
  - Dockerfile.sandbox: 言語非依存の最小イメージ
  - service.py: llm_sandbox → docker exec 全面書換
  - ペルソナ別ユーザー: `{persona}` で分離
  - データ永続: `data/persona/{persona}/sandbox/` → `/home/{persona}/`
  - ライブラリ: pip --user / npm --global でペルソナ別永続化
```

- [ ] **Step 3: TODO.md 更新**

T002 (A-2) と T006 (C-2) を完了マーク、新しいTODOに置き換え。

- [ ] **Step 4: コミット**

```bash
git add .spec/
git commit -m "docs(spec): update sandbox architecture specs"
```

---

## 完了条件チェックリスト

- [ ] プロジェクト名 MemoryMCP → Nous 全置換完了 (Chunk 0)
- [ ] `python -m nous.main` で起動、`/health` 正常
- [ ] `Dockerfile.sandbox` が ubuntu:22.04 ベース、言語ランタイムのみでライブラリなし
- [ ] `docker compose up -d sandbox` で単一コンテナが起動
- [ ] `service.py` に `llm_sandbox` インポートが存在しない
- [ ] ユーザー名 = persona名（プレフィックスなし）。`default` ペルソナ → ユーザー `default`
- [ ] 2つ以上のペルソナで sandbox_execute 可能、互いにファイル干渉なし
- [ ] `pip install --user` したパッケージが永続化され、再実行後に使える
- [ ] ペルソナ作成時にsandbox Linuxユーザー自動作成される
- [ ] ペルソナ削除時にsandboxユーザー + ファイルがクリーンアップされる
- [ ] LLMが `sandbox_reset` ツールでfiles/packages/fullレベルでリセット可能
- [ ] LLMが `get_sandbox_context` で現在の環境を確認可能
- [ ] ツール説明がLLMフレンドリー（cd/export不要の案内）
- [ ] `_exec_user` が HOME/USER/PATH/PIP_USER を自動注入
- [ ] コード実行はファイル経由（シェルエスケープ脆弱性なし）
- [ ] 全言語（python, js, bash, go, rust）がファイル経由で実行可能
- [ ] 新言語追加がルーティングテーブル+1行で可能
- [ ] pytest 全件パス (1337+ → rename後も維持)
- [ ] 新規テストカバレッジ: 単体15件以上 + 統合10件以上

---

## リスクと緩和策

| リスク | 緩和策 |
|--------|--------|
| `docker-py` の `exec_run` がマルチラインヘッダーで詰まる | heredoc でファイル経由実行にフォールバック |
| シェルエスケープの脆弱性 | コードをファイルに書き込んでから実行する方式を検討 |
| ペルソナ数増加時の静的volumeマウント不足 | 動的マウントは `docker cp` で代替、永続化はvolumeで十分なケースが大部分 |
| `docker exec` のレイテンシ | コンテナ常駐によりミリ秒単位。毎回コンテナ起動するより10倍以上高速 |
