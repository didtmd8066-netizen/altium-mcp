# -*- coding: utf-8 -*-
"""rules_rul.py: .RUL 읽기·쓰기와 클리어런스 매트릭스 편집."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rules_rul as rr

# 실제 Export 파일의 한 줄과 같은 꼴 (값만 줄였다)
LINE = ('SELECTION=FALSE|LAYER=TOP|LOCKED=FALSE|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|KEEPOUT=FALSE|UNIONINDEX=0|'
        'RULEKIND=Clearance|NETSCOPE=AnyNet|LAYERKIND=SameLayer|SCOPE1EXPRESSION=(IsVia + IsPad)|'
        'SCOPE2EXPRESSION=(IsVia + IsPad)|NAME=Clearance_Via and Pad|ENABLED=TRUE|PRIORITY=4|COMMENT= |'
        'UNIQUEID=KSTVIAPAD|DEFINEDBYLOGICALDOCUMENT=FALSE|GAP=7.874mil|GENERICCLEARANCE=7.874mil|'
        'IGNOREPADTOPADCLEARANCEINFOOTPRINT=TRUE|'
        'OBJECTCLEARANCES=ClearanceObj_Track-ClearanceObj_Poly:196850;ClearanceObj_SMDPad-ClearanceObj_Via:118110;'
        'ClearanceObj_Via-ClearanceObj_Fill:0')


def test_text_round_trip_is_byte_identical(tmp_path):
    src = tmp_path / 'a.RUL'
    src.write_bytes((LINE + '\n').encode('latin-1').replace(b'\n', rr.END) * 2)
    rules = rr.load(str(src))
    assert [r.name for r in rules] == ['Clearance_Via and Pad'] * 2
    out = tmp_path / 'b.RUL'
    rr.save(rules, str(out))
    assert out.read_bytes() == src.read_bytes()


def test_cells_in_mm():
    r = rr.Rule(LINE)
    assert round(r.generic_mm(), 4) == 0.2
    cells = {k: round(v, 4) for k, v in r.cells().items()}
    assert cells == {('Track', 'Poly'): 0.5, ('SMDPad', 'Via'): 0.3, ('Via', 'Fill'): 0.0}


def test_pair_order_and_aliases():
    assert rr.pair('Poly', 'Track') == ('Track', 'Poly')          # 파일에는 앞선 종류가 왼쪽
    assert rr.pair('hole', 'via') == ('Via', 'Hole')
    assert rr.pair('pad', 'polygon') == ('SMDPad', 'Poly')
    with pytest.raises(ValueError):
        rr.pair('Trace', 'Poly')
    assert rr.parse_cell('poly-track=0.5') == (('Track', 'Poly'), 0.5)
    assert rr.parse_cell(' Via - Hole = 0.3mm ') == (('Via', 'Hole'), 0.3)
    with pytest.raises(ValueError):
        rr.parse_cell('Track/Poly:0.5')


def test_set_cells_drops_default_valued_and_sorts():
    r = rr.Rule(LINE)
    cells = r.cells()
    cells[rr.pair('Poly', 'Track')] = 0.2                            # 기본값과 같아지면 목록에서 빠진다
    cells[rr.pair('Hole', 'Arc')] = 0.3
    r.set_cells(cells)
    assert r.get('OBJECTCLEARANCES') == ('ClearanceObj_Arc-ClearanceObj_Hole:118110;'
                                         'ClearanceObj_SMDPad-ClearanceObj_Via:118110;ClearanceObj_Via-ClearanceObj_Fill:0')


def test_set_generic_keeps_explicit_cells():
    r = rr.Rule(LINE)
    r.set_generic(0.3)
    assert r.get('GAP') == r.get('GENERICCLEARANCE') == '11.811mil'
    cells = {k: round(v, 4) for k, v in r.cells().items()}
    assert cells == {('Track', 'Poly'): 0.5, ('Via', 'Fill'): 0.0}   # 0.3 이던 칸은 새 기본값과 같아 빠진다


def test_new_rule_fields():
    r = rr.new_rule('Clearance_HV', 0.5, "InNetClass('HV')", 'All')
    r.set_cells({('Poly', 'Track'): 1.0, ('Via', 'Hole'): 0.5})
    t = r.text()
    assert t.startswith('SELECTION=FALSE|') and '|RULEKIND=Clearance|NETSCOPE=DifferentNetsOnly|' in t
    assert "|SCOPE1EXPRESSION=InNetClass('HV')|SCOPE2EXPRESSION=All|NAME=Clearance_HV|" in t
    assert '|GAP=19.685mil|GENERICCLEARANCE=19.685mil|' in t
    assert t.endswith('OBJECTCLEARANCES=ClearanceObj_Track-ClearanceObj_Poly:393701')
    assert len(r.get('UNIQUEID')) == 8 and r.get('UNIQUEID').isupper()
    assert rr.new_rule('a', 0.2).get('UNIQUEID') != rr.new_rule('a', 0.2).get('UNIQUEID')


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, 'argv', ['rules_rul.py'] + [str(a) for a in argv])
    return rr.main()


def test_cli_copy_with_edits(tmp_path, monkeypatch, capsys):
    src = tmp_path / 'a.RUL'
    other = LINE.replace('NAME=Clearance_Via and Pad', 'NAME=Clearance').replace('RULEKIND=Clearance|NETSCOPE', 'RULEKIND=Clearance|NETSCOPE')
    width = LINE.replace('RULEKIND=Clearance', 'RULEKIND=Width').replace('NAME=Clearance_Via and Pad', 'NAME=Width')
    src.write_bytes(b''.join(x.encode('latin-1') + rr.END for x in (LINE, other, width)))
    out = tmp_path / 'b.RUL'
    assert run(monkeypatch, 'copy', src, out, '--names', 'Clearance', '--set', 'Clearance:Via-Hole=0.3', '--gap', 'Clearance=0.25') == 0
    rules = rr.load(str(out))
    assert [r.name for r in rules] == ['Clearance']                  # Width 와 이름 안 고른 룰은 빠진다
    assert round(rules[0].generic_mm(), 4) == 0.25
    assert round(rules[0].cells()[('Via', 'Hole')], 4) == 0.3 and round(rules[0].cells()[('Track', 'Poly')], 4) == 0.5
    with pytest.raises(SystemExit):
        run(monkeypatch, 'copy', src, out, '--names', 'Nope')
    assert run(monkeypatch, 'copy', src, out, '--kind', 'all') == 0 and len(rr.load(str(out))) == 3


def test_cli_new_like_existing(tmp_path, monkeypatch, capsys):
    src = tmp_path / 'a.RUL'
    src.write_bytes(LINE.encode('latin-1') + rr.END)
    out = tmp_path / 'n.RUL'
    assert run(monkeypatch, 'new', out, '--name', 'Clearance_New', '--gap', '0.2', '--scope1', 'IsVia',
               '--like', f'{src}:Clearance_Via and Pad', '--cell', 'Track-Poly=0.4') == 0
    r = rr.load(str(out))[0]
    assert r.name == 'Clearance_New' and r.get('SCOPE1EXPRESSION') == 'IsVia'
    assert {k: round(v, 4) for k, v in r.cells().items()} == {('Track', 'Poly'): 0.4, ('SMDPad', 'Via'): 0.3, ('Via', 'Fill'): 0.0}
    assert out.read_bytes().endswith(rr.END)
