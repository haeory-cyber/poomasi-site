# infra/ — seed.poomasi.org 인프라 코드 봉인

> seed.poomasi.org를 띄우는 데 필요한 인프라 코드와 설정을 git으로 관리하는 폴더.
> 사고가 나도 여기서 복구할 수 있도록 만든 안전금고.
>
> 봉인 이력:
> - 2026-04-06 1단계: 그동안 git 밖이던 seed_server.py 등을 정식 편입.
> - 2026-04-06 2단계: working tree와 라이브 서빙 디렉터리 분리. 심볼릭 링크 릴리즈 방식 도입 (`seed-live` → `seed-releases/v_*`). 무재시작 atomic 배포.

---

## 폴더 구조

```
infra/
├── README.md                  # 이 파일
├── seed_server.py             # FastAPI 정적 서버 본체 (라이브 코드)
├── deploy-seed.sh             # atomic 배포 스크립트 (Phase 2)
├── systemd/
│   └── seed-server.service    # systemd 서비스 정의 사본
├── .env.example               # 환경변수 키 이름만 (값 X)
└── .snapshots/                # 변경 직전 스냅샷 (git 밖, .gitignore로 제외)
```

> `.env` 파일 자체(키 값 포함)는 절대 이 폴더에 두지 않음. 위치는 `/home/haeory/poomasi/.env` (권한 600).

---

## 라이브 동작 방식

1. **systemd**가 부팅 시 `seed-server.service`를 띄움
2. 서비스가 `/home/haeory/poomasi/seed_server.py`를 실행 → **이건 심볼릭 링크**
3. 실제 파일은 `poomasi-site-git/infra/seed_server.py` (= 이 폴더 안)
4. seed_server.py는 FastAPI로 포트 8030에 떠서, **`/home/haeory/poomasi/seed-live` 심볼릭 링크**가 가리키는 디렉터리를 정적 파일로 서빙
5. `seed-live`는 `/home/haeory/poomasi/seed-releases/v_TIMESTAMP/` 중 하나를 가리킴 (배포 시 atomic 스왑)
6. Cloudflare Tunnel(`/home/haeory/.cloudflared/config.yml`)이 `seed.poomasi.org` → `localhost:8030`으로 연결

```
[조합원] → [Cloudflare] → [터널] → [localhost:8030 = seed_server.py]
                                          ↓ STATIC_DIR
                                  [seed-live → seed-releases/v_TIMESTAMP/*.html]
```

**핵심: git working tree(`poomasi-site-git/seed/`)와 라이브 서빙 디렉터리(`seed-releases/v_*/`)는 완전히 분리됨.** working tree에서 자유롭게 편집해도 라이브에는 전혀 영향 없음. 배포는 `infra/deploy-seed.sh` 한 번으로 atomic 스왑.

---

## 수정 → 배포 절차

### 정적 콘텐츠(seed/*.html, *.js 등) 수정 시

1. `poomasi-site-git/seed/` 안의 파일을 자유롭게 편집 (작업 트리, 라이브 영향 0)
2. `bash infra/deploy-seed.sh --dry-run` 으로 시뮬레이션 (선택)
3. `bash infra/deploy-seed.sh` — 새 릴리즈 디렉터리 생성 → atomic 심볼릭 링크 스왑 → live health check
4. 실패 시 자동 롤백
5. 수동 롤백: `bash infra/deploy-seed.sh --rollback`
6. 옛 릴리즈는 최근 5개만 자동 보관

### seed_server.py 수정 시

1. `infra/seed_server.py` 직접 편집 (이 폴더 안에서)
2. `infra/.snapshots/seed_server.py.YYYYMMDD` 백업
3. `python3 -c "import ast; ast.parse(open('infra/seed_server.py').read())"` 로 문법 검사
4. `git add infra/seed_server.py` → 커밋 → 푸시
5. `sudo systemctl restart seed-server` (다운타임 1~2초)
6. `curl http://localhost:8030/api/health` 로 정상 확인
7. `curl https://seed.poomasi.org/store.html` 로 라이브 확인

### seed-server.service (systemd unit) 수정 시

1. `infra/systemd/seed-server.service` 편집
2. `sudo cp infra/systemd/seed-server.service /etc/systemd/system/seed-server.service`
3. `sudo systemctl daemon-reload`
4. `sudo systemctl restart seed-server`
5. 검증

### .env 수정 시 (값 변경)

1. `/home/haeory/poomasi/.env` 직접 편집 (이 폴더 안 X)
2. `sudo systemctl restart seed-server`
3. **절대 git에 commit 금지** (`.gitignore`로 차단되어 있음)

---

## 사고 시 복구 절차

### 케이스 1: seed_server.py가 망가졌을 때

```bash
cd /home/haeory/poomasi/poomasi-site-git
git log --oneline infra/seed_server.py     # 정상이었던 커밋 찾기
git checkout <COMMIT_HASH> -- infra/seed_server.py
sudo systemctl restart seed-server
```

### 케이스 2: 심볼릭 링크가 깨졌을 때

```bash
cd /home/haeory/poomasi
rm -f seed_server.py
ln -s poomasi-site-git/infra/seed_server.py seed_server.py
sudo systemctl restart seed-server
```

### 케이스 3: 서비스 자체가 사라졌을 때

```bash
sudo cp /home/haeory/poomasi/poomasi-site-git/infra/systemd/seed-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable seed-server
sudo systemctl start seed-server
```

### 케이스 4: .env가 사라졌을 때

```bash
cp infra/.env.example /home/haeory/poomasi/.env
chmod 600 /home/haeory/poomasi/.env
# 21개 키에 실제 값 채워넣기 (다른 안전한 백업처에서 복원)
sudo systemctl restart seed-server
```

---

## 알려진 이슈 / 미해결 사항

### ✅ 라이브 디렉터리 = git working tree (Phase 2 해결)

~~`seed_server.py`의 `STATIC_DIR`은 `/home/haeory/poomasi/poomasi-site-git/seed`...~~

**해결 (2026-04-06 Phase 2)**: `STATIC_DIR`을 `/home/haeory/poomasi/seed-live` 심볼릭 링크로 변경. 작업 트리(`poomasi-site-git/seed/`)와 라이브 디렉터리(`seed-releases/v_*/`) 완전 분리. 배포는 `infra/deploy-seed.sh`로 atomic 스왑.

### 🟡 RAG 엔진 의존성 (`/home/haeory/poomasi/rag/`)

seed_server.py는 `from engine import RAGEngine`을 통해 9GB 규모의 RAG 디렉터리에 의존. 이 디렉터리는 git에 들어가기 부적합(chroma_db 797MB 등). 별도 봉인 전략이 필요하며 아직 미해결. 사고 시 RAG 디렉터리는 별도 백업에서 복원해야 함.

### 🟡 Cloudflare 터널 설정

`/home/haeory/.cloudflared/config.yml` 도 git 밖. 다음 단계에서 봉인 예정.

### 🟡 .env 21개 키의 백업

`.env`는 git에 절대 들어가면 안 되므로, 별도 안전한 저장소(예: 1Password, 암호화된 USB)에 따로 보관해야 함. 현재는 후니님이 직접 관리.

---

## 의존성

- **OS**: Linux (systemd)
- **Python**: `/home/haeory/poomasi/rag/venv/` (가상환경, RAG 엔진과 공유)
- **외부 서비스**: Cloudflare Tunnel, Supabase, (선택) Gemini API
- **방화벽**: 포트 8030은 localhost만 (Cloudflare Tunnel을 통해서만 외부 노출)

---

## 변경 이력

- **2026-04-06** — 1단계: seed_server.py를 git 밖에서 `infra/`로 이동, 심볼릭 링크로 호환성 유지. systemd unit 사본 + .env.example + 본 README 신설. PID 75696 무중단 유지, 라이브 md5 변화 없음.
- **2026-04-06** — 2단계: working tree와 라이브 분리. `seed-releases/v_TIMESTAMP/` 릴리즈 디렉터리 + `seed-live` 심볼릭 링크 도입. `STATIC_DIR` 변경. `deploy-seed.sh` 신설 (atomic 심볼릭 링크 스왑, 자동 롤백, 옛 릴리즈 자동 정리). 배포는 무재시작. 부수 — 사전 지뢰 발견: `rag/engine.py`가 `from rag.fuzzy_utils import ...`를 추가했는데 `seed_server.py`의 `sys.path`에 부모 dir이 없었음. lifespan에 부모 dir 추가로 해결.
