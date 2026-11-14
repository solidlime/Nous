"""WikiStore — wiki ページのファイル層（正）を読み書きする。

計画書: ``docs/archive/superpowers/plans/2026-11-07-wiki-dreaming.md`` §3.1 / §4.1。

- ページ実体: ``{data_root}/persona/{persona}/wiki/{slug}.md``
- frontmatter: ``---`` で挟んだ ``key: value`` 行（YAML パーサは使わない）
- ``index.md`` は全ページの目次。書き込みは ``rebuild_index()`` 専用（read-only 扱い）
- slug は Windows でも安全な文字だけを使う（``:`` は使わない。記憶側の
  ``project:nous`` タグとは別名前空間で、ページ slug は ``project-nous``）
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from nous.domain.shared.result import Failure, Result, Success
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

#: index page slug (auto maintained, never written through write_page).
INDEX_SLUG = "index"
#: hard cap for a single page body (plan §3.1: Borges map avoidance).
MAX_PAGE_BYTES = 8192

#: max path depth for nested topic pages (``project-nous/memory``).
MAX_SLUG_DEPTH = 3

_SLUG_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)

#: ページタグの形（frontmatter ``tags:``）。不正値は捨てる。
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
#: 1 ページが持てるタグ数。超過分は捨てる（順序は先勝ち）。
MAX_TAGS = 8

#: first N chars of body used as the one-line summary in index.md.
_INDEX_SUMMARY_CHARS = 80

#: index.md の最大行数（上位層を小さく保つ契約。超分は 「… +N more」に畳む）。
MAX_INDEX_LINES = 120

#: index.md に並べる日記の最大件数（古い日記は件数表示に畳む）。
MAX_INDEX_JOURNALS = 7

#: 日記ページの slug 接頭辞（``journal-YYYY-MM-DD``）。index では別節にする。
JOURNAL_SLUG_PREFIX = "journal-"

#: リビジョン履歴の置き場（wiki ルート配下。``.jsonl`` なので slug 走査に拾われない）。
HISTORY_DIRNAME = "_history"
#: 1 ページにつき保持するリビジョン数（古いものから捨てる）。
MAX_REVISIONS = 20


class WikiStoreError(Exception):
    """Wiki ファイル層の失敗（slug 不正・サイズ超過・読み書き失敗）。"""


def _rev_of(entry: dict) -> int:
    """履歴エントリの rev（壊れた値は 0 扱い。履歴で例外を投げない）。"""
    try:
        return int(entry.get("rev") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class WikiPage:
    """1 つの wiki ページ。"""

    slug: str
    title: str
    body: str
    project: str | None = None
    sources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    updated: str | None = None
    links: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_index(self) -> bool:
        return self.slug == INDEX_SLUG


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip().lower()] = value.strip()
    return meta, match.group(2)


def _parse_sources(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_tags(raw: str) -> tuple[str, ...]:
    """カンマ区切りのタグを正規化する（strip + lower、不正値と 9 個目以降は捨てる）。

    壊れた frontmatter でページ全体を落とさないため、例外にはしない。
    """
    tags: list[str] = []
    for item in raw.split(","):
        tag = item.strip().lower()
        if _TAG_RE.match(tag) and tag not in tags:
            tags.append(tag)
            if len(tags) >= MAX_TAGS:
                break
    return tuple(tags)


def extract_links(body: str) -> tuple[str, ...]:
    """本文の ``[[slug]]`` / ``[[slug|表示名]]`` からリンク先 slug を抽出する。"""
    links: list[str] = []
    for match in _WIKILINK_RE.finditer(body):
        target = match.group(1).split("|", 1)[0].strip().strip("/")
        if target and target not in links:
            links.append(target)
    return tuple(links)


def parse_page(slug: str, raw: str) -> WikiPage:
    """Markdown 文字列を :class:`WikiPage` にする（frontmatter は任意）。"""
    meta, body = _split_frontmatter(raw)
    return WikiPage(
        slug=slug,
        title=meta.get("title", slug),
        body=body.strip("\n"),
        project=meta.get("project") or None,
        sources=_parse_sources(meta.get("sources", "")),
        tags=_parse_tags(meta.get("tags", "")),
        updated=meta.get("updated") or None,
        links=extract_links(body),
        # 旧 frontmatter の ``manual: true`` は読み捨てる（編集保護は廃止）。
    )


def render_page(page: WikiPage) -> str:
    """:class:`WikiPage` を Markdown 文字列にする（保存形式）。"""
    lines = ["---", f"title: {page.title}"]
    if page.project:
        lines.append(f"project: {page.project}")
    if page.sources:
        lines.append(f"sources: {', '.join(page.sources)}")
    tags = _parse_tags(",".join(page.tags))
    if tags:
        lines.append(f"tags: {', '.join(tags)}")
    lines.append(f"updated: {page.updated or _now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(page.body.rstrip("\n"))
    lines.append("")
    return "\n".join(lines)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def page_hash(title: str, body: str) -> str:
    """ページ内容の安定ハッシュ（embedding 再計算の判断に使う）。

    ``updated`` を含む render 後の全文ではなく title+body から取る —
    render は毎回 ``updated`` を書き換えるため、全文ハッシュでは毎 cycle 再 embed になる。
    """
    digest = hashlib.sha256(f"{title}\x00{body}".encode())
    return digest.hexdigest()[:32]


def _validate_slug(slug: str) -> None:
    if slug != slug.strip() or not slug:
        raise WikiStoreError(f"invalid slug: {slug!r}")
    parts = slug.split("/")
    if len(parts) > MAX_SLUG_DEPTH:
        raise WikiStoreError(f"slug too deep (max {MAX_SLUG_DEPTH}): {slug!r}")
    for part in parts:
        if not _SLUG_SEGMENT_RE.match(part):
            raise WikiStoreError(f"invalid slug segment {part!r} in {slug!r}")


class WikiStore:
    """persona ごとの wiki ディレクトリを操作する（ファイル層のみ）。"""

    def __init__(self, data_root: str | Path, persona: str) -> None:
        if not persona or "/" in persona or "\\" in persona or persona in (".", ".."):
            raise WikiStoreError(f"invalid persona: {persona!r}")
        self.persona = persona
        self.root = Path(data_root) / "persona" / persona / "wiki"

    # ------------------------------------------------------------------
    # paths
    # ------------------------------------------------------------------

    def _path_for(self, slug: str) -> Path:
        _validate_slug(slug)
        path = self.root.joinpath(*slug.split("/")).with_suffix(".md")
        # 親ディレクトリ経由の symlink 脱出を防ぐ（resolve 後に root 配下を強制）
        resolved_root = self.root.resolve()
        if not path.parent.resolve().is_relative_to(resolved_root):
            raise WikiStoreError(f"slug escapes wiki root: {slug!r}")
        return path

    def wiki_dir(self) -> Path:
        return self.root

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def list_slugs(self) -> list[str]:
        if not self.root.is_dir():
            return []
        slugs: list[str] = []
        for path in sorted(self.root.rglob("*.md")):
            rel = path.relative_to(self.root).with_suffix("")
            slug = "/".join(rel.parts)
            if slug == INDEX_SLUG or all(_SLUG_SEGMENT_RE.match(part) for part in rel.parts):
                slugs.append(slug)
            else:
                logger.warning("Skipping invalid wiki file name: %s", path)
        return slugs

    def read_page(self, slug: str) -> Result[WikiPage, WikiStoreError]:
        try:
            path = self._path_for(slug)
        except WikiStoreError as exc:
            return Failure(exc)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Failure(WikiStoreError(f"wiki page not found: {slug}"))
        except OSError as exc:
            return Failure(WikiStoreError(f"cannot read {slug}: {exc}"))
        return Success(parse_page(slug, raw))

    def list_pages(self, include_index: bool = False) -> list[WikiPage]:
        pages: list[WikiPage] = []
        for slug in self.list_slugs():
            if slug == INDEX_SLUG and not include_index:
                continue
            result = self.read_page(slug)
            if isinstance(result, Success):
                pages.append(result.value)
        return pages

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write_page(
        self,
        slug: str,
        title: str,
        body: str,
        project: str | None = None,
        sources: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> Result[WikiPage, WikiStoreError]:
        """ページを原子的に書き込み、``index.md`` を更新する。

        ``index`` slug への書き込みは拒否する（rebuild_index 専用）。
        """
        if slug == INDEX_SLUG:
            return Failure(WikiStoreError("index page is generated; use rebuild_index()"))
        try:
            path = self._path_for(slug)
        except WikiStoreError as exc:
            return Failure(exc)
        page = WikiPage(
            slug=slug,
            title=title.strip() or slug,
            body=body.strip("\n"),
            project=project,
            sources=tuple(sources),
            tags=_parse_tags(",".join(tags)),
            updated=_now_iso(),
            links=extract_links(body),
        )
        rendered = render_page(page)
        size = len(rendered.encode("utf-8"))
        if size > MAX_PAGE_BYTES:
            return Failure(WikiStoreError(f"page too large: {size} bytes > {MAX_PAGE_BYTES}"))
        # 上書き前の内容を履歴に退避する（失敗しても書込みは止めない）。
        created = False
        try:
            self._push_history(slug, path.read_text(encoding="utf-8"), "write")
        except FileNotFoundError:
            created = True  # 新規ページ: 後で作成版を積む（v1 も戻せるように）
        except (OSError, WikiStoreError) as exc:
            logger.warning("Wiki history push failed for %s: %s", slug, exc)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(rendered, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.error("Wiki write failed for %s: %s", slug, exc)
            return Failure(WikiStoreError(f"cannot write {slug}: {exc}"))
        if created:
            try:
                self._push_history(slug, rendered, "create")
            except (OSError, WikiStoreError) as exc:
                logger.warning("Wiki history push failed for %s: %s", slug, exc)
        self.rebuild_index()
        return Success(page)

    def delete_page(self, slug: str) -> Result[None, WikiStoreError]:
        if slug == INDEX_SLUG:
            return Failure(WikiStoreError("index page cannot be deleted"))
        try:
            path = self._path_for(slug)
        except WikiStoreError as exc:
            return Failure(exc)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = None
        if raw is not None:
            # 削除も履歴に残す（「消した」を後から戻せるようにする）。
            try:
                self._push_history(slug, raw, "delete")
            except (OSError, WikiStoreError) as exc:
                logger.warning("Wiki history push failed for %s: %s", slug, exc)
        try:
            path.unlink()
        except FileNotFoundError:
            return Failure(WikiStoreError(f"wiki page not found: {slug}"))
        except OSError as exc:
            return Failure(WikiStoreError(f"cannot delete {slug}: {exc}"))
        self.rebuild_index()
        return Success(None)

    # ------------------------------------------------------------------
    # search / links
    # ------------------------------------------------------------------

    def grep(self, pattern: str, limit: int = 50) -> list[tuple[str, int, str]]:
        """本文を行単位で regex 検索する（index.md を含む）。"""
        hits: list[tuple[str, int, str]] = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise WikiStoreError(f"invalid pattern: {exc}") from exc
        for slug in self.list_slugs():
            if slug == INDEX_SLUG:
                continue  # 目次は本文の要約の写しなので grep 対象外
            result = self.read_page(slug)
            if not isinstance(result, Success):
                continue
            for line_no, line in enumerate(result.value.body.splitlines(), start=1):
                if regex.search(line):
                    hits.append((slug, line_no, line.strip()))
                    if len(hits) >= limit:
                        return hits
        return hits

    def dangling_links(self) -> dict[str, list[str]]:
        """``{slug: [dangling_target, ...]}``（self link と index は除外）。"""
        existing = set(self.list_slugs())
        dangling: dict[str, list[str]] = {}
        for page in self.list_pages():
            missing = [link for link in page.links if link not in existing and link != page.slug]
            if missing:
                dangling[page.slug] = missing
        return dangling

    # ------------------------------------------------------------------
    # history（版管理 / ロールバック）
    # ------------------------------------------------------------------

    def _history_path(self, slug: str) -> Path:
        _validate_slug(slug)
        return self.root / HISTORY_DIRNAME / Path(*slug.split("/")).with_suffix(".jsonl")

    def _history_entries(self, slug: str) -> list[dict]:
        path = self._history_path(slug)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise WikiStoreError(f"cannot read history for {slug}: {exc}") from exc
        entries: list[dict] = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # 壊れた行は捨てる（履歴でページを落とさない）
            if isinstance(entry, dict) and isinstance(entry.get("raw"), str):
                entries.append(entry)
        return entries

    def _push_history(self, slug: str, raw: str, action: str) -> None:
        """旧本文（または削除された本文）を履歴に 1 行追記し、古い版を切り捨てる。"""
        entries = self._history_entries(slug)
        # 同じ内容を二度積まない（改訂時は前版、新規時は作成版を積むため重なりうる）。
        # shortcut: 同一本文の作り直しは版として数えない（updated だけ進む）、問題になったら時刻も比べる。
        if entries and entries[-1].get("raw") == raw:
            return
        rev = max((_rev_of(e) for e in entries), default=0) + 1
        entries.append({"rev": rev, "at": _now_iso(), "action": action, "raw": raw})
        path = self._history_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-MAX_REVISIONS:]),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def history(self, slug: str) -> list[dict]:
        """``{rev, action, at, title, updated, bytes, hash}`` を新しい順に返す（本文は含めない）。"""
        out: list[dict] = []
        for entry in reversed(self._history_entries(slug)):
            page = parse_page(slug, entry["raw"])
            out.append(
                {
                    "rev": _rev_of(entry),
                    "action": entry.get("action") or "write",
                    "at": entry.get("at"),
                    "title": page.title,
                    "updated": page.updated,
                    "bytes": len(entry["raw"].encode("utf-8")),
                    "hash": page_hash(page.title, page.body),
                }
            )
        return out

    def read_revision(self, slug: str, rev: int) -> Result[WikiPage, WikiStoreError]:
        for entry in self._history_entries(slug):
            if _rev_of(entry) == rev:
                return Success(parse_page(slug, entry["raw"]))
        return Failure(WikiStoreError(f"revision {rev} not found for {slug}"))

    def restore_revision(self, slug: str, rev: int) -> Result[WikiPage, WikiStoreError]:
        """過去の版の本文でページを書き戻す（書き戻し自体も履歴に残る）。"""
        found = self.read_revision(slug, rev)
        if isinstance(found, Failure):
            return found
        page = found.value
        return self.write_page(
            slug,
            page.title,
            page.body,
            project=page.project,
            sources=page.sources,
            tags=page.tags,
        )

    # ------------------------------------------------------------------
    # index.md
    # ------------------------------------------------------------------

    def rebuild_index(self) -> Result[None, WikiStoreError]:
        """``index.md`` を全ページから再生成する（小さい目次を保つ）。

        目次は上位 :data:`MAX_INDEX_LINES` 行まで。超過分は ``… +N more`` 行に
        畳む（計画 §4.4 の「上位層は小さく保つ」契約）。
        """
        pages = sorted(self.list_pages(), key=lambda p: (p.project or "~", p.slug))
        # 日記は 1 枚/日で無期限に増えるので、通常ページと同じ枠で並べると
        # 古い順に切り飛ばされていく（project=None は末尾に並ぶため）。
        # 直近の数枚だけを専用節に置き、残りは件数で見せる。
        journals = [p for p in pages if p.slug.startswith(JOURNAL_SLUG_PREFIX)]
        pages = [p for p in pages if not p.slug.startswith(JOURNAL_SLUG_PREFIX)]
        rows: list[str] = ["# Wiki index", ""]
        shown = pages[:MAX_INDEX_LINES]
        for page in shown:
            summary = " ".join(page.body.split())[:_INDEX_SUMMARY_CHARS]
            label = f"{page.title}" + (f" ({page.project})" if page.project else "")
            rows.append(f"- [[{page.slug}]] — {label}: {summary}")
        if len(pages) > len(shown):
            rows.append(f"- … +{len(pages) - len(shown)} more pages (wiki_ls で全件)")
        if journals:
            rows += ["", "## 日記", ""]
            for page in sorted(journals, key=lambda p: p.slug, reverse=True)[:MAX_INDEX_JOURNALS]:
                rows.append(f"- [[{page.slug}]] — {page.title}")
            rest = len(journals) - MAX_INDEX_JOURNALS
            if rest > 0:
                rows.append(f"- … 他 {rest} 日分（wiki_ls で全件）")
        rows.append("")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{INDEX_SLUG}.md"
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text("\n".join(rows), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.error("Wiki index rebuild failed: %s", exc)
            return Failure(WikiStoreError(f"cannot write index: {exc}"))
        return Success(None)
