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
        return {"answer": answer, "refs": refs}
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


# ── 정적 파일 (API 라우트보다 뒤에 마운트) ─────────────
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[seed] 서버 시작: http://0.0.0.0:{PORT} → {STATIC_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
