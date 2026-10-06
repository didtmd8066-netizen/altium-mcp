# -*- coding: utf-8 -*-
"""설계 룰을 .RUL 파일로 만든다 - Advanced(객체 종류별) 클리어런스 매트릭스까지.

    python rules_rul.py list <보드.PcbDoc 또는 .RUL> [--kind Clearance]
    python rules_rul.py copy <보드.PcbDoc 또는 .RUL> <out.RUL> [--kind Clearance] [--names "룰1,룰2"]
                             [--set "룰:Track-Poly=0.5" ...] [--gap "룰=0.25" ...]
    python rules_rul.py new  <out.RUL> --name 이름 --gap 0.2 [--scope1 All] [--scope2 All]
                             [--cell Track-Poly=0.5 ...] [--net-scope DifferentNetsOnly]
                             [--layer-kind SameLayer] [--priority 1] [--like <보드 또는 RUL>:룰이름]

만든 파일은 Altium 에서 사용자가 넣는다:  Design > Rules > (룰 목록에서 우클릭) Import Rules...
> 종류 선택 > 파일 선택. 같은 이름의 룰이 있으면 Altium 이 덮어쓸지 묻는다.

왜 파일로 하나
--------------
클리어런스 룰의 Advanced 매트릭스(Track-Poly, Via-Hole ... 쌍마다 다른 값)는 DelphiScript 로 읽지도
쓰지도 못한다. 스크립트로 만들 수 있는 것은 값 하나짜리(Simple) 룰뿐이다 (MCP `create_pcb_clearance_rule`).
그런데 `Design > Rules` 의 Export 파일(.RUL)은 PcbDoc 안의 룰 레코드와 같은 글자열이고, 매트릭스가
`OBJECTCLEARANCES` 에 그대로 들어 있다. 그래서 그 파일을 만들어 Import 하게 한다.

형식 (실제 Export 파일에서 확인: e-SC(Clearance) - KST.RUL, 2026-10-06)
- 룰 하나가 한 줄. PcbDoc 레코드에서 맨 앞 `|` 만 뺀 것. 줄 끝은 0xB6 + CRLF. 인코딩은 ANSI.
- `GENERICCLEARANCE` 가 매트릭스의 기본값이고, `OBJECTCLEARANCES` 에는 **기본값과 다른 칸만** 적는다.
  `ClearanceObj_Track-ClearanceObj_Poly:196850;...`  값은 1/10000 mil 정수 (0.5mm = 196850).
- 매트릭스는 대칭이라 쌍마다 한 번만 적는다. 순서는 Arc, Track, SMDPad, THPad, Via, Fill, Poly,
  Region, Text, Hole 이고 앞선 종류가 왼쪽에 온다 (Track-Poly 는 있어도 Poly-Track 은 없다).

단위는 모두 mm 로 주고받는다. 파일 안의 mil 은 Altium 형식이라 그대로 둔다.

copy 의 --set / --gap 은 복사하면서 일부만 고칠 때 쓴다. --gap 은 기본값을 바꾸는데, 이때 예전
기본값을 따르던 칸들이 새 기본값을 따르게 된다 (명시된 칸은 그대로).
"""
import argparse
import os
import random
import re
import string
import sys

END = b'\xb6\r\n'
MIL = 0.0254
KINDS = ['Arc', 'Track', 'SMDPad', 'THPad', 'Via', 'Fill', 'Poly', 'Region', 'Text', 'Hole']
ALIAS = {k.lower(): k for k in KINDS}
ALIAS.update(pad='SMDPad', smd='SMDPad', th='THPad', polygon='Poly', copper='Poly')
FIELD = re.compile(r'([A-Za-z0-9_. ]+)=([^|]*)')


class Rule:
    """룰 한 줄. 필드를 순서대로 들고 있어 손대지 않은 필드는 원문 그대로 나간다."""

    def __init__(self, text):
        self.fields = [list(m) for m in FIELD.findall(text.strip().lstrip('|'))]

    def get(self, key, default=''):
        return next((v for k, v in self.fields if k == key), default)

    def set(self, key, value):
        for f in self.fields:
            if f[0] == key:
                f[1] = value
                return
        self.fields.append([key, value])

    name = property(lambda self: self.get('NAME'))
    kind = property(lambda self: self.get('RULEKIND'))

    def text(self):
        return '|'.join(f'{k}={v}' for k, v in self.fields)

    # ── 클리어런스 매트릭스 ──
    def generic_mm(self):
        return _mil_to_mm(self.get('GENERICCLEARANCE') or self.get('GAP') or '0mil')

    def cells(self):
        """{(종류1, 종류2): mm} - 기본값과 다른 칸만."""
        out = {}
        for part in self.get('OBJECTCLEARANCES').split(';'):
            m = re.fullmatch(r'ClearanceObj_(\w+)-ClearanceObj_(\w+):(-?\d+)', part.strip())
            if m:
                out[(m.group(1), m.group(2))] = int(m.group(3)) / 10000 * MIL
        return out

    def set_cells(self, cells):
        unit = lambda mm: round(mm / MIL * 10000)          # 파일 단위(1/10000 mil)로 맞춰 비교한다
        generic = unit(self.generic_mm())
        keep = {pair(*k): unit(v) for k, v in cells.items() if unit(v) != generic}
        order = sorted(keep, key=lambda k: (KINDS.index(k[0]), KINDS.index(k[1])))
        self.set('OBJECTCLEARANCES', ';'.join(f'ClearanceObj_{a}-ClearanceObj_{b}:{keep[(a, b)]}' for a, b in order))

    def set_generic(self, mm):
        cells = self.cells()                       # 명시된 칸은 값이 그대로 남는다
        self.set('GAP', _mm_to_mil(mm)); self.set('GENERICCLEARANCE', _mm_to_mil(mm))
        self.set_cells(cells)


def _mil_to_mm(text):
    t = text.strip().lower()
    return float(t[:-2]) if t.endswith('mm') else float(t.replace('mil', '') or 0) * MIL


def _mm_to_mil(mm):
    return ('%.4f' % (mm / MIL)).rstrip('0').rstrip('.') + 'mil'


def pair(a, b):
    """종류 이름 둘 -> 파일에 적는 순서의 (왼쪽, 오른쪽)."""
    try:
        a, b = ALIAS[a.lower()], ALIAS[b.lower()]
    except KeyError as e:
        raise ValueError(f'모르는 객체 종류 {e.args[0]!r} - 쓸 수 있는 것: {", ".join(KINDS)}')
    return (a, b) if KINDS.index(a) <= KINDS.index(b) else (b, a)


def parse_cell(text):
    """'Track-Poly=0.5' -> (('Track', 'Poly'), 0.5)."""
    m = re.fullmatch(r'\s*(\w+)\s*-\s*(\w+)\s*=\s*([\d.]+)\s*(mm)?\s*', text)
    if not m:
        raise ValueError(f'칸 지정은 "Track-Poly=0.5" 꼴이다: {text!r}')
    return pair(m.group(1), m.group(2)), float(m.group(3))


def load(path):
    """PcbDoc 또는 .RUL 에서 룰 목록."""
    if str(path).lower().endswith('.pcbdoc'):
        import olefile
        ole = olefile.OleFileIO(path)
        try:
            data = ole.openstream(['Rules6', 'Data']).read()
        finally:
            ole.close()
        return [Rule(m.decode('mbcs' if sys.platform == 'win32' else 'latin-1', 'replace'))
                for m in re.findall(rb'\|SELECTION=[^\x00]*', data) if b'RULEKIND=' in m]
    with open(path, 'rb') as f:
        data = f.read()
    return [Rule(line.decode('mbcs' if sys.platform == 'win32' else 'latin-1', 'replace'))
            for line in data.replace(b'\xb6', b'').splitlines() if b'RULEKIND=' in line]


def save(rules, path):
    with open(path, 'wb') as f:
        for r in rules:
            f.write(r.text().encode('mbcs' if sys.platform == 'win32' else 'latin-1', 'replace') + END)


def new_rule(name, gap_mm, scope1='All', scope2='All', net_scope='DifferentNetsOnly', layer_kind='SameLayer', priority=1):
    uid = ''.join(random.choice(string.ascii_uppercase) for _ in range(8))
    return Rule('|'.join([
        'SELECTION=FALSE', 'LAYER=TOP', 'LOCKED=FALSE', 'POLYGONOUTLINE=FALSE', 'USERROUTED=TRUE', 'KEEPOUT=FALSE',
        'UNIONINDEX=0', 'RULEKIND=Clearance', f'NETSCOPE={net_scope}', f'LAYERKIND={layer_kind}',
        f'SCOPE1EXPRESSION={scope1}', f'SCOPE2EXPRESSION={scope2}', f'NAME={name}', 'ENABLED=TRUE', f'PRIORITY={priority}',
        'COMMENT=', f'UNIQUEID={uid}', 'DEFINEDBYLOGICALDOCUMENT=FALSE', f'GAP={_mm_to_mil(gap_mm)}',
        f'GENERICCLEARANCE={_mm_to_mil(gap_mm)}', 'IGNOREPADTOPADCLEARANCEINFOOTPRINT=FALSE', 'OBJECTCLEARANCES=']))


def show(r):
    print(f'{r.kind:<20} {r.name:<28} 우선순위 {r.get("PRIORITY"):<3} {"" if r.get("ENABLED") == "TRUE" else "(꺼짐) "}'
          f'{r.get("SCOPE1EXPRESSION")}  /  {r.get("SCOPE2EXPRESSION")}')
    if r.kind == 'Clearance':
        cells = r.cells()
        print(f'    기본 {r.generic_mm():.3f}mm, {r.get("NETSCOPE")}, 기본값과 다른 칸 {len(cells)}개')
        by = {}
        for (a, b), v in cells.items():
            by.setdefault(round(v, 4), []).append(f'{a}-{b}')
        for v in sorted(by):
            print(f'      {v:.3f}mm  ' + ', '.join(by[v]))


def pick(rules, kind, names):
    out = [r for r in rules if not kind or kind == 'all' or r.kind.lower() == kind.lower()]
    if names:
        want = [n.strip() for n in names.split(',') if n.strip()]
        missing = [n for n in want if n not in {r.name for r in out}]
        if missing:
            sys.exit(f'없는 룰: {", ".join(missing)}  (있는 것: {", ".join(r.name for r in out)})')
        out = [r for r in out if r.name in want]
    return out


def main():
    ap = argparse.ArgumentParser(description='설계 룰 .RUL 만들기 (Advanced 클리어런스 매트릭스 포함)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('list'); p.add_argument('src'); p.add_argument('--kind', default='Clearance')
    p = sub.add_parser('copy'); p.add_argument('src'); p.add_argument('out')
    p.add_argument('--kind', default='Clearance'); p.add_argument('--names')
    p.add_argument('--set', action='append', default=[], metavar='룰:Track-Poly=0.5')
    p.add_argument('--gap', action='append', default=[], metavar='룰=0.25')
    p = sub.add_parser('new'); p.add_argument('out'); p.add_argument('--name', required=True)
    p.add_argument('--gap', type=float, required=True, help='매트릭스 기본값 (mm)')
    p.add_argument('--scope1', default='All'); p.add_argument('--scope2', default='All')
    p.add_argument('--cell', action='append', default=[], metavar='Track-Poly=0.5')
    p.add_argument('--net-scope', default='DifferentNetsOnly', choices=['DifferentNetsOnly', 'SameNetOnly', 'AnyNet'])
    p.add_argument('--layer-kind', default='SameLayer'); p.add_argument('--priority', type=int, default=1)
    p.add_argument('--like', metavar='보드또는RUL:룰이름', help='이 룰의 매트릭스를 그대로 가져와 시작한다')
    a = ap.parse_args()

    if a.cmd == 'list':
        rules = pick(load(a.src), a.kind, None)
        for r in rules:
            show(r)
        print(f'{len(rules)}개')
        return 0

    if a.cmd == 'copy':
        rules = pick(load(a.src), a.kind, a.names)
        by_name = {r.name: r for r in rules}
        for g in a.gap:
            n, _, v = g.rpartition('=')
            if n not in by_name:
                sys.exit(f'--gap: 복사할 룰에 {n!r} 가 없다')
            by_name[n].set_generic(float(v))
        for s in a.set:
            n, _, cell = s.partition(':')
            if n not in by_name:
                sys.exit(f'--set: 복사할 룰에 {n!r} 가 없다')
            k, v = parse_cell(cell)
            cells = by_name[n].cells(); cells[k] = v
            by_name[n].set_cells(cells)
    else:
        r = new_rule(a.name, a.gap, a.scope1, a.scope2, a.net_scope, a.layer_kind, a.priority)
        cells = {}
        if a.like:
            src, _, n = a.like.rpartition(':')
            base = pick(load(src), 'Clearance', n)[0]
            # 원본에서 기본값을 따르던 칸은 새 룰에서도 기본값(--gap)을 따른다. 명시된 칸만 가져온다.
            cells = base.cells()
        for c in a.cell:
            k, v = parse_cell(c)
            cells[k] = v
        r.set_cells(cells)
        rules = [r]

    save(rules, a.out)
    for r in rules:
        show(r)
    print(f'{len(rules)}개 -> {os.path.abspath(a.out)}')
    print('Altium: Design > Rules > 룰 목록에서 우클릭 > Import Rules... 로 넣는다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
