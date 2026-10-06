# -*- coding: utf-8 -*-
"""좌우 대칭 짝 보드: 기준 보드의 배선을 반전해 대상 보드와 대조하고, 모자란 것을 채우는 계획을 만든다.

    python mirror_board.py <기준> <대상>                        대조만 (읽기 전용)
    python mirror_board.py <기준> <대상> --out <폴더> [--sync]   계획(del.txt / new.txt)까지

<기준>, <대상> 은 덤프(`snippets/dump_copper.pas`) 또는 `.PcbDoc` 파일이다. `.PcbDoc` 를 주면
Altium 없이 저장된 파일을 읽는다 (`pcbdoc_dump.py`) - 대조는 Altium 을 한 번도 부르지 않고 끝난다.
계획을 **적용**할 때만 대상 보드를 dump_copper 로 다시 떠서 쓴다 (저장 안 된 변경이 있을 수 있다).

하는 일
-------
1. 넷 짝짓기: 기준 보드의 패드를 x -> -x 로 뒤집은 자리에 있는 대상 보드 패드를 찾아
   기준 넷 -> 대상 넷 표를 만든다 (CHEEK_L_LED3 -> CHEEK_R_LED3). 이름 규칙을 가정하지 않으므로
   커넥터 핀 번호가 뒤집혀 있어도 된다. 짝이 안 맞는 패드가 있으면 배치가 대칭이 아니라는
   뜻이다 - 먼저 배치를 맞춘다 (`dxf_import.py --place-ref ... --mirror`).
2. 기준 보드의 트랙·아크·비아를 뒤집고 넷을 바꿔 "있어야 할 것" 을 만든다.
   아크는 중심 x 만 뒤집고 각도는 (시작, 끝) -> (180-끝, 180-시작).
3. 대상 보드와 대조해 넷으로 나눈다.
     같음      자리·폭·넷이 모두 같다
     넷 다름   자리는 같은데 넷이 다르거나 없다 (붙여 넣기만 하고 넷이 안 들어간 선)
     없음      대상에 없다
     대상에만  기준에 없는 선이 대상에 있다
   한 직선 위에 이어진 토막은 양쪽 모두 하나로 합쳐서 본다 (같은 선을 한쪽은 한 토막, 다른 쪽은
   두 토막으로 갖고 있어도 차이가 아니다). 길이 0.002mm 미만의 찌꺼기 토막은 대조하지 않는다 -
   다만 대상 보드의 찌꺼기에 넷이 없으면 쇼트 위반이 되므로 지울 대상으로 센다.
4. --out 이면 계획을 쓴다: "넷 다름" 은 지우고 다시 만들고, "없음" 은 만든다.
   "대상에만" 은 그대로 둔다 - 사용자가 대상 보드에서 따로 그린 것일 수 있다. --sync 를 주면
   그것도 지워 대상을 기준과 똑같이 만든다.

적용
----
같은 자리에 넷만 바꿔 다시 만들기 때문에 **삭제를 먼저** 해야 한다 (생성을 먼저 하면 방금 만든
객체가 삭제 키에 같이 걸린다). MCP `apply_plan(..., delete_first=True)` 또는 apply_plan.pas 의
삭제 블록을 앞에 놓고 실행한다. 비아 견본은 지워지지 않는 비아에서 고른다.

기존 객체에 넷만 넣는 길(Obj.Net :=)은 Altium 에서 반영되지 않는다. 그래서 지우고 다시 만든다.
Altium 자체 기능으로는 `Design > Netlist > Update Free Primitives From Component Pads` 가 같은
일을 한다 - 패드에 닿은 선부터 넷이 퍼진다. 이 도구의 대조 기능은 그 뒤 검산에도 쓴다.

폴리곤(GND 면)은 다루지 않는다. 폴리곤이 부은 선은 덤프에서 빠지거나(오프라인) 넷이 같아
"같음" 으로 지나간다. 면은 대상 보드에서 Repour 한다.
"""
import argparse
import collections
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_lib as rl

KIND = {'T': '트랙', 'A': '아크', 'V': '비아'}
DUST = 0.002          # 이보다 짧은 트랙은 Altium 이 끌기·Gloss 뒤에 남긴 찌꺼기다 (구리로는 의미가 없다) - 대조에서 뺀다


def mirror(o):
    """x -> -x 로 뒤집은 새 객체 (넷은 그대로)."""
    if o.kind == 'T':
        return rl.Obj(kind='T', net=o.net, layer=o.layer, a=(-o.a[0], o.a[1]), b=(-o.b[0], o.b[1]), w=o.w)
    if o.kind == 'A':
        return rl.Obj(kind='A', net=o.net, layer=o.layer, c=(-o.c[0], o.c[1]), r=o.r,
                      a1=(180 - o.a2) % 360, a2=(180 - o.a1) % 360, w=o.w)
    if o.kind == 'V':
        return rl.Obj(kind='V', net=o.net, x=-o.x, y=o.y, size=o.size)
    if o.kind == 'P':
        return rl.Obj(kind='P', net=o.net, ref=o.ref, x=-o.x, y=o.y)
    raise ValueError(o.kind)


def net_map(ref, tgt, tol=0.05):
    """기준 넷 -> 대상 넷. 반환: (표, 짝 없는 기준 패드, 한 넷이 여러 넷으로 갈린 것)."""
    grid = collections.defaultdict(list)
    for p in tgt:
        if p.kind == 'P':
            grid[(round(p.x), round(p.y))].append(p)
    votes = collections.defaultdict(collections.Counter)
    lonely = []
    for p in ref:
        if p.kind != 'P':
            continue
        m = mirror(p)
        near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in grid.get((round(m.x) + dx, round(m.y) + dy), ())
                if math.dist((q.x, q.y), (m.x, m.y)) <= tol]
        if not near:
            lonely.append(p)
            continue
        q = min(near, key=lambda q: math.dist((q.x, q.y), (m.x, m.y)))
        if p.net or q.net:
            votes[p.net][q.net] += 1
    table = {n: c.most_common(1)[0][0] for n, c in votes.items()}
    split = {n: dict(c) for n, c in votes.items() if len(c) > 1}
    return table, lonely, split


def same_shape(a, b):
    """자리가 같은 객체인가 (넷은 보지 않는다). 좌표는 키(um)로 이미 맞췄다."""
    if a.kind != b.kind:
        return False
    if a.kind == 'V':
        return abs(a.size - b.size) < 0.002
    if a.layer != b.layer or abs(a.w - b.w) > 0.002:
        return False
    if a.kind == 'A':
        return all(abs((x - y + 180) % 360 - 180) < 0.05 for x, y in ((a.a1, b.a1), (a.a2, b.a2)))
    return True


def merge_collinear(objs):
    """한 직선 위에 끝이 맞닿아 이어진 트랙 토막을 하나로 합친다 (넷·층·폭이 같을 때).

    같은 선을 한쪽 보드는 한 토막, 다른 쪽은 두 토막으로 갖고 있으면 구리는 같은데 객체가
    달라 "없음 / 대상에만" 으로 잡힌다. 대조 전에 양쪽을 합쳐 그 잡음을 없앤다.
    합친 트랙은 `parts` 에 원래 토막들을 들고 있다 (지울 때는 원래 토막을 지워야 한다).
    길이가 DUST 보다 짧은 토막은 버린다 - 한쪽 보드에만 있어도 차이로 치지 않는다.
    """
    out = [o for o in objs if o.kind != 'T']
    groups = collections.defaultdict(list)
    for o in objs:
        if o.kind == 'T' and math.dist(o.a, o.b) >= DUST:
            t = rl.Obj(o); t['parts'] = [o]
            groups[(o.net, o.layer, round(o.w, 3))].append(t)
    key = lambda p: (round(p[0], 3), round(p[1], 3))
    for ts in groups.values():
        merged = True
        while merged:
            merged = False
            ends = collections.defaultdict(list)
            for t in ts:
                if math.dist(t.a, t.b) > 1e-6:
                    ends[key(t.a)].append(t); ends[key(t.b)].append(t)
            for k, here in ends.items():
                # 갈림길에서도 곧게 이어지는 두 토막은 합친다 (가지는 합친 선의 중간에 닿은 채로 남는다)
                pair = next(((t, u) for x, t in enumerate(here) for u in here[x + 1:] if t is not u and _straight(t, u, k, key)), None)
                if pair:
                    t, u = pair
                    ft = t.b if key(t.a) == k else t.a
                    fu = u.b if key(u.a) == k else u.a
                    j = rl.Obj(kind='T', net=t.net, layer=t.layer, a=ft, b=fu, w=t.w, parts=t.parts + u.parts)
                    ts[:] = [x for x in ts if x is not t and x is not u] + [j]
                    merged = True
                    break
        out += ts
    return out


def _straight(t, u, k, key):
    """t 와 u 가 점 k 에서 맞닿아 일직선으로 이어지는가 (어긋남 0.5um 이내, 서로 반대쪽)."""
    p = t.a if key(t.a) == k else t.b
    ft = t.b if key(t.a) == k else t.a
    fu = u.b if key(u.a) == k else u.a
    d1 = (ft[0] - p[0], ft[1] - p[1]); d2 = (fu[0] - p[0], fu[1] - p[1])
    L = max(math.hypot(*d1), math.hypot(*d2))
    return abs(d1[0] * d2[1] - d1[1] * d2[0]) / L < 0.0005 and d1[0] * d2[0] + d1[1] * d2[1] < 0


def compare(ref, tgt, table):
    """반환: dict(same, renet, missing, extra, dust). renet 은 (있어야 할 것, 지금 있는 것) 쌍.

    트랙은 양쪽 모두 `merge_collinear` 로 합친 뒤 본다. 대상 쪽 객체의 `parts` 가 실제 보드 객체다.
    """
    want = []
    for o in merge_collinear([o for o in ref if o.kind in 'TAV' and (o.kind == 'V' or o.layer in (rl.TOP, rl.BOT))]):
        m = mirror(o)
        m['net'] = table.get(o.net, o.net) if o.net else ''
        want.append(m)
    have = merge_collinear([o for o in tgt if o.kind in 'TAV' and (o.kind == 'V' or o.layer in (rl.TOP, rl.BOT))])
    index = collections.defaultdict(list)
    for o in have:
        for k in rl.keys(o):
            index[k].append(o)
    used = set()
    out = dict(same=[], renet=[], missing=[], extra=[])
    for m in want:
        cands = []
        for k in rl.keys(m):
            cands += [o for o in index.get(k, ()) if id(o) not in used and same_shape(m, o)]
        hit = next((o for o in cands if o.net == m.net), cands[0] if cands else None)
        if hit is None:
            out['missing'].append(m)
        else:
            used.add(id(hit))
            (out['same'] if hit.net == m.net else out['renet']).append((m, hit))
    out['extra'] = [o for o in have if id(o) not in used]
    # 넷 없는 찌꺼기 토막은 넷 있는 선 위에 얹혀 쇼트 위반으로 잡힌다 - 지울 대상으로 따로 모은다
    out['dust'] = [o for o in tgt if o.kind == 'T' and o.layer in (rl.TOP, rl.BOT) and not o.net and math.dist(o.a, o.b) < DUST]
    return out


def where(o):
    if o.kind == 'T':
        return f'({o.a[0]:.3f}, {o.a[1]:.3f}) -> ({o.b[0]:.3f}, {o.b[1]:.3f})  폭 {o.w:g}  {o.layer}'
    if o.kind == 'A':
        return f'중심 ({o.c[0]:.3f}, {o.c[1]:.3f})  R {o.r:.3f}  {o.a1:.2f}~{o.a2:.2f}  폭 {o.w:g}  {o.layer}'
    return f'({o.x:.3f}, {o.y:.3f})  지름 {o.size:g}'


def report(res, limit):
    count = lambda xs, k: sum(1 for x in xs if (x[0] if isinstance(x, tuple) else x).kind == k)
    print(f'{"":10}{"트랙":>6}{"아크":>6}{"비아":>6}')
    for key, label in (('same', '같음'), ('renet', '넷 다름'), ('missing', '없음'), ('extra', '대상에만')):
        print(f'{label:<8}' + ''.join(f'{count(res[key], k):>8}' for k in 'TAV'))
    for m, hit in res['renet'][:limit]:
        print(f'  넷 다름 {KIND[m.kind]}: {where(hit)}   지금 "{hit.net}" -> "{m.net}"')
    for m in res['missing'][:limit]:
        print(f'  없음 {KIND[m.kind]} {m.net}: {where(m)}')
    for o in res['extra'][:limit]:
        print(f'  대상에만 {KIND[o.kind]} {o.net or "(넷 없음)"}: {where(o)}')
    if res['dust']:
        print(f'  넷 없는 찌꺼기 토막 {len(res["dust"])}개 (길이 {DUST}mm 미만) - 계획에서 지운다')
    for key, label in (('renet', '넷 다름'), ('missing', '없음'), ('extra', '대상에만')):
        if len(res[key]) > limit:
            print(f'  ... {label} {len(res[key]) - limit}개 더 (--limit 로 늘린다)')


def plan(res, tgt, board, outdir, sync):
    """del.txt / new.txt 를 쓴다. 반환: (삭제 수, 생성 수, 간격 오류)."""
    parts = lambda o: o.parts if o.kind == 'T' and o.parts else [o]
    rem = [p for _, hit in res['renet'] for p in parts(hit)] + ([p for o in res['extra'] for p in parts(o)] if sync else []) + list(res['dust'])
    gone = {id(o) for o in rem}
    keep = [o for o in tgt if o.kind == 'V' and id(o) not in gone]
    make = [m for m, _ in res['renet']] + list(res['missing'])
    new = []
    for m in make:
        if m.kind == 'V':
            if keep:                                  # 크기가 같은 비아를 견본으로 (텐팅이 따라온다)
                t = min(keep, key=lambda v: (abs(v.size - m.size), v.net != m.net))
                new.append(rl.new_via(m.net, m.x, m.y, t, m.size))
            else:
                new.append(rl.Obj(kind='V', net=m.net, x=m.x, y=m.y, size=m.size, template=None, hole=0.3))
        elif m.kind == 'T':
            new.append(rl.new_track(m.net, m.layer, m.a, m.b, m.w))
        else:
            new.append(rl.new_arc(m.net, m.layer, m.c, m.r, m.a1, m.a2, m.w))
    errs = rl.check(new, tgt, rem, board=board)
    os.makedirs(outdir, exist_ok=True)
    dk = set()
    for o in rem:
        dk |= rl.keys(o)
    # 같은 자리에 넷만 바꿔 다시 만드므로 새 객체와 삭제 키가 겹치는 것이 정상이다 -
    # write_plan 의 겹침 검사를 쓰지 않고, 적용을 "삭제 먼저" 로 한다.
    with open(os.path.join(outdir, 'del.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(dk)) + ('\n' if dk else ''))
    rl.write_plan(new, [], os.path.join(outdir, '_unused_del.txt'), os.path.join(outdir, 'new.txt'))
    os.remove(os.path.join(outdir, '_unused_del.txt'))
    return len(rem), len(new), errs, (not keep and any(m.kind == 'V' for m in make))


def main():
    ap = argparse.ArgumentParser(description='좌우 대칭 짝 보드 배선 대조·복제')
    ap.add_argument('ref', help='기준 보드 (덤프 또는 .PcbDoc)')
    ap.add_argument('target', help='대상 보드 (덤프 또는 .PcbDoc)')
    ap.add_argument('--out', help='계획을 쓸 폴더 (없으면 대조만)')
    ap.add_argument('--sync', action='store_true', help='대상에만 있는 선도 지운다')
    ap.add_argument('--limit', type=int, default=12, help='종류별로 보여 줄 항목 수')
    a = ap.parse_args()

    ref, _, _ = rl.load_board(a.ref)
    tgt, _, board = rl.load_board(a.target)
    table, lonely, split = net_map(ref, tgt)
    npad = sum(1 for p in ref if p.kind == 'P')
    renamed = sum(1 for k, v in table.items() if k != v)
    print(f'패드 짝 {npad - len(lonely)} / {npad}, 넷 {len(table)}개 (이름이 바뀌는 것 {renamed})')
    for p in lonely[:a.limit]:
        print(f'  짝 없는 패드 {p.ref} {p.net}: 기준 ({p.x:.3f}, {p.y:.3f}) -> 대상 ({-p.x:.3f}, {p.y:.3f}) 에 패드가 없다')
    for n, c in split.items():
        print(f'  넷이 갈린다 {n}: {c}')
    if lonely or split:
        print('배치가 대칭이 아니거나 넷 구성이 다르다 - 아래 결과는 맞는 부분만 본 것이다.')

    res = compare(ref, tgt, table)
    report(res, a.limit)
    ok = not (res['renet'] or res['missing'] or res['extra'] or res['dust'] or lonely or split)
    if ok:
        print('대상 보드의 배선이 기준 보드의 좌우 대칭과 일치한다.')
    if a.out:
        nd, nn, errs, default_via = plan(res, tgt, board, a.out, a.sync)
        print(f'계획: 삭제 {nd}, 생성 {nn}, 간격 오류 {len(errs)}  ->  {a.out} (적용은 삭제 먼저)')
        for e in errs[:a.limit]:
            print('  ', e)
        if default_via:
            print('남는 비아가 없어 기본 비아로 만든다 (선택 상태로 남는다) - 사용자가 Tented 를 체크해야 한다.')
        return 1 if errs else 0
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
