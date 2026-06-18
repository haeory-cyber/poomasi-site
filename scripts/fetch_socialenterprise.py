"""
fetch_socialenterprise.py — 한국사회적기업진흥원 공고 수집 → Supabase bizinfo_grants 저장

출처: https://www.socialenterprise.or.kr/homepage/bbs/board.do?bsIdx=10002&menuId=822
AJAX: POST /homepage/bbs/ajax/boardList.do (JSON 반환, 인증 불필요)

실행: python fetch_socialenterprise.py
"""

import os
import sys
import re
import datetime
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']

SE_BASE_URL  = 'https://www.socialenterprise.or.kr'
SE_AJAX_URL  = f'{SE_BASE_URL}/homepage/bbs/ajax/boardList.do'
SE_VIEW_URL  = f'{SE_BASE_URL}/homepage/bbs/boardView.do'

# 수집 파라미터 (공지사항 게시판: bsIdx=10002, menuId=822)
BS_IDX  = '10002'
MENU_ID = '822'

# 사업공고 관련 카테고리만 수집 (안내/선정결과/홍보 제외)
INCLUDE_CATEGORIES = {'사업공고', '공모', '모집'}

AUTHOR = '한국사회적기업진흥원'


def parse_posted_date(write_date: str) -> str | None:
    """'YYYY/MM/DD' 또는 'YYYY-MM-DD' → 'YYYY-MM-DD' 변환."""
    if not write_date:
        return None
    m = re.match(r'(\d{4})[/-](\d{2})[/-](\d{2})', write_date.strip())
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    return None


def build_link(b_idx: str, bs_idx: str, page: int = 1) -> str:
    """상세 페이지 절대 URL 구성."""
    return (
        f'{SE_VIEW_URL}'
        f'?bsIdx={bs_idx}&bIdx={b_idx}'
        f'&page={page}&menuId={MENU_ID}&bcIdx=0'
    )


def get_category(item: dict) -> str:
    """noticeList는 CATEGORYNAME, resultList는 CATEGORY_NAME 필드 사용 — 두 경우 모두 처리."""
    return (item.get('CATEGORYNAME') or item.get('CATEGORY_NAME') or '').strip()


def fetch_announcements(pages: int = 10) -> list:
    """지정 페이지 수만큼 수집하되 '사업공고' 카테고리만 저장. 기본 10페이지."""
    headers = {
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Content-Type':    'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer':         f'{SE_BASE_URL}/homepage/bbs/board.do?bsIdx={BS_IDX}&menuId={MENU_ID}',
    }

    result = []
    seen_b_idx = set()

    for page_no in range(1, pages + 1):
        payload = {
            'menuId':          MENU_ID,
            'bsIdx':           BS_IDX,
            'page':            str(page_no),
            'bcIdx':           '0',
            'writerCert':      '',
            'searchCondition': '',
            'searchKeyword':   '',
            'categoryAllYn':   'Y',
        }
        try:
            resp = requests.post(SE_AJAX_URL, data=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f'[ERROR] 페이지 {page_no} 수집 실패: {e}', file=sys.stderr)
            break

        if data.get('resultCode') != '0':
            print(f'[WARN] 페이지 {page_no} resultCode={data.get("resultCode")}')
            break

        # noticeList(공지 고정글) + resultList(일반 목록) 합산
        items = data.get('noticeList', []) + data.get('resultList', [])
        if not items:
            break

        page_saved = 0
        for item in items:
            b_idx = str(item.get('B_IDX', ''))
            if not b_idx or b_idx in seen_b_idx:
                continue
            seen_b_idx.add(b_idx)

            category = get_category(item)
            subject  = item.get('SUBJECT', '').strip()
            if not subject:
                continue

            # '사업공고' 카테고리만 저장 (안내·선정결과·일반공지·교육 제외)
            if category not in INCLUDE_CATEGORIES:
                print(f'  [SKIP] {category or "(없음)"} | {subject[:40]}')
                continue

            result.append({
                'title':       subject,
                'link':        build_link(b_idx, item.get('BS_IDX', BS_IDX), page_no),
                'author':      AUTHOR,
                'posted_date': parse_posted_date(item.get('WRITE_DATE', '')),
                'end_date':    None,  # 사이트에 마감일 필드 없음
            })
            page_saved += 1

        print(f'[INFO] 페이지 {page_no}: {len(items)}개 중 {page_saved}개 사업공고 저장')

        # 마지막 페이지 초과 시 중단
        pagination = data.get('paginationInfo', {})
        total_pages = int(pagination.get('totalPageCount', 1))
        if page_no >= total_pages:
            break

    return result


def save_to_supabase(announcements: list) -> None:
    if not announcements:
        print('[INFO] 저장할 공고 없음')
        return

    today = datetime.date.today().isoformat()
    rows = [
        {
            'title':       a['title'],
            'link':        a['link'],
            'author':      a['author'],
            'end_date':    a['end_date'],
            'posted_date': a['posted_date'],
            'fetched_at':  today,
        }
        for a in announcements
    ]

    # link 기준 upsert (같은 공고를 날짜 달리해서 중복 적재 방지)
    resp = requests.post(
        f'{SUPABASE_URL}/rest/v1/bizinfo_grants?on_conflict=title,fetched_at',
        json=rows,
        headers={
            'apikey':        SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type':  'application/json',
            'Prefer':        'resolution=merge-duplicates',
        },
    )

    if resp.status_code < 300:
        print(f'[OK] {len(rows)}건 저장(upsert) 완료')
    elif resp.status_code == 409:
        print(f'[WARN] 중복 공고 존재, 무시: {resp.text[:200]}')
    else:
        print(f'[ERROR] 저장 실패: {resp.status_code} {resp.text[:300]}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    print(f'[START] 한국사회적기업진흥원 공고 수집 시작 (사업공고 카테고리만)')
    announcements = fetch_announcements(pages=10)
    print(f'[INFO] 수집된 공고: {len(announcements)}건')
    save_to_supabase(announcements)
