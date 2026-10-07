# -*- coding: utf-8 -*-
"""칩 R·C 의 Description 을 회로도에 보이는 표기로 통일한다.

    python sch_description.py <프로젝트 폴더 | .PrjPcb | .SchDoc ...> <plan.txt>
                              [--csv 목록.csv] [--skip C106,R245] [--res "..."] [--cap "..."]

이 스크립트(Altium 없이 저장본을 읽는다) -> MCP `apply_sch_descriptions` 1회.
BOM 을 뽑을 때 Description 열이 부품마다 다른 꼴이고, 복사한 뒤 값만 바꾼 부품은 Description 에 원본의
값이 남아 있어 쓸 수 없다 (2026-10-07 NEW_BASE_MOTOR: 칩 R·C 530개 중 208개가 화면 값과 달랐다).

정하는 방식
-----------
- **회로도에 보이는 글자만 쓴다.** 숨겨진 파라미터(Package (Metric), Case Code, Tolerance, Power ...)는
  복사 원본의 값이 남아 있을 수 있어 쓰지 않는다.
- 대상은 지정자가 R숫자 / C숫자 이고 크기(`Package (Imperial)`)가 보이는 부품 = 칩 부품.
  크기가 안 보이는 부품(전해, 시멘트 저항)은 건드리지 않고 "칩 아님" 으로만 알린다.
- 저항값: `Resistance` 가 보이면 그 값, 아니면 `Comment`. **글자를 고치지 않고 그대로 쓴다**
  (15.4k, 100R, 2R7, 4mOHM). 이미 OHM 이 들어 있으면 OHM 을 덧붙이지 않는다.
  `Comment` 가 숨겨져 있고 `Resistance` 가 보이는 부품은 둘이 다를 수 있다 (화면 10K, Comment 22).
- 커패시터: 값은 보이는 `Capacitance` / `Value` / `ValueDisplayed` / `Comment` 순, 전압은 `Voltage` / `VDC_V`.
- 값 자리에 DNP 가 보이면 값 대신 DNP 를 쓴다 (`RES DNP 0402`).
- 미터 코드로 적힌 크기(2012 등, 인치 코드와 헷갈리지 않는 것만)는 다른 부품과 같은 꼴로 바꾼다.
- 값이 읽히지 않는 부품(Comment 가 제품명뿐 등), 지정자가 `?` 인 부품, 한 시트 안에서 같은 지정자가
  서로 다른 내용으로 나오는 부품은 **보류**로 알리고 계획에 넣지 않는다.
- 지정자는 시트 안에서만 유일하면 된다. 계획은 시트별로 묶여 있어 시트끼리 지정자가 겹쳐도 섞이지 않는다.

계획 파일 (ANSI): `#<SchDoc 전체 경로>` 한 줄 뒤에 그 시트의 `지정자=새 Description` 줄들.
저장본을 읽으므로 **Altium 에서 저장하지 않은 수정이 있으면 먼저 저장**한다.
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys

FIELD = re.compile(r'\|([A-Za-z0-9_. %/()@-]+)=([^|]*)')
ENC = 'mbcs' if sys.platform == 'win32' else 'latin-1'
SIZE_PARAMS = ('Package (Imperial)',)
R_VALUE = ('Resistance', 'Comment')
C_VALUE = ('Capacitance', 'Value', 'ValueDisplayed', 'Comment')
C_VOLT = ('Voltage', 'VDC_V')
# 인치 코드에 같은 숫자가 없는 미터 코드만 바꾼다 (0603, 0402 는 양쪽에 다 있어 건드리지 않는다)
METRIC = {'1005': '0402', '1608': '0603', '2012': '0805', '3216': '1206', '3225': '1210', '5025': '2010', '6432': '2512'}
R_OK = re.compile(r'[\d.]+\s*(k|K|M|R|m|mOHM|OHM|Ω)?|\d+[RKkM]\d+', re.I)
C_OK = re.compile(r'[\d.]+\s*[pnuµμ]F', re.I)
RES_FMT = 'RES {value} OHM {size}'
CAP_FMT = 'CAP CER {value} {volt} {size}'


def records(data):
    """FileHeader 스트림의 레코드 본문들. [길이 3바이트][종류 1바이트][본문] 이 이어진다.
    NUL 로 자르면 안 된다 - 길이 바이트에도 NUL 이 있어 순번(OwnerIndex)이 어긋난다."""
    out, pos = [], 0
    while pos + 4 <= len(data):
        n = int.from_bytes(data[pos:pos + 3], 'little')
        out.append(data[pos + 4:pos + 4 + n].rstrip(b'\x00'))
        pos += 4 + n
    return out


def read_components(data):
    """한 시트의 부품들: [{des, desc, par: {이름: (글자, 보임)}}]. 필드 이름은 대소문자가 섞여 있다."""
    recs = [{k.upper(): v for k, v in FIELD.findall(r.decode(ENC, 'replace') + '|')} for r in records(data)]
    comps = {}
    for i, f in enumerate(recs):
        if f.get('RECORD') == '1':
            comps[i - 1] = dict(des='?', desc=f.get('COMPONENTDESCRIPTION', ''), par={})
    for f in recs:
        o = f.get('OWNERINDEX', '')
        if not o.isdigit() or int(o) not in comps:
            continue
        c = comps[int(o)]
        if f.get('RECORD') == '34':
            c['des'] = f.get('TEXT', '?').strip()
        elif f.get('RECORD') == '41':
            c['par'][f.get('NAME', '')] = (f.get('TEXT', '').strip(), f.get('ISHIDDEN') != 'T')
    return list(comps.values())


def shown(comp):
    """화면에 보이는 파라미터만 {이름: 글자}."""
    return {n: t for n, (t, vis) in comp['par'].items() if vis and t not in ('', '*')}


def first(d, names):
    for n in names:
        if d.get(n):
            return d[n]
    return ''


def describe(comp, res_fmt=RES_FMT, cap_fmt=CAP_FMT):
    """(새 Description, 보류 사유). 칩 R·C 가 아니면 (None, None)."""
    m = re.fullmatch(r'([RC])(\d+|\?)', comp['des'])
    if not m:
        return None, None
    s = shown(comp)
    size = first(s, SIZE_PARAMS)
    if not size:
        return None, '칩 아님 (크기 표기 없음)'
    if m.group(2) == '?':
        return None, '지정자 미지정'
    size = METRIC.get(size, size)
    if m.group(1) == 'R':
        value = first(s, R_VALUE)
        if value.upper() == 'DNP':
            return ' '.join(res_fmt.format(value='DNP', size=size).replace(' OHM', '').split()), None
        if not R_OK.fullmatch(value):
            return None, '값을 읽을 수 없음 (%s)' % (value or '보이는 값 없음')
        fmt = res_fmt.replace(' OHM', '') if re.search(r'OHM|Ω', value, re.I) else res_fmt
        return fmt.format(value=value, size=size), None
    value, volt = first(s, C_VALUE), first(s, C_VOLT)
    if value.upper() != 'DNP' and not C_OK.fullmatch(value):
        return None, '값을 읽을 수 없음 (%s)' % (value or '보이는 값 없음')
    if not volt:
        return None, '전압 표기 없음'
    return cap_fmt.format(value='DNP' if value.upper() == 'DNP' else value.replace(' ', ''), volt=volt, size=size), None


def plan(sheets, skip=(), res_fmt=RES_FMT, cap_fmt=CAP_FMT):
    """sheets: [(경로, [부품])] -> (rows, hold). rows: (경로, 지정자, 기존, 변경). 이미 같은 것도 넣는다."""
    rows, hold = [], []
    for path, comps in sheets:
        new_of = collections.defaultdict(set)
        mine = []
        for c in comps:
            if c['des'] in skip:
                continue
            new, why = describe(c, res_fmt, cap_fmt)
            if why:
                hold.append((path, c['des'], why))
            elif new:
                new_of[c['des']].add(new); mine.append((c, new))
        for c, new in mine:
            if len(new_of[c['des']]) > 1:
                hold.append((path, c['des'], '시트 안에서 지정자가 겹치고 내용이 다름'))
            else:
                rows.append((path, c['des'], c['desc'], new))
    return rows, hold


def find_sheets(args):
    """폴더 -> 그 안의 *.SchDoc, .PrjPcb -> 등록된 SchDoc, 그 밖에는 파일 그대로."""
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(glob.glob(os.path.join(a, '*.SchDoc')))
        elif a.lower().endswith('.prjpcb'):
            with open(a, encoding=ENC, errors='replace') as f:
                for ln in f:
                    if ln.startswith('DocumentPath=') and ln.strip().lower().endswith('.schdoc'):
                        out.append(os.path.join(os.path.dirname(os.path.abspath(a)), ln.strip()[13:]))
        else:
            out.append(a)
    return [os.path.abspath(p) for p in out]


def load(paths):
    import olefile
    sheets = []
    for p in paths:
        ole = olefile.OleFileIO(p)
        try:
            sheets.append((p, read_components(ole.openstream('FileHeader').read())))
        finally:
            ole.close()
    return sheets


def write_plan(rows, path):
    """바뀌는 줄만 쓴다. 같은 시트·지정자·내용은 한 줄 (멀티파트 부품). 쓴 줄 수를 돌려준다."""
    by = collections.OrderedDict()
    for sheet, des, old, new in rows:
        if old != new:
            by.setdefault(sheet, collections.OrderedDict())[des] = new
    with open(path, 'w', encoding=ENC, newline='\n') as f:
        for sheet, items in by.items():
            f.write('#%s\n' % sheet)
            for des, new in items.items():
                f.write('%s=%s\n' % (des, new))
    return sum(len(v) for v in by.values())


def read_plan(path):
    """{(시트 경로, 지정자): 새 Description}"""
    want, cur = {}, None
    with open(path, encoding=ENC) as f:
        for ln in f.read().splitlines():
            if ln.startswith('#'):
                cur = ln[1:]
            elif '=' in ln and cur:
                d, _, v = ln.partition('=')
                want[(cur, d)] = v
    return want


def verify(plan_path, readback_path):
    """적용 뒤 Altium 에서 다시 읽은 것(`@경로` 뒤에 `지정자=Description`)을 계획과 대조한다.
    돌려주는 것: dict(expected, ok, wrong=[(시트, 지정자, 읽힌 값)], missing=[(시트, 지정자)])"""
    want = read_plan(plan_path)
    got, cur = collections.defaultdict(list), None
    with open(readback_path, encoding=ENC, errors='replace') as f:
        for ln in f.read().splitlines():
            if ln.startswith('@'):
                cur = ln[1:]
            elif ln.startswith('#'):
                cur = None
            elif cur and '=' in ln:
                d, _, v = ln.partition('=')
                got[(cur, d)].append(v)
    wrong = [(os.path.basename(k[0]), k[1], got[k][0]) for k, v in want.items() if k in got and any(g != v for g in got[k])]
    missing = [(os.path.basename(k[0]), k[1]) for k in want if k not in got]
    return dict(expected=len(want), ok=len(want) - len(wrong) - len(missing), wrong=wrong, missing=missing)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='칩 R·C Description 을 화면 표기로 통일')
    ap.add_argument('source', nargs='+', help='프로젝트 폴더, .PrjPcb, 또는 .SchDoc 들')
    ap.add_argument('plan', help='쓸 계획 파일')
    ap.add_argument('--csv', help='기존 -> 변경 목록 (엑셀로 열 수 있는 CSV)')
    ap.add_argument('--skip', default='', help='건드리지 않을 지정자 (쉼표로 구분)')
    ap.add_argument('--res', default=RES_FMT, help='저항 형식. 기본 "%s"' % RES_FMT)
    ap.add_argument('--cap', default=CAP_FMT, help='커패시터 형식. 기본 "%s"' % CAP_FMT)
    a = ap.parse_args()
    paths = find_sheets(a.source)
    if not paths:
        sys.exit('SchDoc 이 없다')
    rows, hold = plan(load(paths), {s.strip() for s in a.skip.split(',') if s.strip()}, a.res, a.cap)
    n = write_plan(rows, a.plan)
    kinds = collections.Counter((des[0], '변경' if old != new else '그대로') for _, des, old, new in rows)
    print('시트 %d개   R 변경 %d / 그대로 %d   C 변경 %d / 그대로 %d   계획 %d줄 -> %s' % (
        len(paths), kinds[('R', '변경')], kinds[('R', '그대로')], kinds[('C', '변경')], kinds[('C', '그대로')], n, a.plan))
    why = collections.defaultdict(list)
    for sheet, des, w in hold:
        why[w].append(des)
    for w, des in why.items():
        print('  %s %d개: %s' % ('제외' if w.startswith('칩 아님') else '보류', len(des), w), ' '.join(sorted(des, key=lambda d: (len(d), d))[:30]))
    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(['시트', '지정자', '기존 Description', '변경 Description', '바뀜'])
            for sheet, des, old, new in sorted(rows, key=lambda r: (r[1][0], int(r[1][1:]), r[0])):
                w.writerow([os.path.basename(sheet), des, old, new, 'O' if old != new else ''])


if __name__ == '__main__':
    main()
