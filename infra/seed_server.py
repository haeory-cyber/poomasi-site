"""seed.poomasi.org — FastAPI 서버 (정적 파일 + 품아이 API)"""
import os
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
import jwt
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── 설정 ──────────────────────────────────────────────
PORT = 8030
# Phase 2: live serving dir is a symlink (seed-live → seed-releases/v_*),
# 작업 트리(poomasi-site-git/seed)와 분리. 배포는 infra/deploy-seed.sh.
STATIC_DIR = "/home/haeory/poomasi/seed-live"
RAG_DIR = "/home/haeory/poomasi/rag"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # anon key
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

# ── Rate Limiting (in-memory) ─────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_WINDOW = 60  # seconds
RATE_ANON = 30
RATE_AUTH = 60


def _check_rate(ip: str, authenticated: bool) -> bool:
    """True면 허용, False면 초과."""
    now = time.time()
    cutoff = now - RATE_WINDOW
    # 오래된 항목 정리
    _rate_store[ip] = [t for t in _rate_store[ip] if t > cutoff]
    limit = RATE_AUTH if authenticated else RATE_ANON
    if len(_rate_store[ip]) >= limit:
        return False
    _rate_store[ip].append(now)
    return True


# ── JWT 검증 ──────────────────────────────────────────
def verify_token(token: str) -> str:
    """JWT에서 email 추출. 실패 시 빈 문자열."""
    if not token or not SUPABASE_JWT_SECRET:
        return ""
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload.get("email", "")
    except Exception:
        return ""


def _extract_email(request: Request) -> str:
    """Authorization 헤더에서 Bearer 토큰 추출 후 email 반환."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return verify_token(auth[7:])
    return ""


# ── Engine 초기화 ─────────────────────────────────────
engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    try:
        # rag 패키지 절대 임포트 (from rag.fuzzy_utils import ...) 지원을 위해 부모 dir도 추가
        sys.path.insert(0, os.path.dirname(RAG_DIR))
        sys.path.insert(0, RAG_DIR)
        from engine import RAGEngine
        engine = RAGEngine()
        print(f"[seed] RAGEngine 초기화 완료")
    except Exception as e:
        print(f"[seed] RAGEngine 초기화 실패: {e}")
        engine = None
    yield
    print("[seed] 서버 종료")


# ── FastAPI 앱 ────────────────────────────────────────
app = FastAPI(title="seed.poomasi.org", lifespan=lifespan)

# ── CORS (모든 *.poomasi.org 서브도메인 허용) ─────────
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?poomasi\.org",
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── API 엔드포인트 ────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "engine": engine is not None,
        "timestamp": time.time(),
    }


@app.post("/api/chat")
async def chat(request: Request):
    # Rate limit 체크
    ip = request.client.host if request.client else "unknown"
    email = _extract_email(request)
    authenticated = bool(email)

    if not _check_rate(ip, authenticated):
        return JSONResponse(
            status_code=429,
            content={"error": "요청 한도 초과. 잠시 후 다시 시도해주세요."},
        )

    # Engine 상태 확인
    if engine is None:
        return JSONResponse(
            status_code=503,
            content={"error": "AI 엔진이 준비되지 않았습니다."},
        )

    # 요청 파싱
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "잘못된 요청 형식입니다."},
        )

    query = body.get("query", "").strip()
    if not query:
        return JSONResponse(
            status_code=400,
            content={"error": "질문을 입력해주세요."},
        )

    history = body.get("history", [])
    page_context = body.get("page_context", "")
    top_k = body.get("top_k", 5)

    # 페이지 맥락을 query에 힌트로 추가
    if page_context:
        page_hints = {
            "/store.html": "매장운영(발주/가격태그/SMS/이벤트/출퇴근/공동구매) 페이지",
            "/work.html": "사무국(경영현황/할일/경영관리/소통/자료실) 페이지",
            "/market.html": "직매장 안내(지족점/관저점) 페이지",
            "/join.html": "조합원 가입 페이지",
            "/feedback.html": "조합원말씀(피드백) 페이지",
            "/delivery.html": "배달 주문 페이지",
            "/babsang.html": "모두의밥상 페이지",
            "/zerowaste.html": "제로웨이스트존(푸미) 페이지",
            "/ai-tools.html": "AI경영지원실 페이지",
            "/annual_report.html": "경영 연차 보고서 페이지",
            "/display.html": "일일 판매 현황 디스플레이",
        }
        hint = page_hints.get(page_context, "")
        if hint:
            query = f"[현재 페이지: {hint}] {query}"

    # Engine 호출
    try:
        answer, refs = engine.generate(
            query, top_k=top_k, history=history, user_email=email
        )
        # 위젯 액션 객체 (engine이 self._last_action에 담아주면 응답에 통과)
        action = getattr(engine, '_last_action', None)
        if action is not None:
            try:
                engine._last_action = None  # 1회용
            except Exception:
                pass
        resp = {"answer": answer, "refs": refs}
        if action:
            resp["action"] = action
        return resp
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"처리 중 오류가 발생했습니다: {str(e)}"},
        )


@app.post("/api/auth/login")
async def auth_login(request: Request):
    # Rate limit 체크
    ip = request.client.host if request.client else "unknown"
    if not _check_rate(ip, False):
        return JSONResponse(
            status_code=429,
            content={"error": "요청 한도 초과. 잠시 후 다시 시도해주세요."},
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        return JSONResponse(
            status_code=503,
            content={"error": "인증 서비스가 설정되지 않았습니다."},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "잘못된 요청 형식입니다."},
        )

    email = body.get("email", "")
    password = body.get("password", "")
    if not email or not password:
        return JSONResponse(
            status_code=400,
            content={"error": "이메일과 비밀번호를 입력해주세요."},
        )

    # Supabase Auth 프록시
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Content-Type": "application/json",
                },
                json={"email": email, "password": password},
                timeout=10,
            )

        if resp.status_code == 200:
            data = resp.json()
            return {
                "access_token": data.get("access_token", ""),
                "user_email": data.get("user", {}).get("email", email),
            }
        else:
            return JSONResponse(
                status_code=401,
                content={"error": "인증 실패"},
            )
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"error": "인증 서버 연결 실패"},
        )


# ── 개인화 SMS ───────────────────────────────────────
@app.post("/api/personalize-sms")
async def personalize_sms(request: Request):
    """조합원별 구매이력 기반 개인화 문자 메시지 생성."""
    ip = request.client.host if request.client else "unknown"
    email = _extract_email(request)
    if not email:
        return JSONResponse(status_code=401, content={"error": "인증이 필요합니다."})

    if not _check_rate(ip, True):
        return JSONResponse(status_code=429, content={"error": "요청 한도 초과. 잠시 후 다시 시도해주세요."})

    if not SUPABASE_URL or not SUPABASE_KEY:
        return JSONResponse(status_code=503, content={"error": "데이터베이스 설정이 없습니다."})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "잘못된 요청 형식입니다."})

    members = body.get("members", [])
    broadcast = body.get("broadcast", "").strip()

    if not members:
        return JSONResponse(status_code=400, content={"error": "members가 비어 있습니다."})
    if not broadcast:
        return JSONResponse(status_code=400, content={"error": "broadcast 텍스트가 없습니다."})

    # 최대 100명 제한
    members = members[:100]

    # broadcast에서 품목 추출: "- 품목명(가격)" 패턴 파싱
    import re
    broadcast_lines = broadcast.splitlines()
    broadcast_items = []  # [(item_name, original_line), ...]
    for line in broadcast_lines:
        m = re.match(r'\s*[-•]\s*(.+)', line)
        if m:
            item_text = m.group(1).strip()
            # 괄호 앞 품목명 추출
            item_name = re.split(r'[\(（]', item_text)[0].strip()
            if item_name:
                broadcast_items.append((item_name, line.strip()))

    broadcast_item_names = [name for name, _ in broadcast_items]

    cutoff_date = (
        __import__('datetime').datetime.utcnow()
        - __import__('datetime').timedelta(days=90)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    results = []

    async with httpx.AsyncClient() as client:
        for member in members:
            mid  = member.get("member_id", "")
            name = member.get("member_name", mid)
            phone_raw = member.get("phone", "")
            phone = phone_raw.replace("-", "")

            if not phone:
                continue

            # 최근 90일 구매 품목 조회 (최대 500건)
            top_items = []
            try:
                url = (
                    f"{SUPABASE_URL}/rest/v1/pos_transactions"
                    f"?select=item_name"
                    f"&member_id=eq.{mid}"
                    f"&sold_at=gte.{cutoff_date}"
                    f"&order=sold_at.desc"
                    f"&limit=500"
                )
                resp = await client.get(
                    url,
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                    },
                    timeout=8,
                )
                if resp.status_code == 200:
                    rows = resp.json()
                    # 품목별 빈도 집계
                    freq: dict[str, int] = {}
                    for row in rows:
                        iname = (row.get("item_name") or "").strip()
                        if iname:
                            freq[iname] = freq.get(iname, 0) + 1
                    top_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
                    top_items = [name_f for name_f, _ in top_items]
            except Exception:
                pass  # 조회 실패해도 나머지 처리 계속

            # broadcast 품목과 교집합
            intersection = []
            for b_name, b_line in broadcast_items:
                for t_item in top_items:
                    # 부분 일치 (broadcast 품목명이 구매이력 품목에 포함되거나 반대)
                    if b_name in t_item or t_item in b_name:
                        intersection.append((b_name, b_line))
                        break

            if intersection:
                first_name, first_line = intersection[0]
                intersect_lines = "\n".join(line for _, line in intersection)
                text = (
                    f"{name}님, 자주 찾으시는 {first_name} 오늘도 들어왔어요!\n\n"
                    f"{intersect_lines}\n\n"
                    f"품앗이마을 지족점"
                )
            else:
                summary_lines = [l for l in broadcast_lines if l.strip()][:3]
                summary = "\n".join(summary_lines)
                text = (
                    f"{name}님, 이번 주 품앗이마을 소식이에요!\n\n"
                    f"{summary}\n\n"
                    f"품앗이마을 지족점"
                )

            results.append({"member_id": mid, "phone": phone, "text": text})

    return results


# ── SMS 발송 (Solapi 프록시) ──────────────────────────
# localStorage 의존 제거. 위젯·store.html 모두 이 엔드포인트로 호출.
SOLAPI_API_KEY    = os.environ.get("SOLAPI_API_KEY", "")
SOLAPI_API_SECRET = os.environ.get("SOLAPI_API_SECRET", "")
SOLAPI_FROM       = os.environ.get("SOLAPI_FROM", "")
STORE_NAME        = os.environ.get("STORE_NAME", "품앗이마을 지족점")  # 발신 매장명


def _format_sms_text(text: str, recipient_name: str | None, store_branch: str | None = None) -> str:
    """SMS 본문에 매장명 + 조합원 호명 prefix 자동 추가.

    포맷: "[{지족점}] 품앗이마을입니다.\n{이름} 조합원님, {본문}"
    store_branch 입력은 "품앗이마을 지족점" 또는 "지족점" 둘 다 허용.
    매장 단축명("지족점")만 대괄호로 추출. 매장 미식별 시 그냥 "품앗이마을입니다".
    """
    text = (text or "").strip()
    if not text:
        return text
    branch_input = (store_branch or "").strip() or STORE_NAME
    branch_short = branch_input.replace("품앗이마을", "").strip()
    prefix = f"[{branch_short}] 품앗이마을입니다." if branch_short else "품앗이마을입니다."
    if recipient_name:
        return f"{prefix}\n{recipient_name} 조합원님, {text}"
    return f"{prefix}\n{text}"


@app.post("/api/sms-send")
async def sms_send(request: Request):
    """Solapi SMS 발송 프록시.

    POST body 형태:
      { "messages": [{ "to": "01012345678", "text": "...", "recipient_name": "김성훈" }, ...] }
      또는 단일: { "to": "01012345678", "text": "...", "recipient_name": "김성훈" }

    recipient_name이 있으면 본문에 매장명+조합원님 호명 자동 prefix.

    응답: { "ok": true, "count": N, "fail": M, "group_id": "..." }
       또는 { "ok": false, "error": "..." }
    """
    ip = request.client.host if request.client else "unknown"

    # rate limit (익명 호출 30/분/IP)
    if not _check_rate(ip, False):
        return JSONResponse(status_code=429, content={"ok": False, "error": "요청 한도 초과. 잠시 후 다시 시도해주세요."})

    if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Solapi 환경변수 미설정 (.env)"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})

    raw_messages = body.get("messages")
    if not raw_messages:
        to = body.get("to") or ""
        text = body.get("text") or ""
        if not to or not text:
            return JSONResponse(status_code=400, content={"ok": False, "error": "to, text 필수"})
        raw_messages = [{
            "to": to,
            "text": text,
            "recipient_name": body.get("recipient_name"),
            "store_branch": body.get("store_branch"),
        }]

    from_clean = SOLAPI_FROM.replace("-", "")
    messages_norm = []
    for m in raw_messages[:50]:  # 최대 50건/요청
        to_clean = (m.get("to") or "").replace("-", "")
        text_raw = (m.get("text") or "").strip()
        recipient = (m.get("recipient_name") or "").strip() or None
        store_branch = (m.get("store_branch") or "").strip() or None
        if not to_clean or not text_raw:
            continue
        text_formatted = _format_sms_text(text_raw, recipient, store_branch)
        messages_norm.append({"to": to_clean, "from": from_clean, "text": text_formatted})

    if not messages_norm:
        return JSONResponse(status_code=400, content={"ok": False, "error": "유효한 메시지 없음"})

    # Solapi HMAC-SHA256 인증
    import hmac as _hmac
    import hashlib as _hashlib
    import datetime as _dt
    import secrets as _secrets

    date = _dt.datetime.utcnow().isoformat() + "Z"
    salt = _secrets.token_hex(16)
    sig = _hmac.new(
        SOLAPI_API_SECRET.encode(),
        (date + salt).encode(),
        _hashlib.sha256,
    ).hexdigest()
    auth_header = f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={date}, salt={salt}, signature={sig}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.solapi.com/messages/v4/send-many",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": auth_header,
                },
                json={"messages": messages_norm},
            )
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"Solapi 호출 실패: {e}"})

    if resp.status_code != 200:
        try:
            err = resp.json()
            err_msg = err.get("message") or err.get("errorMessage") or str(err)[:200]
        except Exception:
            err_msg = resp.text[:200]
        return JSONResponse(status_code=502, content={"ok": False, "error": f"Solapi 응답 {resp.status_code}: {err_msg}"})

    try:
        result = resp.json()
    except Exception:
        return JSONResponse(status_code=502, content={"ok": False, "error": "Solapi 응답 파싱 실패"})

    # Solapi send-many 응답: count/groupId/status가 최상위 키
    # count = { total, sentTotal, sentSuccess, sentFailed, sentPending,
    #           registeredSuccess, registeredFailed, ... }
    # status: "SENDING" | "COMPLETE" | "PENDING" | ...
    count_obj = result.get("count") or {}
    total            = count_obj.get("total")             or 0
    sent_success     = count_obj.get("sentSuccess")       or 0
    sent_failed      = count_obj.get("sentFailed")        or 0
    registered_ok    = count_obj.get("registeredSuccess") or 0
    registered_fail  = count_obj.get("registeredFailed")  or 0

    group_id = result.get("groupId") or result.get("_id") or ""
    status_str = result.get("status", "")

    # 등록 자체 실패 (잘못된 번호 형식 등 사전 검증 실패)
    if registered_fail > 0 and registered_ok == 0:
        return JSONResponse(status_code=502, content={
            "ok": False,
            "error": f"메시지 등록 실패 ({registered_fail}건). group: {group_id}",
        })

    # 등록 성공 + status가 발송 흐름이면 ok (실제 도착은 비동기)
    if registered_ok > 0 or sent_success > 0 or status_str in ("SENDING", "COMPLETE", "PENDING"):
        return {
            "ok": True,
            "count": sent_success or registered_ok or total,
            "fail": sent_failed + registered_fail,
            "group_id": group_id,
            "status": status_str,
        }

    # 알 수 없는 상태
    return JSONResponse(status_code=502, content={
        "ok": False,
        "error": f"Solapi 응답 분석 불가 — total:{total}, status:{status_str}, group:{group_id}",
    })


# ── 정적 파일 (API 라우트보다 뒤에 마운트) ─────────────
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[seed] 서버 시작: http://0.0.0.0:{PORT} → {STATIC_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
