"""seed.poomasi.org — FastAPI 서버 (정적 파일 + 품아이 API)"""
import os
import sys
import threading
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

# ── CLI 브릿지 (v2.1 — 로그인 유저 전용) ─────────────
# POOMAI_CLI_BRIDGE=off 이면 모든 경로 Gemini 폴백
_cli_bridge = None
_cli_bridge_load_error = None
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "poomai"))
    from cli_bridge import (
        send_message as _cli_send,
        get_user_slug as _get_user_slug,
        is_cli_bridge_enabled as _cli_enabled,
        get_or_restore_session as _get_session,
        cleanup_on_shutdown as _cli_cleanup,
        check_quota_alert as _check_quota,
        get_today_message_count as _today_count,
        _ALLOWED_EMAIL,
    )
    _cli_bridge = True
except Exception as _e:
    _cli_bridge_load_error = str(_e)
    _cli_bridge = False

# ── 설정 ──────────────────────────────────────────────
PORT = 8030
# Phase 2: live serving dir is a symlink (seed-live → seed-releases/v_*),
# 작업 트리(poomasi-site-git/seed)와 분리. 배포는 infra/deploy-seed.sh.
STATIC_DIR = "/home/haeory/poomasi/seed-live"
RAG_DIR = "/home/haeory/poomasi/rag"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # anon key
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "")  # 코아이 환류 테이블 직접 접근(psycopg2)
COAI_FEEDBACK_JSONL = "/home/haeory/poomasi/finetune/coai_feedback_candidates.jsonl"

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


# ── 코아이 트레이너 환류 ───────────────────────────────
# JWT_SECRET이 없어 verify_token이 무력하므로, access_token을
# Supabase /auth/v1/user 로 직접 검증해 email을 얻는다.
async def _coai_email_from_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not SUPABASE_URL or not SUPABASE_KEY:
        return ""
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return (r.json() or {}).get("email", "") or ""
    except httpx.HTTPError:
        pass
    return ""


# ── 로이(Roy) 멀티테넌트 스코프 ───────────────────────
# app_metadata.roy 클레임을 실은 계정만 자기 org/store 스코프로 조회.
# JWT_SECRET이 비어 verify_token이 무력한 배포이므로 /auth/v1/user 로 직접 검증
# (코아이 경로와 동일 패턴). 클레임 없는 사용자는 None → 기존 동작 유지(회귀 0).
async def _roy_context(request: Request):
    """반환:
      None                            → 로이 계정 아님(통과, 회귀 0)
      {"error": ...}                  → 로이 계정이나 org 스코프 없음(fail-closed 차단)
      {"email","org_id","store_id"}   → 유효 스코프
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not SUPABASE_URL or not SUPABASE_KEY:
        return None
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                return None
            u = r.json() or {}
    except httpx.HTTPError:
        return None
    am = u.get("app_metadata") or {}
    if not am.get("roy"):
        return None
    org_id = am.get("org_id")
    if not org_id:
        # 로이 클레임인데 스코프가 없다 → 전역 유출 방지(fail-closed)
        return {"error": "로이 계정에 조합(org) 스코프가 없습니다. 관리자에게 문의하세요."}
    return {"email": u.get("email", ""), "org_id": org_id, "store_id": am.get("store_id")}


def _coai_db():
    import psycopg2
    return psycopg2.connect(SUPABASE_DB_URL)


def coai_is_trainer(email: str):
    """(is_trainer, name). 화이트리스트 active 행이 있으면 트레이너."""
    if not email or not SUPABASE_DB_URL:
        return (False, None)
    conn = _coai_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "select name from coai_trainers where email=%s and active=true", (email,)
        )
        row = cur.fetchone()
        cur.close()
        return (True, row[0]) if row else (False, None)
    finally:
        conn.close()


def coai_insert_feedback(row: dict) -> int:
    import json as _json
    conn = _coai_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "insert into coai_feedback "
            "(question, ai_answer, refs, tags, ideal_answer, trainer_email, trainer_name) "
            "values (%s,%s,%s,%s,%s,%s,%s) returning id",
            (
                row.get("question", ""),
                row.get("ai_answer"),
                _json.dumps(row.get("refs", []), ensure_ascii=False),
                row.get("tags", []),
                row.get("ideal_answer"),
                row.get("trainer_email", ""),
                row.get("trainer_name"),
            ),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return new_id
    finally:
        conn.close()


def coai_upsert_override(feedback_id, question, ideal_answer, meta):
    """승인된 모범답안을 coai_overrides 컬렉션에 즉시 반영(임베더 보유 프로세스에서만)."""
    if coai_engine is None:
        raise RuntimeError("coai_engine 미초기화")
    col = coai_engine._overrides_collection()
    emb = coai_engine._embed(question)
    md = {"ideal_answer": ideal_answer}
    md.update({k: v for k, v in (meta or {}).items() if v is not None})
    col.upsert(
        ids=[f"fb_{feedback_id}"],
        embeddings=[emb],
        documents=[question],
        metadatas=[md],
    )


# ── Engine 초기화 ─────────────────────────────────────
engine = None
coai_engine = None  # 코아이(주민운동 RAG + EXAONE), persona=coai 전용


def _init_engines():
    """RAG/코아이 엔진 초기화. 임베딩 모델 로딩이 수분 걸려 백그라운드로 돈다.

    준비되기 전 요청은 기존 `engine is None` 경로가 503("AI 엔진이 준비되지 않았습니다")로
    받아내고, /api/health 는 engine:false 로 보고한다.
    """
    global engine, coai_engine
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
    # 코아이 엔진 — engine의 임베더 재사용. 실패해도 품아이 경로 무영향.
    if engine is not None:
        try:
            from coai_engine import CoaiEngine
            coai_engine = CoaiEngine(engine.embed_model)
            print(f"[seed] CoaiEngine 초기화 완료")
        except Exception as e:
            print(f"[seed] CoaiEngine 초기화 실패 (코아이만 비활성): {e}")
            coai_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 🔴 엔진 초기화를 여기서 기다리면 uvicorn 이 포트를 안 연다.
    # 2026-08-03 실측: 재부팅 후 정적 페이지까지 3분 54초 동안 502 였다.
    threading.Thread(target=_init_engines, name="seed-engine-init", daemon=True).start()
    print("[seed] 엔진 초기화 백그라운드 시작 (정적 서빙은 즉시 가능)")
    if _cli_bridge_load_error:
        print(f"[seed] CLI 브릿지 로드 실패 (Gemini 폴백): {_cli_bridge_load_error}")
    elif _cli_bridge:
        print("[seed] CLI 브릿지 로드 완료")
    yield
    # CLI 브릿지 세션 정리
    if _cli_bridge:
        try:
            _cli_cleanup()
        except Exception:
            pass
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


# ── 코아이 트레이너 환류 API ───────────────────────────
@app.get("/api/coai/me")
async def coai_me(request: Request):
    email = await _coai_email_from_token(request)
    ok, name = coai_is_trainer(email)
    return {"is_trainer": ok, "name": name}


@app.post("/api/coai/feedback")
async def coai_feedback(request: Request):
    email = await _coai_email_from_token(request)
    ok, name = coai_is_trainer(email)
    if not ok:
        return JSONResponse(status_code=403, content={"error": "트레이너만 코멘트할 수 있어요."})
    try:
        b = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "잘못된 요청 형식입니다."})
    question = (b.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": "질문이 비어 있습니다."})
    try:
        new_id = coai_insert_feedback({
            "question": question,
            "ai_answer": b.get("ai_answer"),
            "refs": b.get("refs", []),
            "tags": b.get("tags", []),
            "ideal_answer": (b.get("ideal_answer") or None),
            "trainer_email": email,
            "trainer_name": name,
        })
    except Exception as e:
        print(f"[seed] coai feedback insert 오류: {e}")
        return JSONResponse(status_code=500, content={"error": "코멘트 저장에 실패했습니다."})
    return {"ok": True, "id": new_id}


@app.post("/internal/coai/override")
async def coai_override(request: Request):
    # admin_server(localhost)만 호출. 외부 차단.
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse(status_code=403, content={"error": "localhost only"})
    try:
        b = await request.json()
        coai_upsert_override(
            b["feedback_id"], b["question"], b["ideal_answer"],
            {"trainer": b.get("trainer"), "approved_at": b.get("approved_at")},
        )
    except Exception as e:
        print(f"[seed] coai override 오류: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"ok": True}


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

    # ── 코아이 분기 (persona=coai) ─ 주민운동 RAG + EXAONE 전용 경로 ──
    # 품아이(persona 미지정)는 이 블록을 건너뛰어 기존 동작 100% 유지(회귀 0).
    if body.get("persona") == "coai":
        if coai_engine is None:
            return JSONResponse(
                status_code=503,
                content={"error": "코아이가 준비되지 않았습니다."},
            )
        try:
            answer, refs = await coai_engine.generate(
                query, top_k=body.get("top_k", 5), history=body.get("history", [])
            )
            return {"answer": answer, "refs": refs, "via": "coai"}
        except Exception as e:
            print(f"[seed] 코아이 오류: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "코아이 응답 생성 중 오류가 발생했습니다."},
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
            "/poomasi_philosophy.html": "품앗이생협 철학 페이지",
            "/privacy.html": "개인정보처리방침 페이지",
            "/sitemap.html": "전체 사이트맵 페이지",
            "/delivery_app.html": "배달 관리(관리자) 페이지",
            "/workshop.html": "데이터 파이프라인 작업실 페이지",
            "/tags.html": "QR 가격태그 인쇄 페이지",
            "/print_tags_6m.html": "비농산물 가격태그 일괄인쇄 페이지",
            "/print_qr_notice.html": "조합원말씀 QR 안내물 인쇄 페이지",
            "/print_paper_form.html": "조합원말씀 수기 양식 인쇄 페이지",
            "/location.html": "매장 위치 인증 페이지",
            "/carbon/index.html": "탄소중립 실천 포인트 페이지",
            "/carbon/scan.html": "탄소중립 QR 스캔 페이지",
            "/ai-dashboard.html": "AI 비용/에이전트 대시보드 페이지",
        }
        hint = page_hints.get(page_context, "")
        if hint:
            query = f"[현재 페이지: {hint}] {query}"

    # ── 로이 분기 (멀티테넌트 스코프) — app_metadata.roy 클레임 보유 계정 ──
    # 클레임이 있으면 반드시 자기 org/store 스코프로만 조회(CLI 브릿지·전역 우회 없이).
    # 클레임 없는 일반 사용자는 roy_ctx=None → 아래로 통과, 기존 동작 100% 유지(회귀 0).
    roy_ctx = await _roy_context(request)
    if roy_ctx is not None:
        if roy_ctx.get("error"):
            return JSONResponse(status_code=403, content={"error": roy_ctx["error"]})
        scope = {"org_id": roy_ctx["org_id"], "store_id": roy_ctx["store_id"]}
        try:
            answer, refs = engine.generate(
                query, top_k=top_k, history=history,
                user_email=roy_ctx["email"], scope=scope,
            )
            action = getattr(engine, "_last_action", None)
            if action is not None:
                try:
                    engine._last_action = None
                except Exception:
                    pass
            resp = {"answer": answer, "refs": refs, "via": "roy", "scope": scope}
            if action:
                resp["action"] = action
            return resp
        except Exception as e:
            print(f"[seed] 로이 오류: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "로이 응답 생성 중 오류가 발생했습니다."},
            )

    # ── CLI 브릿지 분기 (로그인 + 화이트리스트 유저) ──────
    # POOMAI_CLI_BRIDGE=off 이면 이 블록 전체 스킵 → Gemini 폴백
    if (
        _cli_bridge
        and email
        and _cli_enabled()
        and _get_user_slug(email) is not None
    ):
        # 쿼터 체크 (95% 도달 시 신규 세션 거절)
        today_count = _today_count()
        quota_level = _check_quota(today_count)

        if quota_level == "deny_95":
            # 기존 세션 유지, 신규만 거절
            existing_session = _get_session(email)
            if not existing_session:
                return JSONResponse(
                    status_code=503,
                    content={"error": "오늘 AI 사용 한도가 거의 소진되었습니다. 잠시 후 다시 시도해주세요."},
                )

        # CLI 호출
        try:
            session_id = body.get("session_id") or _get_session(email)
            result = await _cli_send(email, query, session_id=session_id)

            if result.get("via") == "cli":
                answer = result.get("answer", "")
                tool_summaries = result.get("tool_summaries", [])
                resp: dict = {
                    "answer": answer,
                    "refs": [],
                    "via": "cli",
                    "session_id": result.get("session_id"),
                }
                if tool_summaries:
                    resp["tool_summaries"] = tool_summaries
                # 쿼터 경고 80% 알림 (비동기 MCP 알림은 pending_alerts.jsonl 경유)
                if quota_level == "warn_80":
                    import asyncio as _asyncio
                    _asyncio.create_task(_send_quota_alert(today_count))
                return resp
            # via == "gemini_fallback" → 아래 Gemini 경로로 계속
        except Exception as e:
            # CLI 오류 시 Gemini 폴백 (사용자에게 투명하게)
            print(f"[seed] CLI 브릿지 오류 — Gemini 폴백: {e}")

    # ── Gemini 경로 (비로그인 또는 CLI 브릿지 off/fallback) ──
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


async def _send_quota_alert(today_count: int):
    """80% 쿼터 도달 시 pending_alerts.jsonl에 기록 (텔레그램 알림용)"""
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt, timezone as _tz
    alert_file = _Path(__file__).parent / "logs" / "pending_alerts.jsonl"
    alert_file.parent.mkdir(exist_ok=True)
    entry = {
        "ts": _dt.now(_tz.utc).astimezone().isoformat(),
        "type": "quota_warn_80",
        "message": f"[품아이 쿼터 경고] 오늘 메시지 수: {today_count}건 — 한도 80% 도달",
    }
    try:
        with alert_file.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


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


async def _solapi_send_many(messages_norm: list) -> tuple:
    """Solapi send-many 호출. 반환 (ok, payload, http_code).

    ok=True  → payload = {count, fail, group_id, status}
    ok=False → payload = {"error": "..."} , http_code = 502
    /api/sms-send 와 /api/order/send 가 공유한다(2026-09-04 추출, 동작 불변).
    """
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
        return (False, {"error": f"Solapi 호출 실패: {e}"}, 502)

    if resp.status_code != 200:
        try:
            err = resp.json()
            err_msg = err.get("message") or err.get("errorMessage") or str(err)[:200]
        except Exception:
            err_msg = resp.text[:200]
        return (False, {"error": f"Solapi 응답 {resp.status_code}: {err_msg}"}, 502)

    try:
        result = resp.json()
    except Exception:
        return (False, {"error": "Solapi 응답 파싱 실패"}, 502)

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
        return (False, {"error": f"메시지 등록 실패 ({registered_fail}건). group: {group_id}"}, 502)

    # 등록 성공 + status가 발송 흐름이면 ok (실제 도착은 비동기)
    if registered_ok > 0 or sent_success > 0 or status_str in ("SENDING", "COMPLETE", "PENDING"):
        return (True, {
            "count": sent_success or registered_ok or total,
            "fail": sent_failed + registered_fail,
            "group_id": group_id,
            "status": status_str,
        }, 200)

    # 알 수 없는 상태
    return (False, {
        "error": f"Solapi 응답 분석 불가 — total:{total}, status:{status_str}, group:{group_id}",
    }, 502)


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

    ok, payload, code = await _solapi_send_many(messages_norm)
    if not ok:
        return JSONResponse(status_code=code, content={"ok": False, "error": payload["error"]})
    return {"ok": True, **payload}


# ── 발주 API (order.html + 우니 CLI) ──────────────────
# 설계서: business/order/설계_우니발주_20260904.md §4
# 🔴 발송은 사람(store_admins)의 세션 토큰이 있어야만 된다. 우니는 비밀번호가 없어
#    구조적으로 혼자 못 보낸다. 인증으로 막지, 훅으로 막지 않는다.
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "") or SUPABASE_KEY
ZOHO_SMTP_HOST = os.environ.get("ZOHO_SMTP_HOST", "smtp.zoho.com")
ZOHO_SMTP_USER = os.environ.get("ZOHO_SMTP_USER", "")
ZOHO_SMTP_PASS = os.environ.get("ZOHO_SMTP_PASS", "")

# 관리자(store_admins)별 발신 계정 — 다운 님 지메일로 직발송하기 위한 저장소.
# .env 가 아닌 파일인 이유: ① 사람이 화면에서 넣는다 ② 서버 재시작 없이 요청 시점에 읽는다.
ORDER_SMTP_STORE = os.environ.get("ORDER_SMTP_STORE", "/home/haeory/poomasi/.secrets/order_smtp.json")

# site = 업체 웹사이트 장바구니(두레생협 등). 우니가 담고, 다운 님이 주문 버튼을 누른다.
ORDER_CHANNELS = ("sms", "email", "kakao", "phone", "fax", "site")


def _err(code: int, msg: str):
    return JSONResponse(status_code=code, content={"ok": False, "error": msg})


async def _sb(method: str, table: str, params: dict = None, body=None, prefer: str = None):
    """service 키로 Supabase REST 호출. 반환 (status_code, json|None)."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.request(
            method, f"{SUPABASE_URL}/rest/v1/{table}", params=params, json=body, headers=headers
        )
    try:
        return r.status_code, (r.json() if r.text.strip() else None)
    except ValueError:
        return r.status_code, None


async def _order_admin(request: Request):
    """(email, error_response). 토큰 검증 → store_admins 확인.

    🔴 4xx(로그인 문제)와 5xx(서버 문제)를 합치지 않는다. Supabase가 죽었을 때
       401을 돌려주면 화면이 멀쩡한 세션을 지워버린다.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not auth[7:].strip():
        return "", _err(401, "로그인이 필요합니다.")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return "", _err(503, "인증 서버 설정이 없습니다 (.env).")
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        return "", _err(503, f"인증 서버에 연결하지 못했습니다: {e}")
    if r.status_code >= 500:
        return "", _err(503, f"인증 서버 오류({r.status_code}). 잠시 후 다시 시도해주세요.")
    if r.status_code != 200:
        return "", _err(401, "로그인이 만료되었습니다. 다시 로그인해주세요.")
    email = ((r.json() or {}).get("email") or "").strip()
    if not email:
        return "", _err(401, "토큰에서 계정을 확인하지 못했습니다.")

    code, rows = await _sb("GET", "store_admins", {"email": f"eq.{email}", "limit": "1"})
    if code >= 500:
        return "", _err(503, "관리자 확인에 실패했습니다. 잠시 후 다시 시도해주세요.")
    if not rows:
        return "", _err(403, f"매장 관리자만 발주를 보낼 수 있습니다 ({email}).")
    return email, None


def _sms_type(text: str) -> str:
    """Solapi 과금 타입. EUC-KR 90바이트 초과면 LMS."""
    try:
        n = len(text.encode("euc-kr", errors="replace"))
    except Exception:
        n = len(text.encode("utf-8"))
    return "SMS" if n <= 90 else "LMS"


def _smtp_store_read() -> dict:
    """발신 계정 저장소 읽기. 없으면 {}. 깨졌거나 못 읽으면 예외(→ 호출부에서 503)."""
    import json

    try:
        with open(ORDER_SMTP_STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _smtp_store_write(data: dict):
    import json

    d = os.path.dirname(ORDER_SMTP_STORE)
    if d:
        os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = ORDER_SMTP_STORE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ORDER_SMTP_STORE)
    os.chmod(ORDER_SMTP_STORE, 0o600)


def _mask_email(addr: str) -> str:
    name, _, dom = (addr or "").partition("@")
    if not dom:
        return "***"
    return (name[0] if name else "*") + "***@" + dom


def _order_smtp_creds(admin_email: str):
    """로그인한 관리자의 발신 계정 → 없으면 ZOHO_SMTP_* 폴백 → 둘 다 없으면 (None, None, None)."""
    ent = _smtp_store_read().get(admin_email) or {}
    user = (ent.get("smtp_user") or "").strip()
    pw = ent.get("app_password") or ""
    if user and pw:
        return (ent.get("smtp_host") or "smtp.gmail.com").strip(), user, pw
    if ZOHO_SMTP_USER and ZOHO_SMTP_PASS:
        return ZOHO_SMTP_HOST, ZOHO_SMTP_USER, ZOHO_SMTP_PASS
    return None, None, None


def _smtp_login_test_sync(host: str, user: str, password: str):
    """(ok, kind). kind='auth'(비밀번호 문제=4xx) | 'network'(서버·회선 문제=5xx).

    🔴 로그인 거부(사용자 문제)와 연결 실패(서버 문제)를 한 분기로 합치지 않는다.
    """
    import smtplib
    import ssl

    try:
        with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=20) as s:
            s.login(user, password)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "auth"
    except (smtplib.SMTPException, OSError):
        return False, "network"


def _send_order_email_sync(host: str, user: str, password: str, to: str, subject: str, text: str):
    import smtplib
    import ssl
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = user
    msg["Reply-To"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=20) as s:
        s.login(user, password)
        s.send_message(msg)


async def _save_supplier_contact(supplier_name: str, channel: str, to_contact: str, warnings: list):
    """발송 성공 시 업체 연락처 자동 저장. 비어 있으면 채우고, 다르면 note에 이력."""
    if not supplier_name or not to_contact:
        return
    field = {"email": "email", "site": "site_url"}.get(channel, "phone")
    code, rows = await _sb("GET", "suppliers", {"name": f"eq.{supplier_name}", "limit": "1"})
    if code != 200 or not rows:
        warnings.append(f"업체 '{supplier_name}' 를 찾지 못해 연락처를 저장하지 못했습니다.")
        return
    sup = rows[0]
    import datetime as _dt

    patch = {"channel": channel, "contact_updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    old = (sup.get(field) or "").strip()
    if not old:
        patch[field] = to_contact
    elif old != to_contact:
        stamp = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime("%m-%d")
        label = {"phone": "이전 번호", "email": "이전 이메일", "site_url": "이전 사이트"}[field]
        patch[field] = to_contact
        patch["note"] = ((sup.get("note") or "") + f" [{stamp} {label}: {old}]").strip()
    code, _ = await _sb("PATCH", "suppliers", {"id": f"eq.{sup['id']}"}, body=patch)
    if code >= 400:
        warnings.append(f"업체 연락처 저장 실패 ({code}).")


async def _order_bookkeeping(batch: dict, items: list, warnings: list):
    """staff_data 수량 갱신 + 현재고 실사(snapshot) 기록."""
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    snaps = []
    for it in items or []:
        ids = it.get("staff_ids") or []
        qty = it.get("qty")
        # 🔴 현장요청이 여러 건이면 수량 배분을 시스템이 지어내지 않는다(사람이 확인한 값만).
        if len(ids) == 1 and isinstance(qty, int):
            code, _ = await _sb("PATCH", "staff_data", {"id": f"eq.{ids[0]}"}, body={"qty": qty})
            if code >= 400:
                warnings.append(f"현장요청 #{ids[0]} 수량 갱신 실패 ({code}).")
        elif len(ids) > 1:
            warnings.append(
                f"'{it.get('item_name')}' 는 현장요청 {len(ids)}건이 묶여 있어 수량을 나누지 않았습니다."
            )
        sn = it.get("stock_now")
        if isinstance(sn, bool) or not isinstance(sn, (int, float)):
            continue
        snaps.append({
            "item_name": it.get("item_name"),
            "farmer_name": batch.get("supplier_name"),
            "kind": "snapshot",
            "qty": int(sn),
            "at": now,
            "source": "order.html",
            "batch_id": batch["id"],
            "org_id": batch.get("org_id") or "poomasi",
        })
    if snaps:
        code, _ = await _sb("POST", "stock_events", body=snaps)
        if code >= 400:
            warnings.append(f"현재고 기록 실패 ({code}).")


@app.get("/api/order/email-setup")
async def order_email_setup_get(request: Request):
    """내 발신 지메일이 연결돼 있는지. 주소는 마스킹해서만 돌려준다."""
    email, err = await _order_admin(request)
    if err:
        return err
    try:
        ent = _smtp_store_read().get(email) or {}
    except Exception:
        return _err(503, "발신 계정 설정을 읽지 못했습니다.")
    user = (ent.get("smtp_user") or "").strip()
    if user:
        return {"ok": True, "configured": True, "smtp_user": _mask_email(user),
                "smtp_host": ent.get("smtp_host") or "smtp.gmail.com", "source": "personal"}
    if ZOHO_SMTP_USER and ZOHO_SMTP_PASS:
        return {"ok": True, "configured": True, "smtp_user": _mask_email(ZOHO_SMTP_USER),
                "smtp_host": ZOHO_SMTP_HOST, "source": "server"}
    return {"ok": True, "configured": False, "smtp_user": ""}


@app.post("/api/order/email-setup")
async def order_email_setup_post(request: Request):
    """발신 지메일 + 앱 비밀번호 저장. 🔴 실제 SMTP 로그인에 성공해야만 저장한다."""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate(ip, True):
        return _err(429, "요청 한도 초과. 잠시 후 다시 시도해주세요.")

    email, err = await _order_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _err(400, "JSON 파싱 실패")

    smtp_user = (body.get("smtp_user") or "").strip()
    if "@" not in smtp_user or " " in smtp_user or len(smtp_user) < 5:
        return _err(400, "지메일 주소를 정확히 입력해주세요.")
    app_password = "".join((body.get("app_password") or "").split())
    if len(app_password) != 16:
        return _err(400, "앱 비밀번호는 공백을 빼고 16자입니다. 다시 확인해주세요.")
    smtp_host = (body.get("smtp_host") or "smtp.gmail.com").strip()
    if not smtp_host or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in smtp_host):
        return _err(400, "메일 서버 주소 형식이 아닙니다.")

    import asyncio as _asyncio

    ok, kind = await _asyncio.to_thread(_smtp_login_test_sync, smtp_host, smtp_user, app_password)
    if not ok:
        if kind == "auth":
            return _err(400, "구글 로그인 실패: 앱 비밀번호를 확인하세요.")
        return _err(503, "메일 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.")

    import datetime as _dt

    try:
        store = _smtp_store_read()
        store[email] = {
            "smtp_host": smtp_host,
            "smtp_user": smtp_user,
            "app_password": app_password,
            "saved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        _smtp_store_write(store)
    except Exception:
        return _err(503, "발신 계정을 저장하지 못했습니다.")
    return {"ok": True, "configured": True, "smtp_user": _mask_email(smtp_user)}


@app.delete("/api/order/email-setup")
async def order_email_setup_delete(request: Request):
    email, err = await _order_admin(request)
    if err:
        return err
    try:
        store = _smtp_store_read()
        if email in store:
            del store[email]
            _smtp_store_write(store)
    except Exception:
        return _err(503, "발신 계정을 지우지 못했습니다.")
    return {"ok": True, "configured": False}


@app.post("/api/order/send")
async def order_send(request: Request):
    """문자·이메일 발주 발송. body: {batch_id, channel, to_contact, message, items, dry_run}"""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate(ip, True):
        return _err(429, "요청 한도 초과. 잠시 후 다시 시도해주세요.")

    email, err = await _order_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _err(400, "JSON 파싱 실패")

    batch_id = body.get("batch_id")
    if not isinstance(batch_id, int):
        try:
            batch_id = int(batch_id)
        except (TypeError, ValueError):
            return _err(400, "batch_id 가 필요합니다.")

    channel = (body.get("channel") or "").strip()
    if channel not in ("sms", "email"):
        return _err(400, "이 창구는 문자(sms)·이메일(email)만 보냅니다. 카톡·전화는 /api/order/mark 로 기록하세요.")

    to_contact = (body.get("to_contact") or "").strip()
    if not to_contact:
        return _err(400, "받는 곳(전화번호 또는 이메일)을 입력해주세요.")
    if channel == "email" and "@" not in to_contact:
        return _err(400, "이메일 주소 형식이 아닙니다.")
    if channel == "sms" and not to_contact.replace("-", "").isdigit():
        return _err(400, "전화번호 형식이 아닙니다.")

    code, rows = await _sb("GET", "order_batches", {"id": f"eq.{batch_id}", "limit": "1"})
    if code >= 500:
        return _err(503, "발주 정보를 읽지 못했습니다. 잠시 후 다시 시도해주세요.")
    if not rows:
        return _err(404, f"발주 #{batch_id} 를 찾을 수 없습니다.")
    batch = rows[0]
    if batch.get("status") in ("received", "cancelled"):
        return _err(400, f"발주 #{batch_id} 는 이미 '{batch.get('status')}' 상태입니다.")

    message = (body.get("message") or batch.get("message") or "").strip()
    if not message:
        return _err(400, "보낼 문구가 비었습니다.")
    items = body.get("items")
    if items is None:
        items = batch.get("items") or []

    smtp_host = smtp_user = smtp_pass = None
    if channel == "sms":
        if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
            return _err(503, "Solapi 환경변수 미설정 (.env)")
    else:
        try:
            smtp_host, smtp_user, smtp_pass = _order_smtp_creds(email)
        except Exception:
            return _err(503, "발신 계정 설정을 읽지 못했습니다.")
        if not smtp_user:
            # 409 = 화면이 「내 지메일로 보내기 설정」 모달을 띄우라는 신호.
            return JSONResponse(status_code=409, content={"ok": False, "error": "needs_email_setup"})

    if body.get("dry_run"):
        if channel == "email":
            import asyncio as _asyncio

            ok, kind = await _asyncio.to_thread(_smtp_login_test_sync, smtp_host, smtp_user, smtp_pass)
            if not ok:
                if kind == "auth":
                    return _err(400, "구글 로그인 실패: 앱 비밀번호를 확인하세요.")
                return _err(503, "메일 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.")
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": batch_id,
            "channel": channel,
            "to": to_contact,
            "sms_type": _sms_type(message) if channel == "sms" else None,
            "message_length": len(message),
            "item_count": len(items),
            "approved_by": email,
        }

    # ── 실제 발송 ──
    if channel == "sms":
        to_clean = to_contact.replace("-", "")
        msgs = [{
            "to": to_clean,
            "from": SOLAPI_FROM.replace("-", ""),
            "text": message,
            "type": _sms_type(message),
        }]
        ok, payload, http_code = await _solapi_send_many(msgs)
        if not ok:
            return JSONResponse(status_code=http_code, content={"ok": False, "error": payload["error"]})
        send_result = {"via": "solapi", **payload}
    else:
        import asyncio as _asyncio

        subject = f"[품앗이생협 지족점] 발주 요청 — {batch.get('supplier_name') or ''}".strip()
        try:
            await _asyncio.to_thread(
                _send_order_email_sync, smtp_host, smtp_user, smtp_pass, to_contact, subject, message
            )
        except Exception as e:
            return _err(502, f"이메일 발송 실패: {e}")
        send_result = {"via": "smtp", "host": smtp_host, "from": smtp_user, "to": to_contact}

    # ── 발송 성공 이후 기록 (실패해도 '보냈다'는 사실은 남긴다) ──
    import datetime as _dt

    warnings = []
    code, _ = await _sb(
        "PATCH",
        "order_batches",
        {"id": f"eq.{batch_id}"},
        body={
            "status": "sent",
            "sent_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "channel": channel,
            "to_contact": to_contact,
            "message": message,
            "items": items,
            "send_result": send_result,
            "approved_by": email,
        },
    )
    if code >= 400:
        warnings.append(f"발주 상태 저장 실패 ({code}) — 문자는 나갔습니다.")

    try:
        await _save_supplier_contact(batch.get("supplier_name"), channel, to_contact, warnings)
        await _order_bookkeeping(batch, items, warnings)
    except Exception as e:
        warnings.append(f"뒷정리 중 오류: {e}")

    return {"ok": True, "batch_id": batch_id, "channel": channel, "send_result": send_result,
            "approved_by": email, "warnings": warnings}


@app.post("/api/order/mark")
async def order_mark(request: Request):
    """카톡·전화·사이트 주문 기록, 입고 기록, 장바구니 담김 기록.

    body: {batch_id, status, channel, items, carted, carted_note, dry_run}
    status 없이 carted:true 만 오면 담김만 기록하고 주문 상태는 건드리지 않는다.
    """
    ip = request.client.host if request.client else "unknown"
    if not _check_rate(ip, True):
        return _err(429, "요청 한도 초과. 잠시 후 다시 시도해주세요.")

    email, err = await _order_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _err(400, "JSON 파싱 실패")

    batch_id = body.get("batch_id")
    if not isinstance(batch_id, int):
        try:
            batch_id = int(batch_id)
        except (TypeError, ValueError):
            return _err(400, "batch_id 가 필요합니다.")

    status = (body.get("status") or "").strip()
    carted = bool(body.get("carted"))
    if status not in ("sent", "received") and not (carted and not status):
        return _err(400, "status 는 sent 또는 received 여야 합니다.")

    code, rows = await _sb("GET", "order_batches", {"id": f"eq.{batch_id}", "limit": "1"})
    if code >= 500:
        return _err(503, "발주 정보를 읽지 못했습니다. 잠시 후 다시 시도해주세요.")
    if not rows:
        return _err(404, f"발주 #{batch_id} 를 찾을 수 없습니다.")
    batch = rows[0]
    if batch.get("status") == "cancelled":
        return _err(400, f"발주 #{batch_id} 는 취소된 건입니다.")

    channel = (body.get("channel") or "").strip()
    if channel and channel not in ORDER_CHANNELS:
        return _err(400, f"모르는 채널입니다: {channel}")

    items = body.get("items")
    if items is None:
        items = batch.get("items") or []

    if body.get("dry_run"):
        return {"ok": True, "dry_run": True, "batch_id": batch_id, "status": status,
                "channel": channel or batch.get("channel"), "item_count": len(items),
                "carted": carted, "by": email}

    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    warnings = []

    # 사이트 발주: 장바구니에 담김 기록. status 없이 오면 여기서 끝(주문은 사람이 누른다).
    if carted and not status:
        patch = {"carted_at": now}
        if body.get("carted_note") is not None:
            patch["carted_note"] = (body.get("carted_note") or "").strip() or None
        code, _ = await _sb("PATCH", "order_batches", {"id": f"eq.{batch_id}"}, body=patch)
        if code >= 400:
            return _err(502, f"담김 기록 저장 실패 ({code}).")
        return {"ok": True, "batch_id": batch_id, "carted_at": now, "status": batch.get("status"),
                "by": email, "warnings": warnings}

    if status == "sent":
        patch = {
            "status": "sent",
            "sent_at": now,
            "channel": channel or batch.get("channel") or "kakao",
            "approved_by": email,
            "send_result": {"via": "manual", "channel": channel or batch.get("channel")},
        }
        if body.get("to_contact"):
            patch["to_contact"] = (body.get("to_contact") or "").strip()
        if carted and not batch.get("carted_at"):
            patch["carted_at"] = now
        code, _ = await _sb("PATCH", "order_batches", {"id": f"eq.{batch_id}"}, body=patch)
        if code >= 400:
            return _err(502, f"발주 상태 저장 실패 ({code}).")
        if patch.get("to_contact"):
            await _save_supplier_contact(batch.get("supplier_name"), patch["channel"], patch["to_contact"], warnings)
        if batch.get("status") == "draft":
            await _order_bookkeeping(batch, items, warnings)
        return {"ok": True, "batch_id": batch_id, "status": "sent", "channel": patch["channel"],
                "by": email, "warnings": warnings}

    # status == "received"
    events = []
    for it in items:
        try:
            q = int(it.get("qty") or 0)
        except (TypeError, ValueError):
            q = 0
        if q <= 0:
            continue
        events.append({
            "item_name": it.get("item_name"),
            "farmer_name": batch.get("supplier_name"),
            "kind": "inbound",
            "qty": q,
            "at": now,
            "source": "order.html",
            "batch_id": batch_id,
            "org_id": batch.get("org_id") or "poomasi",
        })
    if events:
        code, _ = await _sb("POST", "stock_events", body=events)
        if code >= 400:
            return _err(502, f"입고 기록 실패 ({code}).")
    code, _ = await _sb(
        "PATCH",
        "order_batches",
        {"id": f"eq.{batch_id}"},
        # 🔴 items 는 덮어쓰지 않는다 — "몇 개 시켰나"가 발주 기록이고,
        #    "몇 개 들어왔나"는 stock_events inbound 가 원장이다.
        body={"status": "received", "received_at": now, "received_by": email},
    )
    if code >= 400:
        warnings.append(f"발주 상태 저장 실패 ({code}) — 입고는 기록됐습니다.")
    return {"ok": True, "batch_id": batch_id, "status": "received", "inbound": len(events),
            "by": email, "warnings": warnings}


# ── 위젯 JS 캐시 방지 (자주 업데이트되는 파일) ──────────
from starlette.responses import FileResponse

@app.get("/poomai-widget.js")
async def widget_js():
    return FileResponse(
        os.path.join(STATIC_DIR, "poomai-widget.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

# ── 푸드플랜 실증 API (include. 임포트 실패해도 서버 기동 무영향) ──
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from foodplan_api import router as _foodplan_router
    app.include_router(_foodplan_router)
except Exception as _fp_e:
    print(f"[seed] foodplan_api 미로드(무시): {_fp_e}")

# ── 정적 파일 (API 라우트보다 뒤에 마운트) ─────────────
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[seed] 서버 시작: http://0.0.0.0:{PORT} → {STATIC_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
