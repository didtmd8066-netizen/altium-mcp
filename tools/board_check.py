# -*- coding: utf-8 -*-
"""보드를 넘기기 전에 한 번에 훑는다 - Altium 을 부르지 않는다.

    python board_check.py <보드.PcbDoc 또는 덤프> [--clearance 0.2] [--edge 0.3] [--fpcb]
                          [--pour-nets GND] [--limit 15]

저장된 `.PcbDoc` 을 그대로 읽는다 (`pcbdoc_dump.py`). 저장 안 된 변경이 있으면 dump_copper 덤프를 준다.
Altium DRC 를 대신하지는 않는다 - 룰을 읽지 않고 한 가지 값으로만 잰다. DRC 를 돌리기 전에
스크립트 배선이 남긴 문제를 먼저 걸러 내는 용도다. 문제가 있으면 종료 코드 1.

보는 것
-------
1. 간격      넷이 다른 구리 사이가 --clearance 미만인 곳 (리전은 .PcbDoc 로 읽었을 때만 - 덤프에는 외접 사각형뿐). 중심선 거리에서 반지름을 빼 정확히 잰다
             (`route_lib.core`). 0.1996mm 처럼 눈으로 안 보이는 위반이 대상이다 - 평행 줄 사이의
             동심 아크 중심이 0.0007mm 어긋난 것만으로 생긴다. 패드끼리는 보지 않는다 (풋프린트 몫).
2. 외곽      구리가 보드 외곽에서 --edge 미만인 곳, 보드 밖으로 나간 것.
3. 넷 없는 구리   넷이 빠진 트랙·아크·비아. 붙여 넣은 뒤 넷이 안 들어간 선이 여기 나온다.
4. 찌꺼기    길이 0.01mm 미만 트랙, 2 도 미만 아크, 같은 자리에 겹친 객체. 끌기·Gloss 뒤에 남는다.
5. 끊긴 끝   트랙·아크의 끝이 같은 넷의 아무것에도 닿지 않는 곳 (배선하다 만 자리).
6. 미연결    한 넷의 패드들이 구리로 다 이어지지 않은 넷과, 떨어져 있는 패드.
7. 꺾임 (--fpcb)   각지게 꺾인 곳, 아크와 직선이 접하지 않는 곳. FPCB 는 각진 꺾임을 남기지 않는다.
                   리지드 보드의 45 도 꺾임은 정상이므로 기본으로는 보지 않는다.

5·6 은 폴리곤이 부은 구리를 모른다 (덤프에 없다). 면으로 이어지는 넷은 --pour-nets 에 적어 빼 준다
(기본 GND). 패드 템플릿을 쓰는 패드는 저장 파일에 크기가 없어 0.025mm 로 읽힌다 - 그 패드의 실제
모양은 같은 넷의 리전으로 들어와 있어 간격·연결 판정에는 그 리전(외접 사각형)을 쓴다.
"""
import argparse
import collections
import math
import os
import sys

from shapely.geometry import Point, Polygon, box
from shapely.ops import nearest_points
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corner_arcs
import route_lib as rl

KIND = {'T': '트랙', 'A': '아크', 'V': '비아', 'P': '패드', 'R': '리전'}
TOUCH = 0.002                       # 이만큼 떨어져 있어도 닿은 것으로 본다 (좌표 반올림)


def cores(o):
    """route_lib.core 에 구리 리전을 더한 것. 리전은 꼭짓점이 있으면 실제 모양, 없으면 외접 사각형."""
    if o.kind == 'R':
        if o.what not in ('copper', 'padshape'):
            return []
        g = Polygon(o.pts).buffer(0) if o.pts and len(o.pts) >= 3 else box(*o.box)
        return [(o.layer, g, 0.0)]
    return rl.core(o)


def is_pad(o):
    """패드, 또는 패드 모양을 그린 리전 (풋프린트 안의 일이라 서로의 간격은 보지 않는다)."""
    return o.kind == 'P' or (o.kind == 'R' and o.what == 'padshape')


def label(o):
    if o.kind == 'P':
        return f'패드 {o.ref}'
    return KIND[o.kind]


def pt(p):
    return f'({p.x:.3f}, {p.y:.3f})' if hasattr(p, 'x') else f'({p[0]:.3f}, {p[1]:.3f})'


def build(objs):
    items = [(o, c) for o in objs for c in cores(o)]
    tree = STRtree([c[1] for _, c in items]) if items else None
    rmax = max([c[2] for _, c in items] or [0.0])
    return items, tree, rmax


def near(tree, g, margin):
    x1, y1, x2, y2 = g.bounds
    return sorted(int(i) for i in tree.query(box(x1 - margin, y1 - margin, x2 + margin, y2 + margin)))


def clearance(items, tree, rmax, limit_gap):
    """넷이 다른 구리 쌍 중 간격이 limit_gap 미만인 것: [(간격, 위치, a, b)]."""
    out = []
    for i, (o, c) in enumerate(items):
        for j in near(tree, c[1], limit_gap + c[2] + rmax):
            if j <= i:
                continue
            o2, c2 = items[j]
            if o.net == o2.net or c[0] != c2[0] or (is_pad(o) and is_pad(o2)):
                continue
            if any(x.kind == 'R' and not x.pts for x in (o, o2)):
                continue                      # 외접 사각형뿐인 리전: 실제 모양을 몰라 간격을 말할 수 없다
            d = rl.gap(c, c2)
            if d < limit_gap - rl.TOL:
                out.append((d, nearest_points(c[1], c2[1])[0], o, o2, c[0]))
    return sorted(out, key=lambda e: e[0])


def edge(items, board, limit):
    out = []
    for o, c in items:
        if o.kind in 'PR':
            continue
        d = board.exterior.distance(c[1]) - c[2]
        inside = board.contains(c[1])
        if d < limit - rl.TOL or not inside:
            out.append((d if inside else -abs(d), nearest_points(c[1], board.exterior)[0], o, c[0]))
    seen, uniq = set(), []                       # 비아는 층마다 한 번씩 나온다
    for e in sorted(out, key=lambda e: e[0]):
        if id(e[2]) not in seen:
            seen.add(id(e[2])); uniq.append(e)
    return uniq


def debris(objs):
    tiny = [o for o in objs if o.kind == 'T' and math.dist(o.a, o.b) < 0.01]
    deg = [o for o in objs if o.kind == 'A' and (o.a2 - o.a1) % 360 < 2]
    seen, dup = collections.defaultdict(list), []
    for o in objs:
        if o.kind in 'TAV':
            for k in sorted(rl.keys(o))[:1]:
                seen[(k, o.net, o.get('layer'))].append(o)
    for group in seen.values():
        if len(group) > 1 and (group[0].kind != 'A' or abs(group[0].a1 - group[1].a1) < 0.05):
            dup.append(group)
    return tiny, deg, dup


def where(o):
    if o.kind == 'T':
        return f'{pt(o.a)} -> {pt(o.b)}'
    if o.kind == 'A':
        return f'중심 {pt(o.c)} R {o.r:.3f}'
    return pt((o.x, o.y))


def connectivity(objs, items, tree, rmax, skip):
    """같은 넷끼리 닿은 것을 묶는다. 반환: (끊긴 끝 [(넷, 점, 층)], 미연결 {넷: [패드 묶음...]})."""
    parent = list(range(len(objs)))
    index = {id(o): i for i, o in enumerate(objs)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    for i, (o, c) in enumerate(items):
        if not o.net or o.net in skip:
            continue
        for j in near(tree, c[1], c[2] + rmax + TOUCH):
            if j <= i:
                continue
            o2, c2 = items[j]
            if o2.net == o.net and c2[0] == c[0] and rl.gap(c, c2) <= TOUCH:
                a, b = find(index[id(o)]), find(index[id(o2)])
                if a != b:
                    parent[a] = b
    dangling = []
    for i, (o, c) in enumerate(items):
        if o.kind not in 'TA' or not o.net or o.net in skip:
            continue
        if (o.kind == 'T' and math.dist(o.a, o.b) < 0.01) or (o.kind == 'A' and (o.a2 - o.a1) % 360 < 2):
            continue
        for e in ((o.a, o.b) if o.kind == 'T' else rl.arc_ends(o)):
            p = Point(e)
            hit = False
            for j in near(tree, p, rmax + TOUCH):
                o2, c2 = items[j]
                if o2 is not o and o2.net == o.net and c2[0] == c[0] and c2[1].distance(p) - c2[2] <= TOUCH:
                    hit = True; break
            if not hit:
                dangling.append((o.net, e, c[0]))
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for o in objs:
        if o.kind == 'P' and o.net and o.net not in skip:
            groups[o.net][find(index[id(o)])].append(o.ref)
    open_nets = {n: sorted(g.values(), key=lambda refs: (-len(refs), refs)) for n, g in groups.items() if len(g) > 1}
    return dangling, open_nets


def main():
    ap = argparse.ArgumentParser(description='보드 검사 (Altium 없이)')
    ap.add_argument('board', help='.PcbDoc 또는 dump_copper 덤프')
    ap.add_argument('--clearance', type=float, default=0.2); ap.add_argument('--edge', type=float, default=0.3)
    ap.add_argument('--fpcb', action='store_true', help='각진 꺾임·접하지 않는 아크도 본다')
    ap.add_argument('--pour-nets', default='GND', help='면(폴리곤)으로 이어지는 넷 - 끊긴 끝·미연결에서 뺀다')
    ap.add_argument('--limit', type=int, default=15, help='항목별로 보여 줄 개수')
    a = ap.parse_args()
    skip = {n for n in a.pour_nets.split(',') if n}

    objs, comps, board = rl.load_board(a.board)
    objs = [o for o in objs if o.kind in 'TAVPR' and (o.kind != 'R' or o.what in ('copper', 'padshape'))]
    n = collections.Counter(o.kind for o in objs)
    print(f'{os.path.basename(a.board)}: 트랙 {n["T"]}, 아크 {n["A"]}, 비아 {n["V"]}, 패드 {n["P"]}, 구리 리전 {n["R"]}')
    items, tree, rmax = build(objs)
    bad = 0

    def section(title, rows, fmt, note=''):
        nonlocal bad
        if not rows:
            print(f'{title}: 이상 없음'); return
        bad += 1
        print(f'{title}: {len(rows)}곳{note}')
        for r in rows[:a.limit]:
            print('   ' + fmt(r))
        if len(rows) > a.limit:
            print(f'   ... {len(rows) - a.limit}곳 더 (--limit)')

    cl = clearance(items, tree, rmax, a.clearance) if tree else []
    section(f'1. 간격 {a.clearance:g}mm 미만', cl,
            lambda e: f'{e[0]:.4f}mm  {pt(e[1])}  {e[4]}  {label(e[2])} {e[2].net or "(넷 없음)"} <-> {label(e[3])} {e[3].net or "(넷 없음)"}')
    if board is not None:
        section(f'2. 외곽에서 {a.edge:g}mm 미만', edge(items, board, a.edge),
                lambda e: f'{e[0]:.4f}mm  {pt(e[1])}  {label(e[2])} {e[2].net or "(넷 없음)"}' + ('  보드 밖' if e[0] < 0 else ''))
    else:
        print('2. 외곽: 덤프에 외곽이 없어 건너뜀')
    section('3. 넷 없는 구리', [o for o in objs if o.kind in 'TAV' and not o.net],
            lambda o: f'{label(o)} {o.get("layer") or ""} {where(o)}')
    tiny, deg, dup = debris(objs)
    section('4. 찌꺼기', [('0.01mm 미만 트랙', o) for o in tiny] + [('2도 미만 아크', o) for o in deg] + [('겹친 객체 %d개' % len(g), g[0]) for g in dup],
            lambda r: f'{r[0]}  {r[1].net or "(넷 없음)"}  {r[1].get("layer") or ""}  {where(r[1])}')
    dangling, open_nets = connectivity(objs, items, tree, rmax, skip) if tree else ([], {})
    excl = f' ({", ".join(sorted(skip))} 제외)' if skip else ''
    section('5. 끊긴 끝' + excl, sorted(dangling), lambda r: f'{r[0]:<18} {pt(r[1])}  {r[2]}')
    section('6. 미연결 넷' + excl, sorted(open_nets.items()),
            lambda r: f'{r[0]:<18} 덩어리 {len(r[1])}개: ' + ' / '.join(', '.join(g[:4]) + (' ...' if len(g) > 4 else '') for g in r[1][:4]))
    if a.fpcb:
        rows = []
        for lay, k in corner_arcs.find_kinks(objs).items():
            rows += [('각진 꺾임', lay) + r for r in k['sharp']] + [('접하지 않는 아크', lay) + r for r in k['kink']]
        section('7. 꺾임', sorted(rows, key=lambda r: (r[0], r[1], r[2])), lambda r: f'{r[0]}  {r[2]:<18} {pt(r[3])}  {r[4]:.1f}도  {r[1]}')
    print('문제 없음' if not bad else f'확인할 항목 {bad}가지')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
