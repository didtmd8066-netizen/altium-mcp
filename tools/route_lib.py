# -*- coding: utf-8 -*-
"""스크립트 배선용 공통 부품: 보드 덤프 읽기, 간격 검사, 적용 계획 쓰기.

흐름
----
1. 보드를 덤프한다 (선택 여부 포함): MCP 도구 `dump_copper`. 저장된 보드이고 선택 여부가
   필요 없으면 덤프 없이 `.PcbDoc` 경로를 그대로 준다 (`pcbdoc_dump.py`, Altium 을 부르지 않는다).
2. 이 모듈로 덤프를 읽고, 지울 객체와 새 객체를 정한 뒤 `check()` 로 간격을 본다.
3. `write_plan()` 이 만든 두 파일을 MCP 도구 `apply_plan` 으로 적용한다. 보드를 고칠 때는
   `board` 를 꼭 준다 - 사용자가 그사이 다른 보드로 넘어갔으면 아무것도 하지 않고 끝난다.
MCP 도구가 없는 세션에서는 `plan_script.py` 가 찍어 주는 스크립트를 `run_altium_script` 에 넣는다
(`snippets/dump_copper.pas`, `snippets/apply_plan.pas` 를 조립한 것).

간격 검사는 실제 형상으로 한다 (shapely). 트랙은 폭만큼 부풀린 선, 아크는 점열,
비아는 원, 패드는 회전된 사각형. 아크는 Altium 규약대로 시작각 -> 끝각 반시계이고,
끝각이 시작각보다 작으면 0 도를 넘어간 것이다 - 이걸 빼먹으면 길이 0 에 가까운 아크
조각이 한 바퀴 원으로 읽혀 멀쩡한 선이 전부 오류로 뜬다 (2026-10-01 에 겪음).

0.4mm 피치 평행선은 간격이 정확히 0.2mm 다. 판정은 `clearance - TOL` (TOL 0.00005) 로 한다 -
간격은 중심선 거리에서 반지름을 빼 정확히 잰다 (`core()`).

부품을 옮기거나 돌릴 때 (2026-10-01 CHEST BLOOD 에서 정리)
--------------------------------------------------------
패드가 움직이면 거기 붙은 비아·선도 따라가야 한다. 끝점만 옮기면 선 각도가 틀어지므로
각도를 지키는 두 함수를 쓴다.
  slide_chain()  비아 -> 선 -> (아크) -> 레인. 비아가 m 만큼 움직일 때 첫 선과 레인의 방향을
                 그대로 두고 레인 길이만 바꾼다.
  fillet()       패드에서 나온 선과 다음 선을 반지름 r 아크로 다시 잇는다.
아주 조금(um 단위) 움직이면 새 객체와 지울 객체의 키가 같아진다. 그대로 두면 만든 직후
지워지므로 `drop_unchanged()` 로 양쪽에서 빼고 기존 객체를 살린다.

**덤프는 적용 직전에 뜬다.** 사용자가 같은 보드를 만지는 중이면 덤프와 보드가 어긋나
삭제 키와 비아 견본을 못 찾는다 (계획 118 개 중 71 개만 지워진 적이 있다). apply_plan.pas 가
돌려준 개수가 write_plan() 의 반환값과 다르면 부분 적용된 것이니 바로 알리고 멈춘다.
"""
import itertools
import math

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

# 판정은 `간격 < clearance - TOL`. 간격은 core() 로 정확히 재므로 TOL 은 좌표 반올림 몫만 둔다:
# 계획 파일은 소수 5자리(0.00001mm), Altium 내부 단위는 0.00000254mm 다. 예전에는 부풀린 다각형끼리
# 재느라 TOL 이 0.001 이었고, 그 탓에 0.1996 / 0.1998mm 짜리가 "오류 0" 으로 통과해 Altium DRC 에서
# 걸렸다 (2026-10-02 BOT_RIGHT 아크 25개, 2026-10-06 HEAD_LEFT CHEEK11-UP1).
TOL = 0.00005
TOP, BOT = 'Top Layer', 'Bottom Layer'


# ── 덤프 ────────────────────────────────────────────────────────────────
class Obj(dict):
    __getattr__ = dict.get


def _lines(path):
    """덤프 줄들. `.PcbDoc` 를 주면 Altium 없이 파일에서 바로 읽는다 (pcbdoc_dump.py) -
    저장된 상태이고 선택 여부는 없다."""
    if str(path).lower().endswith('.pcbdoc'):
        import pcbdoc_dump
        return pcbdoc_dump.read(path)[0]
    with open(path, encoding='latin-1') as fh:
        return fh.read().splitlines()


def load_dump(path, lines=None):
    out = []
    for line in (lines if lines is not None else _lines(path)):
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
                           r=float(f[6]), a1=float(f[7]), a2=float(f[8]),
                           w=float(f[9]) if len(f) > 9 else 0.2))
        elif k == 'P':
            # 패드 크기 칸(x 크기, y 크기, 패드 회전)은 2026-10-06 부터 덤프에 들어간다 - 없으면 None
            sz = (float(f[7]), float(f[8]), float(f[9])) if len(f) > 9 else (None, None, None)
            # 패드 층 칸은 2026-10-06 부터 (없으면 Top 으로 본다 - 아랫면 SMD 패드가 있는 보드는 새 덤프를 쓸 것)
            out.append(Obj(kind='P', net=net, sel=sel, ref=f[3], x=float(f[4]), y=float(f[5]), rot=float(f[6]),
                           sx=sz[0], sy=sz[1], prot=sz[2], layer=f[10] if len(f) > 10 else TOP))
        elif k == 'R' and len(f) >= 9:
            # 폴리곤이 부은 것이 아닌 리전·필의 외접 사각형. what: copper / cutout(폴리곤 컷아웃) / keepout
            # pts: 실제 꼭짓점 (오프라인 덤프에만 있다). 없으면 외접 사각형뿐이라 간격 판정에는 못 쓴다
            pts = [tuple(float(v) for v in p.split(',')) for p in f[9].split(';')] if len(f) > 9 and f[9] else None
            out.append(Obj(kind='R', net=net, sel=sel, layer=f[3], box=tuple(float(v) for v in f[4:8]), what=f[8], pts=pts))
    return out


def load_board(path):
    """덤프 전체: (동박 객체, {지정자: (x, y, 회전)}, 외곽 Polygon 또는 None)."""
    comps, outline = {}, []
    lines = _lines(path)
    for line in lines:
        f = line.strip().split('|')
        if f[0] == 'C' and len(f) >= 6:
            comps[f[1]] = (float(f[3]), float(f[4]), float(f[5]))
        elif f[0] == 'O' and f[1] == 'L':
            outline.append((float(f[2]), float(f[3])))
        elif f[0] == 'O' and f[1] == 'A':
            pts = arc_points((float(f[4]), float(f[5])), float(f[6]), float(f[7]), float(f[8]))
            if math.dist(pts[-1], (float(f[2]), float(f[3]))) < math.dist(pts[0], (float(f[2]), float(f[3]))):
                pts.reverse()
            outline += pts
    board = Polygon(outline) if len(outline) >= 3 else None
    objs = load_dump(path, lines)
    if board is not None:
        # Altium 은 보드 영역 자체를 Multi Layer 의 넷 없는 리전으로 돌려준다. 장애물로 두면 보드 전체가
        # 막힌 것으로 읽힌다 (스티칭 자리 0개). 외곽 넓이의 절반을 넘는 넷 없는 리전은 버린다 -
        # 폭이 아니라 넓이로 거른다 (좁고 긴 FPCB 는 폭 기준으로 걸러지지 않는다).
        x1, y1, x2, y2 = board.bounds
        full = (x2 - x1) * (y2 - y1)
        objs = [o for o in objs if not (o.kind == 'R' and not o.net and
                                        (o.box[2] - o.box[0]) * (o.box[3] - o.box[1]) > 0.5 * full)]
    return objs, comps, board


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
        if o.sx:                                   # 덤프에 실제 크기가 있으면 그것을 쓴다 (패드 회전은 절대각)
            w, h, rot = o.sx, o.sy, o.prot
        else:
            w, h = (pad_size or {}).get(o.ref.split('-')[0][0], (None, None))
            rot = o.rot
        if w is None:
            return []
        g = affinity.translate(affinity.rotate(box(-w / 2, -h / 2, w / 2, h / 2), rot, origin=(0, 0)), o.x, o.y)
        return [(TOP, g)]
    return []


def fine_arc(c, r, a1, a2, eps=2e-6):
    """현과 호의 차이(새지타)가 eps 이하가 되게 잘게 나눈 점열. 간격을 um 아래까지 잴 때 쓴다."""
    sweep = math.radians((a2 - a1) % 360 or 360)
    step = 2 * math.sqrt(2 * eps / r) if r > 2 * eps else sweep
    return arc_points(c, r, a1, a2, max(24, min(4000, math.ceil(sweep / step))))


def core(o, pad_size=None):
    """객체 -> [(층, 중심 형상, 반지름)]. 구리 = 중심 형상을 반지름만큼 부풀린 것.

    트랙·아크는 중심선과 폭/2, 비아는 점과 지름/2, 패드는 사각형과 0. 두 구리 사이의 간격은
    `중심 형상 사이 거리 - 두 반지름` 으로 정확히 나온다. 부풀린 다각형끼리 재면 원을 다각형으로
    근사한 오차(0.3mm 원에서 0.0004mm)가 끼어, 0.1996mm 같은 위반을 놓친다.
    """
    if o.kind == 'V':
        g = Point(o.x, o.y)
        return [(TOP, g, o.size / 2), (BOT, g, o.size / 2)]
    if o.kind == 'T':
        g = Point(o.a) if math.dist(o.a, o.b) < 1e-9 else LineString([o.a, o.b])
        return [(o.layer, g, o.w / 2)]
    if o.kind == 'A':
        return [(o.layer, LineString(fine_arc(o.c, o.r, o.a1, o.a2)), o.w / 2)]
    if o.kind == 'P':
        lays = (TOP, BOT) if o.layer == 'Multi Layer' else (o.layer or TOP,)
        return [(lay, g, 0.0) for _, g in geom(o, pad_size) for lay in lays]
    return []


def gap(a, b):
    """core() 항목 둘 사이의 구리 간격 (겹치면 음수)."""
    return a[1].distance(b[1]) - a[2] - b[2]


def check(new, existing, removed=(), clearance=0.2, board=None, edge=0.3, pad_size=None):
    """새 객체들의 간격 위반 목록. `removed` 는 지울 기존 객체 (장애물에서 뺀다).

    pad_size: {부품 접두 첫 글자: (축 방향 길이, 폭)} 예 {'D': (1.6, 2.4)}. 없으면 패드는 보지 않는다.
    """
    gone = {id(o) for o in removed}
    obs = [(o.net, c, o) for o in existing if id(o) not in gone for c in core(o, pad_size)]
    ng = [(o.net, c, o) for o in new for c in core(o, pad_size)]
    errs = []
    rmax = max([c[2] for _, c, _ in obs + ng] or [0.0])
    otree = STRtree([c[1] for _, c, _ in obs]) if obs else None
    ntree = STRtree([c[1] for _, c, _ in ng]) if ng else None
    for net, c, o in ng:
        if board is not None:
            d = board.exterior.distance(c[1]) - c[2]
            if d < edge - TOL or not board.contains(c[1]):
                errs.append(('외곽', o.kind, net, round(d, 4)))
        for i in _nearby(otree, c[1], clearance + c[2] + rmax):
            on, oc, oo = obs[i]
            if on != net and oc[0] == c[0] and gap(c, oc) < clearance - TOL:
                errs.append((o.kind, net, '<->', oo.kind, on, round(gap(c, oc), 4)))
    for i, (n1, c1, o1) in enumerate(ng):
        for j in _nearby(ntree, c1[1], clearance + c1[2] + rmax):
            if j <= i:
                continue
            n2, c2, o2 = ng[j]
            if n1 != n2 and c1[0] == c2[0] and gap(c1, c2) < clearance - TOL:
                errs.append((o1.kind, n1, '<->', o2.kind, n2, round(gap(c1, c2), 4)))
    return errs


def _nearby(tree, g, clearance):
    """g 의 외접 사각형에서 clearance 안에 걸치는 형상의 번호 (오름차순). 먼저 이것으로 거른다 -
    객체 수백 개짜리 계획(보드 한 장 복제)을 전수 비교하면 수십 초가 걸린다."""
    if tree is None:
        return ()
    x1, y1, x2, y2 = g.bounds
    return sorted(int(i) for i in tree.query(box(x1 - clearance, y1 - clearance, x2 + clearance, y2 + clearance)))


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
    out = {tag + ',' + ','.join(str(int(c)) for c in combo) for combo in itertools.product(*[_cands(v) for v in vals])}
    if o.kind == 'T':
        # 양방향 모두 낸다. Altium 은 등록할 때 끝점 순서를 바꿔 저장하기도 해서, 한 방향 키만 보면
        # "옛 선과 같은 자리의 새 선"을 못 알아보고 만든 직후 지운다 (2026-10-01 팬아웃에서 3개 사라짐).
        vals = (o.b[0], o.b[1], o.a[0], o.a[1])
        out |= {tag + ',' + ','.join(str(int(c)) for c in combo) for combo in itertools.product(*[_cands(v) for v in vals])}
    return out


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
            if o.template:
                rows += [net, 'V', f'{o.x:.5f}', f'{o.y:.5f}', round(o.template[0] * 1000), round(o.template[1] * 1000), '-', '-']
            else:                                  # 복제할 via 가 없다 -> 기본 via (크기/홀), 만든 뒤 선택 상태로 둔다
                rows += [net, 'V', f'{o.x:.5f}', f'{o.y:.5f}', '-', '-', o.size, o.hole or 0.3]
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


# ── 부품 이동을 따라가는 배선 ───────────────────────────────────────────
def _unit(a, b):
    L = math.dist(a, b)
    return ((b[0] - a[0]) / L, (b[1] - a[1]) / L)


def real_arcs(objs, p, net, layer, tol=0.03):
    """끝점이 p 에 닿는 아크. 길이가 거의 0 인 조각(Gloss 찌꺼기)은 뺀다."""
    return [a for a in objs if a.kind == 'A' and a.net == net and a.layer == layer and (a.a2 - a.a1) % 360 > 1
            and any(near(e, p, tol) for e in arc_ends(a))]


def slide_chain(objs, via_pos, m, net, layer=BOT):
    """비아가 m 만큼 움직일 때 붙은 배선을 각도를 지킨 채 따라가게 한다.

    비아 -> 첫 선 -> (아크) -> 레인 구조에서 첫 선과 레인의 방향은 그대로 두고, 레인 끝과
    아크를 레인 방향으로 al 만큼 민다 (m = al*레인방향 + be*첫선방향 으로 분해).
    구조가 다르거나 두 방향이 평행에 가까우면 첫 선의 끝점만 옮긴다.
    반환: (지울 객체, 새 객체, 설명). 비아 자체는 호출자가 옮긴다.
    """
    nv = (via_pos[0] + m[0], via_pos[1] + m[1])
    t1s = touching(objs, via_pos, net, layer)
    if len(t1s) == 1:
        t1 = t1s[0]
        f1 = other_end(t1, via_pos)
        d1 = _unit(f1, via_pos)
        arcs = real_arcs(objs, f1, net, layer)
        q = [e for e in arc_ends(arcs[0]) if not near(e, f1)][0] if len(arcs) == 1 else f1
        t2 = [x for x in touching(objs, q, net, layer) if x is not t1]
        if len(t2) == 1 and len(arcs) <= 1:
            t2 = t2[0]
            f2 = other_end(t2, q)
            d2 = _unit(f2, q)
            det = d2[0] * d1[1] - d2[1] * d1[0]
            if abs(det) > 0.2:
                al = (m[0] * d1[1] - m[1] * d1[0]) / det
                mv = (al * d2[0], al * d2[1])
                rem = [t1, t2] + arcs
                new = [new_track(net, layer, f2, (q[0] + mv[0], q[1] + mv[1]), t2.w),
                       new_track(net, layer, (f1[0] + mv[0], f1[1] + mv[1]), nv, t1.w)]
                if arcs:
                    a = arcs[0]
                    new.append(new_arc(net, layer, (a.c[0] + mv[0], a.c[1] + mv[1]), a.r, a.a1, a.a2, a.w))
                return rem, new, f'레인 {al:+.3f}'
    return list(t1s), [new_track(net, layer, other_end(t, via_pos), nv, t.w) for t in t1s], '끝점만'


def fillet(p, e, q, f, r):
    """p 에서 방향 e 로 나가는 선과, q 에서 f 쪽으로 가는 선을 반지름 r 아크로 잇는다.

    반환: (아크 중심, 첫 선의 접점, 둘째 선의 접점, 시작각, 끝각) - 각도는 Altium 규약(반시계).
    둘째 선의 q 쪽 끝은 접점으로 옮겨야 한다.
    """
    dn = _unit(q, f)
    n1 = (-e[1], e[0]); s1 = 1 if n1[0] * (f[0] - p[0]) + n1[1] * (f[1] - p[1]) > 0 else -1
    n2 = (-dn[1], dn[0]); s2 = 1 if n2[0] * (p[0] - q[0]) + n2[1] * (p[1] - q[1]) > 0 else -1
    b1 = s1 * r + n1[0] * p[0] + n1[1] * p[1]
    b2 = s2 * r + n2[0] * q[0] + n2[1] * q[1]
    det = n1[0] * n2[1] - n1[1] * n2[0]
    c = ((b1 * n2[1] - b2 * n1[1]) / det, (n1[0] * b2 - n2[0] * b1) / det)
    t1 = (c[0] - s1 * r * n1[0], c[1] - s1 * r * n1[1])
    t2 = (c[0] - s2 * r * n2[0], c[1] - s2 * r * n2[1])
    a1 = math.degrees(math.atan2(t1[1] - c[1], t1[0] - c[0])) % 360
    a2 = math.degrees(math.atan2(t2[1] - c[1], t2[0] - c[0])) % 360
    if (a2 - a1) % 360 > 180:
        a1, a2 = a2, a1
    return c, t1, t2, a1, a2


def remap_ends(objs, mapping, net, layer, skip=(), tol=0.05):
    """끝점이 mapping 의 키에 닿는 선을 새 끝점으로 다시 만든다 (분기점을 민 뒤 간선 정리용).

    반환: (지울 객체, 새 객체). skip 에 든 객체는 건드리지 않는다.
    """
    gone = {id(o) for o in skip}
    rem, new = [], []
    for t in objs:
        if t.kind != 'T' or t.net != net or t.layer != layer or id(t) in gone:
            continue
        a, b = t.a, t.b
        for k, v in mapping.items():
            if near(a, k, tol):
                a = v
            if near(b, k, tol):
                b = v
        if a != t.a or b != t.b:
            rem.append(t); new.append(new_track(net, layer, a, b, t.w))
    return rem, new


def drop_unchanged(new, removed):
    """새 객체와 지울 객체의 키가 같은 쌍을 양쪽에서 뺀다 (um 이하 이동). 뺀 개수를 돌려준다."""
    n = 0
    for o in list(new):
        if o.kind == 'P':
            continue
        ko = keys(o)
        for r in removed:
            if r.kind == o.kind and r.kind != 'V' and ko & keys(r):
                new.remove(o); removed.remove(r); n += 1
                break
    return n
