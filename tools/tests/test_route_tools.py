# -*- coding: utf-8 -*-
"""Altium 없이 도는 검사: 간격 검사, 대칭 대조·계획, 스크립트 조립, PcbDoc 레코드 읽기.

    python -m pytest tools/tests -q

Altium 이 있어야 확인되는 부분(스크립트 실행)은 여기서 다루지 않는다 - 2026-10-06 에
HEAD_RIGHT_BLOOD 사본을 숨겨 열어 덤프 -> 계획 -> 적용 -> 재덤프 -> 대조로 확인했다.
"""
import itertools
import math
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mirror_board as mb
import pcbdoc_dump
import plan_script as ps
import route_lib as rl

TOP, BOT = rl.TOP, rl.BOT


def T(net, a, b, layer=BOT, w=0.2):
    return rl.Obj(kind='T', net=net, sel=False, layer=layer, a=a, b=b, w=w)


def A(net, c, r, a1, a2, layer=BOT, w=0.2):
    return rl.Obj(kind='A', net=net, sel=False, layer=layer, c=c, r=r, a1=a1, a2=a2, w=w)


def V(net, x, y, size=0.6):
    return rl.Obj(kind='V', net=net, sel=False, x=x, y=y, size=size)


def P(net, ref, x, y):
    return rl.Obj(kind='P', net=net, sel=False, ref=ref, x=x, y=y, rot=0.0, sx=0.5, sy=0.5, prot=0.0)


# ── route_lib.check: 외접 사각형으로 거르는 검사가 전수 비교와 같은 답을 내는가 ──────────
def brute_check(new, existing, removed=(), clearance=0.2):
    """모든 쌍을 그대로 비교하는 기준 구현 (간격은 route_lib.core / gap 으로 잰다)."""
    gone = {id(o) for o in removed}
    obs = [(o.net, c, o) for o in existing if id(o) not in gone for c in rl.core(o)]
    ng = [(o.net, c, o) for o in new for c in rl.core(o)]
    errs = []
    for net, c, o in ng:
        for on, oc, oo in obs:
            if on != net and oc[0] == c[0] and rl.gap(c, oc) < clearance - rl.TOL:
                errs.append((o.kind, net, '<->', oo.kind, on, round(rl.gap(c, oc), 4)))
    for (n1, c1, o1), (n2, c2, o2) in itertools.combinations(ng, 2):
        if n1 != n2 and c1[0] == c2[0] and rl.gap(c1, c2) < clearance - rl.TOL:
            errs.append((o1.kind, n1, '<->', o2.kind, n2, round(rl.gap(c1, c2), 4)))
    return errs


def random_objs(rng, n):
    out = []
    for _ in range(n):
        net = rng.choice(['N1', 'N2', 'N3', ''])
        lay = rng.choice([TOP, BOT])
        x, y = rng.uniform(0, 8), rng.uniform(0, 8)
        k = rng.random()
        if k < 0.5:
            out.append(T(net, (x, y), (x + rng.uniform(-2, 2), y + rng.uniform(-2, 2)), lay))
        elif k < 0.75:
            a1 = rng.uniform(0, 360)
            out.append(A(net, (x, y), rng.uniform(0.3, 1.5), a1, (a1 + rng.uniform(10, 200)) % 360, lay))
        elif k < 0.9:
            out.append(V(net, x, y))
        else:
            out.append(P(net, 'R1-1', x, y))
    return out


@pytest.mark.parametrize('seed', range(5))
def test_check_matches_brute_force(seed):
    rng = random.Random(seed)
    existing = random_objs(rng, 60)
    new = [o for o in random_objs(rng, 40) if o.kind != 'P']
    removed = existing[:5]
    assert rl.check(new, existing, removed) == brute_check(new, existing, removed)


def test_check_has_errors_to_compare():
    """위 비교가 빈 목록끼리의 비교가 아님을 확인한다."""
    rng = random.Random(0)
    assert len(brute_check([o for o in random_objs(rng, 40) if o.kind != 'P'], random_objs(rng, 60))) > 10


def test_check_empty_inputs():
    assert rl.check([], []) == []
    assert rl.check([T('A', (0, 0), (1, 0))], []) == []


# ── mirror_board ────────────────────────────────────────────────────────────────────────
def left_board():
    """기준 보드: R1(패드 2개), 한 직선을 두 토막으로 가진 선, 아크, 비아."""
    return [P('SIG_L', 'R1-1', 5, 0), P('GND', 'R1-2', 10, 0),
            T('SIG_L', (5, 0), (6, 0)), T('SIG_L', (6, 0), (7, 0)),          # 일직선 두 토막
            T('SIG_L', (7, 0), (7, 3)),
            A('SIG_L', (8, 3), 1.0, 90, 180),                                # (7,3) -> (8,4)
            T('SIG_L', (8, 4), (12, 4)),
            V('SIG_L', 12, 4), V('GND', 10, -2),
            T('GND', (10, 0), (10, -2), TOP, 0.3)]


def right_pads():
    return [P('SIG_R', 'R1-1', -5, 0), P('GND', 'R1-2', -10, 0)]


def mirrored_copper(nets):
    """기준 보드 배선을 뒤집어 대상 보드에 붙인 것. nets: 기준 넷 -> 대상에 들어간 넷."""
    out = []
    for o in left_board():
        if o.kind != 'P':
            m = mb.mirror(o); m['net'] = nets.get(o.net, o.net); m['sel'] = False
            out.append(m)
    return out


def test_mirror_arc_keeps_endpoints():
    a = A('N', (8, 3), 1.0, 90, 180)
    e1, e2 = rl.arc_ends(a)
    m1, m2 = rl.arc_ends(mb.mirror(a))
    flipped = sorted([(-e1[0], e1[1]), (-e2[0], e2[1])])
    assert all(math.dist(p, q) < 1e-9 for p, q in zip(sorted([m1, m2]), flipped))


def test_net_map_from_pad_positions():
    table, lonely, split = mb.net_map(left_board(), right_pads())
    assert table == {'SIG_L': 'SIG_R', 'GND': 'GND'} and not lonely and not split


def test_net_map_reports_unmirrored_placement():
    tgt = [P('SIG_R', 'R1-1', -5, 0), P('GND', 'R1-2', -10.5, 0)]            # 0.5mm 어긋난 배치
    table, lonely, split = mb.net_map(left_board(), tgt)
    assert [p.ref for p in lonely] == ['R1-2']


def test_identical_mirror_is_all_same():
    tgt = right_pads() + mirrored_copper({'SIG_L': 'SIG_R'})
    res = mb.compare(left_board(), tgt, mb.net_map(left_board(), tgt)[0])
    assert not (res['renet'] or res['missing'] or res['extra'] or res['dust'])
    assert len(res['same']) == 7                                             # 토막 둘이 하나로 합쳐진다


def test_split_track_is_not_a_difference():
    """같은 선을 대상은 한 토막으로 갖고 있어도 차이가 아니다."""
    tgt = right_pads() + [o for o in mirrored_copper({'SIG_L': 'SIG_R'})
                          if not (o.kind == 'T' and o.a[1] == 0 and o.b[1] == 0 and o.layer == BOT)]
    tgt.append(T('SIG_R', (-5, 0), (-7, 0)))
    res = mb.compare(left_board(), tgt, mb.net_map(left_board(), tgt)[0])
    assert not (res['renet'] or res['missing'] or res['extra'])


def test_merge_through_t_junction():
    """갈림길에서도 곧게 이어지는 두 토막은 합치고, 가지는 그대로 둔다."""
    objs = [T('N', (0, 0), (5, 0)), T('N', (5, 0), (9, 0)), T('N', (5, 0), (5, 3))]
    merged = [o for o in mb.merge_collinear(objs) if o.kind == 'T']
    spans = sorted(round(math.dist(o.a, o.b), 6) for o in merged)
    assert spans == [3.0, 9.0]
    assert sorted(len(o.parts) for o in merged) == [1, 2]


def test_merge_keeps_different_width_apart():
    objs = [T('N', (0, 0), (5, 0), w=0.2), T('N', (5, 0), (9, 0), w=0.3)]
    assert len([o for o in mb.merge_collinear(objs) if o.kind == 'T']) == 2


def apply_delete_first(tgt, outdir):
    """apply_plan.pas 를 흉내 낸다: 삭제 키에 걸리는 것을 지우고 new.txt 를 만든다."""
    keys = set(open(os.path.join(outdir, 'del.txt'), encoding='utf-8').read().split())
    kept = [o for o in tgt if o.kind == 'P' or not (rl.keys(o) & keys)]
    rows = open(os.path.join(outdir, 'new.txt'), encoding='utf-8').read().splitlines()
    for i in range(0, len(rows) - 7, 8):
        net, kind = rows[i], rows[i + 1]
        f = [float(v) for v in rows[i + 2:i + 4]]
        if kind == 'T':
            kept.append(T(net, (f[0], f[1]), (float(rows[i + 4]), float(rows[i + 5])), rows[i + 6], float(rows[i + 7])))
        elif kind == 'A':
            lay, w = rows[i + 7].split(':')
            kept.append(A(net, (f[0], f[1]), float(rows[i + 4]), float(rows[i + 5]), float(rows[i + 6]), lay, float(w)))
        else:
            kept.append(V(net, f[0], f[1]))
    return kept


def test_plan_fixes_pasted_copper_without_nets(tmp_path):
    """붙여 넣기만 해서 신호 넷이 빈 대상 보드 -> 계획 적용 뒤 기준과 일치."""
    tgt = right_pads() + mirrored_copper({'SIG_L': ''})
    tgt.append(T('', (-7, 3), (-7.0005, 3)))                                 # 넷 없는 찌꺼기
    ref = left_board()
    table = mb.net_map(ref, tgt)[0]
    res = mb.compare(ref, tgt, table)
    assert len(res['renet']) == 5 and len(res['dust']) == 1 and not res['missing'] and not res['extra']
    nd, nn, errs, default_via = mb.plan(res, tgt, None, str(tmp_path), sync=False)
    assert (nd, nn, errs, default_via) == (7, 5, [], False)                  # 토막 6 + 찌꺼기 1 삭제, 합친 5개 생성
    rows = open(tmp_path / 'new.txt', encoding='utf-8').read().splitlines()
    via = [rows[i:i + 8] for i in range(0, len(rows), 8) if rows[i + 1] == 'V'][0]
    assert via[0] == 'SIG_R' and (via[4], via[5]) == ('-10000', '-2000')     # 견본은 지워지지 않는 GND 비아
    after = apply_delete_first(tgt, str(tmp_path))
    res2 = mb.compare(ref, after, table)
    assert not (res2['renet'] or res2['missing'] or res2['extra'] or res2['dust'])


def test_plan_leaves_target_only_copper_unless_sync(tmp_path):
    tgt = right_pads() + mirrored_copper({'SIG_L': 'SIG_R'}) + [T('SIG_R', (-12, 4), (-12, 6))]
    ref = left_board()
    res = mb.compare(ref, tgt, mb.net_map(ref, tgt)[0])
    assert len(res['extra']) == 1
    assert mb.plan(res, tgt, None, str(tmp_path / 'keep'), sync=False)[:2] == (0, 0)
    assert mb.plan(res, tgt, None, str(tmp_path / 'sync'), sync=True)[:2] == (1, 0)


def test_missing_copper_is_created(tmp_path):
    tgt = right_pads() + [o for o in mirrored_copper({'SIG_L': 'SIG_R'}) if o.kind != 'A']
    ref = left_board()
    res = mb.compare(ref, tgt, mb.net_map(ref, tgt)[0])
    assert [m.kind for m in res['missing']] == ['A']
    m = res['missing'][0]
    assert m.net == 'SIG_R' and m.c == (-8, 3) and (m.a1, m.a2) == (0, 90)


# ── plan_script: 스크립트 조립 ───────────────────────────────────────────────────────────
@pytest.fixture
def plan(tmp_path):
    new = tmp_path / 'new.txt'; dele = tmp_path / 'del.txt'
    new.write_text('\n'.join(['N1', 'T', '0', '0', '1', '0', 'Bottom Layer', '0.2'] * 3) + '\n', encoding='utf-8')
    dele.write_text('T,0,0,1000,0\nT,1000,0,0,0\nV,5,5\n', encoding='utf-8')
    return str(new), str(dele), str(tmp_path)


def test_apply_script_order_and_placeholders(plan):
    new, dele, work = plan
    a = ps.apply_script(new, dele, workdir=work)
    b = ps.apply_script(new, dele, delete_first=True, workdir=work)
    for text in (a, b):
        assert '{' not in text and '//' not in text
        assert 'PCBServer.PreProcess' in text and text.rstrip().endswith('end;')
    assert a.index("'created '") < a.index("'removed '")                     # 기본: 생성 -> 삭제
    assert b.index("'removed '") < b.index("'created '")                     # delete_first: 삭제 -> 생성
    assert 'OList1.Count > 3 then' in a                                      # 상한 = 키 줄 수
    assert 'OList1.Count > 9 then' in ps.apply_script(new, dele, max_delete=9, workdir=work)


def test_apply_script_drops_empty_side(plan):
    new, dele, work = plan
    only_new = ps.apply_script(new, None, workdir=work)
    only_del = ps.apply_script(None, dele, workdir=work)
    assert 'RemovePCBObject' not in only_new and 'AddPCBObject' in only_new
    assert 'AddPCBObject' not in only_del and 'RemovePCBObject' in only_del
    with pytest.raises(ValueError):
        ps.apply_script(None, None, workdir=work)


def test_board_block_guards_the_target(plan):
    _, _, work = plan
    assert ps.board_block() == ['Brd1 := PCBServer.GetCurrentPCBBoard;'] + ps.LIB_GUARD
    assert any('IsLibrary' in ln for ln in ps.LIB_GUARD)
    block = '\n'.join(ps.board_block('HEAD_RIGHT', work))
    assert 'GetPCBBoardByPath' in block and 'Brd1 := nil' in block and 'IsLibrary' in block
    path = block.split("'")[1]
    assert open(path, encoding='mbcs' if sys.platform == 'win32' else 'utf-8').read().splitlines() == ['HEAD_RIGHT', 'HEAD_RIGHT']


def test_board_block_full_path_falls_back_to_file_name(plan, tmp_path):
    _, _, work = plan
    doc = tmp_path / '보드 폴더' / 'X_BOARD.PcbDoc'
    doc.parent.mkdir(); doc.write_bytes(b'')
    path = '\n'.join(ps.board_block(str(doc), work)).split("'")[1]
    full, frag = open(path, encoding='mbcs' if sys.platform == 'win32' else 'utf-8').read().splitlines()
    assert full.endswith('X_BOARD.PcbDoc') and os.path.isabs(full) and frag == 'X_BOARD.PcbDoc'


def test_dump_script(plan):
    _, _, work = plan
    text = ps.dump_script(os.path.join(work, 'd.txt'), workdir=work)
    assert '{' not in text and "SaveToFile('" in text and 'InPolygon' in text and text.rstrip().endswith('end;')


def test_counts_and_result(plan):
    new, dele, _ = plan
    assert ps.count_new(new) == 3 and ps.count_keys(dele) == 3
    assert ps.parse_result('created 10 / removed 12 | B.PcbDoc') == {
        'raw': 'created 10 / removed 12 | B.PcbDoc', 'created': 10, 'removed': 12, 'board': 'B.PcbDoc'}
    assert 'created' not in ps.parse_result('NO BOARD')


# ── pcbdoc_dump: 레코드 읽기 ─────────────────────────────────────────────────────────────
def test_bin_records():
    body = bytes(49)
    data = bytes([4]) + struct.pack('<I', 49) + body + bytes([4]) + struct.pack('<I', 3) + b'abc'
    assert [(t, len(b)) for t, b in pcbdoc_dump._bin_records(data)] == [(4, 49), (4, 3)]


def test_text_records():
    recs = [b'|NAME=GND|X=1mil', b'|NAME=SIG_1']
    data = b''.join(struct.pack('<I', len(r)) + r for r in recs)
    assert [r['NAME'] for r in pcbdoc_dump._text_records(data)] == ['GND', 'SIG_1']


def test_pads_blocks():
    def blk(b):
        return struct.pack('<I', len(b)) + b
    main = bytearray(60)
    main[0] = 1                                                              # Top
    struct.pack_into('<H', main, 3, 7)                                       # 넷 번호
    struct.pack_into('<H', main, 7, 2)                                       # 부품 번호
    struct.pack_into('<iiii', main, 13, 10000000, 20000000, 472441, 1023622)
    struct.pack_into('<d', main, 52, 29.65)
    pad = bytes([2]) + blk(b'\x02A1') + blk(b'\x00') + blk(b'|&|0\x00') + blk(b'\x00') + blk(bytes(main)) + blk(b'')
    out = list(pcbdoc_dump._pads(pad + pad))
    assert [n for n, _ in out] == ['A1', 'A1']
    b = out[0][1]
    assert b[0] == 1 and struct.unpack_from('<H', b, 3)[0] == 7 and struct.unpack_from('<d', b, 52)[0] == 29.65
    with pytest.raises(ValueError):
        list(pcbdoc_dump._pads(b'\x05' + pad))
