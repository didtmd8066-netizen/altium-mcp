# -*- coding: utf-8 -*-
"""land_check.py: 동박이 닿는데 land 가 제거된 비아·패드 찾기 (파일을 읽지 않는 부분)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import land_check as lc

GND, SIG = 0, 1


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def piece(pts, holes=()):
    return (lc.bbox(pts), pts, list(holes))


def via(x, y, removed, net=GND, layers=(1, 4, 32)):
    return lc.Hole('비아', '', x, y, 0.4, 0.2, net, list(layers), removed)


def test_coverage_counts_copper_and_respects_holes():
    solid = [(square(-5, -5, 5, 5), [])]
    assert lc.coverage((0, 0), 0.1, solid) == 1.0
    assert 0.45 < lc.coverage((0, 0), 0.1, [(square(-5, 0, 5, 5), [])]) < 0.55        # 경계가 중심을 지난다
    assert lc.coverage((0, 0), 0.1, [(square(-5, -5, 5, 5), [square(-1, -1, 1, 1)])]) == 0.0
    assert lc.coverage((9, 9), 0.1, solid) == 0.0


def test_removed_land_on_copper_edge_is_reported():
    """동박 경계가 비아 중심을 지나는데 land 가 빠진 경우 (CES_motor_drive 의 (6.525, 33.425))."""
    pieces = {(4, GND): [piece(square(-5, 0, 5, 5))]}
    got = lc.judge(via(0, 0, {4: True}), pieces)
    assert [(lid, verdict) for lid, verdict, c in got] == [(4, '일부만 닿음')] and 0.4 < got[0][2] < 0.6


def test_removed_land_under_solid_copper_is_the_milder_case():
    pieces = {(4, GND): [piece(square(-5, -5, 5, 5))]}
    assert [(lid, v) for lid, v, c in lc.judge(via(0, 0, {4: True}), pieces)] == [(4, '덮여 있음')]


def test_kept_land_and_clear_copper_are_fine():
    edge = {(4, GND): [piece(square(-5, 0, 5, 5))]}
    assert lc.judge(via(0, 0, {4: False}), edge) == []                 # land 가 남아 있으면 정상
    assert lc.judge(via(0, 0, {}), edge) == []                         # 표시를 읽지 못한 것은 판정하지 않는다
    cleared = {(4, GND): [piece(square(-5, -5, 5, 5), [square(-1, -1, 1, 1)])]}
    assert lc.judge(via(0, 0, {4: True}), cleared) == []               # 동박이 물러나 있으면 제거가 맞다
    assert lc.judge(via(0, 0, {4: True}, net=SIG), edge) == []         # 다른 넷 동박은 보지 않는다
    assert lc.judge(via(0, 0, {4: True}, layers=(1, 32)), edge) == []  # 지나가지 않는 층


def test_thermal_spokes_without_land_count_as_partial():
    """써멀 스포크만 홀 벽에 닿는 패드 (J904-5 의 Signal Layer 5)."""
    spokes = [piece(square(-5, -0.05, 5, 0.05)), piece(square(-0.05, -5, 0.05, 5))]
    pad = lc.Hole('패드', 'J904-5', 0, 0, 1.07, 0.7, GND, [1, 6, 32], {6: True})
    got = lc.judge(pad, {(6, GND): spokes})
    assert got[0][:2] == (6, '일부만 닿음') and got[0][2] < 0.3


def test_flag_positions():
    rec = bytes(203) + lc.VIA_MARK + bytes([0, 0, 0, 1, 0, 1, 1, 0]) + bytes(40)
    r = lc.via_removed(rec)
    assert [lid for lid in range(1, 8) if r[lid]] == [2, 4, 5]          # 층 ID + 1 번째 바이트
    assert lc.via_removed(bytes(321)) == {}
    block = bytes(596) + bytes([0, 1, 0, 0, 1, 1, 0]) + bytes(25) + bytes(23)
    assert len(block) == 651
    p = lc.pad_removed(block)
    assert [lid for lid in range(1, 8) if p[lid]] == [2, 5, 6]          # 층 ID - 1 번째 바이트
    assert lc.pad_removed(b'') == {}
