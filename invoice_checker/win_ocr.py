# -*- coding: utf-8 -*-
"""قراءة النصوص من صور الفواتير عبر محرك ويندوز المدمج.

مجاني وبدون إنترنت وبدون تنصيب أي برنامج خارجي — المحرك جزء من ويندوز نفسه
ويدعم العربية والإنجليزية. يُستخدم للفواتير اللي ما فيها باركود زاتكا.
"""
import asyncio
import io
import threading

import cv2
import numpy as np
from PIL import Image

try:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    AVAILABLE = True
except ImportError:  # مو ويندوز، أو المكتبات مو منصّبة
    AVAILABLE = False

# المحرك يقبل حتى 10000 بكسل، لكن فوق 5000 يبطّئ بدون فايدة تُذكر
MAX_DIMENSION = 5000
# التكبير هو أهم عامل في الدقة: قياسنا على فاتورة حقيقية 785×1280 أعطى
# 3 من 5 حقول بالمقاس الأصلي، و5 من 5 بعد التكبير للضلع الأطول ≈ 3800.
MIN_DIMENSION = 3600

_engines = {}
_lock = threading.Lock()


def available_languages():
    """يرجّع لغات القراءة المتاحة على الجهاز."""
    if not AVAILABLE:
        return []
    try:
        return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    except Exception:
        return []


def has_arabic():
    """هل محرك القراءة العربي منصّب؟"""
    return any(tag.lower().startswith("ar") for tag in available_languages())


def _engine(tag):
    """ينشئ محرك قراءة للغة المطلوبة (ويحتفظ فيه)."""
    with _lock:
        if tag not in _engines:
            try:
                _engines[tag] = OcrEngine.try_create_from_language(Language(tag))
            except Exception:
                _engines[tag] = None
        return _engines[tag]


def _prepare(img):
    """يجهّز الصورة للقراءة: تكبير المناسب وتحويلها إلى PNG."""
    height, width = img.shape[:2]
    longest = max(height, width)

    scale = 1.0
    if longest < MIN_DIMENSION:
        scale = MIN_DIMENSION / longest
    elif longest > MAX_DIMENSION:
        scale = MAX_DIMENSION / longest

    if scale != 1.0:
        interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)

    if scale > 1.0:  # التكبير يطرّي الحواف — الحدّة ترجّعها
        img = cv2.addWeighted(img, 1.7, cv2.GaussianBlur(img, (0, 0), 2), -0.7, 0)

    buffer = io.BytesIO()
    Image.fromarray(img).save(buffer, format="PNG")
    return buffer.getvalue()


async def _recognize(png_bytes, tag):
    engine = _engine(tag)
    if engine is None:
        return ""

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)

    # سطر بسطر — أوضح للتحليل من النص المدموج
    return "\n".join(line.text for line in result.lines)


def read_text(img, languages=None):
    """يقرأ نص الصورة. يرجّع النص، أو نص فاضي إذا ما نجح.

    نشغّل المحركين العربي والإنجليزي ونجمع الناتج، لأن الفواتير السعودية
    ثنائية اللغة وكل محرك يلقط ما يفوت الثاني.
    """
    if not AVAILABLE:
        return ""
    if languages is None:
        languages = available_languages() or ["en-US"]

    try:
        png = _prepare(img)
    except Exception:
        return ""

    chunks = []
    for tag in languages:
        try:
            text = asyncio.run(_recognize(png, tag))
        except Exception:
            text = ""
        if text.strip():
            chunks.append(text)
    return "\n".join(chunks)
