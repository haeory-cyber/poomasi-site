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
  GET  /api/foodplan/optout          — 수신거부 토큰 유효성 확인(무인증). 문자 수신자용.
  POST /api/foodplan/optout          — 수신거부 처리(무인증, 토큰 필수).

주의:
  - 서버 전용 키(SUPABASE_SECRET_KEY)는 로그·응답에 절대 노출 금지.
  - Solapi 실발송은 후니님 승인 후. 기본 dry_run=True.
  - 채널은 문자(SMS/LMS) 단일. 2026-08-20 카카오 알림톡 축 폐기(카카오 검수: 마케팅성
    메시지는 알림톡 대상 아님 — 2차 반려). 스펙 business/foodplan_2026/문자전환_스펙_20260820.md
  - 🔴 광고성 문자는 정보통신망법 제50조·시행령 [별표 6] 규격을 _ad_wrap()으로만 조립한다.
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
from cryptography.fernet import Fernet, InvalidToken
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
OPTOUT_LINK  = "https://seed.poomasi.org/foodplan/optout"
STORE_LABEL  = "품앗이 로컬푸드 지족점"
STORE_PHONE  = "042-716-0019"

# 수신거부 토큰 암호화 키 (Fernet). 전화번호를 URL에 노출하지 않으면서 O(1) 역산 가능.
# 🔴 TTL 미사용 — 수신거부 링크는 몇 달 뒤에 눌러도 동작해야 한다.
FOODPLAN_OPTOUT_KEY = os.environ.get("FOODPLAN_OPTOUT_KEY", "")
_optout_fernet = Fernet(FOODPLAN_OPTOUT_KEY.encode()) if FOODPLAN_OPTOUT_KEY else None

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


async def _sr_patch(client: httpx.AsyncClient, path: str, params: dict, body: dict) -> httpx.Response:
    return await client.patch(
        f"{SUPABASE_URL}/rest/v1/{path}", headers=_sr_headers(), params=params, json=body,
    )


# ══════════════════════════════════════════════════════
# 광고 문자 법정 요건 (정보통신망법 제50조 / 시행령 [별표 6])
# 스펙: business/foodplan_2026/문자전환_스펙_20260820.md §1
# ══════════════════════════════════════════════════════
def _norm_phone(v: str) -> str:
    """전화번호 정규화: 하이픈·공백 등 제거하고 숫자만. 토큰·억제목록의 단일 표기."""
    return _re.sub(r"\D", "", v or "")


def _phone_variants(phone: str) -> list[str]:
    """정규화 번호 → DB에 실재하는 표기 후보. consents는 숫자만, members는 하이픈 표기라 둘 다 필요."""
    d = _norm_phone(phone)
    out = [d]
    if len(d) == 11:
        out.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
    elif len(d) == 10:
        out.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
    return out


def _optout_token(phone: str) -> str:
    """전화번호를 Fernet으로 암호화한 수신거부 토큰. 위조 불가(서명 포함)·역산 가능(O(1) 조회)."""
    if not _optout_fernet:
        return ""
    return _optout_fernet.encrypt(_norm_phone(phone).encode()).decode()


def _phone_from_token(token: str) -> str:
    """토큰 → 전화번호. 위조·훼손·키 불일치면 빈 문자열. 🔴 ttl 미지정 = 만료 없음."""
    if not token or not _optout_fernet:
        return ""
    try:
        return _norm_phone(_optout_fernet.decrypt(token.encode()).decode())
    except (InvalidToken, ValueError, TypeError):
        return ""


def _optout_url(phone: str | None) -> str:
    """수신자별 무료 수신거부 링크. phone=None(미리보기)은 자리표시자."""
    if not phone:
        return f"{OPTOUT_LINK}?t=(수신자별코드)"
    return f"{OPTOUT_LINK}?t={_optout_token(phone)}"


def _ad_wrap(body: str, phone: str | None = None) -> str:
    """🔴 광고성 문자 조립 — [별표 6] 「음성 외의 형태」 규격. 모든 광고 경로가 이 함수만 쓴다.

    시작 부분: (광고) + 전송자 명칭 + 전화번호
    끝 부분  : 전화를 갈음하는 수신거부 방식(웹링크) + 수신자 비용 미부담 명시("무료")
    """
    body = (body or "").strip()
    if body.startswith("(광고)"):          # 호출부가 이미 붙였으면 중복 방지 (표시 회피 조작 금지 조항)
        body = body[len("(광고)"):].lstrip()
    return (
        f"(광고)[{STORE_LABEL}] {STORE_PHONE}\n\n"
        f"{body}\n\n"
        f"무료 수신거부: {_optout_url(phone)}"
    )


# ── 야간 발송 차단 (제50조③ — 21~08시는 별도 사전 동의 필요. 우리는 미보유) ──
_KST = _dt.timezone(_dt.timedelta(hours=9))


def _now_kst() -> _dt.datetime:
    """KST 현재시각. 테스트에서 이 함수를 교체해 야간 가드를 검증한다."""
    return _dt.datetime.now(_KST)


def _night_blocked() -> bool:
    """광고성 실발송 금지 시간대(KST 21:00~08:00)면 True. dry_run·정보성은 호출하지 않는다."""
    return not (8 <= _now_kst().hour < 21)


_NIGHT_ERROR = ("야간 발송 차단(정보통신망법 제50조③): 오후 9시~오전 8시 광고성 전송은 "
                "별도 사전 동의가 필요합니다. 오전 8시 이후 발송해 주세요.")


# ── 수신거부 억제 목록 (foodplan_sms_optout = 정본) ────
async def _fetch_suppressed(client: httpx.AsyncClient, phones: list[str]) -> set[str]:
    """발송 예정 번호 중 수신거부된 것(정규화 표기). 발송 직전 대조용."""
    uniq = sorted({_norm_phone(p) for p in phones if _norm_phone(p)})
    out: set[str] = set()
    for i in range(0, len(uniq), 200):
        rows = await _sr_get(client, "foodplan_sms_optout", {
            "select": "phone",
            "phone": f"in.({','.join(uniq[i:i + 200])})",
        })
        out.update(_norm_phone(r.get("phone") or "") for r in rows)
    return out


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


def _build_t1(items: list[dict], phone: str | None = None) -> str:
    """T1 오늘의 품목 — 광고성. 문자전환 스펙 §2-B."""
    summary, count, max_disc = _summarize_items(items)
    return _ad_wrap(
        f"오늘의 알뜰 농산물\n"
        f"{summary} 등 {count}건이 등록되었습니다.\n"
        f"신선 농산물을 매장 가격보다 최대 {max_disc}% 저렴하게 만나보세요.\n\n"
        f"- 픽업: 매장 영업시간(09:00~21:00) 내 선택 시간대\n"
        f"- 수량 한정, 예약 순 마감\n\n"
        f"▶ 상품 보고 예약하기: {RESERVE_LINK}",
        phone,
    )


def _build_t2(farmer: str, item: str, qty: str, arrive_date: str, phone: str | None = None) -> str:
    """T2 입고 예정 — 광고성. T1과 동일 규격, 본문만 입고 예정 안내."""
    return _ad_wrap(
        f"실증 품목 입고 예정\n"
        f"{farmer} 농가의 {item}({qty})이 {arrive_date} 입고 예정으로 등록되었습니다.\n"
        f"사전 예약하실 수 있습니다.\n\n"
        f"▶ 예약하기: {RESERVE_LINK}",
        phone,
    )


def _build_t3(name: str, items_text: str, slot: str) -> str:
    """T3 예약 확인 — 🔴 정보성. 수신자의 예약 행위에 대한 응답이므로 (광고)·수신거부를 넣지 않는다.
    따라서 _ad_wrap을 쓰지 않는 유일한 문안이다."""
    return (
        f"[{STORE_LABEL}] 예약 확인\n\n"
        f"{name}님, 예약이 접수되었습니다.\n"
        f"- 품목: {items_text}\n"
        f"- 수령: 매장 픽업 {slot}\n"
        f"- 장소: 지족점 (유성구 지족로 364번길 40)\n\n"
        f"시간 내 방문이 어려우시면 매장({STORE_PHONE})으로 연락 주세요."
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
    """발송(JWT). body: {item_ids[], channel('sms'), dry_run(기본 True)}.

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
    if channel != "sms":  # 2026-08-20 알림톡 폐기 — 문자 단일 채널
        return JSONResponse(status_code=400, content={"ok": False, "error": "channel은 sms"})
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})

    try:
        async with httpx.AsyncClient() as client:
            items = await _fetch_items(client, item_ids)
            consents = await _fetch_consents(client)
            # 🔴 수신거부 억제 목록 대조 (정본 foodplan_sms_optout) — dry_run에도 동일 적용
            suppressed = await _fetch_suppressed(client, [c["phone"] for c in consents])
            consents = [c for c in consents if _norm_phone(c["phone"]) not in suppressed]

            if dry_run:
                return {
                    "ok": True, "dry_run": True,
                    "recipient_count": len(consents),
                    "suppressed_count": len(suppressed),
                    "item_count": len(items),
                    "preview_text": _build_t1(items),   # 미리보기: 수신거부 코드 자리표시자
                }

            # ── 실발송 ──
            if _night_blocked():
                return JSONResponse(status_code=403, content={"ok": False, "error": _NIGHT_ERROR})
            if not _check_send_rate(ip):
                return JSONResponse(status_code=429, content={"ok": False, "error": "발송 한도 초과(분당 2회). 잠시 후 재시도."})
            if not SOLAPI_API_KEY or not SOLAPI_API_SECRET or not SOLAPI_FROM:
                return JSONResponse(status_code=503, content={"ok": False, "error": "Solapi 환경변수 미설정(.env)"})
            if not consents:
                return JSONResponse(status_code=400, content={"ok": False, "error": "발송 대상(동의자) 없음"})

            from_clean = SOLAPI_FROM.replace("-", "")
            # 🔴 수신거부 링크가 수신자별 토큰이라 문안을 1인 1건으로 조립한다
            messages_norm = [
                {"to": _norm_phone(c["phone"]), "from": from_clean,
                 "text": _build_t1(items, c["phone"])}
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
# 🔴 광고 문자 법규: 문안은 _ad_wrap()으로만 조립한다([별표 6] 시작부 명칭·전화 / 끝부 무료 수신거부).
#    2026-08-20 정정: 종전 "매장(042) 전화 안내로 갈음"은 유료 시내전화라 제50조⑥ 위반 소지였고
#    "비용 미부담" 명시도 없었다 → 무료 수신거부 웹링크(수신자별 토큰)로 교체.
# ══════════════════════════════════════════════════════
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


def _fans_ad_text(farmer_name: str, body: str, phone: str | None = None) -> str:
    """생산자명 강제 후 [별표 6] 규격으로 감싼다. 본문에 생산자명 없으면 헤더 라인 삽입."""
    body = (body or "").strip()
    if farmer_name and farmer_name not in body:
        body = f"{farmer_name} 할인 소식\n{body}".strip()
    return _ad_wrap(body, phone)


def _fans_sample_text(farmer_name: str) -> str:
    return _fans_ad_text(
        farmer_name,
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


def _fans_manual_text(body: str, is_ad: bool, phone: str | None = None) -> str:
    """수동 발송 문안. is_ad=True: [별표 6] 규격 / False: 매장명 헤더만(정보성 개별 안내용)."""
    body = (body or "").strip()
    if is_ad:
        return _ad_wrap(body, phone)
    if STORE_LABEL not in body:
        body = f"[{STORE_LABEL}]\n{body}".strip()
    return body


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
                ph = _norm_phone(m["phone"])
                if ph and ph not in seen:
                    seen.add(ph)
                    phones.append(ph)
            # 🔴 수신거부 억제 목록 대조 (정본 foodplan_sms_optout) — dry_run에도 동일 적용
            suppressed = await _fetch_suppressed(client, phones)
            phones = [p for p in phones if p not in suppressed]

            if dry_run:
                return {
                    "ok": True, "dry_run": True,
                    "farmer_name": farmer_name,
                    "min_purchases": min_p,
                    "buyers_1y": len(mids),
                    "sendable": len(members),
                    "unique_phones": len(phones),
                    "suppressed_count": len(suppressed),
                    "final_text": text,
                }

            # ── 실발송 ──
            if _night_blocked():
                return JSONResponse(status_code=403, content={"ok": False, "error": _NIGHT_ERROR})
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
                # 수신거부 링크가 수신자별 토큰이라 문안을 1인 1건으로 조립한다
                batch = [{"to": p, "from": from_clean,
                          "text": _fans_ad_text(farmer_name, message_body, p)} for p in phones[i:i + 50]]
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

    # 🔴 광고성이면 수신거부 억제 목록 대조 (정본 foodplan_sms_optout) — dry_run에도 동일 적용
    suppressed: set[str] = set()
    if is_ad:
        try:
            async with httpx.AsyncClient() as client:
                suppressed = await _fetch_suppressed(client, phones)
        except httpx.HTTPError as e:
            return JSONResponse(status_code=502, content={"ok": False, "error": f"수신거부 목록 조회 실패: {type(e).__name__}"})
        phones = [p for p in phones if p not in suppressed]
        if not phones:
            return JSONResponse(status_code=400, content={
                "ok": False, "error": "발송 대상 없음(전원 수신거부)", "suppressed_count": len(suppressed)})

    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "is_ad": is_ad,
            "recipients": len(phones),
            "suppressed_count": len(suppressed),
            "rejected": rejected,
            "final_text": text,
        }

    # ── 실발송 ──
    if is_ad and _night_blocked():   # 정보성(is_ad=false)은 제50조③ 대상 아님
        return JSONResponse(status_code=403, content={"ok": False, "error": _NIGHT_ERROR})
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
                # 광고성은 수신거부 링크가 수신자별 토큰이라 1인 1건으로 조립한다
                batch = [{"to": p, "from": from_clean,
                          "text": _fans_manual_text(text_in, is_ad, p)} for p in phones[i:i + 50]]
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


# ══════════════════════════════════════════════════════
# 수신거부 (무인증 — 문자 받은 사람은 로그인 상태가 아니다)
# 🔴 [별표 6] 공통2: 전송에 이용된 연락처 외의 정보를 요구하면 안 된다 → 토큰 하나만 받는다.
# 정본은 foodplan_sms_optout. 원천(consents/members) 갱신은 부수이며 실패해도 수신거부는 성립한다.
# ══════════════════════════════════════════════════════
async def _revoke_sources(client: httpx.AsyncClient, phone: str) -> dict:
    """원천 테이블 부수 갱신. 표기가 서로 달라(consents=숫자만, members=하이픈) 후보를 모두 대조.
    🔴 실패해도 예외를 올리지 않는다 — 부수 갱신 실패가 수신거부를 막으면 안 된다."""
    quoted = ",".join(f'"{v}"' for v in _phone_variants(phone))
    out = {"consents": False, "members": False}
    try:
        r = await _sr_patch(client, "foodplan_consents", {"phone": f"in.({quoted})", "revoked_at": "is.null"},
                            {"revoked_at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
        out["consents"] = r.status_code < 300
    except httpx.HTTPError:
        pass
    try:
        r = await _sr_patch(client, "members", {"phone": f"in.({quoted})"}, {"sms_optin": False})
        out["members"] = r.status_code < 300
    except httpx.HTTPError:
        pass
    return out


@router.get("/optout")
async def optout_check(request: Request):
    """토큰 유효성만 확인(무인증). 전화번호는 반환하지 않는다(링크 전달 시 PII 노출 방지)."""
    token = request.query_params.get("t", "")
    return {"ok": True, "valid": bool(_phone_from_token(token))}


@router.post("/optout")
async def optout_apply(request: Request):
    """수신거부 처리(무인증). body: {t}. 토큰 외 어떤 정보도 받지 않는다."""
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY or not _optout_fernet:
        return JSONResponse(status_code=503, content={"ok": False, "error": "서버 설정 미완(.env)"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "JSON 파싱 실패"})

    phone = _phone_from_token((body.get("t") or "").strip())
    if not phone:
        return JSONResponse(status_code=400, content={
            "ok": False, "error": "유효하지 않은 수신거부 링크입니다. 문자에 있는 링크를 그대로 눌러 주세요."})

    try:
        async with httpx.AsyncClient() as client:
            # ① 정본 기록 — 최초 거부 시각을 보존하기 위해 기존 행은 건드리지 않는다
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/foodplan_sms_optout",
                headers={**_sr_headers(), "Prefer": "resolution=ignore-duplicates,return=minimal"},
                params={"on_conflict": "phone"},
                json={"phone": phone, "source": "optout_link"},
            )
            r.raise_for_status()
            # ② 원천 부수 갱신 (실패 무시)
            sources = await _revoke_sources(client, phone)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"처리 실패: {type(e).__name__}"})

    return {"ok": True, "revoked": True, "sources": sources}
