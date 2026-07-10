"""
PDF解析ツール (_handle_read_pdf) の単体テスト

テスト対象: nous.application.chat.tools.builtin._handle_read_pdf
シグネチャ: async def _handle_read_pdf(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict

テスト用PDFは PyMuPDF (fitz) で動的に生成し、テスト後に確実に削除する。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fitz  # PyMuPDF
import pytest

# ── ヘルパー ──


def create_test_pdf(path: str) -> str:
    """テスト用PDFを作成 (1ページ、テキスト+図形を含む)

    日本語テキストを正しく抽出できるよう fontname='japan' を指定する。
    """
    doc = fitz.open()
    page = doc.new_page()

    # テキスト挿入 (CJKフォントを指定して日本語を正しく埋め込む)
    page.insert_text((50, 50), "テスト用PDF文書", fontname="japan")
    page.insert_text((50, 80), "これはテスト文書です。", fontname="japan")
    page.insert_text((50, 110), "サンプルテキスト行3", fontname="japan")

    # 簡単な矩形を描画 (画像として抽出されるわけではないがxobjectとして埋め込まれる)
    rect = fitz.Rect(100, 200, 200, 250)
    page.draw_rect(rect, color=(0, 0, 1), fill=(0.5, 0.5, 0.5))

    doc.save(path)
    doc.close()
    return path


def create_test_pdf_multi_page(path: str, pages: int = 3) -> str:
    """複数ページのテストPDFを作成"""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((50, 50), f"ページ {i + 1}", fontname="japan")
        page.insert_text((50, 80), f"内容 {i + 1}", fontname="japan")
    doc.save(path)
    doc.close()
    return path


# ── テスト ──


@pytest.mark.asyncio
async def test_read_pdf_basic_text():
    """PDFテキスト抽出の基本テスト"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = create_test_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        from nous.application.chat.tools.builtin import _handle_read_pdf

        result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert "テスト用PDF文書" in result["text"]
        assert "サンプルテキスト行3" in result["text"]
        assert result["pages"] == 1
        assert result["filename"].endswith(".pdf")
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_multi_page():
    """複数ページPDF"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = create_test_pdf_multi_page(f.name, pages=3)

    try:
        ctx = MagicMock()
        config = MagicMock()

        from nous.application.chat.tools.builtin import _handle_read_pdf

        result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert result["pages"] == 3
        assert "ページ 1" in result["text"]
        assert "ページ 2" in result["text"]
        assert "ページ 3" in result["text"]
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_file_not_found():
    """存在しないファイルのエラーハンドリング"""
    ctx = MagicMock()
    config = MagicMock()

    from nous.application.chat.tools.builtin import _handle_read_pdf

    result = await _handle_read_pdf(ctx, config, {"path": "/tmp/nonexistent_file_xyz.pdf"})

    assert result["status"] == "error"
    assert "File not found" in result["message"]


@pytest.mark.asyncio
async def test_read_pdf_not_a_pdf():
    """PDF以外のファイルはエラー"""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"not a pdf")
        txt_path = f.name

    try:
        ctx = MagicMock()
        config = MagicMock()

        from nous.application.chat.tools.builtin import _handle_read_pdf

        result = await _handle_read_pdf(ctx, config, {"path": txt_path})

        assert result["status"] == "error"
        assert "Not a PDF file" in result["message"]
    finally:
        Path(txt_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_missing_path():
    """pathパラメータ不足"""
    ctx = MagicMock()
    config = MagicMock()

    from nous.application.chat.tools.builtin import _handle_read_pdf

    result = await _handle_read_pdf(ctx, config, {})

    assert result["status"] == "error"
    assert "PDF path not specified" in result["message"]


@pytest.mark.asyncio
async def test_read_pdf_has_tables():
    """tables / images フィールドが常に返されること"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = create_test_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        from nous.application.chat.tools.builtin import _handle_read_pdf

        result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        # tables フィールドがリストであること
        assert "tables" in result
        assert isinstance(result["tables"], list)
        # images フィールドがリストであること
        assert "images" in result
        assert isinstance(result["images"], list)
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_text_truncation():
    """長文テキストが100,000文字で切り詰められること

    複数ページにまたがる大量テキストで、テキスト上限 (100,000文字)
    を超えた場合に切り捨てメッセージが付与されることを確認する。
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    # 100K文字を超えるテキストを含むPDFを生成 (ASCIIテキストで十分)
    doc = fitz.open()
    line = "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 8
    pages_needed = 100  # 100ページあれば 100K を超える
    for i in range(pages_needed):
        page = doc.new_page()
        for j in range(10):
            page.insert_text((50, 50 + j * 15), f"P{i:03d} {line}", fontsize=5)
    doc.save(pdf_path)
    doc.close()

    try:
        ctx = MagicMock()
        config = MagicMock()

        from nous.application.chat.tools.builtin import _handle_read_pdf

        result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        # テキストが上限 (100,000) + 切り捨てメッセージ分に収まっている
        assert len(result["text"]) <= 100_100
        assert "Text truncated" in result["text"]
    finally:
        Path(pdf_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════
# フォールバック連鎖テスト
# ═══════════════════════════════════════════════════════════════════


def _make_minimal_pdf(path: str) -> str:
    """パス検証を通すための最小限PDF (中身は空テキスト)"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "x", fontname="japan")  # 1文字だけ
    doc.save(path)
    doc.close()
    return path


@pytest.mark.asyncio
async def test_read_pdf_fallback_pdfplumber():
    """PyMuPDF空テキスト → pdfplumber フォールバック"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = _make_minimal_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        # Mock fitz module in sys.modules: empty text
        mock_page = MagicMock(spec=fitz.Page)
        mock_page.get_text.return_value = ""
        mock_page.get_images.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([mock_page])
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        mock_doc.close.return_value = None

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # Mock pdfplumber module: returns text + tables
        mock_plumb_page = MagicMock()
        mock_plumb_page.extract_text.return_value = (
            "pdfplumber fallback text content that is definitely much longer than fifty characters so the check passes."
        )
        mock_plumb_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_plumb_page]
        mock_pdf.__enter__.return_value = mock_pdf

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict("sys.modules", {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            from nous.application.chat.tools.builtin import _handle_read_pdf

            result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert "pdfplumber fallback text content" in result["text"]
        assert len(result["text"]) > 50
        assert result["text_source"] == "pdfplumber"
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_fallback_ocr():
    """PyMuPDF + pdfplumber 空テキスト → OCR フォールバック"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = _make_minimal_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        # Mock fitz: empty text, get_pixmap works
        mock_page = MagicMock(spec=fitz.Page)
        mock_page.get_text.return_value = ""
        mock_page.get_images.return_value = []

        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake_png_bytes"
        mock_page.get_pixmap.return_value = mock_pix

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([mock_page])
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        mock_doc.close.return_value = None

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # Mock pdfplumber: empty text
        mock_plumb_page = MagicMock()
        mock_plumb_page.extract_text.return_value = ""
        mock_plumb_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_plumb_page]
        mock_pdf.__enter__.return_value = mock_pdf

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        # Mock PIL.Image
        mock_img = MagicMock()
        mock_img.convert.return_value = mock_img

        mock_image_class = MagicMock()
        mock_image_class.open.return_value = mock_img

        # Mock pytesseract
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "OCR extracted text\n"

        with patch.dict(
            "sys.modules",
            {
                "fitz": mock_fitz,
                "pdfplumber": mock_pdfplumber,
                "PIL": MagicMock(),
                "PIL.Image": mock_image_class,
                "pytesseract": mock_pytesseract,
            },
        ):
            from nous.application.chat.tools.builtin import _handle_read_pdf

            result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert "OCR extracted text" in result["text"]
        assert result["text_source"] == "ocr"
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_pymupdf_normal_text():
    """通常テキスト抽出 → text_source = 'pymupdf' (リグレッションチェック)"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = _make_minimal_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        # Mock fitz: normal text (>50 chars)
        mock_page = MagicMock(spec=fitz.Page)
        mock_page.get_text.return_value = (
            "Normal PDF text content that is longer than fifty characters for testing purposes."
        )
        mock_page.get_images.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([mock_page])
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        mock_doc.close.return_value = None

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz, "pdfplumber": MagicMock()}):
            from nous.application.chat.tools.builtin import _handle_read_pdf

            result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert result["text_source"] == "pymupdf"
        assert "Normal PDF text content" in result["text"]
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_ocr_no_images():
    """OCRテキスト → ページラスター画像が追加されること"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = _make_minimal_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        # Mock fitz: empty text, get_pixmap works, no embedded images
        mock_page = MagicMock(spec=fitz.Page)
        mock_page.get_text.return_value = ""
        mock_page.get_images.return_value = []

        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"raster_png_bytes"
        mock_page.get_pixmap.return_value = mock_pix

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([mock_page])
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        mock_doc.close.return_value = None

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # Mock pdfplumber: empty
        mock_plumb_page = MagicMock()
        mock_plumb_page.extract_text.return_value = ""
        mock_plumb_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_plumb_page]
        mock_pdf.__enter__.return_value = mock_pdf

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        # Mock PIL.Image
        mock_image_class = MagicMock()

        # Mock pytesseract
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "OCR extracted\n"

        with patch.dict(
            "sys.modules",
            {
                "fitz": mock_fitz,
                "pdfplumber": mock_pdfplumber,
                "PIL": MagicMock(),
                "PIL.Image": mock_image_class,
                "pytesseract": mock_pytesseract,
            },
        ):
            from nous.application.chat.tools.builtin import _handle_read_pdf

            result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        assert result["status"] == "success"
        assert len(result["images"]) == 1
        assert result["images"][0]["source"] == "page_raster"
        assert result["images"][0]["mime_type"] == "image/png"
    finally:
        Path(pdf_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_read_pdf_ocr_import_error():
    """pytesseract 未インストール → graceful degradation (text_source = 'empty')"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = _make_minimal_pdf(f.name)

    try:
        ctx = MagicMock()
        config = MagicMock()

        # Mock fitz: empty text
        mock_page = MagicMock(spec=fitz.Page)
        mock_page.get_text.return_value = ""
        mock_page.get_images.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([mock_page])
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        mock_doc.close.return_value = None

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # Mock pdfplumber: empty text
        mock_plumb_page = MagicMock()
        mock_plumb_page.extract_text.return_value = ""
        mock_plumb_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_plumb_page]
        mock_pdf.__enter__.return_value = mock_pdf

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        # Simulate ImportError for pytesseract: don't add it to sys.modules
        # Also mock PIL.Image to avoid "from PIL import Image" failing
        mock_image_class = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "fitz": mock_fitz,
                "pdfplumber": mock_pdfplumber,
                "PIL": MagicMock(),
                "PIL.Image": mock_image_class,
                # pytesseract を sys.modules に入れない → import が ImportError
            },
        ):
            from nous.application.chat.tools.builtin import _handle_read_pdf

            result = await _handle_read_pdf(ctx, config, {"path": pdf_path})

        # OCR がスキップされてもエラーにならず、テキスト空で返る
        assert result["status"] == "success"
        assert isinstance(result["text"], str)
        assert result["text_source"] == "empty"
    finally:
        Path(pdf_path).unlink(missing_ok=True)
