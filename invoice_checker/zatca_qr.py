# -*- coding: utf-8 -*-
"""قراءة باركود الزاتكا (QR) من صور الفواتير وفكّ تشفير بياناته.

باركود الفاتورة السعودية نص Base64 يحمل الحقول بصيغة TLV:
    الوسم 1 = اسم البائع
    الوسم 2 = الرقم الضريبي للبائع
    الوسم 3 = التاريخ والوقت
    الوسم 4 = الإجمالي شامل الضريبة
    الوسم 5 = مبلغ الضريبة

البيانات مقروءة من الباركود نفسه مو من الحبر، فما فيها أخطاء قراءة ضوئية.
القراءة على مراحل: السريعة أولاً، والمكلفة بس إذا فشلت اللي قبلها.
"""
import base64

import cv2
import numpy as np
import zxingcpp

TAG_SELLER_NAME = 1
TAG_SELLER_VAT = 2
TAG_TIMESTAMP = 3
TAG_TOTAL = 4
TAG_VAT = 5

# نحصر البحث في الباركود المربّع فقط — أسرع بكثير من مسح كل الأنواع
QR_FORMATS = zxingcpp.BarcodeFormat.QRCode | zxingcpp.BarcodeFormat.MicroQRCode


def decode_tlv(text):
    """يفكّ نص Base64 بصيغة TLV. يرجّع قاموس {الوسم: القيمة} أو None."""
    if not text or len(text) < 16:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        return None

    fields, i = {}, 0
    while i + 2 <= len(raw):
        tag, length = raw[i], raw[i + 1]
        if i + 2 + length > len(raw):
            return None  # طول غير منطقي — يعني مو TLV
        if tag not in fields:
            value = raw[i + 2 : i + 2 + length]
            try:
                fields[tag] = value.decode("utf-8").strip()
            except UnicodeDecodeError:
                fields[tag] = value.hex()  # التوقيع والمفتاح العام (وسوم 6-9)
        i += 2 + length

    # ما نعتبره باركود زاتكا إلا إذا فيه اسم البائع ورقمه الضريبي
    if TAG_SELLER_NAME in fields and TAG_SELLER_VAT in fields:
        return fields
    return None


def _scan(img):
    """يقرأ نصوص الباركودات المربّعة في الصورة."""
    try:
        return [b.text for b in zxingcpp.read_barcodes(img, formats=QR_FORMATS) if b.text]
    except Exception:
        return []


def _gray3(gray):
    """يحوّل صورة رمادية إلى ثلاث قنوات (المطلوب للقارئ)."""
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)


def _upscale(gray, factor, nearest=False):
    return cv2.resize(
        gray, None, fx=factor, fy=factor,
        interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_CUBIC,
    )


def _crop_qr_region(img, gray):
    """يحدّد مكان الباركود ويقصّه مع هامش. يرجّع None إذا ما لقاه."""
    for source in (img, gray):
        try:
            ok, pts = cv2.QRCodeDetector().detect(source)
        except Exception:
            continue
        if not ok or pts is None:
            continue
        p = pts.reshape(-1, 2).astype(int)
        pad = 30
        x0, y0 = max(p[:, 0].min() - pad, 0), max(p[:, 1].min() - pad, 0)
        x1 = min(p[:, 0].max() + pad, img.shape[1])
        y1 = min(p[:, 1].max() + pad, img.shape[0])
        if x1 > x0 and y1 > y0:
            return img[y0:y1, x0:x1]
    return None


def _stages(img):
    """يولّد نسخ الصورة على مراحل — من الأرخص للأغلى."""
    # ————— المرحلة 1: الصورة كما هي (تكفي لأغلب الفواتير) —————
    yield img

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # ————— المرحلة 2: تحويلات رخيصة —————
    yield _gray3(gray)
    yield _gray3(cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray))
    yield _gray3(
        cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
        )
    )
    if max(img.shape[:2]) < 3000:
        yield _gray3(_upscale(gray, 2))

    # ————— المرحلة 3: قصّ منطقة الباركود وتكبيرها بشدة —————
    # الأنجح للباركودات الصغيرة في الصور البعيدة
    crop = _crop_qr_region(img, gray)
    if crop is not None:
        for factor in (4, 8):
            yield _upscale(crop, factor)

    # ————— المرحلة 4: إزالة الضوضاء (مكلفة — للصور المشوّشة فقط) —————
    small = gray
    if max(gray.shape) > 2000:  # نصغّرها عشان إزالة الضوضاء ما تاخذ عمر
        scale = 2000 / max(gray.shape)
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    den = cv2.fastNlMeansDenoising(small, None, h=10)
    for factor in (2, 3, 4):
        yield _gray3(_upscale(den, factor))

    # زيادة الحدّة تعوّض اهتزاز التصوير
    sharp = cv2.addWeighted(den, 2.0, cv2.GaussianBlur(den, (0, 0), 3), -1.0, 0)
    yield _gray3(sharp)
    for factor in (2, 3):
        yield _gray3(_upscale(sharp, factor))

    _, otsu = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield _gray3(otsu)
    yield _gray3(_upscale(otsu, 3, nearest=True))

    # ————— المرحلة 5: الصورة مقلوبة —————
    for k in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        yield cv2.rotate(img, k)


def read(img):
    """يقرأ باركود الزاتكا من الصورة.

    يرجّع (الحقول, النص_الخام) عند النجاح، أو (None, النص_الخام) إذا لقى
    باركود لكنه مو باركود زاتكا، أو (None, None) إذا ما فيه باركود أصلاً.
    """
    any_text = None
    for stage in _stages(img):
        for text in _scan(stage):
            fields = decode_tlv(text)
            if fields:
                return fields, text
            any_text = any_text or text
    return None, any_text
