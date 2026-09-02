# -*- coding: utf-8 -*-
"""تحميل ملفات الفواتير: صور (شاملة صور الآيفون) وملفات PDF."""
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:  # دعم صور الآيفون بصيغة HEIC
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED = IMAGE_SUFFIXES | PDF_SUFFIXES

# فوق هذا الحد ما فيه فايدة من الدقة الزائدة، بس بطء
MAX_EDGE = 4000


def find_invoices(folder):
    """يرجّع كل ملفات الفواتير داخل المجلد ومجلداته الفرعية، مرتّبة."""
    folder = Path(folder)
    files = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith("~$")
    ]
    return sorted(files, key=lambda p: (str(p.parent).lower(), p.name.lower()))


def _to_array(pil_img):
    """يحوّل صورة PIL إلى مصفوفة RGB مع تصحيح دوران الجوال."""
    pil_img = ImageOps.exif_transpose(pil_img).convert("RGB")
    w, h = pil_img.size
    if max(w, h) > MAX_EDGE:
        scale = MAX_EDGE / max(w, h)
        pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return np.array(pil_img)


def load(path):
    """يحمّل ملف فاتورة.

    يرجّع قاموس فيه:
        pages     — قائمة مصفوفات الصور (صفحة واحدة للصور، أو أكثر للـ PDF)
        pdf_text  — النص المضمّن في PDF إن وُجد (الفواتير الإلكترونية)
        error     — رسالة الخطأ إذا فشل التحميل
    """
    path = Path(path)
    result = {"pages": [], "pdf_text": "", "error": None}

    try:
        if path.suffix.lower() in PDF_SUFFIXES:
            import pymupdf

            with pymupdf.open(path) as doc:
                for page in doc:
                    result["pdf_text"] += page.get_text() + "\n"
                    # 300 نقطة/بوصة — كافية لقراءة الباركود بثقة
                    pix = page.get_pixmap(dpi=300)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    result["pages"].append(_to_array(img))
        else:
            result["pages"].append(_to_array(Image.open(path)))
    except Exception as exc:
        result["error"] = f"تعذّر فتح الملف: {exc}"

    return result
