# -*- coding: utf-8 -*-
"""배치 전 부품을 회로도 시트별 묶음으로 보드 옆에 정렬한다.

    python sheet_groups.py <부품 덤프> <프로젝트 폴더> <move.txt> [--width 90] [--gap 0.6]
                           [--offset 12] [--block-gap 6] [--big 4] [--all]

덤프 1회(MCP `dump_components`) -> 이 스크립트 -> MCP `apply_component_moves` 1회.
ECO 직후 보드 옆에 한 덩어리로 쌓인 부품을 블록 단위로 풀어 놓는 용도다. 배치 자체는 사람이 한다 -
찾는 시간을 줄여 줄 뿐이다. 회전과 면은 건드리지 않는다.

정하는 방식
-----------
- 묶음 = 회로도 시트(.SchDoc) 하나. 프로젝트 폴더의 SchDoc 을 Altium 없이 읽어 지정자를 모은다.
  시트 순서는 파일 이름의 번호 순.
- 보드 외곽 안에 있는 부품은 이미 배치한 것으로 보고 옮기지 않는다 (--all 이면 그것도 옮긴다).
- 부품 크기는 **3D 바디와 패드를 합친 외접 사각형**이다. 패드만으로 재면 바디가 큰 부품
  (D2PAK, 커넥터, 전해 커패시터)이 이웃과 겹친다 - 2026-10-06 NEW_BASE_MOTOR 에서 100쌍이 겹쳐
  다시 했다. 바디가 없는 부품(TP 등)은 패드로, 패드도 없으면 실크를 포함한 전체 범위로 잰다.
- 묶음 안: 위에 큰 부품(긴 변 --big mm 이상)을 큰 순서로, 그 아래에 작은 부품을 종류(C, R, D ...)별로
  줄을 바꿔 번호순으로. 부품 사이 --gap.
- 묶음은 보드 오른쪽에 위에서 아래로 쌓고, 보드 높이를 넘으면 오른쪽 단으로 넘어간다.
- 지정자가 겹치는 부품(annotate 안 된 R? Q?)은 어느 시트인지 알 수 없어 "미지정" 묶음으로 맨 끝에
  모은다. 이름으로는 가릴 수 없으므로 이동 목록에 지금 좌표를 같이 적어 좌표로 찾게 한다.
- 시트에 없는 지정자는 "시트 없음" 묶음.

겹침 검사
---------
옮기는 부품끼리만 보지 않는다. **옮기지 않는 부품까지 포함한 전 부품**으로 본다. 처음에 옮긴 것끼리만
검사했다가, 제자리에 둔 Q? 4개 위에 새 묶음이 올라간 것을 놓쳤다. 묶음을 놓는 자리도 옮기지 않는
부품의 오른쪽 끝 바깥에서 시작한다. 겹침이 남으면 종료 코드 1 이고 목록을 쓰지 않는다.
"""
import argparse
import collections
import glob
import math
import os
import re
import sys

from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl

FIELD = re.compile(r'\|([A-Za-z0-9_. ]+)=([^|]*)')
UNANNOTATED = (10 ** 6, '미지정 (지정자 겹침)')
NOSHEET = (10 ** 6 - 1, '시트 없음')


def natural(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', text)]


def sheet_designators(data):
    """SchDoc 의 FileHeader 스트림에서 지정자들 (RECORD=34)."""
    out = []
    for rec in data.split(b'\x00'):
        t = rec.decode('latin-1')
        if re.search(r'\|RECORD=34(\||$)', t):
            f = {k.upper(): v for k, v in FIELD.findall(t)}
            d = (f.get('TEXT') or '').strip()
            if d and '?' not in d:
                out.append(d)
    return out


def read_sheets(folder):
    """{지정자: (순번, 시트 이름)}. 순번은 파일 이름 순."""
    import olefile
    sheet_of = {}
    for i, path in enumerate(sorted(glob.glob(os.path.join(folder, '*.SchDoc')), key=lambda p: natural(os.path.basename(p)))):
        ole = olefile.OleFileIO(path)
        try:
            names = sheet_designators(ole.openstream('FileHeader').read())
        finally:
            ole.close()
        for d in names:
            sheet_of.setdefault(d, (i, os.path.splitext(os.path.basename(path))[0]))
    return sheet_of


def read_components(path):
    """(외곽 Polygon 또는 None, 부품 dict 목록)."""
    outline, comps = [], []
    for line in open(path, encoding='latin-1'):
        f = line.rstrip('\n').split('|')
        if f[0] == 'O' and f[1] == 'L':
            outline.append((float(f[2]), float(f[3])))
        elif f[0] == 'O' and f[1] == 'A':
            pts = rl.arc_points((float(f[4]), float(f[5])), float(f[6]), float(f[7]), float(f[8]))
            if math.dist(pts[-1], (float(f[2]), float(f[3]))) < math.dist(pts[0], (float(f[2]), float(f[3]))):
                pts.reverse()
            outline += pts
        elif f[0] == 'K' and len(f) >= 20:
            rect = lambda i: tuple(float(v) for v in f[i:i + 4]) if all(f[i:i + 4]) else None
            body, pad, whole = rect(8), rect(12), rect(16)
            parts = [r for r in (body, pad) if r] or [whole]
            bb = (min(r[0] for r in parts), min(r[1] for r in parts), max(r[2] for r in parts), max(r[3] for r in parts))
            comps.append(dict(des=f[1], x=float(f[3]), y=float(f[4]), fp=f[7], bb=bb, has_body=body is not None,
                              w=bb[2] - bb[0], h=bb[3] - bb[1]))
    return (Polygon(outline).buffer(0) if len(outline) >= 3 else None), comps


def prefix(des):
    m = re.match(r'[A-Za-z]+', des)
    return m.group(0) if m else ''


def number(des):
    m = re.search(r'\d+', des)
    return int(m.group(0)) if m else 0


def layout(items, x0, ytop, width, gap, big_mm):
    """묶음 하나를 (x0, ytop) 을 왼쪽 위로 놓는다. 반환: ([(부품, 새 x, 새 y)], 아래 끝 y)."""
    big = sorted([c for c in items if max(c['w'], c['h']) >= big_mm], key=lambda c: (-c['w'] * c['h'], natural(c['des'])))
    small = sorted([c for c in items if max(c['w'], c['h']) < big_mm],
                   key=lambda c: (prefix(c['des']), round(c['h'], 1), round(c['w'], 1), number(c['des']), c['x'], c['y']))
    out, cx, cy, rowh, last = [], x0, ytop, 0.0, None
    for group in (big, small):
        for c in group:
            p = prefix(c['des'])
            if cx > x0 and (cx + c['w'] > x0 + width or (group is small and last is not None and p != last)):
                cx = x0; cy -= rowh + gap; rowh = 0.0
            last = p if group is small else None
            # 부품의 외접 사각형 왼쪽 위가 (cx, cy) 에 오도록 원점을 옮긴다
            out.append((c, c['x'] + cx - c['bb'][0], c['y'] + cy - c['bb'][3]))
            cx += c['w'] + gap; rowh = max(rowh, c['h'])
        if group is big and big:
            cx = x0; cy -= rowh + gap * 2; rowh = 0.0
    return out, cy - rowh


def plan(board, comps, sheet_of, width=90.0, gap=0.6, offset=12.0, block_gap=6.0, big_mm=4.0, move_all=False):
    """반환: (이동 [(부품, 새 x, 새 y)], 묶음 보고 [(순번·이름, 개수, x1, y1, x2, y2)], 그대로 둔 부품)."""
    names = collections.Counter(c['des'] for c in comps)
    stay, groups = [], collections.defaultdict(list)
    for c in comps:
        if not move_all and board is not None and board.buffer(0.5).contains(Point(c['x'], c['y'])):
            stay.append(c)
        elif names[c['des']] > 1 or '?' in c['des']:
            groups[UNANNOTATED].append(c)
        else:
            groups[sheet_of.get(c['des']) or sheet_of.get(re.sub(r'[A-Z]$', '', c['des'])) or NOSHEET].append(c)
    bx1, by1, bx2, by2 = board.bounds if board is not None else (0.0, 0.0, 0.0, 100.0)
    # 그대로 두는 부품이 보드 밖 오른쪽에 있으면 그 바깥에서 시작한다
    x = max([bx2] + [c['bb'][2] for c in stay]) + offset
    ytop, moves, report = by2, [], []
    for key in sorted(groups):
        out, bottom = layout(groups[key], x, ytop, width, gap, big_mm)
        if bottom < by1 - 5 and ytop < by2:                 # 보드 높이를 넘으면 다음 단으로
            x += width + block_gap * 2; ytop = by2
            out, bottom = layout(groups[key], x, ytop, width, gap, big_mm)
        moves += out
        report.append((key, len(groups[key]), x, bottom, x + width, ytop))
        ytop = bottom - block_gap
    return moves, report, stay


def overlaps(moves, stay):
    """옮긴 뒤의 전 부품에서 겹치는 쌍 [(지정자, 지정자)] 과 최소 간격."""
    boxes, names = [], []
    for c, nx, ny in moves:
        dx, dy = nx - c['x'], ny - c['y']
        boxes.append(box(c['bb'][0] + dx, c['bb'][1] + dy, c['bb'][2] + dx, c['bb'][3] + dy)); names.append(c['des'])
    for c in stay:
        boxes.append(box(*c['bb'])); names.append(c['des'])
    if not boxes:
        return [], None
    tree, hits, closest = STRtree(boxes), [], None
    for i, b in enumerate(boxes):
        for j in tree.query(b.buffer(1.0)):
            if j > i:
                if b.intersection(boxes[j]).area > 1e-6:
                    hits.append((names[i], names[j]))
                d = b.distance(boxes[j])
                closest = d if closest is None else min(closest, d)
    return hits, closest


def main():
    ap = argparse.ArgumentParser(description='시트별 부품 모으기')
    ap.add_argument('dump', help='dump_components 덤프'); ap.add_argument('project', help='SchDoc 이 있는 폴더')
    ap.add_argument('out', help='이동 목록을 쓸 파일')
    ap.add_argument('--width', type=float, default=90.0, help='묶음 한 단의 폭 (mm)')
    ap.add_argument('--gap', type=float, default=0.6, help='부품 사이 (mm)')
    ap.add_argument('--offset', type=float, default=12.0, help='보드에서 첫 단까지 (mm)')
    ap.add_argument('--block-gap', type=float, default=6.0, help='묶음 사이 (mm)')
    ap.add_argument('--big', type=float, default=4.0, help='큰 부품으로 치는 긴 변 (mm)')
    ap.add_argument('--all', action='store_true', help='보드 안에 놓인 부품도 옮긴다')
    a = ap.parse_args()

    board, comps = read_components(a.dump)
    if not comps:
        sys.exit('덤프에 부품(K 줄)이 없다 - dump_components 로 뜬 덤프인지 확인.')
    sheet_of = read_sheets(a.project)
    if not sheet_of:
        sys.exit(f'{a.project} 에서 SchDoc 의 지정자를 하나도 못 읽었다.')
    moves, report, stay = plan(board, comps, sheet_of, a.width, a.gap, a.offset, a.block_gap, a.big, a.all)
    hits, closest = overlaps(moves, stay)

    if board is not None:
        b = board.bounds
        print(f'보드 {b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} mm, 부품 {len(comps)}개: 옮김 {len(moves)}, 보드 안이라 그대로 {len(stay)}')
    nobody = sum(1 for c, _, _ in moves if not c['has_body'])
    print(f'크기 기준: 3D 바디 {len(moves) - nobody}개, 바디가 없어 패드·전체 범위 {nobody}개')
    for (order, name), n, x1, y1, x2, y2 in report:
        print(f'  {name[:44]:<44} {n:>4}개  x {x1:.0f}~{x2:.0f}  y {y1:.0f}~{y2:.0f}')
    if hits:
        print(f'겹치는 쌍 {len(hits)}개 - 목록을 쓰지 않는다: {hits[:10]}')
        return 1
    print(f'겹치는 쌍 0 (전 부품 {len(moves) + len(stay)}개 기준), 최소 간격 {closest:.3f}mm' if closest is not None else '겹치는 쌍 0')
    with open(a.out, 'w', encoding='ascii', errors='replace') as f:
        dup = collections.Counter(c['des'] for c in comps)
        for c, nx, ny in moves:                  # 마지막 칸: 지정자가 겹쳐 좌표로 찾아야 하는 부품
            f.write('%s|%.5f|%.5f|%d|%d|%d\n' % (c['des'], nx, ny, round(c['x'] * 1000), round(c['y'] * 1000), dup[c['des']] > 1))
    print(f'이동 목록 {len(moves)}줄 -> {os.path.abspath(a.out)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
