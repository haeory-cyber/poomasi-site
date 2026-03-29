"""
fetch_bizinfo.py — 기업마당 공고 수집 → Supabase bizinfo_grants 저장
실행: python fetch_bizinfo.py
조건: 중앙부처 + 대전 대상 공고만 저장
"""

import os
import sys
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import requests

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']
BIZINFO_KEY  = os.environ['BIZINFO_KEY']

BIZINFO_KEYWORDS = [
    '협동조합', '사회적경제', '소셜벤처', '로컬푸드', '탄소중립',
    '제로웨이스트', '무포장', '직거래', '친환경', '사회적기업',
    '공동체', '농촌', '먹거리',
    '소상공인', '중소기업', '중소벤처', '자활', '마을기업',
    '협동', '생협', '생활협동조합', '농업법인', '영농조합',
    '지역경제', '지역상권', '골목상권', '전통시장',
]

EXCLUDE_REGIONS = [
    '경기', '충청', '충남', '충북', '전라', '전북', '전남',
    '경상', '경북', '경남', '강원', '제주', '인천', '부산',
    '대구', '광주', '울산', '세종', '서울',
]


def is_relevant_region(author: str) -> bool:
    """중앙부처 또는 대전만 허용."""
    if '대전' in author:
        return True
    return not any(k in author for k in EXCLUDE_REGIONS)


def fix_link(url: str) -> str:
    if not url:
        return ''
    if url.startswith('http'):
        return url
    return 'https://www.bizinfo.go.kr' + url


def fetch_announcements(num: int = 30) -> list:
    url = (
        'https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do'
        f'?crtfcKey={BIZINFO_KEY}&numOfRows=100&pageNo=1'
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
    except Exception as e:
        print(f'[ERROR] bizinfo API 호출 실패: {e}', file=sys.stderr)
        return []

    root  = ET.fromstring(raw)
    items = root.findall('.//item')

    result = []
    for item in items:
        def txt(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ''

        author = txt('author')
        if not is_relevant_region(author):
            continue

        title = txt('title')
        if not any(kw in title for kw in BIZINFO_KEYWORDS):
            continue

        result.append({
            'title':    title,
            'link':     fix_link(txt('pblancUrl')),
            'author':   author,
            'end_date': txt('reqstEndDe') or None,
        })
        if len(result) >= num:
            break

    return result


def save_to_supabase(announcements: list) -> None:
    if not announcements:
        print('[INFO] 저장할 공고 없음')
        return

    today = datetime.date.today().isoformat()
    rows  = [
        {
            'title':      a['title'],
            'link':       a['link'] or None,
            'author':     a['author'] or None,
            'end_date':   a['end_date'],
            'fetched_at': today,
        }
        for a in announcements
    ]

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
        print(f'[ERROR] 저장 실패: {resp.status_code} {resp.text[:200]}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    announcements = fetch_announcements()
    print(f'[INFO] 수집된 공고: {len(announcements)}건')
    save_to_supabase(announcements)
