# -*- coding: utf-8 -*-
"""واجهة ويب محلية لفاحص الفواتير.

تشتغل على جهازك فقط (127.0.0.1) — ما يطلع منها أي ملف للإنترنت.
"""
import shutil
import sys
import tempfile
import threading
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from invoice_checker import excel_out, loader, pipeline, validate
from invoice_checker.validate import (
    FIELDS,
    LABEL,
    MISSING,
    OK,
    OPTIONAL,
    REQUIRED,
    REVIEW,
)

BASE = Path(__file__).resolve().parent
WORKSPACE = Path(tempfile.gettempdir()) / "فاحص_الفواتير"
WORKSPACE.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 ميجابايت للدفعة الواحدة
app.config["TEMPLATES_AUTO_RELOAD"] = True  # عشان أي تعديل على الصفحة يبان بدون إعادة تشغيل

SESSIONS = {}
_lock = threading.Lock()


def _session(sid):
    with _lock:
        return SESSIONS.get(sid)


def _public(rec):
    """يحوّل السجل لصيغة مناسبة للمتصفح."""
    out = {
        "file_name": rec["file_name"],
        "status": rec["status"],
        "alerts": rec.get("alerts", []),
        "checks": rec.get("checks", {}),
        "source": rec.get("source", "—"),
        "has_qr": rec.get("has_qr", False),
        "from_qr": [k for k, v in (rec.get("sources") or {}).items() if v == pipeline.SOURCE_QR],
        "printed": rec.get("printed", {}),
    }
    for key, _, _ in FIELDS:
        out[key] = rec.get(key)
    # الحقول اللي لسه ناقصة ولازم تنقرأ من الصورة
    out["gaps"] = [k for k in REQUIRED if rec.get(k) in (None, "")]
    return out


def _payload(sess):
    records = sess["records"]
    return {
        "session": sess["id"],
        "records": [_public(r) for r in records],
        "counts": pipeline.summarize(records),
        "labels": {k: LABEL[k] for k, _, _ in FIELDS},
        "required": REQUIRED,
        "optional": OPTIONAL,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/scan")
def scan():
    """يستقبل الفواتير المرفوعة ويفحصها."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "ما وصلت أي فاتورة"}), 400

    sid = uuid.uuid4().hex
    folder = WORKSPACE / sid
    folder.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped = []
    for storage in files:
        name = Path(storage.filename or "").name
        if not name:
            continue
        if Path(name).suffix.lower() not in loader.SUPPORTED:
            skipped.append(name)
            continue
        storage.save(folder / name)
        saved += 1

    if not saved:
        shutil.rmtree(folder, ignore_errors=True)
        return jsonify({"error": "ما فيه أي ملف بصيغة مدعومة", "skipped": skipped}), 400

    records = pipeline.scan(folder)
    sess = {"id": sid, "dir": folder, "records": records, "manual": {}}
    with _lock:
        SESSIONS[sid] = sess

    data = _payload(sess)
    data["skipped"] = skipped
    return jsonify(data)


@app.post("/api/demo")
def demo():
    """يفحص الفواتير التجريبية — عشان يجرّبها المستخدم قبل فواتيره الحقيقية."""
    samples = BASE / "فواتير_تجريبية"
    files = loader.find_invoices(samples) if samples.exists() else []
    if not files:
        return jsonify({"error": "ما فيه فواتير تجريبية في المجلد"}), 404

    sid = uuid.uuid4().hex
    folder = WORKSPACE / sid
    folder.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, folder / path.name)

    records = pipeline.scan(folder)
    sess = {"id": sid, "dir": folder, "records": records, "manual": {}}
    with _lock:
        SESSIONS[sid] = sess
    return jsonify(_payload(sess))


@app.post("/api/update")
def update():
    """يحدّث فاتورة واحدة بالبيانات اللي كتبها المستخدم ويعيد فحصها."""
    body = request.get_json(silent=True) or {}
    sess = _session(body.get("session"))
    if not sess:
        return jsonify({"error": "انتهت الجلسة — أعد رفع الفواتير"}), 404

    name = body.get("file_name")
    incoming = {k: v for k, v in (body.get("fields") or {}).items() if k in LABEL}

    # ندمج مع المحفوظ سابقاً بدل ما نستبدله — والقيمة الفاضية تمسح الحقل
    stored = sess["manual"].setdefault(name, {})
    for key, value in incoming.items():
        if str(value).strip():
            stored[key] = value
        else:
            stored.pop(key, None)

    for i, rec in enumerate(sess["records"]):
        if rec["file_name"] == name:
            sess["records"][i] = pipeline.build_record(
                sess["dir"] / name, sess["dir"], stored
            )
            break
    else:
        return jsonify({"error": "الفاتورة غير موجودة"}), 404

    validate.find_duplicates(sess["records"])
    return jsonify(_payload(sess))


@app.get("/api/image")
def image():
    """يعرض صورة الفاتورة عشان المستخدم يشوفها وهو يعبّي الناقص."""
    sess = _session(request.args.get("session"))
    if not sess:
        return "الجلسة منتهية", 404
    name = Path(request.args.get("file", "")).name
    path = (sess["dir"] / name).resolve()
    if not str(path).startswith(str(sess["dir"].resolve())) or not path.exists():
        return "غير موجود", 404
    if path.suffix.lower() == ".pdf":
        return send_file(path, mimetype="application/pdf")
    return send_file(path)


@app.get("/api/excel")
def excel():
    """ينزّل ملف الإكسل."""
    sess = _session(request.args.get("session"))
    if not sess:
        return "الجلسة منتهية", 404
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = sess["dir"] / f"فحص_الفواتير_{stamp}.xlsx"
    excel_out.write(sess["records"], out)
    return send_file(out, as_attachment=True, download_name=out.name)


@app.post("/api/clear")
def clear():
    """يمسح جلسة وملفاتها المؤقتة."""
    sid = (request.get_json(silent=True) or {}).get("session")
    with _lock:
        sess = SESSIONS.pop(sid, None)
    if sess:
        shutil.rmtree(sess["dir"], ignore_errors=True)
    return jsonify({"ok": True})


def main():
    port = 5000
    url = f"http://127.0.0.1:{port}"
    print("\n" + "=" * 58)
    print("  فاحص الفواتير الضريبية — الواجهة تشتغل على جهازك")
    print("=" * 58)
    print(f"  افتح المتصفح على: {url}")
    print("  لإيقاف البرنامج: أغلق هذي النافذة أو اضغط Ctrl+C")
    print("=" * 58 + "\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
