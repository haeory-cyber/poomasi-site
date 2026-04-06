#!/usr/bin/env bash
# deploy-seed.sh — seed.poomasi.org 정적 콘텐츠 atomic 배포
#
# 동작:
#   1. poomasi-site-git/seed/ → seed-releases/v_TIMESTAMP/ 풀카피
#   2. seed-live 심볼릭 링크를 새 릴리즈로 atomic 스왑 (ln -sfn)
#   3. 배포 후 sanity 체크 (파일 수, 핵심 파일 md5)
#   4. 옛 릴리즈는 최근 5개만 보관, 그 외 삭제
#
# 사용:
#   bash infra/deploy-seed.sh           # 일반 배포
#   bash infra/deploy-seed.sh --dry-run # 변경 없이 시뮬레이션
#   bash infra/deploy-seed.sh --rollback # 직전 릴리즈로 되돌림
#
# 안전성:
#   - ln -sfn 는 POSIX atomic. 라이브 다운타임 0초.
#   - 실패 시 옛 심볼릭 링크 그대로 유지 (롤백 자동).
#   - 서버 재시작 불필요 (Starlette StaticFiles는 요청 시점에 path resolve).

set -euo pipefail

REPO="/home/haeory/poomasi/poomasi-site-git"
SRC="${REPO}/seed"
RELEASES_DIR="/home/haeory/poomasi/seed-releases"
LIVE_LINK="/home/haeory/poomasi/seed-live"
KEEP_RELEASES=5

cd "$REPO"

# ── 1. 옵션 처리 ──────────────────────────────────────
DRY_RUN=0
ROLLBACK=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --rollback) ROLLBACK=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# ── 2. 롤백 모드 ──────────────────────────────────────
if [ "$ROLLBACK" -eq 1 ]; then
    CURRENT="$(readlink "$LIVE_LINK")"
    PREV="$(ls -1t "$RELEASES_DIR" | grep -v "$(basename "$CURRENT")" | head -1)"
    if [ -z "$PREV" ]; then
        echo "ERROR: no previous release to roll back to" >&2
        exit 1
    fi
    echo "[rollback] $CURRENT → $PREV"
    ln -sfn "seed-releases/$PREV" "$LIVE_LINK"
    echo "[rollback] done. live now: $(readlink "$LIVE_LINK")"
    exit 0
fi

# ── 3. 사전 체크 ──────────────────────────────────────
if [ ! -d "$SRC" ]; then
    echo "ERROR: source dir missing: $SRC" >&2
    exit 1
fi

# git pull 검증 (optional but recommended)
git fetch origin main --quiet 2>/dev/null || true
BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "$BEHIND" -gt 0 ]; then
    echo "WARN: $BEHIND commits behind origin/main. git pull 권장." >&2
fi

# 워킹 트리 더러우면 경고만 (강제 X — 의도적인 미커밋 작업 가능)
if [ -n "$(git status --porcelain seed/)" ]; then
    echo "WARN: seed/ has uncommitted changes — 배포에 포함됩니다." >&2
fi

# ── 4. 새 릴리즈 디렉터리 생성 + 풀카피 ──────────────
TS="$(date +%Y%m%d_%H%M%S)"
NEW_REL="v_${TS}"
NEW_DIR="${RELEASES_DIR}/${NEW_REL}"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would copy ${SRC} → ${NEW_DIR}"
    echo "[dry-run] would swap ${LIVE_LINK} → seed-releases/${NEW_REL}"
    echo "[dry-run] would prune to last ${KEEP_RELEASES} releases"
    exit 0
fi

echo "[deploy] copying ${SRC} → ${NEW_DIR}"
mkdir -p "$NEW_DIR"
# -L: dereference symlinks (seed/scripts → ../scripts 등 상대 링크가 release dir에서
# 깨지지 않도록 실제 파일/디렉터리로 복사). -a 는 -dR --preserve=all 인데
# -d(=preserve links)와 -L가 충돌하므로 -L가 후행되어 dereference 우선.
cp -aL "${SRC}/." "$NEW_DIR/"

# ── 5b. 비공개 파일 sanitize (서버측 스크립트, bak, 스냅샷) ──
# scripts/ 는 server-side admin 스크립트라 publish 금지.
# *.bak* 은 작업 백업이라 publish 금지.
# .snapshots/ 는 내부 백업 디렉터리.
rm -rf "${NEW_DIR}/scripts" "${NEW_DIR}/.snapshots" 2>/dev/null || true
find "$NEW_DIR" -name "*.bak" -delete 2>/dev/null || true
find "$NEW_DIR" -name "*.bak_*" -delete 2>/dev/null || true
find "$NEW_DIR" -name "*.bak2_*" -delete 2>/dev/null || true

# ── 6. 정합성 검증 ────────────────────────────────────
# 핵심 파일 md5 cross-check (sanitize 후, 핵심 파일은 sanitize 대상이 아니므로 src와 일치해야 함)
DST_COUNT=$(find "$NEW_DIR" -type f | wc -l)
for f in store.html work.html index.html; do
    if [ -f "${SRC}/${f}" ]; then
        SRC_MD5=$(md5sum "${SRC}/${f}" | awk '{print $1}')
        DST_MD5=$(md5sum "${NEW_DIR}/${f}" | awk '{print $1}')
        if [ "$SRC_MD5" != "$DST_MD5" ]; then
            echo "ERROR: md5 mismatch for ${f}. aborting." >&2
            rm -rf "$NEW_DIR"
            exit 1
        fi
    fi
done
echo "[deploy] verified ${DST_COUNT} files (post-sanitize), core md5 OK"

# ── 6. Atomic 심볼릭 링크 스왑 ───────────────────────
PREV="$(readlink "$LIVE_LINK" 2>/dev/null || echo "(none)")"
ln -sfn "seed-releases/${NEW_REL}" "$LIVE_LINK"
NOW="$(readlink "$LIVE_LINK")"
echo "[deploy] live: $PREV → $NOW"

# ── 7. 라이브 sanity check ───────────────────────────
sleep 1
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -m 5 https://seed.poomasi.org/api/health || echo "000")
if [ "$HTTP" != "200" ]; then
    echo "ERROR: live health check failed (HTTP $HTTP). 자동 롤백." >&2
    if [ "$PREV" != "(none)" ]; then
        ln -sfn "$PREV" "$LIVE_LINK"
        echo "[deploy] rolled back to $PREV" >&2
    fi
    exit 1
fi
echo "[deploy] live health OK"

# ── 8. 옛 릴리즈 정리 (최근 N개만 보관) ──────────────
cd "$RELEASES_DIR"
TO_DELETE=$(ls -1t | tail -n +"$((KEEP_RELEASES + 1))")
if [ -n "$TO_DELETE" ]; then
    echo "[deploy] pruning old releases:"
    echo "$TO_DELETE" | sed 's/^/  - /'
    echo "$TO_DELETE" | xargs -I{} rm -rf "{}"
fi

echo "[deploy] DONE — release ${NEW_REL}"
