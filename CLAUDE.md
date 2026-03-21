# 품앗이생협 홈페이지 — AI 공지사항

> 이 파일은 poomasi-site 저장소에서 작업하는 모든 AI(패미/지미/터미)가 세션 시작 시 읽는다.
> 후니님이 "여기에 기록해", "공지사항에 올려"라고 하면 이 파일에 추가할 것.

---

## 필수 규칙

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

- 2026-03-17: 후니님이 "여기에 기록해" 또는 "공지사항에 올려"라고 하면, 이 CLAUDE.md 파일에 날짜와 함께 추가할 것.
- 2026-03-18: **배포 흐름 변경** — `패미(staging push) → 지미(diff 검토·승인) → main 머지 → Cloudflare`. 패미는 staging 브랜치만, main 직접 push 금지. 지미가 최종 배포 책임.
- 2026-03-21: **배포 원칙 확정** — 지미가 최종 게이트. 후니님 지시 → poomasi-site-git에서 git pull → 백업 → 수정 → diff → "배포해" 승인 → commit → push. poomasi-site/ 폴더 사용 금지. Cloudflare Pages 자동 반영 (Netlify 아님).
- 2026-03-21: **조합원말씀 시스템 배포** — feedback.html(익명폼) + work.html 조합원말씀탭 + 자료실탭 + QR안내물/수기양식 인쇄용 + index.html 네비 링크.
- 2026-03-21: **사무국 탭 구조 개편** — 12개→6개 그룹화. 매장운영(발주/이음SMS/이벤트등록/출퇴근부), 경영관리(프로젝트/지원사업/AI경영지원실), 소통(조합원말씀/사무국공지). Supabase 키 publishable→legacy anon JWT 교체.
- 2026-03-17: **홈페이지 작업 흐름** — `미르(설계) → 패미/지미(코딩) → 지미(검증·배포) → Cloudflare`.
- 2026-03-17: **GCP(지미) 환경 구축 완료** — git, gh CLI 설치, GitHub 인증(haeory-cyber), poomasi-site 클론, SSH 키 등록(`ssh jimmy`로 접속).
- 2026-03-17: **작업 완료 시 마크다운 업데이트 필수** — 별도 지시 없어도 관련 마크다운(레슨/체크리스트/SHARED_MEMORY 등) 자동 업데이트. 중요하면 이 공지사항에도.
- 2026-03-17: **Supabase Auth 테이블 SQL 직접 수정 절대 금지** — `auth.users.encrypted_password`를 SQL `crypt()`로 수정하면 해시 파괴됨. 비밀번호 변경은 반드시 Admin API(`PUT /auth/v1/admin/users/<id>`) 사용할 것.
- 2026-03-17: **JS 배포 전 문법 검사 권장** — `node --check`로 SyntaxError 확인. 단일 `<script>` 블록 내 문법 에러 1개가 전체 기능(로그인 포함)을 마비시킴.
- 2026-03-17: **pre-commit hook 설치 필수** — GCP(지미)에는 설치 완료. git pull 안 하고 커밋하면 자동 차단됨. **패미/터미도 로컬 클론에 아래 훅을 설치할 것:**
  ```
  printf '#!/bin/bash\ngit fetch origin main --quiet 2>/dev/null\nBEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null)\nif [ "$BEHIND" -gt 0 ]; then\n  echo "BLOCKED: git pull 먼저 실행하세요 (${BEHIND}개 뒤처짐)"\n  exit 1\nfi\nexit 0\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
  ```
