# -*- coding: utf-8 -*-
"""평행 묶음의 모서리를 동심 아크로 만든다. 선택한 것만 보고 알아서 판단한다.

    python corner_arcs.py <dump.txt> <출력폴더> [--inner 0.5]      선택한 것 처리
    python corner_arcs.py <dump.txt> --scan                        어색한 곳 찾기 (계획은 안 만든다)

덤프 1회 -> 이 스크립트 -> apply_plan.pas 1회. 매번 계산 스크립트를 새로 짜지 않는다
(2026-10-01 CHEST BLOOD BOT_LEFT 에서 같은 일을 다섯 번 손으로 했다).

선택에 따라 하는 일
-------------------
- 아크를 선택: 그 모서리의 아크들을 동심 아크로 바꾼다. 줄 하나의 아크가 여러 조각으로 쪼개져
  있어도 된다 (Gloss 뒤에 흔하다). 아크 양 끝에 붙은 직선을 찾아 교점을 구한다.
- 트랙만 선택: 넷마다 두 토막씩 골라져 있으면 끊긴 자리로 보고 동심 아크로 잇는다.
  이미 맞닿아 각지게 꺾인 두 선을 골라도 된다 (그 모서리를 아크로 바꾼다).
두 경우 모두 직선은 접점까지 늘리거나 줄이고, 같은 직선 위에 이어진 조각은 하나로 합친다.

반지름
------
가장 안쪽 줄이 `--inner` (기본 0.5), 바깥으로 줄 간격만큼 커진다. 꺾임각이 작으면(10 도 미만)
0.5 로는 아크 길이가 0.05mm 도 안 되니 `--inner 3` 처럼 크게 준다.
한 줄만 양쪽 간격이 달라 공통 중심에 못 맞추면, 그 줄은 자기 두 직선에 정확히 접하게 하고
중심이 어긋난 양을 출력한다. 0.05mm 넘게 어긋나면 직선을 옮겨 간격부터 맞추는 편이 낫다
(`concentric_arcs.py` 가 한쪽 직선을 평행 이동해서 맞춘다).

--scan 이 찾는 것
-----------------
  각지게 꺾인 곳(3 도 초과), 아크와 직선이 접하지 않는 곳(3 도 초과), 길이 0 에 가까운 아크·트랙.
FPCB 는 각진 꺾임을 남기지 않는다 - CHEST BLOOD 4종이 여기 해당한다.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl

unit = lambda a, b: ((b[0] - a[0]) / math.dist(a, b), (b[1] - a[1]) / math.dist(a, b))
dot = lambda a, b: a[0] * b[0] + a[1] * b[1]
sub = lambda a, b: (a[0] - b[0], a[1] - b[1])
add = lambda a, b, t=1.0: (a[0] + t * b[0], a[1] + t * b[1])
ang = lambda v: math.degrees(math.atan2(v[1], v[0])) % 360
adiff = lambda a, b: abs((a - b + 90) % 180 - 90)          # 방향 차 (180 도 주기)
sweep = lambda a: (a.a2 - a.a1) % 360
ends = lambda o: (o.a, o.b) if o.kind == 'T' else rl.arc_ends(o)


def isect(p, d, q, e):
    det = d[0] * (-e[1]) + e[0] * d[1]
    return add(p, d, ((q[0] - p[0]) * (-e[1]) + e[0] * (q[1] - p[1])) / det)


def tracks(objs, net, layer):
    return [o for o in objs if o.layer == layer and o.net == net and o.kind == 'T' and math.dist(o.a, o.b) > 0.05]


def extend(objs, net, layer, t, near_end):
    """트랙 t 를 near_end 반대쪽으로, 같은 직선 위의 조각을 따라 끝까지 간다. (조각들, 먼 끝)"""
    far = rl.other_end(t, near_end, 0.02)
    ts, a0 = [t], ang(sub(t.b, t.a))
    while True:
        nx = [x for x in tracks(objs, net, layer) if not any(x is y for y in ts)
              and (rl.near(x.a, far, 0.01) or rl.near(x.b, far, 0.01)) and adiff(ang(sub(x.b, x.a)), a0) < 0.3]
        if not nx:
            return ts, far
        ts.append(nx[0]); far = rl.other_end(nx[0], far, 0.01)


def corners_from_selection(objs):
    """선택에서 줄마다 (지울 아크들, A 직선, B 직선) 을 뽑는다. 직선 = (조각들, 모서리 쪽 끝, 먼 끝)."""
    sel = [o for o in objs if o.sel and o.kind in 'TA']
    if not sel:
        sys.exit('선택된 트랙·아크가 없다.')
    out = {}
    arcs = [o for o in sel if o.kind == 'A']
    for net in sorted({o.net for o in sel}):
        lay = next(o.layer for o in sel if o.net == net)
        mine = [a for a in arcs if a.net == net]
        if mine:
            pts = [e for a in mine for e in rl.arc_ends(a)]
            free = [p for p in pts if sum(1 for q in pts if rl.near(p, q, 0.02)) == 1]     # 조각 묶음의 양 끝
            if len(free) != 2:
                sys.exit(f'{net}: 선택한 아크 조각이 한 줄로 이어지지 않는다.')
            lines = []
            for p in free:
                t = [t for t in tracks(objs, net, lay) if rl.near(t.a, p, 0.02) or rl.near(t.b, p, 0.02)]
                if len(t) != 1:
                    sys.exit(f'{net}: 아크 끝 ({p[0]:.3f}, {p[1]:.3f}) 에 직선이 {len(t)}개 붙어 있다.')
                ts, far = extend(objs, net, lay, t[0], p)
                lines.append((ts, p, far))
        else:
            two = [o for o in sel if o.net == net and o.kind == 'T']
            if len(two) != 2:
                sys.exit(f'{net}: 트랙을 넷마다 2개씩 선택해야 한다 ({len(two)}개).')
            n1, n2 = min(((p, q) for p in (two[0].a, two[0].b) for q in (two[1].a, two[1].b)), key=lambda pq: math.dist(*pq))
            lines = []
            for t, ne in ((two[0], n1), (two[1], n2)):
                ts, far = extend(objs, net, lay, t, ne)
                lines.append((ts, ne, far))
        out[net] = (lay, mine, lines[0], lines[1])
    return out


def scan(objs):
    f = lambda p: f'({p[0]:.2f}, {p[1]:.2f})'
    for lay in (rl.BOT, rl.TOP):
        el = [o for o in objs if o.layer == lay and o.kind in 'TA' and o.net]
        deg = [a for a in el if a.kind == 'A' and sweep(a) < 2]
        tiny = [t for t in el if t.kind == 'T' and math.dist(t.a, t.b) < 0.01]
        sharp, kink = [], []

        def out_dir(o, p):
            if o.kind == 'T':
                q = rl.other_end(o, p, 0.02)
                return ang(sub(p, q))
            a = ang(sub(p, o.c))
            return (a + 90) % 360 if rl.near(rl.arc_ends(o)[1], p, 0.02) else (a - 90) % 360

        for net in sorted({o.net for o in el}):
            ok = [o for o in el if o.net == net and not any(o is x for x in deg) and not (o.kind == 'T' and math.dist(o.a, o.b) < 0.05)]
            for i, o in enumerate(ok):
                for p in ends(o):
                    for o2 in ok[i + 1:]:
                        for p2 in ends(o2):
                            if rl.near(p, p2, 0.02):
                                # 셋 이상 만나는 점은 분기점(T 접합)이지 꺾임이 아니다
                                if sum(1 for x in ok for e in ends(x) if rl.near(e, p, 0.02)) > 2:
                                    continue
                                dv =abs((out_dir(o, p) - out_dir(o2, p2) - 180 + 180) % 360 - 180)
                                if dv > 3 and dv < 177:
                                    (sharp if o.kind == o2.kind == 'T' else kink).append((net, p, dv))
        if not (deg or tiny or sharp or kink):
            continue
        print(f'[{lay}]')
        print(f'  각진 꺾임 {len(sharp)}곳')
        for n, p, dv in sorted(sharp, key=lambda k: (round(k[1][0]), k[0])):
            print(f'    {n:<20}{f(p)}  {dv:.1f} 도')
        print(f'  아크와 직선이 접하지 않는 곳 {len(kink)}곳')
        for n, p, dv in kink:
            print(f'    {n:<20}{f(p)}  {dv:.1f} 도')
        print(f'  길이 0 에 가까운 아크 {len(deg)}개, 0.01mm 미만 트랙 {len(tiny)}개')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir', nargs='?')
    ap.add_argument('--inner', type=float, default=0.5); ap.add_argument('--scan', action='store_true')
    a = ap.parse_args()
    objs, comps, board = rl.load_board(a.dump)
    if a.scan:
        scan(objs)
        return 0
    if not a.outdir:
        sys.exit('출력 폴더를 줄 것.')

    J = {}
    for net, (lay, arcs, (ta, na, fa), (tb, nb, fb)) in corners_from_selection(objs).items():
        X = isect(fa, unit(fa, na), fb, unit(fb, nb))
        J[net] = dict(lay=lay, arcs=arcs, ta=ta, tb=tb, fa=fa, fb=fb, X=X, u1=unit(X, fa), u2=unit(X, fb),
                      gap=math.dist(na, nb))
    nets = list(J)
    first = J[nets[0]]
    bis = unit((0, 0), add(first['u1'], first['u2']))          # 꺾임 안쪽 방향
    th = math.acos(max(-1.0, min(1.0, dot(first['u1'], first['u2']))))
    order = sorted(nets, key=lambda n: -dot(J[n]['X'], bis))    # 안쪽 줄부터
    C = add(J[order[0]]['X'], bis, a.inner / math.sin(th / 2))
    print(f'꺾임각 {180 - math.degrees(th):.2f} 도, 공통 중심 ({C[0]:.3f}, {C[1]:.3f}), 줄 {len(nets)}개')
    new, rem = [], []
    for n in order:
        d = J[n]
        n1, n2 = (-d['u1'][1], d['u1'][0]), (-d['u2'][1], d['u2'][0])
        r1, r2 = abs(dot(sub(C, d['X']), n1)), abs(dot(sub(C, d['X']), n2))
        r = (r1 + r2) / 2
        Ck = add(d['X'], bis, r / math.sin(th / 2))             # 두 직선에 정확히 접하는 중심
        tl = r / math.tan(th / 2)
        if tl > min(math.dist(d['X'], d['fa']), math.dist(d['X'], d['fb'])) - 0.05:
            sys.exit(f'{n}: 반지름 {r:.2f} 이면 접점이 직선 밖이다 (필요 길이 {tl:.2f}). --inner 를 줄일 것.')
        tA, tB = add(d['X'], d['u1'], tl), add(d['X'], d['u2'], tl)
        a1, a2 = ang(sub(tA, Ck)), ang(sub(tB, Ck))
        if (a2 - a1) % 360 > 180:
            a1, a2 = a2, a1
        w = d['ta'][0].w
        gone = d['arcs'] + d['ta'] + d['tb']
        # 모서리에 남은 짧은 조각(계단, 쪼개진 아크)도 같이 지운다
        gone += [o for o in objs if o.layer == d['lay'] and o.net == n and o.kind in 'TA' and not any(o is x for x in gone)
                 and all(math.dist(e, d['X']) < tl + 0.45 for e in ends(o))]
        rem += gone
        new += [rl.new_track(n, d['lay'], d['fa'], tA, w), rl.new_track(n, d['lay'], d['fb'], tB, w),
                rl.new_arc(n, d['lay'], Ck, r, a1, a2, w)]
        off = math.dist(Ck, C)
        note = f'  << 양쪽 간격이 달라 중심이 {off:.3f} 어긋남' if off > 0.005 else ''
        print(f'  {n:<20} R {r:.3f}{note}')
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
