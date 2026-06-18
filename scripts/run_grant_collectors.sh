#!/bin/bash
# 매일 1회 지원사업 공고 수집 — 기업마당(전국) + 사회적기업진흥원(사업공고)
# foodnet.poomasi.org 「전국 지원사업」 탭 공급 데이터.
# 크론: 0 7 * * *  (KST 매일 07:00)  ※ 서버 타임존 Asia/Seoul
set -a
source /home/haeory/poomasi/.env
set +a
cd /home/haeory/poomasi/poomasi-site-git/scripts || exit 1

echo "========== $(date '+%Y-%m-%d %H:%M:%S %Z') 수집 시작 =========="
/usr/bin/python3 fetch_bizinfo.py;          rc1=$?
/usr/bin/python3 fetch_socialenterprise.py; rc2=$?
echo "결과코드 → bizinfo=$rc1  socialenterprise=$rc2"
echo "========== $(date '+%Y-%m-%d %H:%M:%S %Z') 수집 완료 =========="
echo ""
