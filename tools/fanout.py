# -*- coding: utf-8 -*-
"""커넥터 핀을 엇갈린 두 열의 via 로 팬아웃한다.

    python fanout.py <dump.txt> <출력폴더> [--conn J1] [--skip GND,전원넷] [--pitch 0.6] [--grid 0.1]
                     [--cols=7.9,8.6] [--bend=7.5] [--lead 0.4] [--gap 0.4] [--width 0.2]

덤프 1회(`snippets/dump_copper.pas`) -> 이 스크립트 -> `snippets/apply_plan.pas` 1회.
같은 보드에 다시 돌리면 이전 팬아웃(같은 넷의 Top 선, via 열의 via)을 지우고 새로 만든다.
via 를 옮기고 싶을 때도 --cols / --bend 만 바꿔 다시 돌리면 된다 - 새 via 는 옛 via 를 복제하므로
사용자가 켜 둔 텐팅이 따라온다.

자리 정하기
-----------
- 대상: 커넥터의 숫자 핀 중 넷이 있고 --skip 에 없는 것. 핀이 세로로 늘어선 커넥터만 다룬다.
- via 는 핀 순서대로 --pitch 간격, 두 열을 번갈아. 묶음의 가운데를 핀 묶음 가운데에 맞추되 --grid 위에
  놓는다 (위아래가 대칭이 되는 쪽을 고른다).
- 모양: 패드 -> 수평 -> 45도 -> 수평 -> via (Top). 모든 줄이 같은 x(꺾임점)에서 via 높이에 도달한다.
  45도 구간끼리 평행하고 간격이 pitch/sqrt(2) 로 일정하다.
- --cols / --bend 를 안 주면 자동으로 잡는다:
    꺾임점 = 패드 끝 + --lead + (패드와 via 의 높이 차 중 가장 큰 값),  via 열 = 꺾임점 + --gap, + --gap + 0.7
  핀이 빈자리 없이 붙어 있으면 핀 피치(0.5)와 via 피치(0.6)의 차이가 바깥 핀으로 갈수록 쌓여 45도 구간이
  길어진다. HEAD_LEFT_BLOOD (24핀 연속, 높이 차 최대 1.15) 에서 꺾임점을 패드에 바짝 붙였다가
  "패드와 via 에 너무 가까이 꺾인다" 는 말을 듣고 lead 0.375 / gap 0.4 로 고쳤다. 그 값이 기본이다.
  via 방향은 커넥터 원점에서 핀 열 쪽(= 보드 안쪽).

via
---
보드에 via 가 있으면 그것을 복제한다 (대상 넷의 via > 다른 신호 via > 아무 via). 텐팅은 스크립트로
켤 수 없으므로 복제가 유일한 방법이다. 보드에 via 가 하나도 없으면 기본 via(--via-size/--via-hole)로
만들고 선택해 둔다 - 사용자가 Properties 에서 Tented 를 한 번 체크해야 한다고 알릴 것.

간격 검사는 실제 패드 크기로 한다 (덤프의 패드 크기 칸). 옛 덤프처럼 크기가 없으면 커넥터 패드만
0.3 x 1.2 로 본다. via 가 다른 부품 패드(바이패스 커패시터 등)와 겹치면 오류로 나온다 - 부품을 옮기거나
--cols 를 바꾼다.
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
    ap.add_argument('--conn', default='J1'); ap.add_argument('--skip', default='GND')
    ap.add_argument('--pitch', type=float, default=0.6); ap.add_argument('--grid', type=float, default=0.1)
    ap.add_argument('--cols'); ap.add_argument('--bend', type=float)
    ap.add_argument('--lead', type=float, default=0.375); ap.add_argument('--gap', type=float, default=0.4)
    ap.add_argument('--width', type=float, default=0.2)
    ap.add_argument('--via-size', type=float, default=0.6); ap.add_argument('--via-hole', type=float, default=0.3)
    a = ap.parse_args()
    objs, comps, board = rl.load_board(a.dump)
    skip = set(a.skip.split(','))
    g = a.grid
    G = lambda v: round(round(v / g) * g, 4)
    up = lambda v, s: G(math.ceil(v * s / g - 1e-6) * g * s)          # s 방향으로 그리드 올림

    cp = [p for p in objs if p.kind == 'P' and p.ref.startswith(a.conn + '-')]
    pins = sorted([p for p in cp if p.ref.split('-')[1].isdigit() and p.net and p.net not in skip], key=lambda p: p.y)
    if not pins:
        sys.exit('팬아웃할 핀이 없다.')
    if max(abs(p.x - pins[0].x) for p in pins) > 1e-3:
        sys.exit('핀이 세로 한 줄이 아니다 - 이 도구는 세로 핀 열만 다룬다.')
    nets = {p.net for p in pins}
    px = pins[0].x
    cx = comps[a.conn][0] if a.conn in comps else board.centroid.x
    sgn = 1 if (px - cx if abs(px - cx) > 1e-3 else board.centroid.x - px) > 0 else -1
    half = rl.geom(pins[0], {a.conn[0]: (0.3, 1.2)})[0][1].bounds                # 패드의 x 범위
    pad_end = half[2] if sgn > 0 else half[0]

    n = len(pins)
    mid = (pins[0].y + pins[-1].y) / 2
    span = a.pitch * (n - 1)
    lo = mid - span / 2
    vy0 = min((G(math.ceil(lo / g - 1e-6) * g), G(math.floor(lo / g + 1e-6) * g)),      # 비기면 위쪽 그리드
              key=lambda v: max(abs(v - pins[0].y), abs(v + span - pins[-1].y)))
    vys = [G(vy0 + a.pitch * i) for i in range(n)]
    dmax = max(abs(vys[i] - pins[i].y) for i in range(n))
    bend = a.bend if a.bend is not None else up(pad_end + sgn * (a.lead + dmax), sgn)
    cols = [float(v) for v in a.cols.split(',')] if a.cols else [G(bend + sgn * a.gap), G(bend + sgn * (a.gap + 0.7))]

    lo_x, hi_x = min(cols + [px]) - 0.8, max(cols + [px]) + 0.8
    inx = lambda x: lo_x <= x <= hi_x
    rem = [o for o in objs if o.net in nets and ((o.kind == 'V' and inx(o.x)) or
                                                 (o.kind in 'TA' and o.layer == rl.TOP and all(inx(e[0]) for e in ((o.a, o.b) if o.kind == 'T' else rl.arc_ends(o)))))]
    vias = [o for o in objs if o.kind == 'V']
    tmpl = next((v for v in vias if v.net in nets), next((v for v in vias if v.net not in skip), vias[0] if vias else None))
    vsize = tmpl.size if tmpl else a.via_size

    new = []
    for i, p in enumerate(pins):
        v = (cols[i % 2], vys[i]); dy = abs(v[1] - p.y)
        q = [(p.x, p.y), (bend - sgn * dy, p.y), (bend, v[1]), v]
        new += [rl.new_track(p.net, rl.TOP, s, t, a.width) for s, t in zip(q, q[1:]) if math.dist(s, t) > 1e-6]
        if tmpl:
            new.append(rl.new_via(p.net, v[0], v[1], tmpl, vsize))
        else:
            new.append(rl.Obj(kind='V', net=p.net, x=v[0], y=v[1], size=a.via_size, template=None, hole=a.via_hole))
        print(f'{p.ref:<7}{p.net:<20} 패드 y {p.y:6.2f} -> via ({v[0]:.1f}, {v[1]:5.1f})')
    print(f'핀 {n}개, 꺾임점 x {bend:g}, via 열 x {cols[0]:g} / {cols[1]:g}, via y {vys[0]:g} ~ {vys[-1]:g}, '
          f'패드 끝에서 45도 시작까지 {abs(bend - sgn * dmax - pad_end):.3f}')
    for o in objs:                                             # via 에서 다른 층으로 뽑아 둔 선
        if o.kind == 'T' and o.layer != rl.TOP and o.net in nets:
            for v in rem:
                if v.kind == 'V' and v.net == o.net and (rl.near(o.a, (v.x, v.y)) or rl.near(o.b, (v.x, v.y))):
                    nv = next((x.x, x.y) for x in new if x.kind == 'V' and x.net == o.net)
                    if not rl.near(nv, (v.x, v.y), 0.001):
                        print(f'  주의: {o.net} 의 {o.layer} 선이 옛 via ({v.x:.3f}, {v.y:.3f}) 에 붙어 있다 - 새 via {nv} 로 맞출 것')
    errs = rl.check(new, objs, rem, board=board, pad_size={a.conn[0]: (0.3, 1.2)})
    print(f'삭제 {len(rem)}, 생성 {len(new)}, 간격 오류 {len(errs)}')
    for e in errs[:20]:
        print('  ', e)
    if not tmpl:
        print('보드에 via 가 없어 기본 via 로 만든다 (선택 상태로 남는다) - 사용자가 Tented 를 체크해야 한다.')
    rl.drop_unchanged(new, rem)
    os.makedirs(a.outdir, exist_ok=True)
    print('계획 (삭제, 생성):', rl.write_plan(new, rem, os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt')))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
