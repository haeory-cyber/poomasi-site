"""foodplan_api.py — 푸드플랜 실증 코어 루프 백엔드 API (seed_server include)

스펙 정본: business/foodplan_2026/코어루프_스펙_v0.1.md §4·§5·§6·§9
설계 방침(2단계): 프론트는 Supabase 직접 접근(anon 뷰/예약 INSERT), 서버 API는
"서버만 할 수 있는 것"에 한정 — 동의자 전화번호 조회(service_role, RLS 우회) + 발송.

seed_server.py에는 try/except include 1줄만 추가. 이 모듈 임포트 실패해도 서버 기동 무영향.

엔드포인트:
  POST /api/foodplan/notify          — 발송(JWT). dry_run 기본 True. 실발송은 dry_run=false 명시.
  GET  /api/foodplan/notify/preview  — 오늘 registered 품목 T1 문안 미리보기(JWT)
  POST /api/foodplan/fans/preview    — 생산자 단골(1년 내 구매 조합원) 수 조회(JWT). PII 미반환.
  POST /api/foodplan/fans/send       — 생산자 단골 SMS 발송(JWT). dry_run 기본 True.
  POST /api/foodplan/fans/manual_send — 수신번호 직접 입력 수동 발송(JWT). dry_run 기본 True.

주의:
  - 서버 전용 키(SUPABASE_SECRET_KEY)는 로그·응답에 절대 노출 금지.
  - Solapi 실발송은 후니님 승인 후. 기본 dry_run=True.
  - alimtalk은 카카오 채널 연동 전 → 501.
"""
import os
import re as _re
import hmac as _hmac
import hashlib as _hashlib
import datetime as _dt
import secrets as _secrets
import time
from collections import defaultdict

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/foodplan", tags=["foodplan"])

# ── 설정 (독립 로드. seed_server 전역에 의존하지 않음) ──
SUPABASE_URL        = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY   = os.environ.get("SUPABASE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")  # service_role. RLS 우회. 노출 금지.

SOLAPI_API_KEY    = os.environ.get("SOLAPI_API_KEY", "")
SOLAPI_API_SECRET = os.environ.get("SOLAPI_API_SECRET", "")
SOLAPI_FROM       = os.environ.get("SOLAPI_FROM", "")

RESERVE_LINK = "https://seed.poomasi.org/foodplan/today"
STORE_LABEL  = "품앗이 로컬푸드 지족점"

# 알림톡 플레이스홀더(채널 연동 전) — 값 있으면 추후 활성화 판단용
KAKAO_PF_ID       = os.environ.get("FOODPLAN_KAKAO_PF_ID", "")
KAKAO_TEMPLATE_T1 = os.environ.get("FOODPLAN_KAKAO_TEMPLATE_T1", "")

# ── 발송 전용 rate limit (분당 2회/IP) ────────────────
_send_rate: dict[str, list[float]] = defaultdict(list)
_SEND_WINDOW = 60
_SEND_LIMIT = 2


def _check_send_rate(ip: str) -> bool:
    now = time.time()
    _send_rate[ip] = [t for t in _send_rate[ip] if t > now - _SEND_WINDOW]
    if len(_send_rate[ip]) >= _SEND_LIMIT:
        return False
    _send_rate[ip].append(now)
    return True


# ── JWT 검증 (seed_server 패턴: /auth/v1/user 직접 검증) ──
async def _email_from_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return ""
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return (r.json() or {}).get("email", "") or ""
    except httpx.HTTPError:
        pass
    return ""


# ── Supabase REST 헬퍼 (service_role) ─────────────────
def _sr_headers() -> dict:
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


async def _sr_get(client: httpx.AsyncClient, path: str, params: dict) -> list:
    r = await client.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sr_headers(), params=params)
    r.raise_for_status()
    return r.json() or []


async def _sr_post(client: httpx.AsyncClient, path: str, body) -> httpx.Response:
    return await client.post(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={**_sr_headers(), "Prefer": "return=representation"},
        json=body,
    )


# ── 문안 생성 (스펙 §9 T1) ────────────────────────────
def _summarize_items(items: list[dict]) -> tuple[str, int, int]:
    """(품목요약, 건수, 최대할인%). items = foodplan_items 행."""
    names = [(it.get("item_name") or "").strip() for it in items if it.get("item_name")]
    count = len(items)
    max_disc = max((int(it.get("discount_rate") or 0) for it in items), default=0)
    if not names:
        summary = "신선 농산물"
    elif len(names) == 1:
        summary = names[0]
    else:
        summary = f"{names[0]} 외 {len(names) - 1}종"
    return summary, count, max_disc


def _build_t1(items: list[dict]) -> str:
    """스펙 §9 T1 형식. SMS 본문(알림톡도 동일 문안 기반)."""
    summary, count, max_disc = _summarize_items(items)
    return (
        f"[{STORE_LABEL}] 오늘의 알뜰 농산물\n\n"
        f"{summary} 등 {count}건이 등록되었습니다.\n"
        f"신선 농산물을 매장 가격보다 최대 {max_disc}% 저렴하게 만나보세요.\n\n"
        f"- 픽업: 매장 영업시간 내 선택 시간대\n"
        f"- 수량 한정, 예약 순 마감\n\n"
        f"▶ 상품 보고 예약하기: {RESERVE_LINK}\n\n"
        f"* 푸드플랜 실증 시범 참여에 동의하신 조합원께 발송됩니다."
    )


# ── 대상 조회 (동의자 — service_role, RLS 우회) ────────
async def _fetch_consents(client: httpx.AsyncClient) -> list[dict]:
    """revoked_at IS NULL 동의자. 전화번호 중복 제거."""
    rows = await _sr_get(client, "foodplan_consents", {
        "select": "name,phone",
        "revoked_at": "is.null",
    })
    seen, out = set(), []
    for row in rows:
        ph = (row.get("phone") or "").strip()
        if ph and ph not in seen:
            seen.add(ph)
            out.append({"name": (row.get("name") or "").strip() or None, "phone": ph})
    return out


async def _fetch_items(client: httpx.AsyncClient, item_ids: list[str]) -> list[dict]:
    if not item_ids:
        return []
    ids_csv = ",".join(item_ids)
    return await _sr_get(client, "foodplan_items", {
        "select": "id,item_name,discount_rate,status,weight_kg,qty,unit",
        "id": f"in.({ids_csv})",
    })


async def _fetch_today_registered(client: httpx.AsyncClient) -> list[dict]:
    today = _dt.date.today().isoformat()
    return await _sr_get(client, "foodplan_items", {
        "select": "id,item_name,discount_rate,status,weight_kg,qty,unit,created_at",
        "status": "eq.registered",
        "created_at": f"gte.{today}T00:00:00",
        "order": "created_at.desc",
    })


# ── Solapi 발송 (seed_server HMAC 패턴 재사용) ─────────
async def _solapi_send_many(client: httpx.AsyncClient, messages_norm: list[dict]) -> dict:
    date = _dt.datetime.utcnow().isoformat() + "Z"
    salt = _secrets.token_hex(16)
    sig = _hmac.new(SOLAPI_API_SECRET.encode(), (date + salt).encode(), _hashlib.sha256).hexdigest()
    auth_header = f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={date}, salt={salt}, signature={sig}"
    resp = await client.post(
        "https://api.solapi.com/messages/v4/send-many",
        headers={"Content-Type": "application/json", "Authorization": auth_header},
        json={"messages": messages_norm},
        timeout=15.0,
    )
    resp.raise_for_status()
    result = resp.json()
    count_obj = result.get("count") or {}
    return {
        "sent": (count_obj.get("sentSuccess") or count_obj.get("registeredSuccess") or 0),
        "failed": ((count_obj.get("sentFailed") or 0) + (count_obj.get("registeredFailed") or 0)),
        "group_id": result.get("groupId") or result.get("_id") or "",
        "status": result.get("status", ""),
    }


# ── RPC: 상태전이 (registered → notified) ─────────────
async def _transition_notified(client: httpx.AsyncClient, item_ids: list[str], actor: str) -> int:
    """service_role로 RPC 호출. 이미 notified 등인 항목은 불허 전이 EXCEPTION → 건너뜀."""
    ok = 0
    for iid in item_ids:
        try:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/foodplan_transition",
                headers=_sr_headers(),
                json={"p_item_id": iid, "p_to_status": "notified", "p_actor": actor, "p_meta": {"via": "notify_api"}},
                timeout=8.0,
            )
            if r.status_code < 300:
                ok += 1
        except httpx.HTTPError:
            pass
    return ok


# ── 엔드포인트 ─────────────────────────────────────────
@router.get("/notify/preview")
async def notify_preview(request: Request):
    """오늘 registered 품목 기준 T1 문안 + 대상 수 미리보기 (JWT 필수)."""
    email = await _email_from_token(request)
    if not email:
        return JSONResponse(status_code=401, content={"ok": False, "error": "로그인이 필요합니다."})
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})
    try:
        async with httpx.AsyncClient() as client:
            items = await _fetch_today_registered(client)
            consents = await _fetch_consents(client)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"조회 실패: {type(e).__name__}"})
    return {
        "ok": True,
        "item_count": len(items),
        "recipient_count": len(consents),
        "preview_text": _build_t1(items) if items else "(오늘 등록된 품목 없음)",
        "item_ids": [it.get("id") for it in items],
    }


@router.post("/notify")
async def notify(request: Request):
    """발송(JWT). body: {item_ids[], channel('sms'|'alimtalk'), dry_run(기본 True)}.

    dry_run=True(기본): 발송 없이 대상 수·문안 미리보기.
    dry_run=false: 실발송 + notify_log INSERT + items registered→notified 전이.
    """
    ip = request.client.host if request.client else "unknown"
    email = await _email_from_token(request)
    if not email:
        return JSONResponse(status_code=401, content={"ok": False, "error": "로그인이 필요합니다."})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})

    item_ids = body.get("item_ids") or []
    channel = (body.get("channel") or "sms").strip()
    dry_run = body.get("dry_run", True)  # 안전: 기본 True

    if not isinstance(item_ids, list) or not item_ids:
        return JSONResponse(status_code=400, content={"ok": False, "error": "item_ids 필수"})
    if channel not in ("sms", "alimtalk"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "channel은 sms|alimtalk"})
    if channel == "alimtalk":
        return JSONResponse(status_code=501, content={
            "ok": False, "error": "알림톡 채널 연동 대기 (카카오 채널 개설·Solapi 연동·템플릿 심사 후 활성화)",
            "pending": {"pfId_set": bool(KAKAO_PF_ID), "template_set": bool(KAKAO_TEMPLATE_T1)},
        })
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})

    try:
        async with httpx.AsyncClient() as client:
            items = await _fetch_items(client, item_ids)
            consents = await _fetch_consents(client)
            text = _build_t1(items) if items else _build_t1([])

            if dry_run:
                return {
                    "ok": True, "dry_run": True,
                    "recipient_count": len(consents),
                    "item_count": len(items),
                    "preview_text": text,
                }

            # ── 실발송 ──
            if not _check_send_rate(ip):
                return JSONResponse(status_code=429, content={"ok": False, "error": "발송 한도 초과(분당 2회). 잠시 후 재시도."})
            if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
                return JSONResponse(status_code=503, content={"ok": False, "error": "Solapi 환경변수 미설정(.env)"})
            if not consents:
                return JSONResponse(status_code=400, content={"ok": False, "error": "발송 대상(동의자) 없음"})

            from_clean = SOLAPI_FROM.replace("-", "")
            messages_norm = [
                {"to": c["phone"].replace("-", ""), "from": from_clean, "text": text}
                for c in consents if c.get("phone")
            ]
            send_res = await _solapi_send_many(client, messages_norm)

            # notify_log 기록
            await _sr_post(client, "foodplan_notify_log", {
                "item_ids": item_ids,
                "channel": "sms",
                "recipients": len(messages_norm),
                "success": send_res["sent"],
            })
            # 상태 전이 registered → notified
            transitioned = await _transition_notified(client, item_ids, actor=email)

            return {
                "ok": True, "dry_run": False,
                "sent": send_res["sent"], "failed": send_res["failed"],
                "recipients": len(messages_norm),
                "transitioned": transitioned,
                "group_id": send_res["group_id"],
            }
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"외부 호출 실패({e.response.status_code})"})
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"네트워크 오류: {type(e).__name__}"})


# ══════════════════════════════════════════════════════
# 생산자 단골 문자 (fans) — 2026-08-07
# 특정 생산자를 최근 1년 내 1회+ 구입한 조합원(sms_optin·전화 보유)에게 SMS.
# 대상 원천 = pos_transactions 직접 조회 (farmer_members 스냅샷 사용 금지).
# 🔴 광고 문자 법규: 본문 맨 앞 "(광고)" + 말미 수신거부 안내 필수.
#    080 무료거부번호 미보유 → 매장 전화 안내로 갈음.
# ══════════════════════════════════════════════════════
FANS_STORE_PHONE = "042-824-0131"
FANS_OPTOUT_LINE = f"수신거부: 매장({FANS_STORE_PHONE}) 문의"
FANS_MIN_CHOICES = (1, 3, 5)  # 단골 기준: 1년 내 구매 횟수
_MEMBER_NO_FLOAT = _re.compile(r"^[0-9]+(\.[0-9]+)?$")


def _norm_member_no(v: str) -> str:
    """POS member_no 정규화: "3785.0" → "3785". (DB trunc(numeric)::text와 동일 결과)"""
    v = (v or "").strip()
    if _MEMBER_NO_FLOAT.match(v):
        return v.split(".", 1)[0]
    return v


def _fans_min_purchases(body: dict):
    """min_purchases 파싱. 1|3|5만 허용, 그 외 None(→400)."""
    v = body.get("min_purchases", 1)
    if isinstance(v, bool) or not isinstance(v, int) or v not in FANS_MIN_CHOICES:
        return None
    return v


def _fans_ad_text(farmer_name: str, body: str) -> str:
    """광고 표기 + 생산자명 강제: 앞 (광고), 본문에 생산자명 없으면 헤더 라인 삽입, 뒤 수신거부 안내."""
    body = (body or "").strip()
    if farmer_name and farmer_name not in body:
        header = f"{farmer_name} 할인 소식"
        if STORE_LABEL not in body:
            header = f"[{STORE_LABEL}] {header}"
        body = f"{header}\n{body}".strip()
    text = body if body.startswith("(광고)") else f"(광고){body}"
    if "수신거부" not in text:
        text += f"\n{FANS_OPTOUT_LINE}"
    return text


def _fans_sample_text(farmer_name: str) -> str:
    return _fans_ad_text(
        farmer_name,
        f"[{STORE_LABEL}]\n"
        f"자주 찾아주신 {farmer_name} 상품 할인 행사를 오늘 매장에서 진행합니다.\n"
        f"조합원님께 먼저 안내드립니다.",
    )


_FANS_PHONE_RE = _re.compile(r"^010\d{7,8}$")  # 하이픈 제거 후 010 시작 10~11자리


def _fans_parse_phones(raw) -> tuple[list[str], list[str]]:
    """수신번호 입력(리스트 또는 개행/쉼표 구분 문자열) → (유효·정규화·중복제거 목록, rejected 원문 목록)."""
    if isinstance(raw, str):
        parts = _re.split(r"[\n,]+", raw)
    elif isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        return [], []
    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for p in parts:
        p0 = p.strip()
        if not p0:
            continue
        ph = _re.sub(r"[-\s]", "", p0)
        if _FANS_PHONE_RE.match(ph):
            if ph not in seen:
                seen.add(ph)
                valid.append(ph)
        else:
            rejected.append(p0)
    return valid, rejected


def _fans_manual_text(body: str, is_ad: bool) -> str:
    """수동 발송 문안. is_ad=True: (광고)+매장명+수신거부 강제 / False: 매장명 헤더만(개별 안내용)."""
    body = (body or "").strip()
    if STORE_LABEL not in body:
        body = f"[{STORE_LABEL}]\n{body}".strip()
    if not is_ad:
        return body
    text = body if body.startswith("(광고)") else f"(광고){body}"
    if "수신거부" not in text:
        text += f"\n{FANS_OPTOUT_LINE}"
    return text


async def _fans_buyer_counts(client: httpx.AsyncClient, farmer_name: str) -> dict[str, int]:
    """최근 1년 내 해당 생산자 구매 조합원 → {member_no(정규화): 구매건수}. 1000행씩 페이지네이션.

    구매건수 = pos_transactions 행 수 기준(한 방문 3종 구매 = 3회). 2026-08-07 후니님 확정.
    """
    since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=365)).isoformat()
    counts: dict[str, int] = {}
    offset = 0
    while True:
        rows = await _sr_get(client, "pos_transactions", {
            "select": "member_no",
            "farmer_name": f"eq.{farmer_name}",
            "sold_at": f"gte.{since}",
            "limit": "1000",
            "offset": str(offset),
        })
        for r in rows:
            mid = _norm_member_no(r.get("member_no") or "")
            if mid:
                counts[mid] = counts.get(mid, 0) + 1
        if len(rows) < 1000:
            break
        offset += 1000
    return counts


async def _fans_sendable(client: httpx.AsyncClient, mids: set[str]) -> list[dict]:
    """members에서 sms_optin=true·전화 보유 조합원. [{member_id, phone}] (member_id 기준 distinct)."""
    out: list[dict] = []
    mids_sorted = sorted(mids)
    for i in range(0, len(mids_sorted), 200):
        chunk = mids_sorted[i:i + 200]
        rows = await _sr_get(client, "members", {
            "select": "member_id,phone",
            "member_id": f"in.({','.join(chunk)})",
            "sms_optin": "is.true",
        })
        for r in rows:
            ph = (r.get("phone") or "").strip()
            if ph:
                out.append({"member_id": r.get("member_id"), "phone": ph})
    return out


@router.post("/fans/preview")
async def fans_preview(request: Request):
    """생산자 단골 수 미리보기(JWT). body: {farmer_name, min_purchases(1|3|5, 기본 1)}.

    PII 미반환(수치+예시문만). counts/buyers_counts에 세 기준 인원수를 한 번의 집계로 담는다.
    """
    email = await _email_from_token(request)
    if not email:
        return JSONResponse(status_code=401, content={"ok": False, "error": "로그인이 필요합니다."})
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})
    farmer_name = (body.get("farmer_name") or "").strip()
    if not farmer_name:
        return JSONResponse(status_code=400, content={"ok": False, "error": "farmer_name 필수"})
    min_p = _fans_min_purchases(body)
    if min_p is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "min_purchases는 1|3|5"})
    try:
        async with httpx.AsyncClient() as client:
            tx_counts = await _fans_buyer_counts(client, farmer_name)
            members = await _fans_sendable(client, set(tx_counts))
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"조회 실패: {type(e).__name__}"})
    sendable_mids = {m["member_id"] for m in members}
    buyers_counts = {str(k): sum(1 for c in tx_counts.values() if c >= k) for k in FANS_MIN_CHOICES}
    counts = {str(k): sum(1 for m, c in tx_counts.items() if c >= k and m in sendable_mids) for k in FANS_MIN_CHOICES}
    return {
        "ok": True,
        "farmer_name": farmer_name,
        "min_purchases": min_p,
        "buyers_1y": buyers_counts[str(min_p)],
        "sendable": counts[str(min_p)],
        "buyers_counts": buyers_counts,   # 기준별 1년 내 구매 조합원 수
        "counts": counts,                 # 기준별 발송 가능(수신동의·전화 보유) 수
        "sample_text": _fans_sample_text(farmer_name),
    }


@router.post("/fans/send")
async def fans_send(request: Request):
    """생산자 단골 SMS 발송(JWT). body: {farmer_name, message_body, min_purchases(1|3|5, 기본 1), dry_run(기본 True)}.

    dry_run=True(기본): 발송 없이 대상 수·최종 문안 반환.
    dry_run=false: Solapi 실발송(50건 배치) + foodplan_notify_log 기록.
    """
    ip = request.client.host if request.client else "unknown"
    email = await _email_from_token(request)
    if not email:
        return JSONResponse(status_code=401, content={"ok": False, "error": "로그인이 필요합니다."})
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})

    farmer_name = (body.get("farmer_name") or "").strip()
    message_body = (body.get("message_body") or "").strip()
    dry_run = body.get("dry_run", True)  # 안전: 기본 True
    if not farmer_name:
        return JSONResponse(status_code=400, content={"ok": False, "error": "farmer_name 필수"})
    if not message_body:
        return JSONResponse(status_code=400, content={"ok": False, "error": "message_body 필수"})
    min_p = _fans_min_purchases(body)
    if min_p is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "min_purchases는 1|3|5"})

    text = _fans_ad_text(farmer_name, message_body)

    try:
        async with httpx.AsyncClient() as client:
            tx_counts = await _fans_buyer_counts(client, farmer_name)
            # 프론트가 준 숫자를 믿지 않고 서버가 기준(min_purchases)으로 재추출
            mids = {m for m, c in tx_counts.items() if c >= min_p}
            members = await _fans_sendable(client, mids)
            # 전화번호 중복 제거(가족 공유 번호 등 이중 발송 방지)
            seen: set[str] = set()
            phones: list[str] = []
            for m in members:
                ph = m["phone"].replace("-", "").replace(" ", "")
                if ph and ph not in seen:
                    seen.add(ph)
                    phones.append(ph)

            if dry_run:
                return {
                    "ok": True, "dry_run": True,
                    "farmer_name": farmer_name,
                    "min_purchases": min_p,
                    "buyers_1y": len(mids),
                    "sendable": len(members),
                    "unique_phones": len(phones),
                    "final_text": text,
                }

            # ── 실발송 ──
            if not _check_send_rate(ip):
                return JSONResponse(status_code=429, content={"ok": False, "error": "발송 한도 초과(분당 2회). 잠시 후 재시도."})
            if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
                return JSONResponse(status_code=503, content={"ok": False, "error": "Solapi 환경변수 미설정(.env)"})
            if not phones:
                return JSONResponse(status_code=400, content={"ok": False, "error": "발송 대상 없음"})

            from_clean = SOLAPI_FROM.replace("-", "")
            sent = failed = 0
            group_ids: list[str] = []
            for i in range(0, len(phones), 50):  # seed_server /api/sms-send와 동일한 50건 배치
                batch = [{"to": p, "from": from_clean, "text": text} for p in phones[i:i + 50]]
                res = await _solapi_send_many(client, batch)
                sent += res["sent"]
                failed += res["failed"]
                if res["group_id"]:
                    group_ids.append(res["group_id"])

            # notify_log 단일 기록 — 수치는 기존 컬럼, 맥락(생산자명 등)은 meta jsonb (2026-08-07 승인 마이그레이션)
            await _sr_post(client, "foodplan_notify_log", {
                "channel": "sms",
                "recipients": len(phones),
                "success": sent,
                "meta": {
                    "kind": "fans",
                    "farmer_name": farmer_name,
                    "min_purchases": min_p,
                    "failed": failed,
                    "group_ids": group_ids,
                    "actor": email,
                },
            })

            return {
                "ok": True, "dry_run": False,
                "farmer_name": farmer_name,
                "min_purchases": min_p,
                "sent": sent, "failed": failed,
                "recipients": len(phones),
                "group_ids": group_ids,
            }
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"외부 호출 실패({e.response.status_code})"})
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"네트워크 오류: {type(e).__name__}"})


@router.post("/fans/manual_send")
async def fans_manual_send(request: Request):
    """수동 문자 발송(JWT). body: {phones(리스트 또는 개행/쉼표 문자열), text, is_ad(기본 true), dry_run(기본 True)}.

    is_ad=true: (광고)+매장명+수신거부 강제 / false: 매장명 헤더만(개별 안내용).
    dry_run=True(기본): 발송 없이 최종 문안·유효 건수·rejected 반환.
    """
    ip = request.client.host if request.client else "unknown"
    email = await _email_from_token(request)
    if not email:
        return JSONResponse(status_code=401, content={"ok": False, "error": "로그인이 필요합니다."})
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})

    text_in = (body.get("text") or "").strip()
    is_ad = bool(body.get("is_ad", True))
    dry_run = body.get("dry_run", True)  # 안전: 기본 True
    if not text_in:
        return JSONResponse(status_code=400, content={"ok": False, "error": "text 필수"})
    phones, rejected = _fans_parse_phones(body.get("phones"))
    if not phones:
        return JSONResponse(status_code=400, content={"ok": False, "error": "유효한 수신번호 없음", "rejected": rejected})

    text = _fans_manual_text(text_in, is_ad)

    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "is_ad": is_ad,
            "recipients": len(phones),
            "rejected": rejected,
            "final_text": text,
        }

    # ── 실발송 ──
    if not _check_send_rate(ip):
        return JSONResponse(status_code=429, content={"ok": False, "error": "발송 한도 초과(분당 2회). 잠시 후 재시도."})
    if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Solapi 환경변수 미설정(.env)"})

    try:
        async with httpx.AsyncClient() as client:
            from_clean = SOLAPI_FROM.replace("-", "")
            sent = failed = 0
            group_ids: list[str] = []
            for i in range(0, len(phones), 50):  # 기존 발송과 동일한 50건 배치
                batch = [{"to": p, "from": from_clean, "text": text} for p in phones[i:i + 50]]
                res = await _solapi_send_many(client, batch)
                sent += res["sent"]
                failed += res["failed"]
                if res["group_id"]:
                    group_ids.append(res["group_id"])

            # notify_log 단일 기록 — 수치는 기존 컬럼, 맥락은 meta jsonb (2026-08-07 승인 마이그레이션)
            await _sr_post(client, "foodplan_notify_log", {
                "channel": "sms",
                "recipients": len(phones),
                "success": sent,
                "meta": {
                    "kind": "manual",
                    "is_ad": is_ad,
                    "rejected": len(rejected),
                    "failed": failed,
                    "group_ids": group_ids,
                    "actor": email,
                },
            })
        return {
            "ok": True, "dry_run": False,
            "is_ad": is_ad,
            "sent": sent, "failed": failed,
            "recipients": len(phones),
            "rejected": rejected,
            "group_ids": group_ids,
        }
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"외부 호출 실패({e.response.status_code})"})
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"네트워크 오류: {type(e).__name__}"})
