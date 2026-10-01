# -*- coding: utf-8 -*-
"""DWG/DXF 기구도면을 PCB 에 넣을 목록으로 바꾼다.

    python dxf_import.py <도면.dxf|.dwg> <출력폴더> [--origin X,Y|auto]
                         [--all-layer "Mechanical Layer 3:0.127"]
                         [--outline-layer "Keep Out Layer:0.2" --outline-layer "Mechanical Layer 2:0.127"]
                         [--flat 0.005] [--dwg2dxf 경로]
                         [--place-dump 덤프 | --place-ref 덤프 [--mirror] [--flip180 J1]] [--suffix _1]

출력
----
  objs.txt   `snippets/create_from_list.pas` 입력. 도면 전체 선·원 -> --all-layer,
             닫힌 외곽 -> 각 --outline-layer
  shape.txt  보드 외곽 꼭짓점 (x, y 한 줄씩) -> `snippets/set_board_shape.pas` 입력
  place.json 부품 배치 (place_components 입력). --place-dump 나 --place-ref 를 줬을 때만

한 번에 끝내는 순서 (도면 변환 1회 + Altium 호출 3회)
--------------------------------------------------
  1. 이 스크립트를 `--origin auto --place-ref ...` 로 한 번 돌린다
  2. create_from_list.pas (objs.txt)  3. set_board_shape.pas (shape.txt)  4. place_components (place.json)

부품 배치
---------
도면의 원(CIRCLE) 중심이 LED 자리다. 위치는 항상 원 중심 그대로 쓴다 (PDF·PPT 좌표는
0.02mm 반올림돼 있어 기준이 못 된다). 지정자와 각도는 두 방식 중 하나로 정한다.

  --place-ref 덤프 [--mirror]   짝이 되는 보드(이미 맞춰 놓은 쪽)를 기준으로 한다. --mirror 면
        좌우 대칭: 위치 x -> -x, 각도 r -> 180-r. 커넥터처럼 핀 배열을 뒤집을 수 없는 부품은
        `--flip180 J1` 로 지정해 r+180 으로 돌린다. LED 는 대칭 위치에서 가장 가까운 원으로
        붙이고, 원이 없는 부품(J1, C1...)은 대칭 위치 그대로 놓는다.
  --place-dump 덤프             이 보드 자신의 덤프. 지정자는 가장 가까운 현재 부품에서 가져오고,
        각도는 외곽선 방향으로 계산한다: 원 중심에서 가장 가까운 변과 그 반대편 변의 접선
        (둘레 +-2.5mm 현) 평균. 패드2 가 탭(원점)에서 멀어지는 쪽을 향하게 하고, 세로에 가까우면
        그대로 둔다. 양쪽 변 각도가 12 도 넘게 다르면 가지가 갈라지는 자리다 - `<<` 로
        표시하니 사람이 정한다 (CHEST BLOOD BOT_LEFT 에서 D1, D5, D11, D19 를 손으로 정했다).

덤프는 `C|지정자|선택|x|y|회전|풋프린트` 줄만 본다 (origin 기준 mm). 보드에 따라 지정자에
`_1` 같은 접미사가 붙어 있으면 `--suffix _1` 로 맞춘다.

원점
----
`--origin` 에 준 도면 좌표가 PCB (0,0) 이 된다. 안 주면 원점 이동 없이 쓰고,
원점 후보로 쓸 만한 세로선(길이 5mm 이상) 목록과 중심점을 출력한다.
CHEST BLOOD 보드들은 "J1 옆 탭 세로선의 중심" 을 원점으로 했다. `--origin auto` 는 이 규칙을
그대로 쓴다: 점 4개짜리 LWPOLYLINE(탭 사각형)의 세로변 중 원들의 무게중심에서 먼 쪽의 중심.

처리 규칙
---------
- DWG 는 LibreDWG `dwg2dxf` 로 먼저 DXF 로 바꾼다 (`--dwg2dxf` 또는 환경변수 DWG2DXF).
- SPLINE 은 Altium 에 없으므로 `--flat` 오차 이내 직선으로 펼친다.
- 외곽은 LINE / LWPOLYLINE / SPLINE / ARC 의 끝점을 이어 만든다. 짝 없는 끝점은
  먼저 **T 접합**(끝점이 다른 선 위에 있고 그 선이 튀어나옴)인지 보고 돌출부를 잘라낸다.
  그래도 남으면 **틈**으로 보고 가장 가까운 짝끼리 잇는다. 둘 다 출력한다.
  이 수정은 외곽 레이어와 shape.txt 에만 들어가고, 도면 원본을 담는 --all-layer 는
  원본 그대로다.
- CIRCLE 은 --all-layer 에 원(아크 0~360)으로만 넣는다. LED 자리 표시 같은 것이다.
"""
import argparse
import math
import os
import subprocess
import sys

import json

import ezdxf
from shapely.geometry import LinearRing, LineString, Point, Polygon


def to_dxf(path, conv):
    if path.lower().endswith('.dxf'):
        return path
    conv = conv or os.environ.get('DWG2DXF')
    if not conv or not os.path.exists(conv):
        sys.exit('DWG 변환기가 없다. LibreDWG 의 dwg2dxf.exe 경로를 --dwg2dxf 로 주거나 DXF 를 직접 준비할 것.')
    out = os.path.splitext(path)[0] + '.dxf'
    # 쓰지 않는 클래스(MATERIAL 등)에 대한 경고만으로도 종료 코드가 0 이 아닐 수 있다 -> 결과 파일로 판단
    r = subprocess.run([os.path.abspath(conv), '-y', '-o', out, path], capture_output=True, text=True)
    if not os.path.exists(out):
        sys.exit('DWG 변환 실패:\n' + r.stderr[-800:])
    return out


def read(path, flat):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    paths, circles = [], []
    read.tabs = []
    for e in msp:
        t = e.dxftype()
        if t == 'LWPOLYLINE' and len(e) == 4:
            read.tabs.append([tuple(q) for q in e.get_points('xy')])
        if t == 'LINE':
            paths.append([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)])
        elif t == 'LWPOLYLINE':
            pts = [(v.x, v.y) for v in e.flattening(flat)] if any(p[4] for p in e.get_points()) else \
                  [tuple(p) for p in e.get_points('xy')]
            if e.closed:
                pts.append(pts[0])
            paths.append(pts)
        elif t in ('SPLINE', 'ARC'):
            paths.append([(v.x, v.y) for v in e.flattening(flat)])
        elif t == 'CIRCLE':
            circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
    return doc.header.get('$INSUNITS'), paths, circles


def lonely_ends(paths, tol=1e-3):
    ends = []
    for p in paths:
        ends += [p[0], p[-1]]
    return [a for a in ends if sum(1 for b in ends if math.dist(a, b) < tol) == 1]


def project(pt, a, b):
    ax, ay = a; bx, by = b
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = 0 if L2 == 0 else max(0, min(1, ((pt[0] - ax) * (bx - ax) + (pt[1] - ay) * (by - ay)) / L2))
    q = (ax + t * (bx - ax), ay + t * (by - ay))
    return math.dist(pt, q), q


def fix_outline(paths, snap=0.01):
    """외곽을 닫는다. 두 경우를 구분한다.

    T 접합: 한쪽 끝점이 다른 선 위(snap 이내)에 있고 그 선이 접합점을 지나 튀어나온 경우.
            튀어나온 쪽 끝이 짝 없는 끝점이면 그 선을 접합점에서 잘라 돌출부를 버린다.
            (CHEST BLOOD BOT_LEFT: 0.46mm 돌출. 틈으로 보고 이으면 폭 1um 짜리 가시가 생긴다)
    틈:     그래도 남은 짝 없는 끝점은 가장 가까운 것끼리 직선으로 잇는다.
    반환: (고친 외곽 선 목록, [(설명, 점)])
    """
    paths = [list(p) for p in paths]
    notes = []
    for e in lonely_ends(paths):
        if e not in lonely_ends(paths):   # 앞선 처리로 이미 해소됨
            continue
        for pi, p in enumerate(paths):
            if e in (p[0], p[-1]):
                continue
            for si, (a, b) in enumerate(zip(p, p[1:])):
                d, q = project(e, a, b)
                if d > snap:
                    continue
                head, tail = p[:si + 1] + [q], [q] + p[si + 1:]
                lone = lonely_ends(paths)
                if any(math.dist(head[0], x) < 1e-3 for x in lone):      # 앞쪽이 돌출부
                    paths[pi] = [e] + tail[1:]
                    notes.append((f'T 접합 - 돌출 {math.dist(head[0], q):.3f} mm 잘라냄', q))
                elif any(math.dist(tail[-1], x) < 1e-3 for x in lone):   # 뒤쪽이 돌출부
                    paths[pi] = head[:-1] + [e]
                    notes.append((f'T 접합 - 돌출 {math.dist(tail[-1], q):.3f} mm 잘라냄', q))
                else:
                    continue
                break
            else:
                continue
            break
    lone = lonely_ends(paths)
    while len(lone) >= 2:
        a = lone.pop(0)
        j = min(range(len(lone)), key=lambda i: math.dist(a, lone[i]))
        b = lone.pop(j)
        paths.append([a, b])
        notes.append((f'틈 {math.dist(a, b):.3f} mm 이음', a))
    return paths, notes


def chain(paths, tol=1e-3):
    """선들을 끝점 순서대로 이어 한 바퀴 꼭짓점 목록을 만든다."""
    rest = [list(p) for p in paths]
    loop = rest.pop(0)
    while rest:
        end = loop[-1]
        i = min(range(len(rest)), key=lambda k: min(math.dist(end, rest[k][0]), math.dist(end, rest[k][-1])))
        p = rest.pop(i)
        if math.dist(end, p[-1]) < math.dist(end, p[0]):
            p = p[::-1]
        if math.dist(end, p[0]) > tol:
            print(f'  경고: 외곽이 두 덩어리 이상이다 - 간격 {math.dist(end, p[0]):.3f} mm 에서 이어 붙임')
        loop += p[1:]
    out = [loop[0]]
    for q in loop[1:-1]:
        if math.dist(q, out[-1]) > 1e-4:
            out.append(q)
    return out


def auto_origin(tabs, circles):
    if not tabs or not circles:
        sys.exit('--origin auto: 탭 사각형(점 4개 LWPOLYLINE)이나 원이 없다. 좌표를 직접 줄 것.')
    gx = sum(c[0] for c in circles) / len(circles)
    best = None
    for p in tabs:
        for a, b in zip(p, p[1:] + p[:1]):
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) >= 5 and (best is None or abs(a[0] - gx) > abs(best[0] - gx)):
                best = (a[0], (a[1] + b[1]) / 2)
    if best is None:
        sys.exit('--origin auto: 탭 사각형에 세로변이 없다.')
    return best


def read_comps(path):
    out = {}
    for line in open(path, encoding='latin-1'):
        f = line.strip().split('|')
        if f[0] == 'C' and len(f) >= 6:
            out[f[1]] = (float(f[3]), float(f[4]), float(f[5]))
    return out


def outline_rotation(c, ring, window=2.5):
    """원 중심 c 에서 본 외곽선 방향. 반환: (각도 0~180, 양쪽 변 각도 차)."""
    L = ring.length

    def tang(p):
        s = ring.project(p)
        a, b = ring.interpolate((s - window) % L), ring.interpolate((s + window) % L)
        return math.degrees(math.atan2(b.y - a.y, b.x - a.x)) % 180

    pc = Point(c)
    p1 = ring.interpolate(ring.project(pc))
    d1 = pc.distance(p1)
    ux, uy = (c[0] - p1.x) / d1, (c[1] - p1.y) / d1
    hit = LineString([(c[0] + 0.5 * ux, c[1] + 0.5 * uy), (c[0] + 20 * ux, c[1] + 20 * uy)]).intersection(ring)
    hits = [g for g in getattr(hit, 'geoms', [hit]) if not g.is_empty]
    t1 = tang(p1)
    t2 = tang(min(hits, key=pc.distance)) if hits else t1
    # 각도는 180 도 주기라 두 배 각으로 평균한다
    sx = math.cos(math.radians(2 * t1)) + math.cos(math.radians(2 * t2))
    sy = math.sin(math.radians(2 * t1)) + math.sin(math.radians(2 * t2))
    return (math.degrees(math.atan2(sy, sx)) / 2) % 180, abs((t1 - t2 + 90) % 180 - 90)


def place(a, circles, shape):
    """place.json 을 만든다. circles, shape 는 이미 원점 이동된 좌표."""
    sfx = a.suffix or ''
    centres = [(c[0], c[1]) for c in circles]
    rows = []
    if a.place_ref:
        ref = read_comps(a.place_ref)
        flip = set((a.flip180 or '').split(','))
        used = set()
        for name, (x, y, r) in sorted(ref.items()):
            if a.mirror:
                x, r = -x, ((r + 180) if name in flip else (180 - r)) % 360
            q = min(centres, key=lambda p: math.dist(p, (x, y)))
            note = ''
            if math.dist(q, (x, y)) < 1.0:
                if q in used:
                    note = '  << 이미 쓴 원에 다시 붙었다'
                used.add(q); x, y = q
            rows.append((name + sfx, x, y, round(r, 2), note))
        print(f'배치 {len(rows)}개 (원에 붙인 것 {len(used)} / 원 {len(centres)}개)')
    else:
        cur = read_comps(a.place_dump)
        ring = LinearRing(shape)
        gx = sum(p[0] for p in shape) / len(shape)      # 보드가 원점(탭)에서 뻗는 쪽
        for q in centres:
            name = min(cur, key=lambda k: math.dist(cur[k][:2], q))
            t, dev = outline_rotation(q, ring)
            c = math.cos(math.radians(t)) * (1 if gx > 0 else -1)   # 탭에서 멀어지는 방향 성분
            rot = t + 180 if c < -0.26 else t
            rows.append((name, q[0], q[1], round(rot % 360, 2), '  << 가지가 갈라지는 자리 - 각도 확인' if dev > 12 else ''))
    for name, x, y, r, note in rows:
        print(f'  {name:<8} ({x:9.3f}, {y:9.3f})  {r:7.2f}{note}')
    # place_components 는 mil 로 받는다 (도구 입력 규격)
    with open(os.path.join(a.outdir, 'place.json'), 'w', encoding='utf-8') as f:
        json.dump([dict(designator=n, x=round(x / 0.0254, 5), y=round(y / 0.0254, 5), rotation=r) for n, x, y, r, _ in rows], f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('drawing'); ap.add_argument('outdir')
    ap.add_argument('--origin')
    ap.add_argument('--all-layer', default='Mechanical Layer 3:0.127')
    ap.add_argument('--outline-layer', action='append')
    ap.add_argument('--flat', type=float, default=0.005)
    ap.add_argument('--dwg2dxf')
    ap.add_argument('--place-dump'); ap.add_argument('--place-ref')
    ap.add_argument('--mirror', action='store_true'); ap.add_argument('--flip180'); ap.add_argument('--suffix')
    a = ap.parse_args()
    outline_layers = a.outline_layer or ['Keep Out Layer:0.2', 'Mechanical Layer 2:0.127']
    os.makedirs(a.outdir, exist_ok=True)

    units, paths, circles = read(to_dxf(a.drawing, a.dwg2dxf), a.flat)
    print(f'단위 $INSUNITS={units} (4=mm), 선 {len(paths)}, 원 {len(circles)}')
    if units not in (4, None):
        print('  경고: mm 가 아니다 - 좌표를 그대로 mm 로 쓴다')

    if a.origin == 'auto':
        ox, oy = auto_origin(read.tabs, circles)
        print(f'원점 (자동): 도면 ({ox:.4f}, {oy:.4f})')
    elif a.origin:
        ox, oy = map(float, a.origin.split(','))
    else:
        ox = oy = 0.0
        print('원점 후보 (길이 5mm 이상 세로선의 중심):')
        for p in paths:
            for s, t in zip(p, p[1:]):
                if abs(s[0] - t[0]) < 1e-6 and abs(s[1] - t[1]) >= 5:
                    print(f'  x={s[0]:.3f}  y {min(s[1], t[1]):.3f}~{max(s[1], t[1]):.3f}  중심 ({s[0]:.3f}, {(s[1] + t[1]) / 2:.3f})')
    mv = lambda q: (round(q[0] - ox, 4), round(q[1] - oy, 4))

    outline, notes = fix_outline(paths)
    for msg, q in notes:
        print(f'{msg}: ({mv(q)[0]}, {mv(q)[1]})')

    rows = []
    def add(p, layer):
        for s, t in zip(p, p[1:]):
            s, t = mv(s), mv(t)
            if s != t:
                rows.extend(['T', '-', s[0], s[1], t[0], t[1], layer])
    for p in paths:
        add(p, a.all_layer)
    for cx, cy, r in circles:
        c = mv((cx, cy)); rows.extend(['A', '-', c[0], c[1], r, '0:360', a.all_layer])
    for lay in outline_layers:
        for p in outline:
            add(p, lay)
    with open(os.path.join(a.outdir, 'objs.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(map(str, rows)) + '\n')

    shape = [mv(q) for q in chain(outline)]
    poly = Polygon(shape)
    with open(os.path.join(a.outdir, 'shape.txt'), 'w', encoding='utf-8') as f:
        f.write(''.join(f'{x}\n{y}\n' for x, y in shape))
    xs, ys = zip(*shape)
    print(f'객체 {len(rows) // 7}, 외곽 꼭짓점 {len(shape)}, 면적 {poly.area:.1f} mm2, 유효 {poly.is_valid}')
    print(f'외곽 범위 X {min(xs):.3f}~{max(xs):.3f}  Y {min(ys):.3f}~{max(ys):.3f}')
    if a.place_dump or a.place_ref:
        # 원 중심은 반올림하지 않은 값으로 넘긴다 - 부품 중심이 도면과 정확히 일치해야 한다
        place(a, [(cx - ox, cy - oy, r) for cx, cy, r in circles], shape)
    else:
        for cx, cy, r in sorted(circles):
            print(f'  원 R{r:g} ({mv((cx, cy))[0]}, {mv((cx, cy))[1]})')


if __name__ == '__main__':
    main()
