#!/bin/bash
# jimmy_review.sh — 지미 배포 검토·승인 스크립트
# 사용법: bash scripts/jimmy_review.sh [approve|reject|status]

set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

ACTION="${1:-status}"

git fetch origin

case "$ACTION" in
  status)
    echo "=== staging vs main 변경사항 ==="
    git log --oneline origin/main..origin/staging
    echo ""
    echo "=== 파일 변경 통계 ==="
    git diff origin/main..origin/staging --stat
    ;;

  diff)
    echo "=== 상세 diff ==="
    git diff origin/main..origin/staging
    ;;

  approve)
    echo "=== 검토 내용 ==="
    git log --oneline origin/main..origin/staging
    git diff origin/main..origin/staging --stat
    echo ""
    echo "=== main 머지 시작 ==="
    git checkout main
    git pull origin main
    git merge origin/staging --no-ff -m "merge: staging → main (지미 검토 승인)"
    git push origin main
    echo ""
    echo "✅ 배포 완료. Cloudflare 자동 반영 대기 중."
    ;;

  reject)
    REASON="${2:-사유 없음}"
    echo "❌ 배포 거절: $REASON"
    python3 ~/poomasi/ai_bridge.py send_to_pami "배포 거절됨. 사유: $REASON. staging 브랜치 수정 후 다시 보고해줘." jimmy
    ;;

  *)
    echo "사용법: bash scripts/jimmy_review.sh [status|diff|approve|reject '사유']"
    ;;
esac
