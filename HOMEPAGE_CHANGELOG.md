# 홈페이지 수정 이력

> **작업 규칙**: HTML 파일 수정 전 반드시 백업 먼저 (`파일명.bak_YYYYMMDD`). 백업 후 이 파일에 기록.
> 백업 목록 상세: [BACKUP_LOG.md](BACKUP_LOG.md)

---

## 현재 홈페이지 구조

### 파일 목록
| 파일 | 역할 | URL |
|------|------|-----|
| `index.html` | 메인 홈페이지 | poomasi.org |
| `market.html` | 직매장 페이지 | poomasi.org/market.html |
| `display.html` | 매장 TV 전광판 (자동 갱신) | poomasi.org/display.html |
| `work.html` | 경영 관리 보드 (로그인 필요) | poomasi.org/work.html |
| `annual_report.html` | 애뉴얼 리포트 v2.2 (2026-03-14 신규) | poomasi.org/annual_report.html |
| `poomasi_philosophy.html` | 철학·선언 페이지 | poomasi.org/poomasi_philosophy.html |
| `join.html` | 조합원 가입 페이지 | poomasi.org/join.html |
| `workshop.html` | 워크숍 페이지 | poomasi.org/workshop.html |

### index.html 주요 섹션 (위→아래 순서)
1. **nav** — 로고 + 링크 (광장/작업실/철학/가입/푸드마일리지/리포트)
2. **hero** — 메인 타이틀
3. **이벤트 티커** — Supabase events 테이블 실시간 (2026-03-14 추가)
4. **stats-row** — 핵심 숫자 4개
5. **lab-strip** — POS 자동 산출 데이터 (scheduler 자동 갱신)
6. **doors-section** — 4개 도어 (2×2 그리드)
   - 01 MARKET · 광장
   - 02 WORKSHOP · 작업실
   - 03 poomasi_philosophy.html
   - 04 annual_report.html ← 2026-03-14 추가
7. **푸드마일리지 섹션** (`#foodmileage`) — SVG 동심원 + 숫자 대비 ← 2026-03-14 추가
8. **data-sovereignty** — 데이터 주권 섹션
9. **footer**

---

## 수정 이력

### 2026-03-18

#### display.html — Supabase 이벤트 슬라이드 연동
**백업**: `display.html.bak_20260318`
**배포**: commit `2bf7bef` → Cloudflare Pages 자동 반영

| 항목 | 변경 내용 |
|------|-----------|
| 기존 | 정적 슬라이드 7개 (POS 데이터만 표시) |
| 변경 | 로드 시 Supabase `events` 테이블 fetch → 활성 이벤트를 오프닝 직후 동적 슬라이드로 삽입 |
| 이벤트 등록 방법 1 | work.html → 이벤트 등록 탭에서 직접 등록 |
| 이벤트 등록 방법 2 | 패미가 Supabase SQL로 직접 INSERT |
| scheduler.py | `generate_display_html()` 템플릿에 동일 CSS + JS 반영 (스케줄러 덮어써도 유지) |
| 첫 등록 이벤트 | id=10, 공지, 상시: `온누리상품권 결제 가능합니다 — 지류·카드형 즉시 / QR은 4월 초 예정` |

---

### 2026-03-15

#### work.html — 이음SMS 탭 전면 개편
**백업**: `work.html.bak_20260315`

| 항목 | 변경 내용 |
|------|-----------|
| 기존 | 조합원 ID 수동 입력 → sms_history 저장만 (실제 발송 없음) |
| 변경 | 농가-단골 문자 실제 발송 (Solapi API 연동) |
| 1단계 | 농가 선택 — Supabase `farmer_members`에서 농가명 목록 fetch, 검색 필터 포함 |
| 2단계 | 단골 조회 — 구매횟수 상위 30명 체크리스트. `farmer_members` + `members` 테이블 join으로 전화번호 표시. 전체선택/해제 버튼 |
| 3단계 | 문자 작성·발송 — Solapi `send-many` API, HMAC-SHA256 서명 (SubtleCrypto), 발송 결과 표시 |
| 발신번호 기본값 | `0427160019` (042-716-0019) |
| API 설정 | ⚙ Solapi API 설정 접이식 패널 (API Key / Secret / 발신번호) — localStorage 저장 |
| 배포 | commit `b75bbf4` → Cloudflare Pages 자동 반영 |

#### work.html — 헤더 겹침 수정
| 항목 | 변경 내용 |
|------|-----------|
| `.sticky-nav` | `position: sticky` → `position: fixed; left:0; right:0` (데스크탑도 고정) |
| `.tab-content` | `padding-top: 112px` 추가 (헤더+탭바 높이 확보) |
| `.app-logo` | `flex-direction: column; gap: 2px` — "시다워크" / "품앗이생협 경영판" 위아래 정렬, 겹침 제거 |
| 모바일 미디어쿼리 | 중복 `position: fixed` / `padding-top` 선언 제거 |
| 배포 | commit `86ff3af` → Cloudflare Pages 자동 반영 |

---

### 2026-03-14

#### index.html
**백업**: `index.html.bak_20260314` (수정 전 원본)

| 항목 | 변경 내용 |
|------|-----------|
| 이벤트 티커 | stats-row 위에 티커 바 추가. Supabase `events` 테이블에서 실시간 fetch. 이벤트 없으면 "포장하지 않습니다 · 비닐도, 과장도" 기본값 표시 |
| lab-strip 중복 | 03.07 / 03.10 두 블록 연속 → 03.10 블록 삭제, 03.07(55,575kg) 유지 |

#### annual_report.html (신규 생성)
**백업 없음** (신규 파일)

| 항목 | 내용 |
|------|------|
| 기반 | v2.0 HTML 구조 + v2.2 콘텐츠 전면 반영 |
| 표지 | 4번째 stat "27km 평균 푸드마일리지" (기존 "0개 중간플랫폼" 대체) |
| 3-1장 | 푸드마일리지 분석 (신규): 27km vs 200km 비교, KPI 4종, 로컬/비로컬 표, 조합원 거주 바 차트, TOP5 비로컬 표, 전환 시뮬레이션 |
| 4장 | 탄소저감: DEFRA 2021 방법론 업데이트, 유통탄소 분석 표 추가 |
| 6장 | AI 자동화 (신규): 6개 카드 (MCP·POS파이프라인·전광판·탄소계산·영수증·아침브리핑) + 파이프라인 플로우 |
| footer | `ver 2.2 · 2026. 3. 14.` + `← 홈으로 돌아가기` |
| 총 분량 | 1,004줄, 60,272 bytes |

#### Supabase — events 테이블 신규 생성
```sql
CREATE TABLE events (
  id bigserial PRIMARY KEY,
  type text NOT NULL,          -- 신규입점 / 공동구매 / 할인 / 공지
  content text NOT NULL,
  expires_at date DEFAULT NULL,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);
-- RLS: anon SELECT / INSERT / UPDATE 허용
```
- 테스트 데이터: id=1, 신규입점, "테스트 — 홍성 유기농 토마토", expires_at=2099-12-31

#### work.html — 이벤트 등록 탭 추가
| 항목 | 내용 |
|------|------|
| 탭 위치 | 기존 탭(오늘의경영/액션플랜/이음SMS/배포) 맨 오른쪽에 추가 |
| 유형 버튼 | 신규입점 / 공동구매 / 할인 / 공지 |
| 기간 버튼 | 오늘만 / 이번주 / 이번달 / 상시 |
| 기능 | INSERT → events 테이블, 활성 이벤트 목록 표시, ✕ 버튼으로 is_active=false |

---

### 2026-03-13

#### index.html
**백업**: `index.html.bak_github_origin` (GitHub main sha: 3ad25e40, 진짜 원본)
**백업**: `index.html.bak_20260313` (수정 후 — 원본 아님 ⚠️)

| 항목 | 변경 내용 |
|------|-----------|
| stats 업데이트 | 조합원 209명 → **519곳**, 거래농가 96명 → **9.51억** |
| doors-grid | `repeat(3,1fr)` → `repeat(2,1fr)` (2×2 레이아웃) |
| 도어 04 추가 | `annual_report.html` 링크 — "로컬의 반격 2023–2025" |
| nav 링크 추가 | 푸드마일리지 (`#foodmileage`), 리포트 (`annual_report.html`) |
| 푸드마일리지 섹션 | `#foodmileage` 신규 추가 — SVG 동심원 지도(B안) + 숫자 대비(A안) 병합 |

**푸드마일리지 섹션 핵심 수치**
- 평균 거리: **27.1km** (품앗이) vs **200km** (전국 평균)
- 로컬 비율: 81% (품목 수 기준)
- 탄소저감: -40.6%

---

### 2026-03-12

#### market.html
**백업 없음**

| 항목 | 변경 내용 |
|------|-----------|
| gallery alt/caption | 9곳 수정 — "벌크 과일" 등 부정확한 텍스트 → 실제 코너명으로 교체 |

---

## 홈페이지 수정 시 체크리스트

- [ ] 백업 파일 생성 (`파일명.bak_YYYYMMDD`) — **Edit 호출 전**
- [ ] BACKUP_LOG.md 에 백업 기록
- [ ] 수정 후 이 파일(HOMEPAGE_CHANGELOG.md)에 변경사항 기록
- [ ] 배포: `github_deploy.py`의 `github_push()` 함수 사용
- [ ] RESULT.json 업데이트

## 배포 방법

### 표준 배포 (deploy_git.py) — 권장
```
# 전체 배포
py -3.14 deploy_git.py

# 단일 파일 배포
py -3.14 deploy_git.py work.html

# 배포 전 확인 (dry-run)
py -3.14 deploy_git.py --dry-run
```
- 동작: C:\Users\품앗이생협\Desktop\poomasi-site\ 에 clone/pull → 파일 복사 → git push
- 인증: gh CLI keyring (토큰 하드코딩 없음)
- 대상: index.html, display.html, work.html, market.html, join.html, poomasi_philosophy.html, workshop.html, annual_report.html, images/

### 폴백 (github_deploy.py) — REST API 방식
```python
from github_deploy import github_push
with open('index.html', 'rb') as f:
    code, _ = github_push('index.html', f.read(), '커밋 메시지')
print(code)  # 200=업데이트, 201=신규
```
- deploy_git.py 실패 시에만 사용

Cloudflare Pages가 GitHub push 감지 → 자동 빌드 → poomasi.org 반영 (1~2분)
