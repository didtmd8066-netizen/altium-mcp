# -*- coding: utf-8 -*-
"""평행 묶음이 꺾이는 곳의 같은 반지름 아크들을 동심 아크로 바꾼다.

    python concentric_arcs.py <dump.txt> <출력폴더> [--inner 0.5] [--keep 넷이름]

묶음을 Gloss 로 다듬으면 레인마다 같은 반지름(예: R0.3)의 필렛이 붙어서, 모서리에서
레인이 따로따로 꺾여 보인다. 외곽을 따라 띄운 평행선처럼 보이려면 **중심 하나를
공유하고 반지름이 레인 간격만큼씩 커지는** 아크여야 한다.

쓰는 법
------
1. Altium 에서 그 모서리의 아크들을 선택한다 (레인당 하나).
2. `snippets/dump_copper.pas` 로 덤프한다.
3. 이 스크립트를 돌리면 `del.txt`, `new.txt` 가 나온다 -> `snippets/apply_plan.pas`.

계산
----
각 아크의 양쪽 직선을 A 쪽(끝점이 아크 시작점에 닿는 쪽)과 B 쪽으로 나눈다.
공통 중심 C 는 A 쪽 직선들에서 같은 쪽으로 r_k 만큼 떨어져 있어야 하므로, 레인 k 의
반지름은 `r_k = inner + (가장 안쪽 레인에서 A 쪽 직선까지의 거리)` 로 정해진다.
B 쪽 직선도 C 에서 r_k 떨어져야 한다 - 꺾기 전후 레인 간격이 같아야 성립한다.

간격이 다르면 (예: 세로는 0.6mm 인데 대각은 0.4mm) B 쪽 직선을 평행 이동해서 맞춘다.
이때 `--keep` 으로 준 넷의 B 쪽 직선은 움직이지 않고 기준으로 삼는다. B 쪽 직선의
반대편 끝에 또 다른 필렛 아크가 붙어 있으면 그 아크와 그 너머 직선의 끝점도 같이 옮긴다.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl


def unit(a, b):
    L = math.dist(a, b)
    return ((b[0] - a[0]) / L, (b[1] - a[1]) / L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--inner', type=float, default=0.5, help='가장 안쪽 레인의 반지름 (mm)')
    ap.add_argument('--keep', help='B 쪽 직선을 움직이지 않을 기준 넷. 생략하면 가장 바깥 레인')
    a = ap.parse_args()
    objs = rl.load_dump(a.dump)
    sel = [o for o in objs if o.kind == 'A' and o.sel]
    if len(sel) < 2:
        sys.exit('선택된 아크가 2개 이상이어야 한다.')

    lanes = []
    for arc in sel:
        ps, pe = rl.arc_ends(arc)
        ta = rl.touching(objs, ps, arc.net, arc.layer)
        tb = rl.touching(objs, pe, arc.net, arc.layer)
        if len(ta) != 1 or len(tb) != 1:
            sys.exit(f'{arc.net}: 아크 양쪽에 직선이 하나씩 붙어 있어야 한다 (A {len(ta)}, B {len(tb)})')
        lanes.append(dict(arc=arc, ta=ta[0], tb=tb[0], ps=ps, pe=pe,
                          fa=rl.other_end(ta[0], ps), fb=rl.other_end(tb[0], pe)))

    # 기준 방향: A 쪽은 아크로 들어오는 방향, B 쪽은 아크에서 나가는 방향
    da = unit(lanes[0]['fa'], lanes[0]['ps']); db = unit(lanes[0]['pe'], lanes[0]['fb'])
    turn = da[0] * db[1] - da[1] * db[0]                 # >0 이면 반시계로 꺾는다
    na = (-da[1], da[0]) if turn > 0 else (da[1], -da[0])  # 꺾는 안쪽을 향한 법선
    nb = (-db[1], db[0]) if turn > 0 else (db[1], -db[0])
    off = lambda L: L['ps'][0] * na[0] + L['ps'][1] * na[1]
    lanes.sort(key=off, reverse=True)                    # 안쪽 레인부터
    o0 = off(lanes[0])
    for L in lanes:
        L['r'] = a.inner + (o0 - off(L))

    ref = next((L for L in lanes if L['arc'].net == a.keep), lanes[-1])
    # 중심 C: A 쪽 기준선에서 안쪽으로, B 쪽 기준 직선에서 안쪽으로 각각 r 만큼
    # C·na = off(ref) + r_ref,  C·nb = (ref B 직선의 nb 방향 위치) + r_ref
    ca = off(ref) + ref['r']
    cb = ref['pe'][0] * nb[0] + ref['pe'][1] * nb[1] + ref['r']
    det = na[0] * nb[1] - na[1] * nb[0]
    C = ((ca * nb[1] - cb * na[1]) / det, (na[0] * cb - nb[0] * ca) / det)
    a_start = math.degrees(math.atan2(-na[1], -na[0])); a_end = math.degrees(math.atan2(-nb[1], -nb[0]))
    if turn < 0:
        a_start, a_end = a_end, a_start                  # Altium 아크는 항상 반시계

    new, removed = [], []
    print(f'공통 중심 ({C[0]:.3f}, {C[1]:.3f}), 레인 {len(lanes)}개')
    for L in lanes:
        arc, r = L['arc'], L['r']
        ps = (C[0] - r * na[0], C[1] - r * na[1]); pe = (C[0] - r * nb[0], C[1] - r * nb[1])
        shift = (pe[0] - L['pe'][0]) * nb[0] + (pe[1] - L['pe'][1]) * nb[1]   # B 쪽 직선의 평행 이동량
        removed += [arc, L['ta'], L['tb']]
        new.append(rl.new_arc(arc.net, arc.layer, C, r, a_start, a_end, arc.w))
        new.append(rl.new_track(arc.net, arc.layer, L['fa'], ps, L['ta'].w))
        fb = L['fb']
        if abs(shift) > 1e-4:
            # B 쪽 직선의 반대편 끝에 필렛 아크가 있으면 그것과 그 너머 직선 끝도 같이 옮긴다
            far = [o for o in objs if o.kind == 'A' and o.net == arc.net and o.layer == arc.layer and o is not arc
                   and any(rl.near(p, fb) for p in rl.arc_ends(o))]
            if far:
                fa2 = far[0]; q = [p for p in rl.arc_ends(fa2) if not rl.near(p, fb)][0]
                t2 = rl.touching(objs, q, arc.net, arc.layer)
                if len(t2) == 1:
                    d2 = unit(rl.other_end(t2[0], q), q)             # 너머 직선의 방향 (아크 쪽으로)
                    # 그 직선을 따라 미끄러지면서 nb 방향으로 shift 만큼 가는 벡터
                    k = shift / (d2[0] * nb[0] + d2[1] * nb[1])
                    mv = (k * d2[0], k * d2[1])
                    removed += [fa2, t2[0]]
                    new.append(rl.new_arc(arc.net, arc.layer, (fa2.c[0] + mv[0], fa2.c[1] + mv[1]), fa2.r, fa2.a1, fa2.a2, fa2.w))
                    new.append(rl.new_track(arc.net, arc.layer, rl.other_end(t2[0], q), (q[0] + mv[0], q[1] + mv[1]), t2[0].w))
                    fb = (fb[0] + mv[0], fb[1] + mv[1])
                else:
                    fb = (fb[0] + shift * nb[0], fb[1] + shift * nb[1])
            else:
                fb = (fb[0] + shift * nb[0], fb[1] + shift * nb[1])
        new.append(rl.new_track(arc.net, arc.layer, pe, fb, L['tb'].w))
        print(f'  {arc.net:<20} R {r:.2f}   B 쪽 직선 이동 {shift:+.3f} mm')

    errs = rl.check(new, objs, removed)
    print(f'삭제 {len(removed)}, 생성 {len(new)}, 간격 오류 {len(errs)}')
    for e in errs[:20]:
        print('  ', e)
    os.makedirs(a.outdir, exist_ok=True)
    rl.write_plan(new, removed, os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt'))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
