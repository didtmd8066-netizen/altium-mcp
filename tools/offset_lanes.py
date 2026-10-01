# -*- coding: utf-8 -*-
"""이미 그린 기준 넷의 선을 따라 다른 넷들을 평행(offset)하게 배선하고 각자의 LED via 까지 잇는다.

    python offset_lanes.py <dump.txt> <출력폴더> --ref 기준넷 --nets 넷1,넷2,... [--conn J1]
                           [--pitch 0.4] [--extra 0.02] [--width 0.2] [--via-dist 1.4]

덤프 1회 -> 이 스크립트 -> apply_plan.pas 1회로 끝낸다 (2026-10-01 CHEST BLOOD BOT_LEFT 에서
Branch2_L_LED1~6 을 LED7 선에 맞춰 넣은 작업을 정리한 것. 같은 덤프로 결과가 일치하는지 확인함).

전제
----
- 기준 넷은 커넥터 via 에서 LED via 까지 한 층에 이어져 있다 (트랙 + 아크).
- 따라갈 넷들은 커넥터 쪽에서 기준 넷의 첫 직선과 평행한 스텁이 이미 나와 있다 (팬아웃 직후 상태).
  스텁이 기준선에서 떨어진 거리로 몇 번째 줄인지 정한다 (pitch 의 배수여야 한다).

만드는 것
---------
- 줄: 기준 넷의 직선은 평행 이동, 각진 꺾임은 교점(mitre), 반지름 1mm 이상인 아크는 같은 중심의
  동심 아크로 따라간다. 짧은 조각(0.5mm 미만 트랙, 반지름 1mm 미만 아크)은 손으로 고치다 생긴
  계단으로 보고 무시한다.
- 아크 앞뒤 직선이 중심에서 떨어진 거리가 서로 다르면(기준 넷이 정확한 접선이 아닐 때) 앞 직선에
  맞춰 반지름을 정하고, 뒤 직선들을 그만큼 더 민다. 그래서 아크 뒤로는 기준 넷과의 간격이
  pitch 와 조금 다를 수 있다 - 줄끼리는 pitch 를 지킨다.
- `--extra`: 첫 직선 뒤부터 기준 넷과 더 띄우는 양. 기준 넷의 계단 조각이 바깥으로 불룩하면
  0.4 로는 간격이 모자란다 (0.184mm 까지 붙은 적이 있다).
- 끝: 각 넷은 자기 via 옆을 지나는 직선에서 45 도로 빠져나가 via 로 들어간다. 기준 넷이 다른
  가지로 꺾여 떠난 뒤에는 마지막으로 따라가던 직선을 그대로 연장한다.
- LED via: 넷에 via 가 아직 없으면 LED 패드1 에서 축 방향(패드2 반대쪽)으로 `--via-dist` 만큼
  나간 자리에 놓고 Top 선으로 잇는다. 사용자가 이미 놓은 via 가 있으면 그것을 쓴다.
  via 는 기준 넷의 LED 쪽 via 를 복제한다.

간격 오류가 하나라도 있으면 종료 코드 1. 계획 파일은 그래도 쓰니 내용을 보고 판단한다.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl

unit = lambda a, b: ((b[0] - a[0]) / math.dist(a, b), (b[1] - a[1]) / math.dist(a, b))
ang = lambda v: math.degrees(math.atan2(v[1], v[0])) % 360
dot = lambda a, b: a[0] * b[0] + a[1] * b[1]
sub = lambda a, b: (a[0] - b[0], a[1] - b[1])
add = lambda a, b, t=1.0: (a[0] + t * b[0], a[1] + t * b[1])


def isect(p, d, q, e):
    det = d[0] * (-e[1]) + e[0] * d[1]
    t = ((q[0] - p[0]) * (-e[1]) + e[0] * (q[1] - p[1])) / det
    return add(p, d, t)


def ref_path(objs, net, layer, start, min_seg=0.5, min_r=1.0):
    """기준 넷을 start 에서부터 따라가며 직선·아크 목록으로 정리한다.

    반환: [('L', 시작점, 끝점) | ('A', 중심, 반지름)], 그리고 체인의 끝점.
    """
    el = [o for o in objs if o.net == net and o.layer == layer and o.kind in 'TA']
    used, prims, pt = [], [], start
    while True:
        nx = [o for o in el if not any(o is u for u in used)
              and any(rl.near(e, pt, 0.02) for e in ((o.a, o.b) if o.kind == 'T' else rl.arc_ends(o)))]
        nx = [o for o in nx if o.kind == 'A' or math.dist(o.a, o.b) > 1e-4] or nx
        if not nx:
            break
        o = nx[0]; used.append(o)
        ends = (o.a, o.b) if o.kind == 'T' else rl.arc_ends(o)
        q = ends[1] if rl.near(ends[0], pt, 0.02) else ends[0]
        if o.kind == 'A':
            if o.r >= min_r:
                prims.append(('A', o.c, o.r))
        elif math.dist(pt, q) >= min_seg:
            d = unit(pt, q)
            if prims and prims[-1][0] == 'L' and abs(dot(unit(prims[-1][1], prims[-1][2]), (-d[1], d[0]))) < 0.009 \
                    and abs(dot(sub(q, prims[-1][1]), (-d[1], d[0]))) < 0.02:
                prims[-1] = ('L', prims[-1][1], q)          # 한 직선 위의 조각은 합친다
            else:
                prims.append(('L', pt, q))
        pt = q
    return prims, pt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--ref', required=True); ap.add_argument('--nets', required=True)
    ap.add_argument('--conn', default='J1')
    ap.add_argument('--pitch', type=float, default=0.4); ap.add_argument('--extra', type=float, default=0.02)
    ap.add_argument('--width', type=float, default=0.2); ap.add_argument('--via-dist', type=float, default=1.4)
    ap.add_argument('--layer', default=rl.BOT)
    a = ap.parse_args()
    objs, comps, board = rl.load_board(a.dump)
    cpos = comps[a.conn][:2]
    lay = a.layer

    rv = sorted([v for v in objs if v.kind == 'V' and v.net == a.ref], key=lambda v: math.dist((v.x, v.y), cpos))
    if len(rv) < 2:
        sys.exit('기준 넷에 via 가 2개(커넥터 쪽, LED 쪽) 있어야 한다.')
    prims, end = ref_path(objs, a.ref, lay, (rv[0].x, rv[0].y))
    tmpl = rv[-1]

    plans, new, rem = [], [], []
    for net in a.nets.split(','):
        bt = [o for o in objs if o.kind == 'T' and o.layer == lay and o.net == net]
        if not bt:
            sys.exit(f'{net}: {lay} 에 스텁이 없다.')
        stub = max(bt, key=lambda o: math.dist(o.a, o.b))
        plans.append(dict(net=net, stub=stub, sd=unit(stub.a, stub.b)))
    # 기준 직선 중 스텁과 평행한 첫 직선부터 쓴다 (그 앞은 커넥터 쪽 꺾임)
    i0 = next(i for i, p in enumerate(prims) if p[0] == 'L' and math.dist(p[1], p[2]) >= 2
              and abs(dot(unit(p[1], p[2]), (-plans[0]['sd'][1], plans[0]['sd'][0]))) < 0.02)
    prims = prims[i0:]
    lines = [p for p in prims if p[0] == 'L']
    D = [unit(p[1], p[2]) for p in lines]
    lat0 = dot(sub(plans[0]['stub'].a, lines[0][1]), (D[0][1], -D[0][0]))
    side = 1 if lat0 > 0 else -1                           # +1: 줄들이 진행 방향 오른쪽
    N = [(side * d[1], -side * d[0]) for d in D]            # 줄들이 있는 쪽 법선
    arc_after = {}                                          # 직선 i 뒤의 아크 중심
    li = -1
    for p in prims:
        if p[0] == 'L':
            li += 1
        elif li >= 0 and li + 1 < len(lines):
            arc_after[li] = p[1]

    for pl in plans:
        net, stub = pl['net'], pl['stub']
        lat = dot(sub(stub.a, lines[0][1]), N[0])
        k = round(lat / a.pitch)
        if k < 1 or abs(lat - k * a.pitch) > 0.03:
            sys.exit(f'{net}: 스텁이 기준선에서 {lat:.3f} mm - pitch {a.pitch} 의 배수가 아니다.')
        start = min((stub.a, stub.b), key=lambda p: dot(sub(p, lines[0][1]), D[0]))
        rem += [o for o in objs if o.kind == 'T' and o.layer == lay and o.net == net
                and (o is stub or (math.dist(o.a, o.b) < 1e-4 and min(math.dist(o.a, stub.a), math.dist(o.a, stub.b)) < 0.02))]
        # via
        vs = sorted([v for v in objs if v.kind == 'V' and v.net == net], key=lambda v: math.dist((v.x, v.y), cpos))
        if len(vs) >= 2:
            vp, made = (vs[-1].x, vs[-1].y), False
        else:
            p1 = [p for p in objs if p.kind == 'P' and p.net == net and not p.ref.startswith(a.conn + '-')][0]
            p2 = [p for p in objs if p.kind == 'P' and p.ref.split('-')[0] == p1.ref.split('-')[0] and p is not p1][0]
            vp = add((p1.x, p1.y), unit((p2.x, p2.y), (p1.x, p1.y)), a.via_dist)
            new.append(rl.new_via(net, vp[0], vp[1], tmpl))
            new.append(rl.new_track(net, rl.TOP, (p1.x, p1.y), vp, a.width))
            made = True
        # 줄의 각 직선 (점, 방향), 들어오는 점, 나가는 점, 아크
        sh = [a.pitch * k] + [a.pitch * k + a.extra] * (len(lines) - 1)
        P = [None] * len(lines); entry = [None] * len(lines); exit_ = [None] * len(lines); arcs = {}
        adj = 0.0
        for i in range(len(lines)):
            P[i] = add(lines[i][1], N[i], sh[i] + adj)
            if i == 0:
                entry[0] = start
            if i + 1 == len(lines):
                exit_[i] = add(P[i], D[i], dot(sub(lines[i][2], P[i]), D[i]))
                break
            nxt = add(lines[i + 1][1], N[i + 1], sh[i + 1] + adj)
            c = arc_after.get(i)
            h = dot(sub(c, P[i]), N[i]) if c else 0.0     # >0: 중심이 줄 쪽(안쪽 아크), <0: 바깥쪽 아크
            if c and (h < 0 or h > 0.15):
                adj += dot(sub(c, nxt), N[i + 1]) - h       # 뒤 직선도 같은 거리에서 접하게
                R, sg = abs(h), (1 if h < 0 else -1)
                t1, t2 = add(c, N[i], sg * R), add(c, N[i + 1], sg * R)
                a1, a2 = ang(sub(t1, c)), ang(sub(t2, c))
                if (a2 - a1) % 360 > 180:
                    a1, a2 = a2, a1
                exit_[i], entry[i + 1], arcs[i] = t1, t2, (c, R, a1, a2)
            else:
                m = isect(P[i], D[i], nxt, D[i + 1])
                exit_[i], entry[i + 1] = m, m
        # 어느 직선에서 빠져나갈지: via 가 줄 쪽 옆에 있고, 빠지는 점이 그 직선 구간 안이면 우선
        cand = []
        for i in range(len(lines)):
            latv = dot(sub(vp, P[i]), N[i]); alo = dot(sub(vp, P[i]), D[i])
            s0 = dot(sub(entry[i], P[i]), D[i]); s1 = dot(sub(exit_[i], P[i]), D[i])
            if latv > 0.05 and alo - latv >= s0 + 0.3:
                cand.append((0 if alo - latv <= s1 else 1, latv, i, alo))
        if not cand:
            sys.exit(f'{net}: via ({vp[0]:.3f}, {vp[1]:.3f}) 로 빠져나갈 직선을 못 찾았다.')
        ext, latv, last, alo = min(cand)
        cur = start
        for i in range(last + 1):
            if i == last:
                e = add(P[i], D[i], alo - latv)
                new.append(rl.new_track(net, lay, cur, e, a.width))
                new.append(rl.new_track(net, lay, e, vp, a.width))
            else:
                new.append(rl.new_track(net, lay, cur, exit_[i], a.width))
                if i in arcs:
                    c, R, a1, a2 = arcs[i]
                    new.append(rl.new_arc(net, lay, c, R, a1, a2, a.width))
                cur = entry[i + 1]
        print(f'{net}: {k}번째 줄, via ({vp[0]:.3f}, {vp[1]:.3f}){" 새로 만듦" if made else " 기존"}, '
              f'직선 {last + 1}/{len(lines)} 에서 빠짐{" (연장)" if ext else ""}, 옆 거리 {latv:.2f}')

    errs = rl.check(new, objs, rem, board=board, pad_size={'D': (1.6, 2.4), 'J': (0.3, 1.2)})
    print(f'삭제 {len(rem)}, 생성 {len(new)}, 간격 오류 {len(errs)}')
    for e in errs[:20]:
        print('  ', e)
    rl.drop_unchanged(new, rem)
    os.makedirs(a.outdir, exist_ok=True)
    print('계획 (삭제, 생성):', rl.write_plan(new, rem, os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt')))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
