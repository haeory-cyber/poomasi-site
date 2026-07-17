#!/usr/bin/env python3
"""사교원 사이트 서버 — Flask + Supabase REST"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, request, send_from_directory

# ── ENV ──
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path, override=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]  # service_role key

# Anthropic API key (for AI proxy)
_ANTHROPIC_KEY = None
with open(_env_path) as _f:
    for _line in _f:
        if _line.startswith("ANTHROPIC_API_KEY="):
            _ANTHROPIC_KEY = _line.strip().split("=", 1)[1].strip().strip('"').strip("'")
            break

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# 2026-07-17: 화면(HTML)은 데카가 push하는 sakyowon-site 레포 체크아웃에서 서빙 (sakyowon-sync.timer가 1분 주기 git pull)
STATIC_DIR = Path("/home/haeory/poomasi/sakyowon-site")

# static_folder=None 필수 — Flask 내장 정적 라우트가 생기면 아래 차단 라우트를 가로채
# PRIVATE 레포 문서(우편함 md 등)가 그대로 노출된다 (2026-07-17 배달 검증에서 발견)
app = Flask(__name__, static_folder=None)


# ── HELPERS ──

def sb_post(table, data):
    """Supabase REST INSERT."""
    h = {**HEADERS, "Prefer": "return=representation"}
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=data)
    r.raise_for_status()
    return r.json()


# ── STATIC ROUTES ──

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    # PRIVATE 레포 내부 문서(우편함·기획 md·닷파일·스크립트) 웹 노출 차단
    if path.endswith((".md", ".py", ".bak")) or path.startswith((".", "자동화기획/")) or "/." in path:
        abort(404)
    return send_from_directory(STATIC_DIR, path)


# ── INQUIRIES API ──

@app.route("/api/inquiries", methods=["POST"])
def create_inquiry():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    result = sb_post("sakyowon_inquiries", {
        "name": name or None,
        "category": category or "기타",
        "content": content,
    })
    return jsonify(result), 201


# ── AI PROXY ──

@app.route("/api/ai", methods=["POST"])
def ai_proxy():
    """Proxy to Anthropic Messages API (streaming supported)."""
    if not _ANTHROPIC_KEY:
        return jsonify({"error": "API key not configured"}), 500

    payload = request.get_json()
    is_stream = payload.get("stream", False)

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": _ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=payload,
        stream=is_stream,
        timeout=120,
    )

    if not is_stream:
        return Response(resp.content, status=resp.status_code,
                        content_type=resp.headers.get("Content-Type", "application/json"))

    def generate():
        for chunk in resp.iter_content(chunk_size=None):
            if chunk:
                yield chunk

    return Response(generate(), status=resp.status_code,
                    content_type=resp.headers.get("Content-Type", "text/event-stream"))


# ── MAIN ──

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8040, debug=False)
