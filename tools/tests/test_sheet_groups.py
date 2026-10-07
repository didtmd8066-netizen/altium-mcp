# -*- coding: utf-8 -*-
"""sheet_groups.py: 시트별 부품 모으기 (Altium 없이 도는 부분)."""
import os
import sys

from shapely.geometry import Polygon

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plan_script as ps
import sheet_groups as sg

BOARD = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])


def comp(des, x, y, w=2.0, h=1.0, body=True):
    return dict(des=des, x=x, y=y, fp='F', bb=(x - w / 2, y - h / 2, x + w / 2, y + h / 2), has_body=body, w=w, h=h)


def pile(n, prefix='R', x0=120.0):
    """ECO 직후처럼 한 자리에 겹쳐 쌓인 부품들."""
    return [comp(f'{prefix}{i + 1}', x0 + (i % 5) * 0.3, 50 + (i % 7) * 0.3) for i in range(n)]


SHEETS = {**{f'R{i + 1}': (0, '1_PWR') for i in range(30)}, **{f'C{i + 1}': (1, '2_MCU') for i in range(30)},
          'U1': (1, '2_MCU'), 'U5': (1, '2_MCU')}


def test_sheet_designators_reads_mixed_case_records():
    data = (b'|RECORD=34|OwnerIndex=43|Location.X=629|Text=Q21|Name=Designator\x00'
            b'|RECORD=34|OWNERINDEX=2|TEXT=R7|NAME=Designator\x00'
            b'|RECORD=34|Text=R?|Name=Designator\x00'                      # annotate 안 된 부품은 뺀다
            b'|RECORD=41|Text=10k|Name=Value\x00'
            b'|RECORD=340|Text=X9\x00')
    assert sg.sheet_designators(data) == ['Q21', 'R7']


def test_natural_sort_orders_sheet_10_after_9():
    names = ['x_10_HW', 'x_2_PWR', 'x_1_PWR', 'x_9_ENC']
    assert sorted(names, key=sg.natural) == ['x_1_PWR', 'x_2_PWR', 'x_9_ENC', 'x_10_HW']


def test_read_components_uses_body_and_pads(tmp_path):
    p = tmp_path / 'd.txt'
    p.write_text('\n'.join([
        'O|L|0|0', 'O|L|100|0', 'O|L|100|100', 'O|L|0|100',
        'K|Q1|0|10|10|0|Top Layer|D2PAK|5|4|15|19|8|2|12|6|4|1|16|20',       # 바디가 패드보다 크다
        'K|TP1|0|30|30|0|Top Layer|TP|||||29|29|31|31|28|28|32|32',           # 바디 없음 -> 패드
        'K|LOGO|0|50|50|0|Top Layer|LOGO|||||||||45|45|55|55',                # 바디도 패드도 없음 -> 전체
    ]) + '\n', encoding='latin-1')
    board, comps = sg.read_components(str(p))
    assert board.area == 10000
    by = {c['des']: c for c in comps}
    assert by['Q1']['bb'] == (5.0, 2.0, 15.0, 19.0) and by['Q1']['has_body']       # 바디와 패드를 합친 범위
    assert by['TP1']['bb'] == (29.0, 29.0, 31.0, 31.0) and not by['TP1']['has_body']
    assert by['LOGO']['bb'] == (45.0, 45.0, 55.0, 55.0)


def test_plan_groups_by_sheet_without_overlap():
    comps = pile(30, 'R') + pile(30, 'C') + [comp('U1', 121, 51, 12, 12)]
    moves, report, stay = sg.plan(BOARD, comps, SHEETS)
    assert len(moves) == 61 and not stay
    assert [name for (_, name), *_ in report] == ['1_PWR', '2_MCU']
    hits, closest = sg.overlaps(moves, stay)
    assert hits == [] and closest >= 0.6 - 1e-9
    # 묶음은 보드 오른쪽 12mm 밖에서 시작하고, 시트끼리 섞이지 않는다
    assert min(nx - c['w'] / 2 for c, nx, ny in moves) >= 112 - 1e-9
    y_of = lambda pre: [ny for c, nx, ny in moves if c['des'].startswith(pre)]
    assert min(y_of('R')) > max(y_of('C'))
    # 큰 부품이 묶음의 맨 위에 온다
    u1 = next(ny for c, nx, ny in moves if c['des'] == 'U1')
    assert u1 > max(y_of('C'))


def test_parts_on_the_board_stay_unless_all():
    comps = pile(10, 'R') + [comp('C1', 50, 50)]                    # C1 은 보드 안에 배치돼 있다
    moves, report, stay = sg.plan(BOARD, comps, SHEETS)
    assert [c['des'] for c in stay] == ['C1'] and len(moves) == 10
    moves, report, stay = sg.plan(BOARD, comps, SHEETS, move_all=True)
    assert not stay and len(moves) == 11


def test_unannotated_parts_get_their_own_group():
    comps = pile(6, 'R') + [comp('Q?', 121, 51, 10, 15), comp('Q?', 121.2, 51, 10, 15), comp('R?', 122, 52)]
    moves, report, stay = sg.plan(BOARD, comps, SHEETS)
    assert report[-1][0] == sg.UNANNOTATED and report[-1][1] == 3
    assert sg.overlaps(moves, stay)[0] == []
    # 같은 지정자 둘이 서로 다른 자리로 간다
    q = sorted((round(nx, 3), round(ny, 3)) for c, nx, ny in moves if c['des'] == 'Q?')
    assert q[0] != q[1]


def test_unknown_designator_goes_to_no_sheet_and_multipart_follows_base():
    comps = [comp('X9', 120, 50), comp('U5A', 121, 50), comp('R1', 122, 50)]
    moves, report, stay = sg.plan(BOARD, comps, SHEETS)
    groups = {name: n for (_, name), n, *_ in report}
    assert groups == {'1_PWR': 1, '2_MCU': 1, '시트 없음': 1}              # U5A 는 U5 의 시트로


def test_overlap_check_includes_parts_that_do_not_move():
    """옮긴 것끼리만 보면 제자리에 둔 부품 위에 올린 것을 놓친다."""
    parked = comp('J1', 130, 90, 20, 20)                               # 보드 밖에 그대로 둘 부품
    mover = comp('R1', 300, 300)
    hits, _ = sg.overlaps([(mover, 131.0, 91.0)], [parked])
    assert hits == [('R1', 'J1')]
    assert sg.overlaps([(mover, 131.0, 91.0)], [])[0] == []


def test_clusters_start_beyond_parked_parts():
    parked = comp('C1', 50, 50); wide = dict(parked, bb=(40, 40, 160, 60))   # 보드 밖까지 걸친 큰 부품이 보드 안 원점
    moves, report, stay = sg.plan(BOARD, pile(10, 'R') + [wide], SHEETS)
    assert stay and min(nx - c['w'] / 2 for c, nx, ny in moves) >= 160 + 12 - 1e-9
    assert sg.overlaps(moves, stay)[0] == []


def test_tall_stack_wraps_to_next_column():
    sheets = {f'R{i + 1}': (i // 40, f'S{i // 40}') for i in range(400)}
    comps = [comp(f'R{i + 1}', 120 + (i % 3) * 0.2, 50, 6, 6) for i in range(400)]
    moves, report, stay = sg.plan(BOARD, comps, sheets, width=40)
    cols = sorted({round(x1) for _, _, x1, *_ in report})
    assert len(cols) >= 2 and sg.overlaps(moves, stay)[0] == []
    assert all(y1 >= -5 - 60 for _, _, _, y1, _, _ in report)


def test_move_script_and_result(tmp_path):
    mv = tmp_path / 'm.txt'
    mv.write_text('R1|120.00000|50.00000|100000|40000|0\nQ?|130.00000|50.00000|100500|40000|1\n', encoding='ascii')
    text = ps.moves_script(str(mv), 'BOARD_X', str(tmp_path))
    assert '{' not in text and '//' not in text and 'MoveToXY' in text and '.PCBLIB' in text
    assert "Obj6 = '1'" in text                                     # 훑어 찾기는 지정자가 겹친 부품만
    assert ps.parse_moved('moved 611 / skipped 2 | B.PcbDoc') == {'raw': 'moved 611 / skipped 2 | B.PcbDoc', 'moved': 611, 'skipped': 2, 'board': 'B.PcbDoc'}
    assert 'moved' not in ps.parse_moved('NO BOARD')
    empty = tmp_path / 'e.txt'; empty.write_text('', encoding='ascii')
    try:
        ps.moves_script(str(empty))
        assert False
    except ValueError:
        pass
    comp_script = ps.components_script(str(tmp_path / 'c.txt'))
    assert '{' not in comp_script and 'eComponentBodyObject' in comp_script and 'BoundingRectangleNoNameComment' in comp_script
