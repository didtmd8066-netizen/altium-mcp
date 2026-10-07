# -*- coding: utf-8 -*-
"""sch_description.py: 칩 R·C Description 통일 (Altium 없이 도는 부분)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plan_script as ps
import sch_description as sd


def rec(text):
    body = text.encode('latin-1') + b'\x00'
    return len(body).to_bytes(3, 'little') + b'\x00' + body


def sheet(*parts):
    """parts: (지정자, 기존 Description, {이름: (글자, 보임)})"""
    out = [rec('|HEADER=Protel for Windows - Schematic Capture Binary File Version 5.0')]
    n = 0
    for des, desc, par in parts:
        me = n
        out.append(rec('|RECORD=1|LibReference=X|ComponentDescription=%s|PartCount=2' % desc)); n += 1
        out.append(rec('|RECORD=34|OwnerIndex=%d|Text=%s|Name=Designator' % (me, des))); n += 1
        for name, (text, vis) in par.items():
            out.append(rec('|RECORD=41|OwnerIndex=%d%s|Text=%s|Name=%s' % (me, '' if vis else '|IsHidden=T', text, name))); n += 1
    return b''.join(out)


def one(des, par, desc='old'):
    return sd.describe(sd.read_components(sheet((des, desc, par)))[0])


SIZE = {'Package (Imperial)': ('0402', True)}


def test_records_are_length_prefixed_not_nul_split():
    """길이가 256 을 넘으면 길이 바이트에 NUL 이 없어, NUL 로 자르면 순번이 어긋난다."""
    data = sheet(('R1', 'x' * 300, dict(SIZE, Comment=('10K', True))), ('R2', 'old', dict(SIZE, Comment=('22', True))))
    comps = sd.read_components(data)
    assert [(c['des'], sd.shown(c)['Comment']) for c in comps] == [('R1', '10K'), ('R2', '22')]


def test_resistor_uses_what_the_sheet_shows():
    assert one('R1', dict(SIZE, Comment=('10K', True))) == ('RES 10K OHM 0402', None)
    # 글자는 고치지 않는다
    assert one('R1', dict(SIZE, Comment=('15.4k', True)))[0] == 'RES 15.4k OHM 0402'
    assert one('R1', dict(SIZE, Comment=('2R7', True)))[0] == 'RES 2R7 OHM 0402'
    assert one('R1', dict(SIZE, Comment=('100R', True)))[0] == 'RES 100R OHM 0402'
    assert one('R1', dict(SIZE, Comment=('4mOHM', True)))[0] == 'RES 4mOHM 0402'          # OHM 을 두 번 쓰지 않는다


def test_visible_resistance_wins_over_hidden_comment():
    """화면에는 10K 가 보이는데 숨은 Comment 는 22 인 부품이 있었다."""
    assert one('R275', dict(SIZE, Resistance=('10K', True), Comment=('22', False)))[0] == 'RES 10K OHM 0402'
    assert one('R2', dict(SIZE, Resistance=('0.33', True), Comment=('RNCL2010FTR330', True)))[0] == 'RES 0.33 OHM 0402'


def test_hidden_parameters_are_never_used():
    new, why = one('R1', dict(SIZE, Comment=('10K', False), Resistance=('10K', False)))
    assert new is None and '값을 읽을 수 없음' in why
    new, why = one('C1', {'Package (Imperial)': ('0603', False), 'Comment': ('1uF', True), 'Voltage': ('16V', True)})
    assert new is None and why.startswith('칩 아님')


def test_capacitor_and_dnp():
    c = {'Package (Imperial)': ('0603', True), 'Voltage': ('50V', True)}
    assert one('C1', dict(c, Comment=('100nF', True))) == ('CAP CER 100nF 50V 0603', None)
    assert one('C1', dict(c, Capacitance=('1uF', True), Comment=('CL31B105KCHNNNE', True)))[0] == 'CAP CER 1uF 50V 0603'
    assert one('C1', dict(c, Comment=('DNP', True)))[0] == 'CAP CER DNP 50V 0603'
    assert one('R1', dict(SIZE, Comment=('DNP', True)))[0] == 'RES DNP 0402'
    assert one('C1', {'Package (Imperial)': ('0603', True), 'Comment': ('1uF', True)}) == (None, '전압 표기 없음')
    assert '값을 읽을 수 없음' in one('C1', dict(c, Comment=('KAM32LR72A475KU', True)))[1]


def test_metric_size_code_is_normalised_only_when_unambiguous():
    assert one('C189', {'Package (Imperial)': ('2012', True), 'Comment': ('100nF', True), 'Voltage': ('100V', True)})[0] == 'CAP CER 100nF 100V 0805'
    assert one('R1', {'Package (Imperial)': ('0603', True), 'Comment': ('1K', True)})[0] == 'RES 1K OHM 0603'


def test_only_chip_r_and_c():
    assert one('FB1', dict(SIZE, Comment=('ILHB0603ER121V', True))) == (None, None)
    assert one('U1', dict(SIZE, Comment=('LM5069', True))) == (None, None)
    assert one('R245', {'Comment': ('33', True), 'Power': ('WCR 33 10W', True)}) == (None, '칩 아님 (크기 표기 없음)')
    assert one('R?', dict(SIZE, Comment=('10K', True))) == (None, '지정자 미지정')


def test_plan_keeps_sheets_apart_and_holds_conflicts(tmp_path):
    a = sd.read_components(sheet(('R132', 'old', dict(SIZE, Comment=('10K', True))), ('R1', 'RES 22 OHM 0402', dict(SIZE, Comment=('22', True)))))
    b = sd.read_components(sheet(('R132', 'old', {'Package (Imperial)': ('0805', True), 'Comment': ('2R7', True)}),
                                 ('R9', 'old', dict(SIZE, Comment=('1K', True))), ('R9', 'old', dict(SIZE, Comment=('2K', True))),
                                 ('C5', 'old', {'Package (Imperial)': ('0402', True), 'Comment': ('1nF', True), 'Voltage': ('50V', True)}),
                                 ('C5', 'old', {'Package (Imperial)': ('0402', True), 'Comment': ('1nF', True), 'Voltage': ('50V', True)})))
    rows, hold = sd.plan([('A.SchDoc', a), ('B.SchDoc', b)], skip={'R1'})
    new = {(s, d): n for s, d, o, n in rows}
    assert new[('A.SchDoc', 'R132')] == 'RES 10K OHM 0402' and new[('B.SchDoc', 'R132')] == 'RES 2R7 OHM 0805'
    assert ('A.SchDoc', 'R1') not in new
    assert sorted(h[1:] for h in hold) == [('R9', '시트 안에서 지정자가 겹치고 내용이 다름')] * 2
    p = tmp_path / 'plan.txt'
    assert sd.write_plan(rows, str(p)) == 3                              # 멀티파트 C5 는 한 줄
    assert sd.read_plan(str(p)) == {('A.SchDoc', 'R132'): 'RES 10K OHM 0402', ('B.SchDoc', 'R132'): 'RES 2R7 OHM 0805',
                                    ('B.SchDoc', 'C5'): 'CAP CER 1nF 50V 0402'}


def test_unchanged_parts_are_left_out_of_the_plan(tmp_path):
    comps = sd.read_components(sheet(('R1', 'RES 22 OHM 0402', dict(SIZE, Comment=('22', True)))))
    rows, _ = sd.plan([('A.SchDoc', comps)])
    assert rows == [('A.SchDoc', 'R1', 'RES 22 OHM 0402', 'RES 22 OHM 0402')]
    assert sd.write_plan(rows, str(tmp_path / 'p.txt')) == 0


def test_verify_reports_wrong_and_missing(tmp_path):
    plan = tmp_path / 'plan.txt'
    plan.write_text('#A.SchDoc\nR1=RES 1K OHM 0402\nR2=RES 2K OHM 0402\nC5=CAP CER 1nF 50V 0402\n#B.SchDoc\nR1=RES 9 OHM 0402\n', encoding='latin-1')
    back = tmp_path / 'back.txt'
    back.write_text(plan.read_text(encoding='latin-1') + '@A.SchDoc\nR1=RES 1K OHM 0402\nR2=stale\nC5=CAP CER 1nF 50V 0402\nC5=CAP CER 1nF 50V 0402\nU1=x=y\n', encoding='latin-1')
    v = sd.verify(str(plan), str(back))
    assert v['expected'] == 4 and v['ok'] == 2
    assert v['wrong'] == [('A.SchDoc', 'R2', 'stale')] and v['missing'] == [('B.SchDoc', 'R1')]


def test_find_sheets_reads_project_file(tmp_path):
    (tmp_path / 'a.SchDoc').write_bytes(b''); (tmp_path / 'b.SchDoc').write_bytes(b'')
    prj = tmp_path / 'p.PrjPcb'
    prj.write_text('[Document1]\nDocumentPath=a.SchDoc\n[Document2]\nDocumentPath=board.PcbDoc\n', encoding='latin-1')
    assert [os.path.basename(p) for p in sd.find_sheets([str(prj)])] == ['a.SchDoc']
    assert [os.path.basename(p) for p in sd.find_sheets([str(tmp_path)])] == ['a.SchDoc', 'b.SchDoc']


def test_description_scripts(tmp_path):
    plan = tmp_path / 'plan.txt'
    plan.write_text('#C:\\x\\A.SchDoc\nR1=RES 1K OHM 0402\n', encoding='latin-1')
    apply_text = ps.descriptions_script(str(plan))
    assert '{' not in apply_text and '//' not in apply_text and 'ComponentDescription := S3' in apply_text and 'SaveToFile' not in apply_text
    read_text = ps.descriptions_script(str(plan), str(tmp_path / 'back.txt'))
    assert '{' not in read_text and 'SaveToFile' in read_text and ':= S3' not in read_text
    assert ps.parse_described('set 514 / same 16') == {'raw': 'set 514 / same 16', 'changed': 514, 'same': 16}
    assert 'changed' not in ps.parse_described('boom')
    empty = tmp_path / 'e.txt'; empty.write_text('', encoding='latin-1')
    try:
        ps.descriptions_script(str(empty))
        assert False
    except ValueError:
        pass
