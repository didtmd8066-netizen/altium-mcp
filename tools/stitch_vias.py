# -*- coding: utf-8 -*-
"""보드 외곽을 따라 스티칭 비아를 놓는 계획을 만든다.

    python stitch_vias.py <보드.PcbDoc 또는 덤프> <출력폴더> [--land-gap 0.51] [--pitch 2] [--redo]
                          [--net GND] [--size 0.6] [--hole 0.3] [--clear 0.25] [--same-pad 0.2] [--same-via 1.2]

덤프 1회(MCP `dump_copper`, 저장된 보드면 `.PcbDoc` 그대로) -> 이 스크립트 -> `apply_plan` 1회.
출력폴더에 del.txt / new.txt 가 생긴다 (적용은 기본 순서: 생성 -> 삭제).

자리 정하기
-----------
- `--land-gap` 은 **외곽에서 비아 land 끝까지**의 거리다 (기본 0.51). 비아 중심은 거기에 지름의 반을
  더한 만큼 안쪽이다 (0.6 비아면 0.81). 사용자가 "land 끝이 외곽에서 0.5 / 0.55 / 0.51" 처럼 land
  기준으로 말하기 때문에 중심 거리가 아니라 이 값으로 받는다 (2026-10-06 HEAD_LEFT_BLOOD).
- 외곽 둘레를 `--pitch` 에 가장 가까운 등간격으로 나누고, 자리마다 안쪽 경로의 가장 가까운 점에 놓는다.
  오목한 모서리에서 두 자리가 한 점으로 몰리면 하나만 남긴다 (이웃과 0.75 x pitch 이상).
- 못 놓는 자리는 건너뛴다. 밀어 넣거나 옮기지 않는다 - 간격이 벌어진 곳은 목록으로 알려 준다.

피하는 것 (간격은 `route_lib.core` 로 정확히 잰다 - 패드는 회전된 실제 사각형)
- 다른 넷·넷 없는 구리, keepout, 폴리곤 컷아웃: land 에서 `--clear` 이상
- 같은 넷 **패드**: land 에서 `--same-pad` 이상. 같은 넷이라도 패드 위에는 올리지 않는다
  (NECK_BLOOD_LEFT 에서 J1 의 GND 패드와 겹쳐 사용자가 직접 지웠다).
- 같은 넷 비아: 중심 간격 `--same-via` 이상.  같은 넷 트랙·아크·구리 리전 위는 괜찮다.
리전은 덤프에 외접 사각형만 있으면 사각형으로 피한다 (넉넉한 쪽으로 틀린다).

--redo
------
이미 넣은 스티칭 비아를 새 기준으로 다시 놓는다. 외곽에서 land 끝까지가 1.0mm 이내인 같은 넷 비아를
옛 스티칭으로 보고 지운다. 자리가 그대로인 비아는 건드리지 않는다. --redo 없이 다시 돌리면 옛 비아는
그대로 두고 그 사이의 빈자리만 채운다.

비아는 보드에 있던 비아를 복제해서 만든다 (텐팅이 따라온다): 같은 넷 비아 > 아무 비아. 비아가 하나도
없으면 기본 비아(--size / --hole)로 만들고 선택해 둔다 - 사용자가 Tented 를 체크해야 한다.
"""
import argparse
import collections
import math
import os
import sys

from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl


def obstacles(objs, net, old, a):
    """[(중심 형상, 반지름, land 에서 띄울 거리, 설명)]. 층은 가리지 않는다 - 비아는 모든 층을 지난다."""
    gone = {id(o) for o in old}
    out = []
    for o in objs:
        if id(o) in gone:
            continue
        same = o.net == net
        if o.kind == 'R':
            if o.what == 'copper' and same:
                continue
            g = Polygon(o.pts).buffer(0) if o.pts and len(o.pts) >= 3 else box(*o.box)
            out.append((g, 0.0, a.same_pad if same else a.clear, f'{o.what} 리전 {o.net or ""}'.strip()))
            continue
        if o.kind in 'TA' and same:
            continue
        for lay, g, r in rl.core(o)[:1] if o.kind == 'V' else rl.core(o):
            if o.kind == 'V' and same:
                out.append((g, 0.0, a.same_via - a.size / 2, f'같은 넷 비아 ({o.x:.2f}, {o.y:.2f})'))
            elif o.kind == 'P' and same:
                out.append((g, r, a.same_pad, f'같은 넷 패드 {o.ref}'))
            else:
                what = f'패드 {o.ref}' if o.kind == 'P' else {'T': '트랙', 'A': '아크', 'V': '비아'}[o.kind]
                out.append((g, r, a.clear, f'{what} {o.net or "(넷 없음)"}'))
    return out


def place(board, obs, a):
    """반환: (놓을 자리 [(x, y)], 건너뛴 자리 [(x, y, 이유)], 자리 수, 실제 간격)."""
    ring = board.exterior
    inset = a.land_gap + a.size / 2
    inner = board.buffer(-inset, join_style=2)
    rings = [inner.exterior] if inner.geom_type == 'Polygon' else [g.exterior for g in inner.geoms]
    tree = STRtree([o[0] for o in obs]) if obs else None
    reach = max([o[1] + o[2] for o in obs] or [0.0]) + a.size / 2
    n = max(1, round(ring.length / a.pitch))
    step = ring.length / n
    keep, skip = [], []
    for i in range(n):
        s = ring.interpolate(i * step)
        q = min((r.interpolate(r.project(s)) for r in rings), key=s.distance) if rings else None
        if q is None or s.distance(q) > inset + 0.25 or abs(ring.distance(q) - inset) > 0.02:
            skip.append((s.x, s.y, '안쪽 경로가 없다 (폭이 좁은 곳)'))
            continue
        why = None
        if tree is not None:
            for j in sorted(int(k) for k in tree.query(q.buffer(reach))):
                g, r, need, desc = obs[j]
                if g.distance(q) - r - a.size / 2 < need - rl.TOL:
                    why = desc
                    break
        if why:
            skip.append((q.x, q.y, why))
        elif all(math.dist((q.x, q.y), p) >= 0.75 * a.pitch for p in keep[-3:] + keep[:3]):
            keep.append((q.x, q.y))
        else:
            skip.append((q.x, q.y, '이웃 자리와 겹친다 (오목한 모서리)'))
    return keep, skip, n, step


def main():
    ap = argparse.ArgumentParser(description='외곽 스티칭 비아 계획')
    ap.add_argument('board', help='.PcbDoc 또는 dump_copper 덤프'); ap.add_argument('outdir')
    ap.add_argument('--land-gap', type=float, default=0.51, help='외곽에서 비아 land 끝까지 (mm)')
    ap.add_argument('--pitch', type=float, default=2.0)
    ap.add_argument('--net', default='GND')
    ap.add_argument('--size', type=float, default=0.6); ap.add_argument('--hole', type=float, default=0.3)
    ap.add_argument('--clear', type=float, default=0.25, help='다른 넷 구리·keepout 과 land 사이')
    ap.add_argument('--same-pad', type=float, default=0.2, help='같은 넷 패드와 land 사이')
    ap.add_argument('--same-via', type=float, default=1.2, help='같은 넷 비아와의 중심 간격')
    ap.add_argument('--redo', action='store_true', help='옛 스티칭 비아를 지우고 다시 놓는다')
    a = ap.parse_args()

    objs, comps, board = rl.load_board(a.board)
    if board is None:
        sys.exit('덤프에 외곽이 없다.')
    board = board.buffer(0)
    vias = [o for o in objs if o.kind == 'V']
    tmpl = next((v for v in vias if v.net == a.net), vias[0] if vias else None)
    if tmpl is not None:
        a.size = round(tmpl.size, 4)             # 복제하면 견본의 크기를 따라간다 - 자리도 그 크기로 잡는다
    ring = board.exterior
    old = [v for v in vias if v.net == a.net and ring.distance(Point(v.x, v.y)) - v.size / 2 <= 1.0] if a.redo else []

    keep, skip, n, step = place(board, obstacles(objs, a.net, old, a), a)
    taken = sum(1 for _, _, w in skip if w.startswith('같은 넷 비아'))      # 이미 스티칭이 있는 자리 (--redo 없이 다시 돌릴 때)
    if len(keep) + taken < 0.5 * n:
        # 자리의 절반도 못 놓았으면 보드를 잘못 읽은 것이다 (보드 전체를 덮는 장애물 등). 이대로 --redo 계획을
        # 쓰면 옛 비아만 지우고 끝난다 - 실제로 시험 사본에서 366개를 지우고 0개를 만든 적이 있다.
        print(f'둘레 자리 {n}개 중 {len(keep) + taken}개만 놓을 수 있다 - 계획을 쓰지 않는다. 막은 것:')
        for why, c in collections.Counter(w for _, _, w in skip).most_common(5):
            print(f'   {c:>4}  {why}')
        return 1
    # 자리가 그대로인 비아는 건드리지 않는다. 비교는 삭제 키(um, 반올림 경계는 양쪽 후보)로 한다 -
    # 단순 반올림으로 비교하면 경계값에서 "옮길 비아" 로 잘못 잡혀 만든 직후 지워진다.
    old_keys = set().union(*[rl.keys(v) for v in old]) if old else set()
    new_keys = set().union(*[rl.keys(rl.Obj(kind='V', x=x, y=y)) for x, y in keep]) if keep else set()
    rem = [v for v in old if not (rl.keys(v) & new_keys)]
    make = [p for p in keep if not (rl.keys(rl.Obj(kind='V', x=p[0], y=p[1])) & old_keys)]
    stay = [v for v in old if rl.keys(v) & new_keys]
    # 견본이 지워질 비아여도 된다 - 적용 순서가 생성 -> 삭제라 만들 때는 살아 있다
    new = [rl.new_via(a.net, x, y, tmpl, a.size) if tmpl is not None else
           rl.Obj(kind='V', net=a.net, x=x, y=y, size=a.size, template=None, hole=a.hole) for x, y in make]

    print(f'둘레 {ring.length:.1f}mm, 자리 {n}개 (간격 {step:.3f}mm), land 끝 {a.land_gap:g}mm = 중심 {a.land_gap + a.size / 2:g}mm 안쪽')
    print(f'배치 {len(keep)}, 건너뜀 {len(skip)}' + (f' | 옛 스티칭 {len(old)}개 중 그대로 {len(stay)}, 삭제 {len(rem)}' if a.redo else ''))
    for why, c in collections.Counter(w.split(' (')[0] if w.startswith('같은 넷 비아') else w for _, _, w in skip).most_common(8):
        print(f'   건너뜀 {c:>3}  {why}')
    order = sorted(keep, key=lambda p: ring.project(Point(p)))
    wide = [(math.dist(p, q), p, q) for p, q in zip(order, order[1:] + order[:1]) if math.dist(p, q) > 1.5 * a.pitch]
    if wide:
        print(f'간격이 {1.5 * a.pitch:g}mm 넘게 벌어진 곳 {len(wide)}군데:')
        for d, p, q in sorted(wide, reverse=True)[:12]:
            print(f'   {d:4.1f}mm  ({p[0]:.1f}, {p[1]:.1f}) ~ ({q[0]:.1f}, {q[1]:.1f})')
    if tmpl is None and new:
        print('보드에 비아가 없어 기본 비아로 만든다 (선택 상태로 남는다) - 사용자가 Tented 를 체크해야 한다.')
    os.makedirs(a.outdir, exist_ok=True)
    nd, nn = rl.write_plan(new, rem, os.path.join(a.outdir, 'del.txt'), os.path.join(a.outdir, 'new.txt'))
    print(f'계획 (삭제, 생성): ({nd}, {nn})  ->  {a.outdir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
