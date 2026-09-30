# -*- coding: utf-8 -*-
"""보드 외곽을 따라 스티칭 비아 자리를 계산한다.

    python stitch_vias.py <dump.txt> <out.txt> [--offset 1] [--pitch 2]
                          [--size 0.6] [--hole 0.3] [--net GND] [--clear 0.25]

순서
----
1. `snippets/dump_outline_edge.pas` 로 외곽과 외곽 근처 객체를 덤프한다.
2. 이 스크립트가 외곽을 `--offset` 만큼 안쪽으로 줄인 경로를 만들고, 둘레를
   `--pitch` 에 가장 가까운 등간격으로 나눠 후보를 찍는다.
3. 후보마다 주변 객체와의 간격을 **실제 형상**으로 잰다 (shapely).
   - 다른 넷·넷 없음·keepout: 비아 가장자리에서 `--clear` 이상
   - 같은 넷 패드·트랙: 겹치지만 않으면 된다 (0.1mm 여유)
4. `snippets/create_from_list.pas` 입력 형식으로 쓴다. 생성은 넷을 넣은 채로 된다.

같은 넷 비아가 이미 있으면 그 주변(간격의 0.9배)은 건너뛴다. 이미 스티칭한 보드에
다시 돌려도 사이사이에 겹쳐 찍지 않는다.

형상을 외접 사각형으로 보지 않는 이유: 보드 모서리 R 을 그린 Keep-Out 아크를
사각형으로 보면 모서리 근처 후보가 전부 떨어지고, 원 전체로 보면 아크가 없는
사분면까지 떨어진다 (2026-09-30 IM26_Chest 에서 둘 다 겪음). 아크는 아크로 잰다.
패드·리전은 덤프가 외접 사각형만 주므로 사각형으로 잰다 - 이쪽은 보수적으로 틀린다.
"""
import argparse
import math
import sys

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


def arc_points(cx, cy, r, a1, a2, n=24):
    """a1 -> a2 반시계 아크 (Altium 규약)."""
    if a2 <= a1:
        a2 += 360
    return [(cx + r * math.cos(math.radians(a1 + (a2 - a1) * i / n)),
             cy + r * math.sin(math.radians(a1 + (a2 - a1) * i / n))) for i in range(n + 1)]


def read_dump(path):
    outline, obstacles = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        f = line.strip().split('|')
        if not f or not f[0]:
            continue
        if f[0] == 'O':
            v = list(map(float, f[2:]))
            if f[1] == 'A':
                # 아크 구간은 점열로 펼친다. Altium 아크는 항상 a1->a2 반시계로 저장되지만
                # 외곽은 시계 방향으로도 돈다 - 시작 꼭짓점(v0,v1) 쪽부터 오도록 뒤집는다.
                pts = arc_points(*v[2:7])
                if math.dist(pts[-1], (v[0], v[1])) < math.dist(pts[0], (v[0], v[1])):
                    pts.reverse()
                outline += pts
            else:
                outline.append((v[0], v[1]))
            continue
        kind, layer, net, keepout = f[0], f[1], f[2], f[3] in ('-1', 'True')
        if layer.startswith('Mechanical') or 'Overlay' in layer or 'Paste' in layer or 'Solder' in layer:
            continue
        v = list(map(float, f[4:]))
        if kind == 'T':
            geom = LineString([(v[0], v[1]), (v[2], v[3])]).buffer(v[4] / 2)
        elif kind == 'A':
            geom = LineString(arc_points(*v[:5])).buffer(v[5] / 2)
        elif kind == 'V':
            geom = Point(v[0], v[1]).buffer(v[2] / 2)
        else:
            geom = box(*v[:4])
        obstacles.append((geom, net, keepout, f'{kind} {layer} {net or "-"}{" keepout" if keepout else ""}'))
    return outline, obstacles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('out')
    ap.add_argument('--offset', type=float, default=1.0)
    ap.add_argument('--pitch', type=float, default=2.0)
    ap.add_argument('--size', type=float, default=0.6)
    ap.add_argument('--hole', type=float, default=0.3)
    ap.add_argument('--net', default='GND')
    ap.add_argument('--clear', type=float, default=0.25)
    a = ap.parse_args()

    outline, obstacles = read_dump(a.dump)
    board = Polygon(outline).buffer(0)
    # 보드 모양 자체를 그린 리전(Multi/Connect Layer 의 보드 영역)은 장애물이 아니다
    obstacles = [o for o in obstacles if o[0].area < 0.5 * board.area]
    path = board.buffer(-a.offset, join_style=1).exterior  # 모서리는 둥글게 따라간다
    n = max(1, round(path.length / a.pitch))
    step = path.length / n
    r = a.size / 2

    keep, skip = [], []
    for i in range(n):
        p = path.interpolate(i * step)
        hit = None
        for geom, net, ko, desc in obstacles:
            need = 0.1 if (net == a.net and not ko) else a.clear
            # 같은 넷 비아가 이미 있으면 (재실행 등) 간격의 0.9배 안에는 또 찍지 않는다
            if desc.startswith('V ') and net == a.net and geom.centroid.distance(p) < 0.9 * a.pitch:
                hit = desc + ' (기존 스티칭)'
                break
            if geom.distance(p) - r < need:
                hit = desc
                break
        (skip if hit else keep).append((p.x, p.y, hit))

    print(f'경로 {path.length:.3f} mm, 후보 {n}, 간격 {step:.4f} mm, 배치 {len(keep)}, 제외 {len(skip)}')
    for x, y, why in skip:
        print(f'  제외 ({x:.3f}, {y:.3f}) {why}')
    with open(a.out, 'w', encoding='utf-8') as fo:
        for x, y, _ in keep:
            fo.write(f'V\n{a.net}\n{x:.4f}\n{y:.4f}\n{a.size}\n{a.hole}\n-\n')


if __name__ == '__main__':
    sys.exit(main())
