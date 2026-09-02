# -*- coding: utf-8 -*-
"""تشغيل الفحص على مجلد كامل: قراءة -> استخراج -> فحص -> نتائج."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import excel_out, loader, text_hints, validate, win_ocr, zatca_qr
from .validate import FIELDS, LABEL, MISSING, OK, REQUIRED, REVIEW

SOURCE_QR = "باركود"
SOURCE_PDF = "نص PDF"
SOURCE_OCR = "قراءة ويندوز"
SOURCE_MANUAL = "قراءة يدوية"


def _from_qr(fields):
    """يحوّل حقول الباركود إلى حقول السجل."""
    out = {
        "seller_name": fields.get(zatca_qr.TAG_SELLER_NAME),
        "seller_vat": fields.get(zatca_qr.TAG_SELLER_VAT),
        "invoice_date": fields.get(zatca_qr.TAG_TIMESTAMP),
        "total_amount": fields.get(zatca_qr.TAG_TOTAL),
        "vat_amount": fields.get(zatca_qr.TAG_VAT),
    }
    # المبلغ قبل الضريبة = الإجمالي ناقص الضريبة
    total = validate.parse_amount(out["total_amount"])
    vat = validate.parse_amount(out["vat_amount"])
    if None not in (total, vat):
        out["net_amount"] = round(total - vat, 2)
    return {k: v for k, v in out.items() if v is not None}


def build_record(path, root, manual=None, use_ocr=True):
    """يبني سجل فاتورة واحدة."""
    path = Path(path)
    rec = {
        "file_path": str(path),
        "file_name": str(path.relative_to(root)) if root else path.name,
        "has_qr": False,
        "qr_raw": None,
        "qr_amounts": {},
        "sources": {},
    }
    for key, _, _ in FIELDS:
        rec[key] = None

    data = loader.load(path)
    if data["error"]:
        rec["status"] = MISSING
        rec["alerts"] = [data["error"]]
        rec["checks"] = {}
        rec["source"] = "—"
        return rec

    # ----- 1. الباركود (الأدق: بيانات مشفّرة مو مقروءة ضوئياً) -----
    for page in data["pages"]:
        fields, raw = zatca_qr.read(page)
        if fields:
            rec["has_qr"] = True
            rec["qr_raw"] = raw
            for key, value in _from_qr(fields).items():
                rec[key] = value
                rec["sources"][key] = SOURCE_QR
            rec["qr_amounts"] = {
                "total": fields.get(zatca_qr.TAG_TOTAL),
                "vat": fields.get(zatca_qr.TAG_VAT),
            }
            break
        if raw and not rec["qr_raw"]:
            rec["qr_raw"] = raw  # فيه باركود لكنه مو باركود زاتكا

    # ----- 2. نص PDF المضمّن (مجاني كذلك) -----
    for key, value in text_hints.extract(data["pdf_text"], rec.get("seller_vat")).items():
        if rec.get(key) is None:
            rec[key] = value
            rec["sources"][key] = SOURCE_PDF

    # ----- 3. قراءة النص من الصورة عبر محرك ويندوز -----
    # ما نشغّلها إلا إذا ظل حقل إلزامي ناقص — عشان ما نبطّئ الفواتير الكاملة
    if use_ocr and win_ocr.AVAILABLE and any(rec.get(k) in (None, "") for k in REQUIRED):
        for page in data["pages"]:
            text = win_ocr.read_text(page)
            if not text.strip():
                continue
            rec["ocr_text"] = (rec.get("ocr_text", "") + "\n" + text).strip()
            for key, value in text_hints.extract(text, rec.get("seller_vat")).items():
                if rec.get(key) in (None, ""):
                    rec[key] = value
                    rec["sources"][key] = SOURCE_OCR
            if all(rec.get(k) not in (None, "") for k in REQUIRED):
                break  # كملت البيانات — ما نحتاج بقية الصفحات

    # ----- 4. القراءة اليدوية المكمّلة -----
    # القاعدة: الباركود هو المرجع. القراءة اليدوية تعبّي الناقص فقط،
    # وإذا خالفت الباركود تنحفظ للمقارنة وتطلع تنبيه بدل ما تكتب فوقه.
    rec["printed"] = {}
    for key, value in (manual or {}).items():
        if key not in LABEL or value in (None, "", "—"):
            continue
        if rec["sources"].get(key) == SOURCE_QR:
            rec["printed"][key] = value
        else:
            rec[key] = value
            rec["sources"][key] = SOURCE_MANUAL

    rec["source"] = " + ".join(dict.fromkeys(rec["sources"].values())) or "—"
    rec["status"], rec["alerts"], rec["checks"] = validate.check(rec)

    # المبالغ تنحفظ أرقام عشان تنجمع في إكسل
    for key in ("net_amount", "vat_amount", "total_amount"):
        parsed = validate.parse_amount(rec[key])
        if parsed is not None:
            rec[key] = parsed

    # التاريخ من الباركود يجي 2026-08-12T13:45:00Z — نخليه مقروء
    rec["invoice_date"] = validate.format_date(rec["invoice_date"])

    return rec


def scan(folder, manual_file=None, on_progress=None, use_ocr=True):
    """يفحص كل الفواتير في المجلد. يرجّع قائمة السجلات."""
    folder = Path(folder)
    files = loader.find_invoices(folder)

    manual_all = {}
    if manual_file and Path(manual_file).exists():
        manual_all = json.loads(Path(manual_file).read_text(encoding="utf-8"))

    records = []
    for i, path in enumerate(files, 1):
        name = str(path.relative_to(folder))
        if on_progress:
            on_progress(i, len(files), name)
        records.append(build_record(path, folder, manual_all.get(name), use_ocr))

    validate.find_duplicates(records)
    return records


def summarize(records):
    """يرجّع عدّاد الحالات."""
    counts = {OK: 0, REVIEW: 0, MISSING: 0}
    for rec in records:
        status = rec.get("status", MISSING)
        counts[status] = counts.get(status, 0) + 1
    return counts


def write_review_template(records, path):
    """يكتب ملف الحقول الناقصة عشان تنقرأ من الصور وتنملى.

    كل فاتورة يطلع فيها بس الحقول اللي ما قدر البرنامج يطلعها لحاله،
    بالإضافة للمبالغ المطبوعة إذا فيه باركود — عشان نقارنها فيه ونكشف
    أي اختلاف بين المطبوع والمشفّر.
    """
    template = {}
    for rec in records:
        gaps = {key: "" for key in REQUIRED if rec.get(key) in (None, "")}
        if rec.get("has_qr"):
            for key in ("net_amount", "vat_amount", "total_amount"):
                gaps.setdefault(key, "")  # للمقارنة مع الباركود
        if gaps:
            template[rec["file_name"]] = gaps
    Path(path).write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(template)


def run(folder, out_dir, manual_file=None, on_progress=None):
    """التشغيل الكامل: فحص + كتابة الإكسل + ملف القراءة اليدوية."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = scan(folder, manual_file, on_progress)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    excel_path = out_dir / f"فحص_الفواتير_{stamp}.xlsx"
    excel_out.write(records, excel_path)

    (out_dir / "نتائج_الفحص.json").write_text(
        json.dumps(
            {"وقت_الفحص": datetime.now(timezone.utc).isoformat(), "الفواتير": records},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    pending = write_review_template(records, out_dir / "يحتاج_قراءة.json")

    return {
        "records": records,
        "excel": excel_path,
        "counts": summarize(records),
        "pending": pending,
    }
