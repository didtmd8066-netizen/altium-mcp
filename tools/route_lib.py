# -*- coding: utf-8 -*-
"""스크립트 배선용 공통 부품: 보드 덤프 읽기, 간격 검사, 적용 계획 쓰기.

흐름
----
1. `snippets/dump_copper.pas` 로 보드를 덤프한다 (선택 여부 포함).
2. 이 모듈로 덤프를 읽고, 지울 객체와 새 객체를 정한 뒤 `check()` 로 간격을 본다.
3. `write_plan()` 이 만든 두 파일을 `snippets/apply_plan.pas` 에 넘겨 적용한다.

간격 검사는 실제 형상으로 한다 (shapely). 트랙은 폭만큼 부풀린 선, 아크는 점열,
비아는 원, 패드는 회전된 사각형. 아크는 Altium 규약대로 시작각 -> 끝각 반시계이고,
끝각이 시작각보다 작으면 0 도를 넘어간 것이다 - 이걸 빼먹으면 길이 0 에 가까운 아크
조각이 한 바퀴 원으로 읽혀 멀쩡한 선이 전부 오류로 뜬다 (2026-10-01 에 겪음).

0.4mm 피치 평행선은 간격이 정확히 0.2mm 라 부동소수 오차로 0.1999 가 나온다.
그래서 판정은 `clearance - TOL` 로 한다.
"""
import itertools
import math

from shapely import affinity
from shapely.geometry import LineString, Point, box

TOL = 0.001
TOP, BOT = 'Top Layer', 'Bottom Layer'


# ── 덤프 ────────────────────────────────────────────────────────────────
class Obj(dict):
    __getattr__ = dict.get


def load_dump(path):
    out = []
    for line in open(path, encoding='latin-1'):
        f = line.rstrip('\n').split('|')
        if len(f) < 4:
            continue
        k, net, sel = f[0], f[1], f[2] == '-1'
        if k == 'V':
            out.append(Obj(kind='V', net=net, sel=sel, x=float(f[3]), y=float(f[4]), size=float(f[5])))
        elif k == 'T':
            out.append(Obj(kind='T', net=net, sel=sel, layer=f[3], a=(float(f[4]), float(f[5])),
                           b=(float(f[6]), float(f[7])), w=float(f[8])))
        elif k == 'A':
            out.append(Obj(kind='A', net=net, sel=sel, layer=f[3], c=(float(f[4]), float(f[5])),
                           r=float(f[6]), a1=float(f[7]), a2=float(f[8]), w=0.2))
        elif k == 'P':
            out.append(Obj(kind='P', net=net, sel=sel, ref=f[3], x=float(f[4]), y=float(f[5]), rot=float(f[6])))
    return out


# ── 형상 ────────────────────────────────────────────────────────────────
def arc_points(c, r, a1, a2, n=24):
    if a2 < a1:
        a2 += 360
    return [(c[0] + r * math.cos(math.radians(a1 + (a2 - a1) * i / n)),
             c[1] + r * math.sin(math.radians(a1 + (a2 - a1) * i / n))) for i in range(n + 1)]


def geom(o, pad_size=None):
    """객체 -> [(층, shapely 형상)]. 비아는 두 층 모두에 들어간다."""
    if o.kind == 'V':
        g = Point(o.x, o.y).buffer(o.size / 2)
        return [(TOP, g), (BOT, g)]
    if o.kind == 'T':
        if math.dist(o.a, o.b) < 1e-9:
            return [(o.layer, Point(o.a).buffer(o.w / 2))]
        return [(o.layer, LineString([o.a, o.b]).buffer(o.w / 2))]
    if o.kind == 'A':
        return [(o.layer, LineString(arc_points(o.c, o.r, o.a1, o.a2)).buffer(o.w / 2))]
    if o.kind == 'P':
        w, h = (pad_size or {}).get(o.ref.split('-')[0][0], (None, None))
        if w is None:
            return []
        g = affinity.translate(affinity.rotate(box(-w / 2, -h / 2, w / 2, h / 2), o.rot, origin=(0, 0)), o.x, o.y)
        return [(TOP, g)]
    return []


def check(new, existing, removed=(), clearance=0.2, board=None, edge=0.3, pad_size=None):
    """새 객체들의 간격 위반 목록. `removed` 는 지울 기존 객체 (장애물에서 뺀다).

    pad_size: {부품 접두 첫 글자: (축 방향 길이, 폭)} 예 {'D': (1.6, 2.4)}. 없으면 패드는 보지 않는다.
    """
    gone = {id(o) for o in removed}
    obs = [(o.net, lay, g, o) for o in existing if id(o) not in gone for lay, g in geom(o, pad_size)]
    ng = [(o.net, lay, g, o) for o in new for lay, g in geom(o, pad_size)]
    errs = []
    inner = board.buffer(-edge) if board is not None else None
    for net, lay, g, o in ng:
        if inner is not None and not inner.contains(g):
            errs.append(('외곽', o.kind, net, round(board.exterior.distance(g), 3)))
        for on, ol, og, oo in obs:
            if on != net and ol == lay and g.distance(og) < clearance - TOL:
                errs.append((o.kind, net, '<->', oo.kind, on, round(g.distance(og), 3)))
    for (n1, l1, g1, o1), (n2, l2, g2, o2) in itertools.combinations(ng, 2):
        if n1 != n2 and l1 == l2 and g1.distance(g2) < clearance - TOL:
            errs.append((o1.kind, n1, '<->', o2.kind, n2, round(g1.distance(g2), 3)))
    return errs


# ── 적용 계획 ───────────────────────────────────────────────────────────
def _cands(v):
    """um 정수 후보. 스크립트 쪽 Round 와 어긋날 수 있는 반올림 경계값은 양쪽 다 낸다."""
    x = v * 1000
    f = x - math.floor(x)
    return {math.floor(x), math.ceil(x)} if abs(f - 0.5) < 0.3 else {round(x)}


def keys(o):
    if o.kind == 'T':
        vals, tag = (o.a[0], o.a[1], o.b[0], o.b[1]), 'T'
    elif o.kind == 'A':
        vals, tag = (o.c[0], o.c[1], o.r), 'A'
    else:
        vals, tag = (o.x, o.y), 'V'
    return {tag + ',' + ','.join(str(int(c)) for c in combo) for combo in itertools.product(*[_cands(v) for v in vals])}


def new_track(net, layer, a, b, w=0.2):
    return Obj(kind='T', net=net, layer=layer, a=tuple(a), b=tuple(b), w=w)


def new_arc(net, layer, c, r, a1, a2, w=0.2):
    return Obj(kind='A', net=net, layer=layer, c=tuple(c), r=r, a1=a1, a2=a2, w=w)


def new_via(net, x, y, template, size=0.6):
    """template: 복제할 기존 비아 (Obj 또는 (x, y))."""
    t = (template.x, template.y) if isinstance(template, dict) else tuple(template)
    return Obj(kind='V', net=net, x=x, y=y, size=size, template=t)


def write_plan(new, removed, del_path, new_path):
    """apply_plan.pas 입력 두 개를 쓴다. 반환: (삭제 개수, 생성 개수)."""
    dk = set()
    for o in removed:
        dk |= keys(o)
    clash = [o for o in new if keys(o) & dk]
    if clash:
        raise ValueError(f'새 객체 {len(clash)}개가 삭제 키와 같은 좌표다 - 생성 직후 지워진다: {clash[0]}')
    with open(del_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(dk)) + '\n')
    rows = []
    for o in sorted(new, key=lambda o: o.net or '-'):
        net = o.net or '-'
        if o.kind == 'T':
            rows += [net, 'T', f'{o.a[0]:.5f}', f'{o.a[1]:.5f}', f'{o.b[0]:.5f}', f'{o.b[1]:.5f}', o.layer, o.w]
        elif o.kind == 'A':
            rows += [net, 'A', f'{o.c[0]:.5f}', f'{o.c[1]:.5f}', f'{o.r:.5f}', f'{o.a1:.6f}', f'{o.a2:.6f}', f'{o.layer}:{o.w}']
        else:
            rows += [net, 'V', f'{o.x:.5f}', f'{o.y:.5f}', round(o.template[0] * 1000), round(o.template[1] * 1000), '-', '-']
    with open(new_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(map(str, rows)) + '\n')
    return len(removed), len(new)


# ── 기하 도우미 ─────────────────────────────────────────────────────────
def near(a, b, tol=0.03):
    return math.dist(a, b) < tol


def other_end(t, p, tol=0.03):
    return t.b if near(t.a, p, tol) else t.a


def touching(objs, p, net=None, layer=None, kind='T', tol=0.03):
    """끝점이 p 에 닿는 트랙들."""
    return [o for o in objs if o.kind == kind and (net is None or o.net == net) and (layer is None or o.layer == layer)
            and (near(o.a, p, tol) or near(o.b, p, tol))]


def arc_ends(a):
    p = arc_points(a.c, a.r, a.a1, a.a2, 1)
    return p[0], p[-1]
