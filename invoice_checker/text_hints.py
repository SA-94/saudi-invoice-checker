# -*- coding: utf-8 -*-
"""استخراج ما يمكن استخراجه من النص المضمّن في ملفات PDF (الفواتير الإلكترونية).

مجاني تماماً وما يحتاج قراءة ضوئية — النص أصلاً موجود داخل الملف.
"""
import re

from .validate import clean_vat_number, is_valid_saudi_vat, normalize_digits

# الرقم الضريبي جنب تسميته — الطريقة الآمنة.
# بدونها ينلقط أي 15 رقم يبدأ بـ3 وينتهي بـ3 (رقم طلب، رقم سجل، رقم حساب…)
VAT_LABELED = re.compile(
    r"(?:الرقم\s*الضريب[يى]|رقم\s*الضريب[ةيى]|الرقم\s*الضريبي\s*للمورد"
    r"|tax\s*(?:no|number|reg\w*)|vat\s*(?:no|number|reg\w*)|\bTRN\b|\bVAT\b)"
    r"[^\d\n]{0,25}((?:\d[\s.-]?){15})",
    re.I,
)

# الاحتياطي: 15 رقم كاملة بحدود صارمة — لا تكون جزءاً من رقم أطول
VAT_STRICT = re.compile(r"(?<!\d)3\d{13}3(?!\d)")

INVOICE_NO_PATTERNS = [
    re.compile(
        r"(?:رقم\s*الفاتورة|فاتورة\s*رقم|رقم\s*المستند)\s*[:\-#]?\s*([A-Za-z0-9\-/_]{3,30})"
    ),
    re.compile(
        r"(?:invoice\s*(?:no|number|#)|inv\s*#)\s*[:\-#]?\s*([A-Za-z0-9\-/_]{3,30})", re.I
    ),
]

TITLE_PATTERNS = [
    (re.compile(r"فاتورة\s*ضريبية\s*مبسطة"), "فاتورة ضريبية مبسطة"),
    (re.compile(r"فاتورة\s*ضريبية"), "فاتورة ضريبية"),
    (re.compile(r"simplified\s+tax\s+invoice", re.I), "Simplified Tax Invoice"),
    (re.compile(r"tax\s+invoice", re.I), "Tax Invoice"),
]

DATE_PATTERNS = [
    re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
    re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b"),
    # 18-Nov-2022 وصيغها
    re.compile(
        r"\b(\d{1,2}[-/\s](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
        r"[-/\s]\d{4})\b",
        re.I,
    ),
]

MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}

# رقم بصيغة مبلغ: 1,234.56 أو 1234.56 أو 460.00
AMOUNT = r"(-?[\d,]+\.\d{2}|-?[\d,]{1,12})"

# ترتيب المفاتيح مهم: الأكثر تحديداً أولاً عشان لا يلتقط الأعم بالغلط
AMOUNT_PATTERNS = {
    "total_amount": [
        r"(?:الإجمالي|الاجمالي|المجموع)\s*(?:شامل|مع)\s*(?:ال)?ضريبة\D{0,15}" + AMOUNT,
        r"(?:grand\s*total|total\s*(?:incl|inc|with)[\w.\s]{0,12}vat|total\s*amount)\D{0,15}" + AMOUNT,
        r"(?:المبلغ\s*المستحق|الصافي\s*المستحق|net\s*payable|amount\s*due)\D{0,15}" + AMOUNT,
    ],
    "vat_amount": [
        r"(?:مبلغ|قيمة)\s*(?:ال)?ضريبة\D{0,15}" + AMOUNT,
        r"(?:ضريبة\s*القيمة\s*المضافة)\D{0,15}" + AMOUNT,
        r"(?:vat\s*(?:amount|total)|total\s*vat)\D{0,15}" + AMOUNT,
    ],
    "net_amount": [
        r"(?:المجموع|الإجمالي|الاجمالي|المبلغ)\s*(?:قبل|بدون|غير\s*شامل)\s*(?:ال)?ضريبة\D{0,15}" + AMOUNT,
        r"(?:sub\s*total|subtotal|total\s*(?:excl|exc|before)[\w.\s]{0,12}vat|taxable\s*amount)\D{0,15}" + AMOUNT,
    ],
}
AMOUNT_PATTERNS = {
    k: [re.compile(p, re.I) for p in v] for k, v in AMOUNT_PATTERNS.items()
}


def _vat_numbers(text):
    """يستخرج الأرقام الضريبية بالترتيب، بلا تكرار.

    يقدّم الأرقام الملاصقة لتسميتها («الرقم الضريبي: …») لأنها موثوقة،
    وما يرجع للبحث الحر إلا إذا ما لقى ولا واحد معنون.
    """
    def collect(matches, group=0):
        out, seen = [], set()
        for match in matches:
            digits = re.sub(r"\D", "", match.group(group))
            if is_valid_saudi_vat(digits) and digits not in seen:
                seen.add(digits)
                out.append(digits)
        return out

    labeled = collect(VAT_LABELED.finditer(text), 1)
    return labeled or collect(VAT_STRICT.finditer(text))


def extract(text, seller_vat=None):
    """يستخرج تلميحات من نص الفاتورة. يرجّع قاموس بالحقول اللي لقاها فقط."""
    if not text or not text.strip():
        return {}

    flat = normalize_digits(text)
    found = {}

    # ----- الأرقام الضريبية -----
    seller_clean = clean_vat_number(seller_vat)
    vats = _vat_numbers(flat)

    others = [v for v in vats if v != seller_clean]
    if seller_clean is None and vats:
        found["seller_vat"] = vats[0]
        others = vats[1:]
    # ما ننسب رقماً للجمعية إلا إذا لقينا رقمين مختلفين فعلاً —
    # رقم خطأ في خانة الجمعية أسوأ من خانة فاضية
    if others:
        found["buyer_vat"] = others[0]

    # ----- رقم الفاتورة -----
    for pattern in INVOICE_NO_PATTERNS:
        match = pattern.search(flat)
        if match:
            found["invoice_no"] = match.group(1).strip(" :-#")
            break

    # ----- اسم/نوع الفاتورة -----
    for pattern, label in TITLE_PATTERNS:
        if pattern.search(flat):
            found["invoice_title"] = label
            break

    # ----- التاريخ -----
    for pattern in DATE_PATTERNS:
        match = pattern.search(flat)
        if match:
            found["invoice_date"] = _normalize_month(match.group(1))
            break

    # ----- المبالغ -----
    for key, patterns in AMOUNT_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(flat)
            if match:
                found[key] = match.group(1)
                break

    return found


def _normalize_month(text):
    """يحوّل 18-Nov-2022 إلى 2022-11-18، ويترك الباقي كما هو."""
    match = re.match(r"(\d{1,2})[-/\s]([A-Za-z]{3})[A-Za-z]*[-/\s](\d{4})", text)
    if not match:
        return text
    day, month, year = match.groups()
    number = MONTHS.get(month.lower())
    return f"{year}-{number:02d}-{int(day):02d}" if number else text
