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


@asynccontextmanager
async def lifespan(app: FastAPI):
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


# ── 위젯 JS 캐시 방지 (자주 업데이트되는 파일) ──────────
from starlette.responses import FileResponse

@app.get("/poomai-widget.js")
async def widget_js():
    return FileResponse(
        os.path.join(STATIC_DIR, "poomai-widget.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

# ── 정적 파일 (API 라우트보다 뒤에 마운트) ─────────────
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[seed] 서버 시작: http://0.0.0.0:{PORT} → {STATIC_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
