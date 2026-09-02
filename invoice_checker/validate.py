# -*- coding: utf-8 -*-
"""قواعد فحص الفاتورة الضريبية وتحديد حالتها."""
import re
import unicodedata
from datetime import date, datetime

# ————— الحقول: (المفتاح، الاسم بالعربي، إلزامي؟) —————
FIELDS = [
    ("invoice_date", "تاريخ الفاتورة", True),
    ("seller_name", "اسم المورد", True),
    ("seller_vat", "الرقم الضريبي للمورد", True),
    ("net_amount", "المبلغ قبل الضريبة", True),
    ("vat_amount", "الضريبة", True),
    ("total_amount", "المبلغ شامل الضريبة", True),
    ("buyer_name", "اسم الجمعية", True),
    ("buyer_vat", "الرقم الضريبي للجمعية", True),
    ("invoice_no", "رقم الفاتورة", True),
    ("invoice_title", "اسم الفاتورة", True),
    # العناوين اختيارية — ما تطلع تنبيه إذا ما كانت في الفاتورة
    ("seller_address", "عنوان المورد", False),
    ("buyer_address", "عنوان الجمعية", False),
]
LABEL = {k: ar for k, ar, _ in FIELDS}
REQUIRED = [k for k, _, req in FIELDS if req]
OPTIONAL = [k for k, _, req in FIELDS if not req]

OK, REVIEW, MISSING = "سليمة", "تحتاج مراجعة", "ناقصة"

# نسب الضريبة المقبولة في السعودية: القياسية، والقديمة، والمعفاة
VALID_VAT_RATES = (0.15, 0.05, 0.0)
AMOUNT_TOLERANCE = 0.02  # فرق الهللات المسموح من التقريب

# الأرقام العربية والفارسية + الفاصلة العشرية (٫) وفاصلة الآلاف (٬) العربيتين
_ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬",
    "01234567890123456789.,",
)


def normalize_digits(text):
    """يحوّل الأرقام العربية والفارسية إلى أرقام إنجليزية."""
    return str(text).translate(_ARABIC_DIGITS)


def clean_text(value):
    """ينظّف النص: يشيل الفراغات الزائدة والمحارف غير المرئية."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"[​-‏‪-‮﻿]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_amount(value):
    """يحوّل أي صيغة مبلغ إلى رقم عشري. يرجّع None إذا ما قدر.

    يتعامل مع: ١٬١٥٠٫٠٠ ر.س  |  SAR 2,300.00  |  1.234,56  |  (500.00)
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = normalize_digits(clean_text(value) or "")
    negative = bool(re.search(r"^\s*\(.*\)\s*$", text))  # صيغة محاسبية للسالب

    # نلقط الأرقام بدل ما نشيل الحروف — عشان لا تتسرّب نقطة «ر.س»
    tokens = [t.strip(".,") for t in re.findall(r"\d[\d.,]*", text)]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    token = max(tokens, key=len)  # المبلغ عادةً أطول رقم في الحقل

    # يفرّق بين 1,234.56 و 1.234,56
    if "," in token and "." in token:
        token = (
            token.replace(",", "")
            if token.rindex(".") > token.rindex(",")
            else token.replace(".", "").replace(",", ".")
        )
    elif "," in token:
        parts = token.split(",")
        # فاصلة واحدة يتبعها رقم أو رقمين = فاصلة عشرية، غير كذا = فاصلة آلاف
        token = token.replace(",", "." if len(parts) == 2 and len(parts[1]) in (1, 2) else "")
    elif token.count(".") > 1:  # 1.234.567 = فواصل آلاف
        token = token.replace(".", "")

    try:
        amount = float(token)
    except ValueError:
        return None
    if negative or re.search(r"-\s*[\d٠-٩]", text):
        amount = -abs(amount)
    return amount


def parse_date(value):
    """يحوّل أي صيغة تاريخ إلى كائن تاريخ. يرجّع None إذا ما قدر.

    يتعامل مع صيغة الباركود (2026-08-12T13:45:00Z) وصيغ الفواتير المعتادة.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = normalize_digits(clean_text(value) or "")
    if not text:
        return None

    iso = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if iso:
        try:
            return date(*(int(g) for g in iso.groups()))
        except ValueError:
            return None

    dmy = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
    if dmy:
        day, month, year = (int(g) for g in dmy.groups())
        if month > 12 and day <= 12:  # مكتوب بالصيغة الأمريكية
            day, month = month, day
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def format_date(value):
    """يرجّع التاريخ بصيغة YYYY-MM-DD، أو النص كما هو إذا ما انقرأ."""
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else clean_text(value)


def is_valid_saudi_vat(value):
    """الرقم الضريبي السعودي: 15 رقم، يبدأ بـ3 وينتهي بـ3."""
    if not value:
        return False
    digits = re.sub(r"\D", "", normalize_digits(value))
    return len(digits) == 15 and digits[0] == "3" and digits[-1] == "3"


def clean_vat_number(value):
    """يستخرج الأرقام فقط من الرقم الضريبي."""
    if not value:
        return None
    return re.sub(r"\D", "", normalize_digits(value)) or None


def check(record):
    """يفحص فاتورة واحدة ويرجّع (الحالة، قائمة التنبيهات، قائمة الفحوصات).

    `record` قاموس فيه مفاتيح FIELDS + `has_qr` + `qr_amounts`.
    """
    alerts, checks = [], {}
    hard_missing = False  # حقل مطلوب مفقود تماماً
    soft_issue = False    # موجود لكن فيه شك

    # ————— 1. الباركود —————
    checks["الباركود"] = bool(record.get("has_qr"))
    if not record.get("has_qr"):
        alerts.append("ما فيه باركود (QR) في الفاتورة")
        hard_missing = True

    # ————— 2. وجود الحقول المطلوبة —————
    for key in REQUIRED:
        present = clean_text(record.get(key)) is not None
        checks[LABEL[key]] = present
        if not present:
            alerts.append(f"{LABEL[key]} غير موجود")
            hard_missing = True

    # ————— 3. صيغة الأرقام الضريبية —————
    for key in ("seller_vat", "buyer_vat"):
        value = record.get(key)
        if value:
            valid = is_valid_saudi_vat(value)
            checks[f"صيغة {LABEL[key]}"] = valid
            if not valid:
                digits = clean_vat_number(value) or ""
                alerts.append(
                    f"{LABEL[key]} صيغته غير صحيحة ({len(digits)} رقم — المفروض 15 رقم يبدأ بـ3 وينتهي بـ3)"
                )
                soft_issue = True

    # المورد والمشتري ما يمكن يكونون نفس الجهة
    s_vat, b_vat = clean_vat_number(record.get("seller_vat")), clean_vat_number(record.get("buyer_vat"))
    if s_vat and b_vat and s_vat == b_vat:
        alerts.append("الرقم الضريبي للمورد والمشتري نفسه — أحدهما غلط")
        soft_issue = True

    # ————— 4. صحة الحساب —————
    net = parse_amount(record.get("net_amount"))
    vat = parse_amount(record.get("vat_amount"))
    total = parse_amount(record.get("total_amount"))

    if None not in (net, vat, total):
        correct = abs((net + vat) - total) <= max(AMOUNT_TOLERANCE, abs(total) * 0.001)
        checks["الحساب صحيح"] = correct
        if not correct:
            alerts.append(
                f"الحساب ما يضبط: {net:,.2f} + {vat:,.2f} = {net + vat:,.2f} "
                f"لكن المكتوب {total:,.2f}"
            )
            soft_issue = True

        # نسبة الضريبة
        if net > 0:
            rate = vat / net
            sane = any(abs(rate - r) <= 0.005 for r in VALID_VAT_RATES)
            checks["نسبة الضريبة منطقية"] = sane
            if not sane:
                alerts.append(f"نسبة الضريبة {rate * 100:.1f}% — غير معتادة (المتوقع 15%)")
                soft_issue = True

    # ————— 5. مطابقة المكتوب في الفاتورة مع الباركود —————
    # اختلافهما يعني خطأ طباعة أو تلاعب — من أهم الفحوصات
    printed_values = record.get("printed") or {}
    for key in ("net_amount", "vat_amount", "total_amount"):
        from_qr = parse_amount(record.get(key))
        printed = parse_amount(printed_values.get(key))
        if None in (from_qr, printed):
            continue
        matches = abs(from_qr - printed) <= AMOUNT_TOLERANCE
        checks[f"{LABEL[key]} يطابق الباركود"] = matches
        if not matches:
            alerts.append(
                f"{LABEL[key]}: المطبوع في الفاتورة {printed:,.2f} "
                f"لكن الباركود يقول {from_qr:,.2f}"
            )
            soft_issue = True

    # ————— 6. اسم الفاتورة —————
    title = clean_text(record.get("invoice_title"))
    if title:
        looks_right = "فاتورة" in title or "invoice" in title.lower()
        checks["اسم الفاتورة صحيح"] = looks_right
        if not looks_right:
            alerts.append(f"اسم الفاتورة «{title}» ما يوضّح إنها فاتورة ضريبية")
            soft_issue = True

    status = MISSING if hard_missing else (REVIEW if soft_issue else OK)
    return status, alerts, checks


def find_duplicates(records):
    """يعلّم الفواتير المكرّرة. يعدّل السجلات في مكانها."""
    seen = {}
    for rec in records:
        vat = clean_vat_number(rec.get("seller_vat"))
        no = clean_text(rec.get("invoice_no"))
        key = (vat, no) if vat and no else (rec.get("qr_raw") or None,)
        if key == (None,):
            continue
        if key in seen:
            note = f"مكرّرة — نفس فاتورة «{seen[key]}»"
            rec.setdefault("alerts", []).append(note)
            if rec.get("status") == OK:
                rec["status"] = REVIEW
        else:
            seen[key] = rec.get("file_name")
