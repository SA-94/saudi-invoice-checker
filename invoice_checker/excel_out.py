# -*- coding: utf-8 -*-
"""كتابة نتائج الفحص بصيغة «سجل المشتريات المحلية» الرسمي.

النموذج مطابق خلية بخلية للنموذج المعتمد: ترويسة الجمعية، ثم جدول
بعشرة أعمدة لكل عمود تنسيقه وحدوده، ثم صف الإجمالي بمعادلات جمع.
ملاحظات الفحص تظهر في الواجهة فقط، وما تنكتب في الملف.
"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import validate

# ————— نصوص الترويسة —————
HEADER_LINES = [
    "المملكة العربية السعودية",
    "جمعية تحفيظ القرآن الكريم بالدائر",
    "مسجلة بالمركز الوطني للقطاع غير الربحي",
    "ترخيص رقم 3118",
    "رقم الاسترداد (    )",
]
TITLE = " سجل المشتريات المحلية  "
PERIOD_START = "2026/01/01"   # بداية الفترة ثابتة بطلب الجمعية
TOTAL_LABEL = "الاجمـــــــالي"

# ————— صيغ الأرقام —————
ACC_INT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
ACC_DEC = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
DATE_FMT = "mm/dd/yyyy"

# ————— الأعمدة: العنوان، المفتاح، العرض، صيغة الخلية، المحاذاة، الالتفاف —————
# (المحاذاة والصيغة منقولة حرفياً من النموذج المعتمد)
COLUMNS = [
    ("م",                     "_index",        8.375,  "General", "center", False),
    ("تاريخ الفاتورة ",       "invoice_date", 17.75,   DATE_FMT,  "center", False),
    ("رقم الفاتورة ",         "invoice_no",   21.0,    "General", "center", False),
    ("اسم المورد ",           "seller_name",  49.375,  "0.00",    "right",  False),
    ("الرقم الضريبي للمورد",  "seller_vat",   25.25,   "0",       "center", False),
    ("وصف المنتج / الخدمة ",  "_description", 53.5,    "0.00",    "right",  True),
    ("معدل الضريبة ",         "_vat_rate",    15.875,  "0%",      "center", True),
    ("القيمة قبل الضريبة ",   "net_amount",   21.5,    ACC_DEC,   "center", True),
    ("ضريبة القيمة المضافة ", "vat_amount",   24.375,  ACC_DEC,   "center", True),
    ("القيمة بعد الضريبة ",   "total_amount", 21.375,  ACC_DEC,   "center", True),
]
SUM_KEYS = ("net_amount", "vat_amount", "total_amount")
MANUAL_KEYS = ("_description",)   # تُعبّأ يدوياً

# عناوين بلا التفاف نص (عمود «اسم المورد» فقط)، وأعمدة حدّها الأيمن عريض
HEADER_NO_WRAP = {"seller_name"}
RIGHT_MEDIUM = {"total_amount"}   # J آخر عمود
LAST_COLUMN = "total_amount"
TOP_HAIR_FIRST_ROW = {"_description"}       # F في النموذج حدّها العلوي رفيع

# ————— الأنماط —————
FONT = "Arial"
HEADER_ROW = 7
FIRST_DATA_ROW = 8
MIN_DATA_ROWS = 13          # نبقي شكل النموذج حتى لو الفواتير أقل

TITLE_FONT = Font(name=FONT, size=16)
BIG_FONT = Font(name=FONT, size=18, bold=True)
BOLD16 = Font(name=FONT, size=16, bold=True)

TH_FILL = PatternFill("solid", fgColor=Color(theme=8, tint=0.8))
TD_FILL = PatternFill("solid", fgColor=Color(theme=0, tint=0.0))
SUM_FILL = PatternFill("solid", fgColor="FFFFFF00")

MEDIUM, THIN, HAIR = Side(style="medium"), Side(style="thin"), Side(style="hair")
CENTER = Alignment(horizontal="center", vertical="center")

ROW_HEIGHTS = {1: 25.15, 2: 25.15, 3: 25.15, 4: 25.15, 5: 25.15, 6: 38.45, 7: 51.6}
DATA_ROW_HEIGHT = 30.0


def _period_line(records):
    """سطر الفترة: من بداية الفترة الثابتة إلى أحدث تاريخ فاتورة."""
    dates = [d for d in (validate.parse_date(r.get("invoice_date")) for r in records) if d]
    if not dates:
        return f"الفترة من {PERIOD_START}م  :"
    return f"الفترة من {PERIOD_START}م  :  {max(dates).strftime('%Y/%m/%d')} م"


def _vat_rate(rec):
    """نسبة الضريبة الفعلية، أو 15% الافتراضية لو ما قدرنا نحسبها."""
    net = validate.parse_amount(rec.get("net_amount"))
    vat = validate.parse_amount(rec.get("vat_amount"))
    if net and vat is not None and net > 0:
        return round(vat / net, 4)
    return 0.15


def _value(rec, key, index):
    if key == "_index":
        return index
    if rec is None:
        return 0.15 if key == "_vat_rate" else None
    if key == "_vat_rate":
        return _vat_rate(rec)
    if key in MANUAL_KEYS:
        return None
    value = rec.get(key)
    if key == "invoice_date":
        return validate.parse_date(value) or validate.clean_text(value)
    if key in SUM_KEYS:
        parsed = validate.parse_amount(value)
        return float(parsed) if parsed is not None else None
    if key == "seller_vat" and value:
        return str(value)                 # نص عشان لا يفقد إكسل خانات الرقم
    return value


def _border(key, col, is_header, is_first, is_last):
    """حدود الخلية حسب موقعها — منقولة من النموذج."""
    if is_header:
        return Border(
            left=MEDIUM if col == 1 else THIN,
            right=MEDIUM if key in RIGHT_MEDIUM else THIN,
            top=MEDIUM, bottom=MEDIUM,
        )
    top = HAIR
    if is_first:
        top = HAIR if key in TOP_HAIR_FIRST_ROW else MEDIUM
    return Border(
        left=THIN,
        right=MEDIUM if key == LAST_COLUMN else THIN,
        top=top,
        bottom=MEDIUM if is_last else HAIR,
    )


def _write_header(ws, records):
    for i, text in enumerate(HEADER_LINES, start=1):
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=3)
        cell = ws.cell(row=i, column=1, value=text)
        cell.font, cell.alignment = TITLE_FONT, CENTER

    for row, text in ((5, TITLE), (6, _period_line(records))):
        cell = ws.cell(row=row, column=6, value=text)
        cell.font, cell.alignment = BIG_FONT, CENTER

    for row, height in ROW_HEIGHTS.items():
        ws.row_dimensions[row].height = height


def _write_table_header(ws):
    for col, (title, key, width, _, _, _) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
        cell = ws.cell(row=HEADER_ROW, column=col, value=title)
        cell.font, cell.fill, cell.number_format = BOLD16, TH_FILL, ACC_INT
        cell.alignment = Alignment(
            horizontal="center", vertical="center",
            wrap_text=key not in HEADER_NO_WRAP,
        )
        cell.border = _border(key, col, True, False, False)


def _write_rows(ws, records):
    count = max(len(records), MIN_DATA_ROWS)
    for i in range(count):
        row = FIRST_DATA_ROW + i
        rec = records[i] if i < len(records) else None
        ws.row_dimensions[row].height = DATA_ROW_HEIGHT

        for col, (_, key, _, fmt, halign, wrap) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row, column=col, value=_value(rec, key, i + 1))
            cell.font = BOLD16
            cell.fill = TD_FILL
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal=halign, vertical="center", wrap_text=wrap)
            cell.border = _border(key, col, False, i == 0, i == count - 1)
    return FIRST_DATA_ROW + count - 1


def _write_total(ws, first, last):
    row = last + 1
    # الخطوط قبل الدمج — الخلايا المدموجة تصير للقراءة فقط بعده
    for col in range(2, 8):
        ws.cell(row=row, column=col).font = Font(name=FONT, size=11)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    label = ws.cell(row=row, column=1, value=TOTAL_LABEL)
    label.font, label.alignment = BIG_FONT, CENTER
    label.border = Border(right=MEDIUM, top=MEDIUM)

    plain11 = Font(name=FONT, size=11)
    for col, (_, key, _, _, _, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=row, column=col)
        if key in SUM_KEYS:
            letter = get_column_letter(col)
            cell.value = f"=SUM({letter}{first}:{letter}{last})"
            cell.font, cell.fill = BOLD16, SUM_FILL
            cell.alignment, cell.number_format = CENTER, ACC_DEC
            cell.border = Border(left=MEDIUM, right=MEDIUM, bottom=MEDIUM)
        elif col > 1:
            cell.font = plain11   # بقية خلايا الصف تتبع خط النموذج


def write(records, path):
    """يكتب سجل المشتريات المحلية في ملف إكسل."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ورقة1"
    ws.sheet_view.rightToLeft = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9          # A4

    _write_header(ws, records)
    _write_table_header(ws)
    last = _write_rows(ws, records)
    _write_total(ws, FIRST_DATA_ROW, last)

    wb.save(path)
    return path
