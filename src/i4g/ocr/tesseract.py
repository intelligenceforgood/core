"""
OCR module using Tesseract for text extraction from screenshots or PDFs.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps
from tqdm import tqdm


def extract_text(image_path: str) -> str:
    """
    Perform OCR on a given image using Tesseract.
    Args:
        image_path (str): Path to the image file.
    Returns:
        str: Extracted text.
    """
    path = Path(image_path)
    if path.suffix.lower() == ".pdf":
        try:
            pdf = pdfium.PdfDocument(image_path)
            text_parts = []
            for i in range(len(pdf)):
                page = pdf[i]
                bitmap = page.render(scale=2)  # scale=2 for better OCR resolution
                pil_image = bitmap.to_pil()
                pil_image = ImageOps.exif_transpose(pil_image)
                pil_image = pil_image.convert("L")
                text_parts.append(pytesseract.image_to_string(pil_image, lang="eng"))
            return "\n".join(text_parts)
        except Exception as e:
            return f"Error processing PDF {path.name}: {e}"

    try:
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)  # auto-rotate if needed
        img = img.convert("L")  # grayscale
        return pytesseract.image_to_string(img, lang="eng")
    except Exception as e:
        return f"Error processing image {path.name}: {e}"


def batch_extract_text(image_dir: str) -> list[dict[str, str]]:
    """
    OCR for all images in a directory.
    Args:
        image_dir (str): Directory containing images.
    Returns:
        List[Dict[str, str]]: List of {filename, text}.
    """
    results = []
    img_paths = list(Path(image_dir).glob("*.*"))
    for img_path in tqdm(img_paths, desc="Running OCR"):
        text = extract_text(str(img_path))
        results.append({"file": img_path.name, "text": text})
    return results
