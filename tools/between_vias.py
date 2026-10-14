# -*- coding: utf-8 -*-
"""선택한 나란한 배선들 사이 중앙선에 GND 비아를 놓는 계획을 만든다 (3W 가드·비아 스티칭).

    python between_vias.py <dump_copper 덤프> <출력폴더> [--net GND] [--pitch 2] [--clear 0.2]
                           [--same-via 1.2] [--template x,y]

1. MCP `dump_copper(out, board)` - 사용자가 사이에 비아를 넣을 배선들을 선택해 둔 상태로 뜬다.
2. 이 도구 -> `<출력폴더>/new.txt`, `del.txt` (지우는 것 없음)
3. MCP `apply_plan(new, del, board, expect_removed=0)`

대각선 배선 사이의 중앙은 0.5mm 그리드에 오지 않는다. 그리드로 잡으면 한쪽으로 쏠려 비아 land 가
폴리곤 밖으로 나간다 (2026-10-14 JX2 LH, 중심 간 1.4mm·폭 0.2mm 배선 사이: 0.6mm 비아면 land 끝에서
양쪽 배선까지 0.3mm, 폴리곤 이격 0.2mm 면 폴리곤 안쪽으로 0.1mm 씩 남는다).

- 짝: 선택된 트랙 중 서로 평행하고 1.6mm 보다 가까운 두 개. 한 트랙의 점에서 다른 트랙에 내린
  수선의 발이 그 트랙 안에 있는 구간만 쓴다 (끝의 꺾임 부근은 빠진다).
- 그 구간을 0.05mm 간격으로 훑어 다른 넷 구리와 --clear 이상 떨어지고 같은 넷 비아와 --same-via
  이상 떨어진 자리를 모은 뒤, --pitch 간격으로 최대 개수를 놓고 남는 길이는 양 끝에 고르게 나눈다.
- 비아는 보드의 같은 넷 비아를 복제한다 (텐팅 유지). --template 으로 견본 좌표를 줄 수 있다.
"""
import argparse
import math
import os
import sys

from shapely.geometry import LineString

import route_lib as rl

STEP = 0.05


def pairs(sel):
    out = []
    for i, t1 in enumerate(sel):
        for t2 in sel[i + 1:]:
            a, b = LineString([t1.a, t1.b]), LineString([t2.a, t2.b])
            if a.length == 0 or b.length == 0 or a.distance(b) >= 1.6:
                continue
            cross = (t1.b[0] - t1.a[0]) * (t2.b[1] - t2.a[1]) - (t1.b[1] - t1.a[1]) * (t2.b[0] - t2.a[0])
            if abs(cross) / a.length / b.length < 0.02:
                out.append((t1, t2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--net', default='GND')
    ap.add_argument('--pitch', type=float, default=2.0)
    ap.add_argument('--clear', type=float, default=0.2, help='다른 넷 구리와 land 사이')
    ap.add_argument('--same-via', type=float, default=1.2, help='같은 넷 비아와의 중심 간격')
    ap.add_argument('--template', help='견본 비아 좌표 x,y (없으면 같은 넷 첫 비아)')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    objs, _, board = rl.load_board(a.dump)
    sel = [o for o in objs if o.kind == 'T' and o.sel]
    vias = [o for o in objs if o.kind == 'V']
    same = [v for v in vias if v.net == a.net]
    if a.template:
        tx, ty = (float(v) for v in a.template.split(','))
        tmpl = min(same, key=lambda v: math.dist((v.x, v.y), (tx, ty)))
    else:
        tmpl = same[0] if same else None
    if tmpl is None:
        sys.exit(f'견본으로 쓸 {a.net} 비아가 없다.')
    others = [o for o in objs if not (o.kind == 'R' and o.net == a.net)]
    plan = []
    for t1, t2 in pairs(sel):
        l1, l2 = LineString([t1.a, t1.b]), LineString([t2.a, t2.b])
        free = []
        for i in range(int(l1.length / STEP) + 1):
            p = l1.interpolate(i * STEP)
            s = l2.project(p)
            if s <= 0 or s >= l2.length:
                continue
            q = l2.interpolate(s)
            m = ((p.x + q.x) / 2, (p.y + q.y) / 2)
            if rl.check([rl.new_via(a.net, m[0], m[1], tmpl, tmpl.size)], others, clearance=a.clear, board=board):
                continue
            if same and min(math.dist(m, (v.x, v.y)) for v in same) < a.same_via:
                continue
            free.append((i * STEP, m))
        if not free:
            print(f'{t1.net} | {t2.net}: 자리 없음')
            continue
        lo, hi = free[0][0], free[-1][0]
        k = int((hi - lo) / a.pitch + 1e-9) + 1
        start = lo + (hi - lo - (k - 1) * a.pitch) / 2
        got = []
        for j in range(k):
            c = min(free, key=lambda c: abs(c[0] - (start + j * a.pitch)))
            if abs(c[0] - (start + j * a.pitch)) < STEP * 1.2:
                got.append(c[1])
        print(f'{t1.net} | {t2.net}: 배선 사이 {l1.distance(l2) - (t1.w + t2.w) / 2:.2f}mm, '
              f'비아 {len(got)}개 ' + ', '.join(f'({x:.3f}, {y:.3f})' for x, y in got))
        plan += [rl.new_via(a.net, x, y, tmpl, tmpl.size) for x, y in got]
    os.makedirs(a.outdir, exist_ok=True)
    res = rl.write_plan(plan, [], os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt'))
    print(f'계획 (삭제, 생성): {res}  ->  {a.outdir}')


if __name__ == '__main__':
    main()
