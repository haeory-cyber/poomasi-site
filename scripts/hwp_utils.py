"""
hwp_utils.py — 한글과컴퓨터 HWP/HWPX 파일 읽기·쓰기 유틸리티
실행: python scripts/hwp_utils.py [read|write|replace] ...

기능:
  - HWP (바이너리) 파일 텍스트 추출  (olefile 필요)
  - HWPX (ZIP+XML) 파일 텍스트 추출  (표준 라이브러리만)
  - HWPX 파일 새로 생성              (표준 라이브러리만)
  - HWPX 파일 텍스트 치환            (표준 라이브러리만)

의존성: pip install olefile  (HWP 읽기용, HWPX만 쓸 경우 불필요)
"""

import argparse
import os
import re
import sys
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

# OWPML 네임스페이스
NS = {
    'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
    'hs': 'http://www.hancom.co.kr/hwpml/2011/section',
    'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
    'hpf': 'urn:oasis:names:tc:opendocument:xmlns:container',
}

# ET 네임스페이스 등록 (쓰기 시 접두사 유지)
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


# ─────────────────────────────────────────────
# HWP 읽기 (바이너리, olefile 필요)
# ─────────────────────────────────────────────

def read_hwp(filepath):
    """HWP(v5 바이너리) 파일에서 텍스트를 추출한다.
    olefile이 설치되어 있어야 함."""
    try:
        import olefile
    except ImportError:
        raise ImportError(
            "HWP 읽기에는 olefile이 필요합니다: pip install olefile"
        )

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filepath}")

    ole = olefile.OleFileIO(filepath)
    try:
        # PrvText: 미리보기 텍스트 (UTF-16LE)
        if ole.exists('PrvText'):
            raw = ole.openstream('PrvText').read()
            return raw.decode('utf-16-le', errors='replace').strip('\x00').strip()

        # PrvText가 없으면 BodyText 섹션들에서 추출 시도
        texts = []
        for entry in ole.listdir():
            path = '/'.join(entry)
            if path.startswith('BodyText/Section'):
                data = ole.openstream(entry).read()
                # 바이너리 레코드에서 유니코드 문자열 추출 (간이 방식)
                text = _extract_text_from_body(data)
                if text:
                    texts.append(text)
        return '\n'.join(texts) if texts else '(텍스트를 추출할 수 없습니다)'
    finally:
        ole.close()


def _extract_text_from_body(data):
    """BodyText 바이너리 레코드에서 텍스트를 간이 추출한다.
    HWP v5 레코드 구조: 태그(4byte) + 크기 + 데이터
    HWPTAG_PARA_TEXT(67) 레코드에서 UTF-16LE 문자열 추출."""
    texts = []
    pos = 0
    while pos + 4 <= len(data):
        header = int.from_bytes(data[pos:pos+4], 'little')
        tag_id = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4

        if size == 0xFFF:
            if pos + 4 > len(data):
                break
            size = int.from_bytes(data[pos:pos+4], 'little')
            pos += 4

        if pos + size > len(data):
            break

        # HWPTAG_PARA_TEXT = 67
        if tag_id == 67:
            chunk = data[pos:pos+size]
            text = _decode_para_text(chunk)
            if text:
                texts.append(text)

        pos += size
    return '\n'.join(texts)


def _decode_para_text(chunk):
    """PARA_TEXT 레코드의 UTF-16LE 바이트에서 텍스트를 추출한다.
    제어 문자(0x00~0x1F 범위의 특수 코드)를 건너뛴다."""
    chars = []
    i = 0
    while i + 1 < len(chunk):
        code = int.from_bytes(chunk[i:i+2], 'little')
        i += 2

        # HWP 인라인 제어 문자 건너뛰기
        if code < 0x20:
            # 확장 제어 문자는 추가 바이트가 있음
            if code in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                i += 14  # 인라인 확장 크기 (7 wchar = 14 bytes)
            elif code == 10:  # 줄바꿈
                chars.append('\n')
            # 나머지 제어 코드는 무시
            continue

        chars.append(chr(code))
    return ''.join(chars).strip()


# ─────────────────────────────────────────────
# HWPX 읽기 (ZIP + XML, 표준 라이브러리)
# ─────────────────────────────────────────────

def read_hwpx(filepath):
    """HWPX 파일에서 텍스트를 추출한다."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filepath}")

    texts = []
    with zipfile.ZipFile(filepath, 'r') as zf:
        # section 파일들을 순서대로 찾기
        section_files = sorted(
            [n for n in zf.namelist() if re.match(r'Contents/section\d+\.xml', n)]
        )
        if not section_files:
            # 대소문자 무시하여 재검색
            section_files = sorted(
                [n for n in zf.namelist()
                 if re.match(r'(?i)contents/section\d+\.xml', n)]
            )

        for section_file in section_files:
            with zf.open(section_file) as f:
                tree = ET.parse(f)
                root = tree.getroot()
                _extract_text_elements(root, texts)

    return '\n'.join(texts)


def _extract_text_elements(element, texts):
    """XML 요소에서 hp:t 태그의 텍스트를 재귀적으로 추출한다."""
    hp_ns = NS['hp']
    t_tag = f'{{{hp_ns}}}t'
    p_tag = f'{{{hp_ns}}}p'

    for p_elem in element.iter(p_tag):
        para_texts = []
        for t_elem in p_elem.iter(t_tag):
            if t_elem.text:
                para_texts.append(t_elem.text)
        if para_texts:
            texts.append(''.join(para_texts))


# ─────────────────────────────────────────────
# HWPX 쓰기 (ZIP + XML, 표준 라이브러리)
# ─────────────────────────────────────────────

def write_hwpx(filepath, content, title=''):
    """텍스트 내용으로 HWPX 파일을 생성한다.

    Args:
        filepath: 출력 파일 경로 (.hwpx)
        content: 문서 본문 (문자열, 줄바꿈으로 문단 구분)
        title: 문서 제목 (선택)
    """
    paragraphs = content.split('\n') if content else ['']

    # section0.xml 생성
    section_xml = _build_section_xml(paragraphs)

    # content.hpf (패키지 매니페스트)
    content_hpf = _build_content_hpf()

    # header.xml (문서 헤더)
    header_xml = _build_header_xml(title)

    # META-INF/manifest.xml
    manifest_xml = _build_manifest_xml()

    # mimetype
    mimetype = 'application/hwp+zip'

    # ZIP으로 패키징
    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
        # mimetype은 압축하지 않고 첫 번째로
        zf.writestr('mimetype', mimetype, compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/manifest.xml', manifest_xml)
        zf.writestr('Contents/content.hpf', content_hpf)
        zf.writestr('Contents/header.xml', header_xml)
        zf.writestr('Contents/section0.xml', section_xml)


def _build_section_xml(paragraphs):
    """문단 리스트로 section0.xml을 생성한다."""
    hp = NS['hp']
    hs = NS['hs']

    sec = ET.Element(f'{{{hs}}}sec')

    for idx, para_text in enumerate(paragraphs):
        p = ET.SubElement(sec, f'{{{hp}}}p')
        p.set('id', str(1000000000 + idx))
        p.set('paraPrIDRef', '0')
        p.set('styleIDRef', '0')
        p.set('pageBreak', '0')
        p.set('columnBreak', '0')
        p.set('merged', '0')

        run = ET.SubElement(p, f'{{{hp}}}run')
        run.set('charPrIDRef', '0')

        t = ET.SubElement(run, f'{{{hp}}}t')
        t.text = para_text

        # 첫 문단에 섹션 속성 추가
        if idx == 0:
            sec_pr = ET.SubElement(p, f'{{{hp}}}secPr')
            sec_pr.set('textDirection', '0')
            sec_pr.set('spaceColumns', '1134')
            sec_pr.set('tabStop', '800')
            sec_pr.set('outlineShapeIDRef', '1')

            pg = ET.SubElement(sec_pr, f'{{{hp}}}pg')
            pg.set('width', '59528')
            pg.set('height', '84188')
            pg.set('gutterType', '0')

            margin = ET.SubElement(sec_pr, f'{{{hp}}}margin')
            margin.set('header', '4252')
            margin.set('footer', '4252')
            margin.set('left', '8504')
            margin.set('right', '8504')
            margin.set('top', '5668')
            margin.set('bottom', '4252')
            margin.set('gutter', '0')

    return _xml_to_string(sec)


def _build_content_hpf():
    """HWPX 패키지 메타파일(content.hpf)을 생성한다."""
    hpf_ns = 'urn:oasis:names:tc:opendocument:xmlns:container'
    root = ET.Element(f'{{{hpf_ns}}}container')
    root.set('version', '1.0')

    rootfiles = ET.SubElement(root, f'{{{hpf_ns}}}rootfiles')

    rf1 = ET.SubElement(rootfiles, f'{{{hpf_ns}}}rootfile')
    rf1.set('full-path', 'Contents/header.xml')
    rf1.set('media-type', 'application/xml')

    rf2 = ET.SubElement(rootfiles, f'{{{hpf_ns}}}rootfile')
    rf2.set('full-path', 'Contents/section0.xml')
    rf2.set('media-type', 'application/xml')

    return _xml_to_string(root)


def _build_header_xml(title=''):
    """문서 헤더 XML을 생성한다."""
    hc = NS['hc']
    root = ET.Element(f'{{{hc}}}head')
    root.set('version', '1.1')
    root.set('secCnt', '1')

    if title:
        doc_info = ET.SubElement(root, f'{{{hc}}}docInfo')
        ti = ET.SubElement(doc_info, f'{{{hc}}}title')
        ti.text = title

    return _xml_to_string(root)


def _build_manifest_xml():
    """META-INF/manifest.xml을 생성한다."""
    ns = 'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0'
    ET.register_namespace('manifest', ns)

    root = ET.Element(f'{{{ns}}}manifest')
    root.set('version', '1.2')

    for path, mtype in [
        ('/', 'application/hwp+zip'),
        ('Contents/header.xml', 'application/xml'),
        ('Contents/content.hpf', 'application/xml'),
        ('Contents/section0.xml', 'application/xml'),
    ]:
        fe = ET.SubElement(root, f'{{{ns}}}file-entry')
        fe.set(f'{{{ns}}}full-path', path)
        fe.set(f'{{{ns}}}media-type', mtype)

    return _xml_to_string(root)


def _xml_to_string(element):
    """ET 요소를 XML 문자열로 변환한다."""
    return "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(
        element, encoding='unicode', xml_declaration=False
    )


# ─────────────────────────────────────────────
# HWPX 텍스트 치환
# ─────────────────────────────────────────────

def replace_text_hwpx(input_path, output_path, find_text, replace_text):
    """HWPX 파일에서 텍스트를 찾아 바꾼다.

    Args:
        input_path: 원본 HWPX 파일
        output_path: 결과 HWPX 파일
        find_text: 찾을 텍스트
        replace_text: 바꿀 텍스트
    Returns:
        치환된 횟수
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {input_path}")

    count = 0
    hp_ns = NS['hp']
    t_tag = f'{{{hp_ns}}}t'

    buf = BytesIO()
    with zipfile.ZipFile(input_path, 'r') as zf_in:
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                data = zf_in.read(item.filename)

                if re.match(r'(?i)contents/section\d+\.xml', item.filename):
                    tree = ET.parse(BytesIO(data))
                    root = tree.getroot()
                    for t_elem in root.iter(t_tag):
                        if t_elem.text and find_text in t_elem.text:
                            t_elem.text = t_elem.text.replace(find_text, replace_text)
                            count += 1
                    data = _xml_to_string(root).encode('utf-8')

                zf_out.writestr(item, data)

    with open(output_path, 'wb') as f:
        f.write(buf.getvalue())

    return count


# ─────────────────────────────────────────────
# 자동 감지 읽기
# ─────────────────────────────────────────────

def read_document(filepath):
    """파일 확장자에 따라 HWP 또는 HWPX로 자동 읽기한다."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.hwp':
        return read_hwp(filepath)
    elif ext == '.hwpx':
        return read_hwpx(filepath)
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext} (.hwp 또는 .hwpx만 지원)")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='한글과컴퓨터 HWP/HWPX 파일 읽기·쓰기 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""사용 예시:
  python hwp_utils.py read  문서.hwp          # HWP 텍스트 추출
  python hwp_utils.py read  문서.hwpx         # HWPX 텍스트 추출
  python hwp_utils.py write 출력.hwpx "내용"  # HWPX 문서 생성
  python hwp_utils.py write 출력.hwpx -f 입력.txt  # 텍스트 파일→HWPX
  python hwp_utils.py replace 원본.hwpx 결과.hwpx "찾기" "바꾸기"
"""
    )

    sub = parser.add_subparsers(dest='command', help='명령')

    # read
    p_read = sub.add_parser('read', help='HWP/HWPX 파일 텍스트 추출')
    p_read.add_argument('file', help='입력 파일 (.hwp 또는 .hwpx)')

    # write
    p_write = sub.add_parser('write', help='HWPX 파일 생성')
    p_write.add_argument('output', help='출력 파일 (.hwpx)')
    p_write.add_argument('content', nargs='?', default='', help='문서 내용 (문자열)')
    p_write.add_argument('-f', '--file', dest='input_file', help='내용을 읽어올 텍스트 파일')
    p_write.add_argument('-t', '--title', default='', help='문서 제목')

    # replace
    p_replace = sub.add_parser('replace', help='HWPX 텍스트 치환')
    p_replace.add_argument('input', help='원본 HWPX 파일')
    p_replace.add_argument('output', help='결과 HWPX 파일')
    p_replace.add_argument('find', help='찾을 텍스트')
    p_replace.add_argument('replace', help='바꿀 텍스트')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'read':
        text = read_document(args.file)
        print(text)

    elif args.command == 'write':
        content = args.content
        if args.input_file:
            with open(args.input_file, 'r', encoding='utf-8') as f:
                content = f.read()
        if not content:
            print("오류: 내용을 지정하세요 (문자열 또는 -f 파일)", file=sys.stderr)
            sys.exit(1)
        write_hwpx(args.output, content, title=args.title)
        print(f"생성 완료: {args.output}")

    elif args.command == 'replace':
        n = replace_text_hwpx(args.input, args.output, args.find, args.replace)
        print(f"치환 완료: {n}건 ({args.output})")


if __name__ == '__main__':
    main()
