# 품앗이생협 홈페이지 — AI 공지사항

> 이 파일은 poomasi-site 저장소에서 작업하는 모든 AI(패미/지미/터미)가 세션 시작 시 읽는다.
> 후니님이 "여기에 기록해", "공지사항에 올려"라고 하면 이 파일에 추가할 것.

---

## 필수 규칙

### 🔴 사이트 정체성 — 절대 헷갈리지 말 것 (사고 2회)
- **`index.html`** = poomasi.org = **품아이 페이지** (메인)
- **`seed/index.html`** = seed.poomasi.org = **품앗이생협 본체** (옮겨짐, 1878줄, `<title>로컬의 반격 — 품앗이소비자생활협동조합`)
- **⛔ `seed/index.html`은 root에서 sync 금지** — 사고 2회 (2026-04-02, 2026-04-06). 상세: `seed/INCIDENT_20260404.md`
- 다른 `seed/*.html` (work, store 등 23개)은 root와 sync **OK** (같은 내용이어야 함)
- 자동 차단: `seed/index.html`은 첫 10줄에 `@PROTECTED-IDENTITY` 마커 + `<title>`에 "품앗이소비자생활협동조합" + `root/index.html`과 다름. 셋 다 검사하는 pre-commit hook이 박혀있음.
- "생협 페이지 수정해" 지시 받으면 → **`seed/index.html`** (root 아님!)
- "메인/홈/품아이" 지시 받으면 → **`index.html`**

### 작업 전
- **`git pull` 먼저** — 항상 최신 파일 기준으로 작업할 것. sida_work/ 파일로 작업 금지.
- **수정 전 백업 필수** — `파일명.bak_YYYYMMDD`

### 작업 중
- 읽기/조사/테스트 → **직접 해** (후니님한테 떠넘기지 마)
- 파일 수정/배포 → **확인받고 해**
- 한 건씩 수정 → 저장 → 확인 → 다음 건 (한꺼번에 하지 말 것)

### 작업 후 (2026-03-18 변경)
- **패미는 `staging` 브랜치에만 push** — `main`에 직접 push 절대 금지
- 작업 완료 후 지미에게 보고: `python3 ~/poomasi/ai_bridge.py send_to_pami "검토 요청: [작업내용]" pami` → 반대로 지미에게 보낼 것
- **지미가 diff 검토 후 main 머지** — `bash scripts/jimmy_review.sh approve`
- `scheduler.py`, `netlify_deploy.py`, `netforce.py` 실행 절대 금지

### 패미 → 지미 검토 요청 방법
```bash
# 1. staging에 push
git push origin staging

# 2. 지미에게 통보 (GCP MCP run_cmd 사용)
python3 ~/poomasi/ai_bridge.py record_result staging-ready "work.html 발주탭 수정 완료. 검토 요청." pami
```

---

## 공지사항

- 2026-07-23: **진흥원 공고 마감일 자동 추출** — `scripts/fetch_socialenterprise.py`에 제목 패턴("~7.10." 등) 기반 `end_date` 추출 추가(외부 요청 추가 없음). 당일 수집 19건 중 15건, 과거 미기재 778건 중 598건 백필 완료. 마감일이 첨부 HWP·포스터에만 있는 공고(~25%)는 여전히 null.
- 2026-07-22: **마감결산 열람 제한 — closing-view 로그인 게이트 + daily_settlement/staff_data SELECT 정책 교체**. `seed/closing-view.html`에 사무국 로그인 게이트 추가(커밋 `be05105`, store.html 인증 패턴). Supabase 정책 `daily_settlement_read`·`staff_data_read` = `is_store_admin() OR 최근 14일`(각각 date·created_at 기준) — 전체 열람은 store_admins 3계정만, 직원용 closing.html(불러오기·저장반환)과 발주봇은 14일 창 안이라 무변경 동작(실측 검증 완료). INSERT/UPDATE는 anon 유지(직원 입력). 6/16 공지의 "직원용 페이지는 로그인 없이 anon 저장"은 유효하되 읽기는 이 범위로 좁혀짐.
- 2026-06-18: **마감결산 개편 — 준비금 두 돈통 검산·현금/현금영수증 분리·모바일 권종칸**. 🔴비즈니스 룰 변경(6/16 룰 일부 대체): ①준비금=포스현금돈통+보관돈통 권종 실측 합(★50만 고정 폐기), 검산=두 돈통 합−50만(불일치=과부족 경고), 기존 매출검산 제거 ②포스현금매출=현금+현금영수증(포스기 표기 그대로 입력, 합이 총액) ③권종 입력칸 type=number→text·폰 1열(스피너 제거·확대, 입력 잘림 해결). `daily_settlement`에 `pos_cash`·`pos_cash_receipt` 컬럼 추가, `denom`은 `{pos:{},store:{}}` 구조. 구데이터 하위호환. 3파일(closing/closing-view/store) 연동, 커밋 `544dde5`. 배포 `bash infra/deploy-seed.sh`. 사무국탭은 로그인 게이트라 후니님 사무국 로그인 확인 권장.
- 2026-06-16: **매장 일일 마감결산 앱 배포** — `seed/closing.html`(직원용 입력, 모바일·매장PC) + `seed/closing-view.html?store=X&date=Y`(저장된 결산서 조회·인쇄) + `seed/store.html` 「일일결산」 사무국 탭 + Supabase `daily_settlement` 테이블. seed 변경이라 배포는 `bash infra/deploy-seed.sh`. 🔴비즈니스 룰: 순수현금=포스현금−기타현금−손익금 / 손익금=택배요금·잔돈기부 등 포스 출금(수동) / 준비금 항상 50만원 고정 / 검산=(실물현금−50만)−순수현금. 직원용 페이지는 로그인 없이 anon 저장(출퇴근앱과 동일).
- 2026-04-08: **매장 가격태그 QR 404 복구 — Cloudflare Page Rule로 해결** — `poomasi.org/tags.html*` → `https://seed.poomasi.org/tags.html$1` (301, 쿼리 `$1` 보존). Page Rules 슬롯 2/3 사용. 코드/배포 0건, DNS 0건, 대시보드 설정만. 배경: 4/7 seed 완전 분리 때 root `tags.html` 삭제로 매장 QR이 죽음. **진단 3회 헛다리(`_redirects` 부활 2회+매장 재인쇄 제안)로 후니님 신뢰 철회 사건.** origin=GitHub Pages라 `_redirects` 미지원 사실 미확인이 원인. 상세: `~/_shared_ai/lessons/errors/20260408_tags_qr_404_진단헛다리_page_rule.md`.
- 2026-03-26: **웹 지미 개통** — jimmy.poomasi.org에서 폰으로 지미와 실시간 채팅. annual_report.html AI섹션 10번 카드 추가, notices.json 공지 추가.
- 2026-03-21: **배포 원칙 확정** — 지미가 최종 게이트. 후니님 지시 → poomasi-site-git에서 git pull → 백업 → 수정 → diff → "배포해" 승인 → commit → push. poomasi-site/ 폴더 사용 금지. **origin 호스팅 = GitHub Pages** (앞단 Cloudflare CDN proxied). ⚠️ **`_redirects` / `netlify.toml` 미지원** — URL 구조 긴급 수정은 Cloudflare 대시보드 Page Rules로. (2026-04-08 정정: 이전에 "Cloudflare Pages 자동 반영"으로 잘못 기재되어 매장 tags.html 404 사고 3회 헛다리의 원인이 되었음. 상세: `lessons/errors/20260408_tags_qr_404_진단헛다리_page_rule.md`)
- 2026-03-21: **조합원말씀 시스템 배포** — feedback.html(익명폼) + work.html 조합원말씀탭 + 자료실탭 + QR안내물/수기양식 인쇄용 + index.html 네비 링크.
- 2026-03-21: **사무국 탭 구조 개편** — 12개→6개 그룹화. 매장운영(발주/이음SMS/이벤트등록/출퇴근부), 경영관리(프로젝트/지원사업/AI경영지원실), 소통(조합원말씀/사무국공지). Supabase 키 publishable→legacy anon JWT 교체.
- 2026-03-18: **배포 흐름 변경** — `패미(staging push) → 지미(diff 검토·승인) → main 머지 → Cloudflare`. 패미는 staging 브랜치만, main 직접 push 금지. 지미가 최종 배포 책임.
- 2026-03-17: 후니님이 "여기에 기록해" 또는 "공지사항에 올려"라고 하면, 이 CLAUDE.md 파일에 날짜와 함께 추가할 것.
- 2026-03-17: **홈페이지 작업 흐름** — `미르(설계) → 패미/지미(코딩) → 지미(검증·배포) → Cloudflare`.
- 2026-03-17: **GCP(지미) 환경 구축 완료** — git, gh CLI 설치, GitHub 인증(haeory-cyber), poomasi-site 클론, SSH 키 등록(`ssh jimmy`로 접속).
- 2026-03-17: **작업 완료 시 마크다운 업데이트 필수** — 별도 지시 없어도 관련 마크다운(레슨/체크리스트/SHARED_MEMORY 등) 자동 업데이트. 중요하면 이 공지사항에도.
- 2026-03-17: **Supabase Auth 테이블 SQL 직접 수정 절대 금지** — `auth.users.encrypted_password`를 SQL `crypt()`로 수정하면 해시 파괴됨. 비밀번호 변경은 반드시 Admin API(`PUT /auth/v1/admin/users/<id>`) 사용할 것.
- 2026-03-17: **JS 배포 전 문법 검사 권장** — `node --check`로 SyntaxError 확인. 단일 `<script>` 블록 내 문법 에러 1개가 전체 기능(로그인 포함)을 마비시킴.
- 2026-03-17: **pre-commit hook 설치 필수** — GCP(지미)에는 설치 완료. git pull 안 하고 커밋하면 자동 차단됨. **패미/터미도 로컬 클론에 아래 훅을 설치할 것:**
  ```
  printf '#!/bin/bash\ngit fetch origin main --quiet 2>/dev/null\nBEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null)\nif [ "$BEHIND" -gt 0 ]; then\n  echo "BLOCKED: git pull 먼저 실행하세요 (${BEHIND}개 뒤처짐)"\n  exit 1\nfi\nexit 0\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
  ```
