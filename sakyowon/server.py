#!/usr/bin/env python3
"""사교원 사이트 서버 — Flask + Supabase REST"""

import os
import time
from collections import defaultdict
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


# IP당 분당 호출 제한 (단일 프로세스 인메모리 — 이 서버 규모엔 충분)
_rate_hits = defaultdict(list)


def rate_limited(key, per_minute):
    now = time.time()
    hits = _rate_hits[key] = [t for t in _rate_hits[key] if now - t < 60]
    if len(hits) >= per_minute:
        return True
    hits.append(now)
    return False


def client_ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "?")


def claude(system, messages, max_tokens=1024):
    """Anthropic Messages API 호출 → 텍스트 반환."""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": _ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        },
        timeout=60,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


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
    # 기존 index.html은 content, LONLO는 message로 보냄 — 둘 다 수용
    content = (data.get("content") or data.get("message") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    row = {
        "name": name or None,
        "category": category or "기타",
        "content": content,
    }
    # 2026-07-22 확장 필드 (LONLO 다국어 문의) — 옵션, 없으면 저장 안 함
    for k in ("contact", "org", "source", "user_lang",
              "name_ko", "contact_ko", "message_ko"):
        v = (data.get(k) or "").strip()
        if v:
            row[k] = v
    result = sb_post("sakyowon_inquiries", row)
    return jsonify(result), 201


# ── FEEDBACK API (2026-07-22 LONLO 사이트 개선의견) ──

@app.route("/api/feedback", methods=["POST"])
def create_feedback():
    if rate_limited(f"fb:{client_ip()}", 3):
        return jsonify({"error": "too many requests"}), 429
    data = request.get_json()
    msg = (data.get("msg") or "").strip()
    if not msg:
        return jsonify({"error": "msg required"}), 400
    row = {
        "id": (data.get("id") or f"fb{int(time.time()*1000):x}")[:64],
        "msg": msg[:4000],
        "ip": client_ip(),
        "status": "미확인",
    }
    for k in ("page", "route", "url", "msg_ko", "contact", "ua", "user_lang"):
        v = (data.get(k) or "").strip()
        if v:
            row[k] = v[:1000]
    row["reply"] = bool(data.get("reply"))
    sb_post("sakyowon_feedback", row)
    return jsonify({"ok": True}), 200


# ── TRANSLATE API (2026-07-22 이용자 메시지 한국어 번역) ──

_LANG_NAMES = {"ko": "Korean", "en": "English", "fr": "French", "es": "Spanish",
               "zh-CN": "Chinese (Simplified)", "ja": "Japanese",
               "ar": "Arabic", "it": "Italian"}


@app.route("/api/translate", methods=["POST"])
def translate():
    if not _ANTHROPIC_KEY:
        return jsonify({"error": "API key not configured"}), 500
    if rate_limited(f"tr:{client_ip()}", 10):
        return jsonify({"error": "too many requests"}), 429
    data = request.get_json()
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    source = _LANG_NAMES.get(data.get("source"), data.get("source") or "auto-detect")
    target = _LANG_NAMES.get(data.get("target") or "ko", "Korean")
    translated = claude(
        "You are a translation engine. Translate the user's text from "
        f"{source} to {target}. Output ONLY the translation — no explanations, "
        "no quotes. Preserve names, emails, phone numbers and URLs as-is.",
        [{"role": "user", "content": text[:4000]}],
    ).strip()
    return jsonify({"translated": translated})


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


# ── LONLO AI CHAT (2026-07-22 신설 — sunvillage의 raw 프록시 /api/ai와 별도) ──

_LONLO_BASE = (
    "너는 LONLO(론로, '로컬리스트 & 로컬리스트') 사이트의 AI 도우미다. "
    "LONLO는 사회혁신교육원 사회적협동조합(사교원)의 새 브랜드로, "
    "사회연대경제·교육컨설팅 공익조직이다(이사장 김일영, 대전 기반, 전국 활동). "
    "차분하고 신뢰감 있는 공익조직의 톤으로, 한국어로 간결하게 답한다. "
    "모르는 것은 모른다고 말하고 지어내지 않는다."
)

_LONLO_CONTEXT_PROMPTS = {
    "admin": _LONLO_BASE + (
        " 지금은 관리자 대시보드다. 회계·세무·인사·자산·SNS·주문·문의·개선의견 "
        "업무를 돕는다. 단, 아직 조합 실제 데이터베이스에는 접근할 수 없다 — "
        "구체적 수치 질문에는 데이터 미연동 상태임을 밝히고, 일반적인 실무 "
        "방법과 절차를 안내한다."
    ),
    "shop": _LONLO_BASE + (
        " 지금은 쇼핑몰 화면이다. 상품·장바구니·주문 예약에 대해 친절한 "
        "커머스 상담 톤으로 답한다. 결제는 아직 주문 예약(연락처 접수) "
        "방식임을 안내한다."
    ),
    "contact": _LONLO_BASE + (
        " 지금은 문의 화면이다. 방문자가 문의 내용을 정리하도록 돕고, "
        "요청하면 정중한 문의 초안을 대신 작성해준다."
    ),
}


def _lonlo_system(context):
    c = (context or "").strip()
    if c.startswith("admin"):
        return _LONLO_CONTEXT_PROMPTS["admin"]
    if c in ("shop", "cart"):
        return _LONLO_CONTEXT_PROMPTS["shop"]
    if c == "contact":
        return _LONLO_CONTEXT_PROMPTS["contact"]
    return _LONLO_BASE + " 지금은 사교원/LONLO 소개 화면이다. 조직의 미션·연혁·사업을 안내한다."


@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    if not _ANTHROPIC_KEY:
        return jsonify({"error": "API key not configured"}), 500
    if rate_limited(f"ai:{client_ip()}", 10):
        return jsonify({"error": "too many requests"}), 429
    data = request.get_json()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    # Anthropic API는 user 시작 + user/assistant 교대 필수 — 어긋나면 병합
    messages = []
    for h in (data.get("history") or [])[-10:]:
        role = "assistant" if h.get("role") in ("ai", "assistant") else "user"
        text = (h.get("content") or "").strip()
        if not text:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text[:2000]
        else:
            messages.append({"role": role, "content": text[:2000]})
    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n" + prompt[:4000]
    else:
        messages.append({"role": "user", "content": prompt[:4000]})
    answer = claude(_lonlo_system(data.get("context")), messages).strip()
    return jsonify({"answer": answer})


# ── MAIN ──

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8040, debug=False)
