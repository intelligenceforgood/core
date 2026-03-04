"""Tests for i4g.ocr.tesseract — OCR text extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_pil():
    """Patch PIL.Image and ImageOps to avoid real image processing."""
    with (
        patch("i4g.ocr.tesseract.Image") as mock_image,
        patch("i4g.ocr.tesseract.ImageOps") as mock_ops,
    ):
        fake_img = MagicMock()
        fake_img.convert.return_value = fake_img
        mock_image.open.return_value = fake_img
        mock_ops.exif_transpose.return_value = fake_img
        yield mock_image, mock_ops, fake_img


@pytest.fixture
def _mock_tesseract():
    """Patch pytesseract.image_to_string."""
    with patch("i4g.ocr.tesseract.pytesseract") as mock_tess:
        mock_tess.image_to_string.return_value = "OCR extracted text"
        yield mock_tess


@pytest.fixture
def _mock_pdfium():
    """Patch pypdfium2 for PDF processing."""
    with patch("i4g.ocr.tesseract.pdfium") as mock_pdf:
        mock_page = MagicMock()
        mock_bitmap = MagicMock()
        mock_pil_img = MagicMock()
        mock_pil_img.convert.return_value = mock_pil_img

        mock_bitmap.to_pil.return_value = mock_pil_img
        mock_page.render.return_value = mock_bitmap

        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 2
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_pdf.PdfDocument.return_value = mock_doc
        yield mock_pdf


class TestExtractTextImage:
    @pytest.mark.usefixtures("_mock_pil", "_mock_tesseract")
    def test_image_ocr(self, tmp_path):
        from i4g.ocr.tesseract import extract_text

        img_path = tmp_path / "test.png"
        img_path.touch()
        result = extract_text(str(img_path))
        assert result == "OCR extracted text"

    @pytest.mark.usefixtures("_mock_pil", "_mock_tesseract")
    def test_jpg_extension(self, tmp_path):
        from i4g.ocr.tesseract import extract_text

        img_path = tmp_path / "photo.jpg"
        img_path.touch()
        result = extract_text(str(img_path))
        assert "OCR" in result

    def test_image_error_returns_message(self, tmp_path):
        from i4g.ocr.tesseract import extract_text

        with patch("i4g.ocr.tesseract.Image") as mock_image:
            mock_image.open.side_effect = FileNotFoundError("No file")
            result = extract_text(str(tmp_path / "missing.png"))
            assert "Error processing image" in result


class TestExtractTextPdf:
    @pytest.mark.usefixtures("_mock_pdfium", "_mock_tesseract")
    def test_pdf_ocr(self, tmp_path):
        from i4g.ocr.tesseract import extract_text

        with patch("i4g.ocr.tesseract.ImageOps") as mock_ops:
            mock_ops.exif_transpose.side_effect = lambda img: img
            pdf_path = tmp_path / "doc.pdf"
            pdf_path.touch()
            result = extract_text(str(pdf_path))
            # Two pages, so two OCR calls joined by newline
            assert "OCR extracted text" in result


class TestBatchExtractText:
    @pytest.mark.usefixtures("_mock_pil", "_mock_tesseract")
    def test_batch_processes_directory(self, tmp_path):
        from i4g.ocr.tesseract import batch_extract_text

        (tmp_path / "img1.png").touch()
        (tmp_path / "img2.jpg").touch()

        with patch("i4g.ocr.tesseract.tqdm", side_effect=lambda x, **kw: x):
            results = batch_extract_text(str(tmp_path))

        assert len(results) == 2
        assert all("file" in r and "text" in r for r in results)

    def test_empty_directory(self, tmp_path):
        from i4g.ocr.tesseract import batch_extract_text

        with patch("i4g.ocr.tesseract.tqdm", side_effect=lambda x, **kw: x):
            results = batch_extract_text(str(tmp_path))
        assert results == []
