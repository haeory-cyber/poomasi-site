#!/usr/bin/env python3
"""DJCO Newsletter Server — Flask + Supabase REST + GWS Gmail"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

# ── ENV ──
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]  # service_role key

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

STATIC_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


# ── HELPERS ──

def sb_get(table, params=None):
    """Supabase REST SELECT."""
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params or {})
    r.raise_for_status()
    return r.json()


def sb_post(table, data):
    """Supabase REST INSERT."""
    h = {**HEADERS, "Prefer": "return=representation"}
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=data)
    r.raise_for_status()
    return r.json()


def sb_patch(table, match_params, data):
    """Supabase REST UPDATE with query params filter."""
    h = {**HEADERS, "Prefer": "return=representation"}
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params=match_params, json=data)
    r.raise_for_status()
    return r.json()


def sb_upsert(table, data, on_conflict):
    """Supabase REST UPSERT."""
    h = {
        **HEADERS,
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    params = {"on_conflict": on_conflict}
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=data, params=params)
    r.raise_for_status()
    return r.json()


# ── STATIC ROUTES ──

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


# ── SUBSCRIBERS API ──

@app.route("/api/subscribers", methods=["GET"])
def list_subscribers():
    rows = sb_get("djco_subscribers", {"order": "created_at.desc"})
    return jsonify(rows)


@app.route("/api/subscribers", methods=["POST"])
def add_subscriber():
    data = request.get_json()
    email = (data.get("email") or "").strip()
    name = (data.get("name") or "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    result = sb_upsert("djco_subscribers", {"email": email, "name": name, "active": True}, "email")
    return jsonify(result), 201


@app.route("/api/subscribers/<sub_id>", methods=["DELETE"])
def deactivate_subscriber(sub_id):
    result = sb_patch("djco_subscribers", {"id": f"eq.{sub_id}"}, {"active": False})
    return jsonify(result)


# ── NEWSLETTERS API ──

@app.route("/api/newsletters", methods=["GET"])
def list_newsletters():
    rows = sb_get("djco_newsletters", {"order": "created_at.desc"})
    return jsonify(rows)


@app.route("/api/newsletters", methods=["POST"])
def create_newsletter():
    data = request.get_json()
    title = (data.get("title") or "").strip()
    category = (data.get("category") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return jsonify({"error": "title and content required"}), 400
    result = sb_post("djco_newsletters", {
        "title": title,
        "category": category,
        "content": content,
    })
    return jsonify(result), 201


@app.route("/api/send-newsletter", methods=["POST"])
def send_newsletter():
    data = request.get_json()
    newsletter_id = data.get("newsletter_id")
    from_email = data.get("from_email", "")
    if not newsletter_id:
        return jsonify({"error": "newsletter_id required"}), 400

    # Fetch newsletter
    rows = sb_get("djco_newsletters", {"id": f"eq.{newsletter_id}"})
    if not rows:
        return jsonify({"error": "newsletter not found"}), 404
    nl = rows[0]

    # Fetch active subscribers
    subs = sb_get("djco_subscribers", {"active": "eq.true", "select": "email,name"})
    if not subs:
        return jsonify({"error": "no active subscribers"}), 400

    # Build email HTML
    email_html = build_email_html(nl["title"], nl["category"], nl["content"])

    # Send to each subscriber via gws gmail +send
    success_count = 0
    errors = []
    for sub in subs:
        try:
            send_email(sub["email"], nl["title"], email_html, from_email)
            success_count += 1
        except Exception as e:
            errors.append({"email": sub["email"], "error": str(e)})

    # Update newsletter record
    from datetime import datetime, timezone
    sb_patch("djco_newsletters", {"id": f"eq.{newsletter_id}"}, {
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "recipient_count": success_count,
    })

    return jsonify({
        "sent": success_count,
        "total": len(subs),
        "errors": errors,
    })


def build_email_html(title, category, content):
    """Build inline-CSS email HTML template."""
    category_badge = ""
    if category:
        category_badge = (
            f'<span style="display:inline-block;background:#f0ebe3;color:#7a5c3e;'
            f'padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;'
            f'margin-bottom:16px;">{category}</span><br>'
        )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f7f3ee;font-family:'Pretendard',-apple-system,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f3ee;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <!-- Header -->
        <tr><td style="background:#2c2418;padding:32px 40px;text-align:center;">
          <h1 style="margin:0;color:#f7f3ee;font-size:20px;font-weight:700;letter-spacing:-0.02em;font-family:Georgia,serif;">
            대전주민운동교육원협동조합
          </h1>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:40px;">
          {category_badge}
          <h2 style="margin:0 0 24px 0;font-size:22px;color:#2c2418;font-family:Georgia,serif;font-weight:700;">{title}</h2>
          <div style="color:#5c4f3c;font-size:15px;line-height:1.8;">
            {content}
          </div>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:#faf8f5;padding:24px 40px;border-top:1px solid rgba(90,70,40,0.1);text-align:center;">
          <p style="margin:0 0 8px 0;font-size:14px;color:#8a7d6a;font-style:italic;font-family:Georgia,serif;">
            "당신을 구할 사람은 오직 당신 뿐"
          </p>
          <p style="margin:0;font-size:12px;color:#8a7d6a;">
            대전주민운동교육원협동조합 | 대전광역시
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(to_email, subject, html_body, from_email=""):
    """Send email using gws gmail +send CLI."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_body)
        tmp_path = f.name

    try:
        cmd = [
            "gws", "gmail", "+send",
            "--to", to_email,
            "--subject", subject,
            "--body", html_body,
            "--html",
        ]
        if from_email:
            cmd.extend(["--reply-to", from_email])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gws send failed: {result.stderr}")
    finally:
        os.unlink(tmp_path)


# ── DRIVE ARCHIVE API ──

DRIVE_FOLDER_ID = "1NaRQrcKe8N200ukWJQ27OhlewRyoiBcD"
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


@app.route("/api/drive/files", methods=["GET"])
def drive_list_files():
    """List files in the DJCO Drive archive folder."""
    try:
        query = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"
        params = json.dumps({
            "q": query,
            "fields": "files(id,name,mimeType,size,createdTime,modifiedTime)",
            "orderBy": "modifiedTime desc",
        })
        result = subprocess.run(
            ["gws", "drive", "files", "list", "--params", params],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip()}), 500
        data = json.loads(result.stdout)
        return jsonify(data.get("files", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/drive/upload", methods=["POST"])
def drive_upload_file():
    """Upload a file to the DJCO Drive archive folder."""
    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "empty filename"}), 400

    # Check size via content-length header
    content_length = request.content_length or 0
    if content_length > MAX_UPLOAD_SIZE:
        return jsonify({"error": f"file too large (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)"}), 413

    # Save to temp file
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, uploaded.filename)
    try:
        uploaded.save(tmp_path)

        # Check actual file size
        if os.path.getsize(tmp_path) > MAX_UPLOAD_SIZE:
            return jsonify({"error": f"file too large (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)"}), 413

        # Upload to Drive via gws CLI
        metadata = json.dumps({"name": uploaded.filename, "parents": [DRIVE_FOLDER_ID]})
        result = subprocess.run(
            [
                "gws", "drive", "files", "create",
                "--json", metadata,
                "--upload", tmp_path,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip()}), 500

        data = json.loads(result.stdout)
        return jsonify({"id": data.get("id"), "name": data.get("name")}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        os.rmdir(tmp_dir)


@app.route("/api/drive/download/<file_id>", methods=["GET"])
def drive_download_file(file_id):
    """Download a file from Drive by file ID."""
    try:
        # First get file metadata for the filename
        meta_result = subprocess.run(
            ["gws", "drive", "files", "get", "--params", json.dumps({"fileId": file_id, "fields": "name,mimeType"})],
            capture_output=True, text=True, timeout=30,
        )
        if meta_result.returncode != 0:
            return jsonify({"error": meta_result.stderr.strip()}), 500

        meta = json.loads(meta_result.stdout)
        filename = meta.get("name", "download")
        mime_type = meta.get("mimeType", "application/octet-stream")

        # Download file content
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, filename)

        dl_result = subprocess.run(
            [
                "gws", "drive", "files", "get",
                "--params", json.dumps({"fileId": file_id, "alt": "media"}),
                "-o", tmp_path,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if dl_result.returncode != 0:
            return jsonify({"error": dl_result.stderr.strip()}), 500

        from flask import send_file
        return send_file(
            tmp_path,
            mimetype=mime_type,
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── MAIN ──

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8020, debug=False)
