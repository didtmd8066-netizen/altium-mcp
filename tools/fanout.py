# -*- coding: utf-8 -*-
"""커넥터 핀을 엇갈린 두 열의 via 로 팬아웃한다.

    python fanout.py <dump.txt> <출력폴더> [--conn J1] [--cols=-7.5,-8.2] [--pitch 0.6]
                     [--bend=-6.5] [--grid 0.1] [--skip GND,LEFT_LUNG_BR] [--width 0.2]

덤프 1회 -> 이 스크립트 -> apply_plan.pas 1회 (2026-10-01 CHEST BLOOD BOT_LEFT J1 22핀).

- 대상: 커넥터의 숫자 핀 중 넷이 있고 --skip 에 없는 것. 핀 y 순서대로 via 를 --pitch 간격으로
  놓고, 열은 --cols 두 값을 번갈아 쓴다. via 묶음의 가운데를 핀 묶음의 가운데에 맞춘다.
- via 좌표와 via 쪽 꺾임점은 --grid 위에 놓는다. 패드 쪽 꺾임점은 패드 y(0.5 피치라 x.25/x.75) 위라
  그리드를 벗어날 수밖에 없다. 처음에 0.05 그리드로 넣었다가 "0.1mm 로 다시" 를 들었다.
- 모양: 패드 -> 수평 -> 45 도 -> 수평 -> via (Top). 이웃과 간격이 안 나오면 꺾임점을 그리드
  한 칸씩 via 쪽으로 옮긴다.
- 이미 있는 팬아웃(같은 넷의 Top 선과 via 열의 via)은 지우고 다시 만든다. 그 via 에서
  다른 층으로 뽑아 둔 선은 건드리지 않으니, via y 가 바뀌면 따로 맞춰야 한다 - 목록을 출력한다.
- via 는 보드에 있는 via 를 복제한다 (텐팅이 따라온다). 대상 넷의 via 가 있으면 그것을, 없으면
  아무 via 나 쓴다. 보드에 via 가 하나도 없으면 사용자에게 하나 놓아 달라고 한다.

핀이 세로로 늘어선 커넥터(핀 x 가 같음)만 다룬다. via 열은 핀의 왼쪽·오른쪽 어느 쪽이든 된다.
"""
import argparse
import math
import os
import sys

from shapely.geometry import LineString, Point

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--conn', default='J1'); ap.add_argument('--cols', default='-7.5,-8.2')
    ap.add_argument('--pitch', type=float, default=0.6); ap.add_argument('--bend', type=float, default=-6.5)
    ap.add_argument('--grid', type=float, default=0.1); ap.add_argument('--skip', default='GND')
    ap.add_argument('--width', type=float, default=0.2)
    a = ap.parse_args()
    objs, comps, board = rl.load_board(a.dump)
    cols = [float(v) for v in a.cols.split(',')]
    skip = set(a.skip.split(','))
    G = lambda v: round(round(v / a.grid) * a.grid, 4)

    pins = sorted([(p.y, p.x, p.net, p.ref) for p in objs if p.kind == 'P' and p.ref.startswith(a.conn + '-')
                   and p.ref.split('-')[1].isdigit() and p.net and p.net not in skip])
    if not pins:
        sys.exit('팬아웃할 핀이 없다.')
    nets = {p[2] for p in pins}
    px = pins[0][1]
    sgn = 1 if cols[0] > px else -1                       # via 가 핀의 어느 쪽에 있는가
    lo, hi = min(cols + [px]) - 0.8, max(cols + [px]) + 0.8
    inx = lambda x: lo <= x <= hi
    rem = [o for o in objs if o.net in nets and ((o.kind == 'V' and inx(o.x)) or
                                                 (o.kind == 'T' and o.layer == rl.TOP and inx(o.a[0]) and inx(o.b[0])))]
    vias = [o for o in objs if o.kind == 'V']
    if not vias:
        sys.exit('보드에 복제할 via 가 없다. 사용자에게 via 하나를 놓아 달라고 할 것.')
    tmpl = next((v for v in vias if v.net in nets), next((v for v in vias if v.net not in skip), vias[0]))

    n = len(pins)
    vy0 = G((pins[0][0] + pins[-1][0]) / 2 - a.pitch * (n - 1) / 2 + a.grid / 2)
    plan = [dict(ref=ref, net=net, p=(x, y), v=(cols[i % 2], G(vy0 + a.pitch * i)), xg=a.bend)
            for i, (y, x, net, ref) in enumerate(pins)]

    def pts(d):
        dy = abs(d['v'][1] - d['p'][1])
        return [d['p'], (d['xg'] - sgn * dy, d['p'][1]), (d['xg'], d['v'][1]), d['v']]

    geom = lambda d: LineString(pts(d)).buffer(a.width / 2).union(Point(d['v']).buffer(tmpl.size / 2))

    def clash(i, xg):
        old, plan[i]['xg'] = plan[i]['xg'], xg
        g = geom(plan[i])
        bad = sum(1 for j in (i - 2, i - 1, i + 1, i + 2) if 0 <= j < n and g.distance(geom(plan[j])) < 0.2 - rl.TOL)
        plan[i]['xg'] = old
        return bad

    cands = [G(a.bend + sgn * a.grid * j) for j in range(5)]
    for _ in range(40):
        moved = False
        for i in range(n):
            if clash(i, plan[i]['xg']) == 0:
                continue
            best = min(cands, key=lambda x: (clash(i, x), abs(x - a.bend)))
            if best != plan[i]['xg']:
                plan[i]['xg'], moved = best, True
        if not moved:
            break

    new = []
    for d in plan:
        q = pts(d)
        new += [rl.new_track(d['net'], rl.TOP, s, t, a.width) for s, t in zip(q, q[1:]) if math.dist(s, t) > 1e-6]
        new.append(rl.new_via(d['net'], d['v'][0], d['v'][1], tmpl))
        print(f"{d['ref']:<7}{d['net']:<20} 패드 y {d['p'][1]:6.2f} -> via ({d['v'][0]:.1f}, {d['v'][1]:5.1f})  꺾임 x {d['xg']:.1f}")
    for o in objs:
        if o.kind == 'T' and o.layer != rl.TOP and o.net in nets:
            for v in rem:
                if v.kind == 'V' and v.net == o.net and (rl.near(o.a, (v.x, v.y)) or rl.near(o.b, (v.x, v.y))):
                    nv = next(d['v'] for d in plan if d['net'] == o.net)
                    if not rl.near(nv, (v.x, v.y), 0.001):
                        print(f'  주의: {o.net} 의 {o.layer} 선이 옛 via ({v.x:.3f}, {v.y:.3f}) 에 붙어 있다 - 새 via {nv} 로 맞출 것')
    errs = rl.check(new, objs, rem, board=board, pad_size={a.conn[0]: (0.3, 1.2)})
    print(f'삭제 {len(rem)}, 생성 {len(new)}, 간격 오류 {len(errs)}')
    for e in errs[:20]:
        print('  ', e)
    rl.drop_unchanged(new, rem)
    os.makedirs(a.outdir, exist_ok=True)
    print('계획 (삭제, 생성):', rl.write_plan(new, rem, os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt')))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
