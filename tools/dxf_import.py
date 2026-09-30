# -*- coding: utf-8 -*-
"""DWG/DXF 기구도면을 PCB 에 넣을 목록으로 바꾼다.

    python dxf_import.py <도면.dxf|.dwg> <출력폴더> [--origin X,Y]
                         [--all-layer "Mechanical Layer 3:0.127"]
                         [--outline-layer "Keep Out Layer:0.2" --outline-layer "Mechanical Layer 2:0.127"]
                         [--flat 0.005] [--dwg2dxf 경로]

출력
----
  objs.txt   `snippets/create_from_list.pas` 입력. 도면 전체 선·원 -> --all-layer,
             닫힌 외곽 -> 각 --outline-layer
  shape.txt  보드 외곽 꼭짓점 (x, y 한 줄씩) -> `snippets/set_board_shape.pas` 입력

원점
----
`--origin` 에 준 도면 좌표가 PCB (0,0) 이 된다. 안 주면 원점 이동 없이 쓰고,
원점 후보로 쓸 만한 세로선(길이 5mm 이상) 목록과 중심점을 출력한다.
CHEST BLOOD 보드들은 "J1 옆 탭 세로선의 중심" 을 원점으로 했다.

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

import ezdxf
from shapely.geometry import Polygon


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
    for e in msp:
        t = e.dxftype()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('drawing'); ap.add_argument('outdir')
    ap.add_argument('--origin')
    ap.add_argument('--all-layer', default='Mechanical Layer 3:0.127')
    ap.add_argument('--outline-layer', action='append')
    ap.add_argument('--flat', type=float, default=0.005)
    ap.add_argument('--dwg2dxf')
    a = ap.parse_args()
    outline_layers = a.outline_layer or ['Keep Out Layer:0.2', 'Mechanical Layer 2:0.127']
    os.makedirs(a.outdir, exist_ok=True)

    units, paths, circles = read(to_dxf(a.drawing, a.dwg2dxf), a.flat)
    print(f'단위 $INSUNITS={units} (4=mm), 선 {len(paths)}, 원 {len(circles)}')
    if units not in (4, None):
        print('  경고: mm 가 아니다 - 좌표를 그대로 mm 로 쓴다')

    if a.origin:
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
    for cx, cy, r in sorted(circles):
        print(f'  원 R{r:g} ({mv((cx, cy))[0]}, {mv((cx, cy))[1]})')


if __name__ == '__main__':
    main()
