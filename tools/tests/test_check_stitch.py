# -*- coding: utf-8 -*-
"""정확한 간격 판정, 보드 검사(board_check), 스티칭 비아(stitch_vias). Altium 없이 돈다.

    python -m pytest tools/tests -q
"""
import argparse
import os
import sys

from shapely.geometry import Point, Polygon

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import board_check as bc
import route_lib as rl
import stitch_vias as sv

TOP, BOT = rl.TOP, rl.BOT
SQUARE = ['O|L|0|0', 'O|L|20|0', 'O|L|20|20', 'O|L|0|20']


def T(net, a, b, layer=BOT, w=0.2):
    return rl.Obj(kind='T', net=net, sel=False, layer=layer, a=a, b=b, w=w)


def A(net, c, r, a1, a2, layer=BOT, w=0.2):
    return rl.Obj(kind='A', net=net, sel=False, layer=layer, c=c, r=r, a1=a1, a2=a2, w=w)


def V(net, x, y, size=0.6):
    return rl.Obj(kind='V', net=net, sel=False, x=x, y=y, size=size)


def P(net, ref, x, y, sx=0.5, sy=0.5, layer=TOP):
    return rl.Obj(kind='P', net=net, sel=False, ref=ref, x=x, y=y, rot=0.0, sx=sx, sy=sy, prot=0.0, layer=layer)


def write_dump(tmp_path, lines):
    p = tmp_path / 'd.txt'
    p.write_text('\n'.join(lines) + '\n', encoding='latin-1')
    return str(p)


# ── 정확한 간격: 0.1996mm 를 놓치지 않는가 ──────────────────────────────────────────────
def test_check_catches_sub_micron_shortfall():
    """HEAD_LEFT_BLOOD 에서 DRC 에 걸린 경우: 0.4mm 피치 평행선이 0.0004mm 모자란다."""
    a = T('N1', (0, 0), (10, 0))
    assert rl.check([T('N2', (0, 0.4), (10, 0.4))], [a]) == []                 # 정확히 0.2
    errs = rl.check([T('N2', (0, 0.3996), (10, 0.3996))], [a])
    assert len(errs) == 1 and errs[0][-1] == 0.1996


def test_check_concentric_arcs_exact():
    """동심 아크는 반지름 차이만큼 정확히 떨어져 있다 (다각형 근사 오차가 끼면 안 된다)."""
    inner = A('N1', (0, 0), 3.0, 10, 80)
    assert rl.check([A('N2', (0, 0), 3.4, 10, 80)], [inner]) == []
    assert rl.check([A('N2', (0, -0.0007), 3.4, 10, 80)], [inner]) != []        # 중심이 0.0007 어긋남 (HEAD_LEFT 의 경우)
    assert rl.check([A('N2', (0, 0.0007), 3.4, 10, 80)], [inner]) == []         # 멀어지는 쪽으로 어긋난 것은 위반이 아니다
    assert rl.check([V('N2', 0.8, 0)], [V('N1', 0, 0)]) == []                   # land 사이 정확히 0.2
    assert rl.check([V('N2', 0.7996, 0)], [V('N1', 0, 0)]) != []


def test_bottom_pad_only_blocks_bottom():
    pad = P('N1', 'R1-1', 0, 0, 1, 1, BOT)
    assert rl.check([T('N2', (-2, 0), (2, 0), TOP)], [pad]) == []
    assert rl.check([T('N2', (-2, 0), (2, 0), BOT)], [pad]) != []


def test_multi_layer_pad_blocks_both_sides():
    pad = P('N1', 'J1-1', 0, 0, 1, 1, 'Multi Layer')
    assert rl.check([T('N2', (-2, 0), (2, 0), TOP)], [pad]) != []
    assert rl.check([T('N2', (-2, 0), (2, 0), BOT)], [pad]) != []


def test_load_board_drops_board_sized_region(tmp_path):
    path = write_dump(tmp_path, SQUARE + ['R||0|Multi Layer|0|0|20|20|copper',
                                          'R|GND|0|Top Layer|1|1|3|3|copper',
                                          'R||0|Top Layer|5|5|6|6|cutout|5,5;6,5;6,6',
                                          'P|GND|0|J1-1|10|10|0|1|2|90|Bottom Layer',
                                          'P|GND|0|J1-2|11|10|0|1|2|90'])
    objs, comps, board = rl.load_board(path)
    regs = [o for o in objs if o.kind == 'R']
    assert [(o.net, o.what) for o in regs] == [('GND', 'copper'), ('', 'cutout')]
    assert regs[1].pts == [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)] and regs[0].pts is None
    assert [o.layer for o in objs if o.kind == 'P'] == [BOT, TOP]             # 층 칸이 없는 옛 덤프는 Top


# ── board_check ─────────────────────────────────────────────────────────────────────────
def test_board_check_clearance_and_netless():
    objs = [T('N1', (0, 0), (10, 0)), T('N2', (0, 0.3996), (10, 0.3996)), T('', (0, 5), (1, 5)),
            P('N1', 'R1-1', 0, 0, layer=BOT), P('N3', 'R1-2', 0.1, 0, layer=BOT)]   # 패드끼리는 보지 않는다
    items, tree, rmax = bc.build(objs)
    hits = bc.clearance(items, tree, rmax, 0.2)
    assert [round(h[0], 4) for h in hits if h[2].kind == h[3].kind == 'T' and {h[2].net, h[3].net} == {'N1', 'N2'}] == [0.1996]
    assert any(h[2].kind != h[3].kind and 'P' in (h[2].kind, h[3].kind) for h in hits)     # 패드 - 다른 넷 선은 본다
    assert not any(h[2].kind == 'P' and h[3].kind == 'P' for h in hits)


def test_board_check_skips_bbox_only_region():
    """외접 사각형뿐인 리전은 실제 모양을 몰라 간격을 말하지 않는다. 꼭짓점이 있으면 잰다."""
    track = T('N1', (0, 0), (10, 0), TOP)
    tri = [(0, 0.5), (10, 5), (0, 5)]                                           # 사각형으로 보면 선에 0.4 까지 온다
    bbox_only = rl.Obj(kind='R', net='N2', sel=False, layer=TOP, box=(0, 0.25, 10, 5), what='copper', pts=None)
    real = rl.Obj(kind='R', net='N2', sel=False, layer=TOP, box=(0, 0.25, 10, 5), what='copper', pts=[(0, 0.25), (10, 5), (0, 5)])
    for reg, expect in ((bbox_only, 0), (real, 1)):
        items, tree, rmax = bc.build([track, reg])
        assert len(bc.clearance(items, tree, rmax, 0.2)) == expect


def test_board_check_dangling_and_open_nets():
    objs = [P('N1', 'R1-1', 0, 0, layer=BOT), P('N1', 'R2-1', 10, 0, layer=BOT), P('N1', 'R3-1', 10, 8, layer=BOT),
            T('N1', (0, 0), (10, 0)),                                          # R1 - R2 연결
            T('N1', (10, 8), (10, 5)),                                         # R3 에서 나오다 만 선
            P('GND', 'R1-2', 0, 5, layer=BOT), P('GND', 'R2-2', 10, -5, layer=BOT)]   # 면으로 이어지는 넷
    items, tree, rmax = bc.build(objs)
    dangling, open_nets = bc.connectivity(objs, items, tree, rmax, {'GND'})
    assert [(n, e) for n, e, _ in dangling] == [('N1', (10, 5))]
    assert open_nets == {'N1': [['R1-1', 'R2-1'], ['R3-1']]}
    assert set(bc.connectivity(objs, items, tree, rmax, set())[1]) == {'N1', 'GND'}


def test_board_check_via_bridges_layers():
    objs = [P('N1', 'R1-1', 0, 0), T('N1', (0, 0), (5, 0), TOP), V('N1', 5, 0), T('N1', (5, 0), (9, 0), BOT),
            P('N1', 'R2-1', 9, 0, layer=BOT)]
    items, tree, rmax = bc.build(objs)
    assert bc.connectivity(objs, items, tree, rmax, set()) == ([], {})
    no_via = [o for o in objs if o.kind != 'V']
    items, tree, rmax = bc.build(no_via)
    dangling, open_nets = bc.connectivity(no_via, items, tree, rmax, set())
    assert len(dangling) == 2 and open_nets == {'N1': [['R1-1'], ['R2-1']]}


def test_board_check_debris():
    objs = [T('N1', (0, 0), (0.001, 0)), A('N1', (5, 5), 0.3, 10, 10.5), V('N1', 3, 3), V('N1', 3, 3), T('N1', (0, 2), (4, 2))]
    tiny, deg, dup = bc.debris(objs)
    assert len(tiny) == 1 and len(deg) == 1 and [len(g) for g in dup] == [2]


def test_board_check_cli(tmp_path, capsys, monkeypatch):
    path = write_dump(tmp_path, SQUARE + ['T|N1|0|Bottom Layer|2|2|18|2|0.2', 'T|N2|0|Bottom Layer|2|2.3996|18|2.3996|0.2',
                                          'P|N1|0|R1-1|2|2|0|0.1|0.1|0|Bottom Layer', 'P|N1|0|R2-1|18|2|0|0.1|0.1|0|Bottom Layer',
                                          'P|N2|0|R1-2|2|2.3996|0|0.1|0.1|0|Bottom Layer', 'P|N2|0|R2-2|18|2.3996|0|0.1|0.1|0|Bottom Layer'])
    monkeypatch.setattr(sys, 'argv', ['board_check.py', path])
    assert bc.main() == 1
    out = capsys.readouterr().out
    assert '0.1996mm' in out and '5. 끊긴 끝 (GND 제외): 이상 없음' in out and '6. 미연결 넷 (GND 제외): 이상 없음' in out
    clean = write_dump(tmp_path, SQUARE + ['T|N1|0|Bottom Layer|2|2|18|2|0.2',
                                           'P|N1|0|R1-1|2|2|0|0.1|0.1|0|Bottom Layer', 'P|N1|0|R2-1|18|2|0|0.1|0.1|0|Bottom Layer'])
    monkeypatch.setattr(sys, 'argv', ['board_check.py', clean])
    assert bc.main() == 0 and '문제 없음' in capsys.readouterr().out


# ── stitch_vias ─────────────────────────────────────────────────────────────────────────
def stitch_args(**kw):
    base = dict(land_gap=0.51, pitch=2.0, net='GND', size=0.6, hole=0.3, clear=0.25, same_pad=0.2, same_via=1.2)
    base.update(kw)
    return argparse.Namespace(**base)


BOARD = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])


def test_stitch_land_gap_is_measured_to_the_land():
    a = stitch_args()
    keep, skip, n, step = sv.place(BOARD, [], a)
    assert n == 40 and len(keep) + len(skip) == 40 and len(keep) >= 36
    for x, y in keep:
        assert abs(BOARD.exterior.distance(Point(x, y)) - a.size / 2 - 0.51) < 1e-6
    wide = sv.place(BOARD, [], stitch_args(land_gap=0.55))[0]
    assert abs(BOARD.exterior.distance(Point(wide[5])) - 0.85) < 1e-6


def test_stitch_avoids_pads_tracks_and_cutouts():
    a = stitch_args()
    objs = [P('GND', 'J1-3', 10, 0.81, 3, 1),                                                    # 같은 넷 패드
            T('SIG', (0.81, 4), (0.81, 12), BOT),                                                # 다른 넷 선
            T('GND', (19.19, 4), (19.19, 12), TOP, 0.3),                                         # 같은 넷 선 - 위에 놓아도 된다
            rl.Obj(kind='R', net='', sel=False, layer=TOP, box=(4, 19, 8, 20), what='cutout', pts=None)]
    keep, skip, n, step = sv.place(BOARD, sv.obstacles(objs, 'GND', [], a), a)
    pad = rl.core(objs[0])[0][1]
    assert all(pad.distance(Point(p)) - 0.3 >= 0.2 - 1e-9 for p in keep)
    assert not any(abs(x - 0.81) < 0.01 and 3.4 < y < 12.6 for x, y in keep)
    assert sum(1 for x, y in keep if abs(x - 19.19) < 0.01 and 4 < y < 12) >= 3
    assert not any(3.45 < x < 8.55 and y > 18.2 for x, y in keep)
    reasons = {w for _, _, w in skip}
    assert {'같은 넷 패드 J1-3', '트랙 SIG', 'cutout 리전'} <= reasons


def test_stitch_rotated_pad_uses_real_shape():
    """45 도 돌아간 패드는 외접 사각형이 아니라 실제 모양으로 피한다."""
    a = stitch_args()
    pad = rl.Obj(kind='P', net='SIG', sel=False, ref='D1-1', x=10, y=2.6, rot=45.0, sx=0.4, sy=3.0, prot=45.0, layer=TOP)
    g = rl.core(pad)[0][1]
    keep, skip, n, step = sv.place(BOARD, sv.obstacles([pad], 'GND', [], a), a)
    bottom = [p for p in keep if abs(p[1] - 0.81) < 0.01]
    assert all(g.distance(Point(p)) - 0.3 >= 0.25 - 1e-9 for p in bottom)
    x1, y1, x2, y2 = g.bounds                                                   # 외접 사각형 안쪽에도 놓인 자리가 있다
    assert any(x1 - 0.55 < p[0] < x2 + 0.55 for p in bottom)


def stitch_cli(tmp_path, monkeypatch, dump_lines, *opts):
    path = write_dump(tmp_path, dump_lines)
    out = tmp_path / 'plan'
    monkeypatch.setattr(sys, 'argv', ['stitch_vias.py', path, str(out)] + list(opts))
    return sv.main(), out


def test_stitch_redo_is_idempotent(tmp_path, monkeypatch, capsys):
    lines = SQUARE + ['V|SIG|0|10|10|0.6']                      # 견본으로 쓸 비아 하나
    code, out = stitch_cli(tmp_path, monkeypatch, lines, '--redo')
    assert code == 0
    rows = (out / 'new.txt').read_text(encoding='utf-8').splitlines()
    vias = [rows[i:i + 8] for i in range(0, len(rows), 8)]
    assert len(vias) >= 36 and all(v[0] == 'GND' and (v[4], v[5]) == ('10000', '10000') for v in vias)
    lines2 = lines + ['V|GND|0|%s|%s|0.6' % (v[2], v[3]) for v in vias]
    code, out = stitch_cli(tmp_path, monkeypatch, lines2, '--redo')
    assert code == 0
    assert (out / 'new.txt').read_text(encoding='utf-8').strip() == '' and (out / 'del.txt').read_text(encoding='utf-8').strip() == ''
    # 기준을 바꾸면 옛 비아를 전부 지우고 새로 놓는다
    code, out = stitch_cli(tmp_path, monkeypatch, lines2, '--redo', '--land-gap', '0.7')
    assert len((out / 'new.txt').read_text(encoding='utf-8').splitlines()) // 8 >= 30
    assert len((out / 'del.txt').read_text(encoding='utf-8').split()) >= len(vias)
    # --redo 없이 다시 돌리면 옛 비아는 두고 빈자리만 본다 (여기서는 빈자리가 없다)
    code, out = stitch_cli(tmp_path, monkeypatch, lines2)
    assert (out / 'del.txt').read_text(encoding='utf-8').strip() == ''


def test_stitch_refuses_when_board_is_blocked(tmp_path, monkeypatch, capsys):
    """보드 전체가 막힌 것으로 읽히면 옛 비아만 지우는 계획을 쓰지 않는다."""
    lines = SQUARE + ['V|GND|0|0.81|10|0.6', 'R|SIG|0|Top Layer|0|0|20|20|copper']
    code, out = stitch_cli(tmp_path, monkeypatch, lines, '--redo')
    assert code == 1 and not (out / 'del.txt').exists()
    assert '계획을 쓰지 않는다' in capsys.readouterr().out
