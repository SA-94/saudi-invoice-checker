# -*- coding: utf-8 -*-
"""فاحص الفواتير الضريبية السعودية.

التشغيل:
    python فحص.py                 يفحص مجلد «الفواتير»
    python فحص.py مسار_المجلد      يفحص مجلد ثاني
"""
import sys
from pathlib import Path

# سطر أوامر ويندوز افتراضياً cp1256 وما يعرض العربي صح
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from invoice_checker import pipeline
from invoice_checker.validate import MISSING, OK, REVIEW

BASE = Path(__file__).resolve().parent
DEFAULT_IN = BASE / "الفواتير"
OUT_DIR = BASE / "نتائج"
MANUAL_FILE = OUT_DIR / "تعبئة_يدوية.json"

BADGE = {OK: "[سليمة]", REVIEW: "[مراجعة]", MISSING: "[ناقصة]"}


def _progress(i, total, name):
    print(f"  ({i}/{total}) {name}", flush=True)


def main():
    folder = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_IN

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"أنشأت مجلد الفواتير: {folder}")
        print("حط الفواتير فيه وشغّل البرنامج مرة ثانية.")
        return 0

    print(f"\nأفحص الفواتير في: {folder}\n")
    result = pipeline.run(folder, OUT_DIR, MANUAL_FILE, _progress)
    records, counts = result["records"], result["counts"]

    if not records:
        print("ما لقيت أي فاتورة في المجلد.")
        print("الصيغ المدعومة: JPG, PNG, HEIC, WEBP, TIFF, PDF")
        return 0

    print("\n" + "=" * 62)
    print(f"  النتيجة: {len(records)} فاتورة")
    print("=" * 62)
    print(f"  سليمة        : {counts[OK]}")
    print(f"  تحتاج مراجعة : {counts[REVIEW]}")
    print(f"  ناقصة        : {counts[MISSING]}")
    print("=" * 62)

    flagged = [r for r in records if r["status"] != OK]
    if flagged:
        print("\nالتنبيهات:\n")
        for rec in flagged:
            print(f"{BADGE[rec['status']]} {rec['file_name']}")
            for alert in rec["alerts"]:
                print(f"     - {alert}")
            print()

    print(f"ملف الإكسل : {result['excel']}")
    if result["pending"]:
        print(f"\nفيه {result['pending']} فاتورة ناقصة بيانات ما يغطيها الباركود.")
        print(f"الحقول الناقصة مكتوبة في: {OUT_DIR / 'يحتاج_قراءة.json'}")
        print("قل لـ Claude Code «اقرأ الناقص» وبيعبّيها لك من الصور.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
