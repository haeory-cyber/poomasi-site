# poomasi.org 방명록 + 연락처 — 설계

작성 2026-08-20 · 상태: 승인 대기

## 왜 하는가

poomasi.org에 방문자가 우리에게 닿을 수단이 하나도 없다. 실측: `index.html`은 192줄이고
생태계 카드 그리드에서 `</main>`으로 끝난다. **푸터 자체가 없다.** 이메일도 주소도 없다.

기존 `seed.poomasi.org/feedback.html`(「조합원 말씀」)이 있지만 매장 QR로 들어오는
고객 의견함이고, 홈페이지에서는 링크되지 않는다. 성격이 다르므로 재사용하지 않는다.

## 범위

1. 홈페이지 푸터 신설 (한글판 + 영문판)
2. `/guestbook.html` 신설 — 승인된 글 열람 + 작성
3. Supabase 테이블 `guestbook` + 공개 뷰
4. admin.poomasi.org에 승인 화면

### 범위 밖 (지금 만들지 않는다)

답글, 좋아요, 페이지네이션, 이메일 알림, 첨부파일. 글이 쌓이는 걸 보고 나중에 판단한다.

## ① 푸터

🔴 **한글판과 영문판의 출발점이 다르다** (26-08-20 실측으로 정정):

- `index.html` — `<footer>` **0건**. `</main>` 뒤에 새로 만든다.
- `en/index.html` — **228행에 `<footer class="si-section si-foot">` 이 이미 있다.**
  기존 푸터를 지우지 않고 그 안에 블록만 덧붙인다. 새 푸터를 또 만들면 푸터가 두 개가 된다.

기존 영문 카피("Based in Daejeon…", join.poomasi.org 링크)는 **삭제·수정하지 않는다.**
`assets/landing-hanji.css:6` 에 「원칙: 카피 불변 · 자체호스팅(외부 에셋 없음) · AA 대비」가
명시돼 있다. 영문 연락처가 join.poomasi.org 와 이메일 둘이 되지만 성격이 달라
(합류 폼 / 일반 문의) 그대로 둔다.

root 푸터는 영문판과 같은 `si-foot` 구조·클래스로 맞춘다.
한지 톤(크림 배경·먹색 텍스트) 유지.

담는 것:

| 항목 | 값 |
|---|---|
| 상호 | 품앗이소비자생활협동조합 |
| 주소 | 대전광역시 유성구 지족로 364번길 40, 105호 |
| 이메일 | haeory@poomasi.org (mailto 링크) |
| 링크 | 방명록 |

- 🔴 **전화번호는 넣지 않는다** (후니님 지시).
- 🔴 **관저점 주소를 넣지 않는다.** 폐점(26-08-07)이라 운영 매장은 지족점 단일이다.
  `business/company_info.md:58`의 서구 관저중로 주소는 옛 매장이다.
- 이메일은 난독화하지 않는다. 조호 스팸필터가 있고, 난독화는 접근성과 검색 노출
  양쪽에서 손해다. 주소가 안 보이는 것보다 스팸 몇 통이 낫다.
- 값의 정본은 `business/company_info.md`.
- 영문판(`en/index.html`)은 항목 이름만 영문("Poomasi Consumer Co-operative",
  "Address", "Contact", "Guestbook")으로 쓰고, **주소는 한글 원문을 그대로 둔다** —
  영문 음역은 정본에 없어서 지어내게 된다. 방명록 링크는 한글판과 같은
  `/guestbook.html`로 보낸다(영문 방명록은 만들지 않는다).

## ② `/guestbook.html`

poomasi.org 안에 둔다(별도 서브도메인 아님). 위쪽 = 승인된 글 목록, 아래쪽 = 작성 폼.

**입력 필드**

| 필드 | 필수 | 공개 |
|---|---|---|
| 이름 | O | O |
| 이메일 | O | **X — 절대 노출 안 함** |
| 내용 | O | O |

폼에 한 줄 고지: "이메일은 공개되지 않으며, 답장이 필요할 때만 씁니다."

**제출 후**: "확인 후 게시됩니다" 안내. 바로 뜨지 않는다는 걸 분명히 말한다.

**목록**: 승인된 글을 `published_at` 최신순으로 **전부** 보여준다. 초기에는 글이 적어
페이지네이션이 필요 없다. 글이 쌓여 화면이 길어지면 그때 판단한다.
글이 하나도 없을 때는 "첫 글을 남겨주세요" 안내를 띄운다.

**라이브러리: 쓰지 않는다** (26-08-20 정정). 방명록이 하는 일은 REST 호출 두 개
(목록 GET, 등록 POST)뿐이라 `fetch` 로 충분하다. supabase-js 는 207KB이고,
`landing-hanji.css:6` 의 「자체호스팅(외부 에셋 없음)」 원칙에는 의존성 0이 더 부합한다.

- 기존 `feedback.html` 은 jsdelivr CDN 을 쓰지만 **따라하지 않는다.**
- POST 에 `Prefer: return=representation` 을 넣지 마라. SELECT 권한을 요구해서 401 이 난다.

## ③ 데이터 — Supabase

**테이블 `guestbook`**

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid PK | |
| created_at | timestamptz | 기본값 now() |
| name | text NOT NULL | 공개 |
| email | text NOT NULL | **비공개** |
| body | text NOT NULL | 공개 |
| status | text NOT NULL | `pending` / `published` / `rejected`, 기본값 `pending` |
| published_at | timestamptz NULL | 승인 시각 |

**열람 통제 — 이 설계의 핵심**

이메일이 필수라 개인정보가 들어온다. 화면에서 감추는 방식으로는 부족하다 —
anon이 테이블을 직접 SELECT하면 컬럼이 다 보이기 때문이다. 그래서:

- **anon은 `guestbook` 테이블을 SELECT할 수 없다.** INSERT만 허용.
- 공개 읽기는 뷰 `guestbook_public`으로만 한다.
  `select id, name, body, published_at from guestbook where status='published'`
  — **email 컬럼이 뷰에 아예 없다.**
- 원본 테이블 SELECT는 service_role만.

- **anon INSERT 는 `status='pending' and published_at is null` 인 행만 허용**한다
  (26-08-20 추가). 이 조건이 없으면 방문자가 `status:"published"` 를 직접 실어 보내
  승인 절차를 건너뛸 수 있다.

즉 승인 전 글도, 이메일도, 데이터베이스 밖으로 나가지 않는다.

**검증 게이트 — 실측 완료 (26-08-20, anon 키로 직접 확인)**

| 시도 | 결과 |
|---|---|
| `guestbook` 직접 SELECT | 401 `permission denied for table guestbook` |
| `guestbook_public` 에서 email 요청 | 400 `column ... does not exist` |
| `status:"published"` 로 우회 INSERT | 401 RLS violation |
| anon UPDATE 로 승인 시도 | 401 `permission denied` |
| anon DELETE | 401 `permission denied` |
| 공개 뷰 SELECT (pending 행 존재 시) | 200 `[]` — 안 새어나옴 |

열람·승인·삭제 어느 쪽으로도 anon 이 넘지 못한다.

## ④ 승인 — admin.poomasi.org

기존 관리자 대시보드(Basic Auth 이미 적용)에 방명록 섹션을 붙인다. 새 관리도구를
만들지 않는다.

- `GET /api/guestbook?status=pending` — 대기 목록 (이메일 포함, 관리자만 봄)
- `POST /api/guestbook/<id>/publish` — 승인, `published_at` 기록
- `POST /api/guestbook/<id>/reject` — 거절

`traffic.html`·`routing.html`과 같은 자리에 링크한다.

## ⑤ 봇 대응

poomasi.org 페이지뷰의 **81.4%가 봇 추정**이다(26-08-20 Cloudflare 실측, 30일).
가정이 아니라 측정값이다.

- 허니팟 필드(사람 눈에 안 보이는 입력란) — 채워져 오면 조용히 버린다
- 최소 작성 시간(폼 로드 후 3초 미만 제출은 거부)
- 이 둘은 **화면 노출을 막는 장치가 아니다.** 어차피 전부 승인 대기로 들어가므로
  노출 위험은 이미 0이다. 목적은 **승인함이 스팸으로 넘쳐 사람이 못 쓰게 되는 것**을 막는 것.

캡차는 넣지 않는다. 방문자 수 대비 과하다.

## 작업 순서

1. Supabase 테이블·뷰·RLS 생성 → anon 키로 열람 통제 실측
2. `assets/`에 supabase-js 자체호스팅
3. `/guestbook.html` 작성
4. 푸터 추가 (한글·영문) — 🔴 HTML 수정 전 `.bak_20260820` 백업, `HOMEPAGE_CHANGELOG.md` 기록
5. admin 대시보드 승인 화면
6. 배포 — **배달 담당**. 지미가 직접 배포하지 않는다

## 참고

- 사이트 정본: `poomasi-site-git` (GitHub Pages + CF CDN)
- 회사 정보 정본: `business/company_info.md`
- 관저점 폐점: 메모리 `project_gwanjeo_closed`
- 자체호스팅 원칙: 메모리 `lesson_selfhost_critical_frontend_libs`
- 배포 담당: 메모리 `feedback_deploy_only_by_baedal`
