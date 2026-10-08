# -*- coding: utf-8 -*-
"""같은 넷 폴리곤 동박이 닿아 있는데 land 가 제거된 비아·패드를 찾는다 - Altium 을 부르지 않는다.

    python land_check.py <보드.PcbDoc> [--csv 결과.csv]

Remove Unused Pad Shapes 는 그 층에서 연결이 없다고 본 비아·패드의 land 를 뺀다. 폴리곤이 오래된
상태에서 돌리면, 동박이 실제로는 닿아 있는 층의 land 까지 빠진다. 다른 층에서 넷이 이어져 있으면
Un-Routed Net 검사에 걸리지 않아 DRC 로는 보이지 않는다. 문제가 있으면 종료 코드 1.

찾는 것
-------
- 일부만 닿음   land 가 없는데 같은 넷 동박이 홀 둘레의 일부만 물고 있다 (동박 경계가 홀을 가로지름,
                써멀 스포크만 홀 벽에 닿음). 고쳐야 하는 곳.
- 덮여 있음     land 가 없는데 같은 넷 동박이 홀을 완전히 감싼다. 도통은 되지만 같은 증상이다.

land 가 남아 있는 곳은 동박 경계가 홀에 걸려 있어도 정상으로 본다 (land 가 이어 준다).
저장된 파일을 읽으므로 먼저 저장한다. 좌표는 보드 원점 기준 mm.

파일 형식 메모
-------------
- 폴리곤이 부은 동박은 `Regions6` 의 KIND=0 리전이고 넷은 리전이 아니라 폴리곤(`Polygons6`)에 있다.
- 비아의 층별 제거 표시: `Vias6` 레코드에서 `0f 00 03 01` 뒤 바이트, 층 ID + 1 번째.
- 패드의 층별 제거 표시: `Pads6` 여섯 번째 블록의 끝에서 55~23 바이트, 층 ID - 1 번째.
  블록이 비어 있는 패드(단순 모드)는 표시를 읽을 수 없어 판정하지 않는다.
- 층 ID 는 쌓인 순서와 다르다 (Signal Layer 4 가 ID 2 인 보드가 있었다). 순서는 V9_STACK 에서 읽는다.
"""
import argparse
import collections
import csv
import math
import re
import struct
import sys

import olefile

U = 0.0254 / 10000                  # 내부 단위 -> mm
FULL, NONE = 0.97, 0.03             # 홀 둘레가 이 비율 이상/이하로 덮이면 전부/없음
STEP = 5                            # 둘레를 몇 도 간격으로 찍어 볼지
VIA_MARK = bytes.fromhex('0f000301')

Hole = collections.namedtuple('Hole', 'kind name x y dia hole net layers removed')


def inside(p, pts):
    x, y = p
    c = False
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def bbox(pts):
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def coverage(center, radius, pieces):
    """반지름 radius 원둘레 가운데 동박(pieces: [(외곽, [구멍...])]) 위에 있는 비율."""
    def copper(p):
        return any(inside(p, pts) and not any(inside(p, h) for h in holes) for pts, holes in pieces)
    n = 360 // STEP
    return sum(copper((center[0] + radius * math.cos(math.radians(a)), center[1] + radius * math.sin(math.radians(a))))
               for a in range(0, 360, STEP)) / n


def via_removed(rec):
    """비아 레코드 -> {층 ID: 제거 여부}. 표시가 없으면 빈 dict."""
    k = rec.find(VIA_MARK, 150)
    if k < 0:
        return {}
    fl = rec[k + 4:k + 40]
    return {lid: bool(fl[lid + 1]) for lid in range(1, 33) if lid + 1 < len(fl)}


def pad_removed(block):
    """패드의 여섯 번째 블록 -> {층 ID: 제거 여부}. 단순 모드 패드는 빈 dict."""
    if len(block) < 600:
        return {}
    fl = block[-55:-23]
    return {lid: bool(fl[lid - 1]) for lid in range(1, 33)}


def judge(hole, pieces_by_layer):
    """한 비아·패드 -> [(층 ID, 판정, 홀 둘레 덮인 비율)]. land 가 제거된 층만 본다."""
    out = []
    for lid in hole.layers:
        if not hole.removed.get(lid):
            continue
        lim = hole.hole / 2 + 0.01
        near = [(pts, holes) for bb, pts, holes in pieces_by_layer.get((lid, hole.net), [])
                if bb[0] - lim <= hole.x <= bb[2] + lim and bb[1] - lim <= hole.y <= bb[3] + lim]
        if not near:
            continue
        c = coverage((hole.x, hole.y), hole.hole / 2 + 0.005, near)
        if c > NONE:
            out.append((lid, '덮여 있음' if c > FULL else '일부만 닿음', c))
    return out


def _text(data):
    pos = 0
    while pos + 4 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], 'little')
        yield data[pos + 4:pos + 4 + n].rstrip(b'\x00').decode('mbcs', 'replace') + '|'
        pos += 4 + n


def _xy(raw, ox, oy):
    x, y = struct.unpack('<dd', raw)
    return (x * U - ox, y * U - oy)


def read(path):
    """저장된 .PcbDoc -> (층 [(ID, 이름)], 넷 이름, {(층, 넷): [(bbox, 외곽, 구멍)]}, [Hole])."""
    ole = olefile.OleFileIO(path)
    get = lambda name: ole.openstream(name).read()
    b = get('Board6/Data').decode('mbcs', 'replace')
    ox = float(re.search(r'\|ORIGINX=([-\d.]+)mil', b).group(1)) * 0.0254
    oy = float(re.search(r'\|ORIGINY=([-\d.]+)mil', b).group(1)) * 0.0254
    names = dict(re.findall(r'\|V9_STACK_LAYER(\d+)_NAME=([^|]*)', b))
    ids = dict(re.findall(r'\|V9_STACK_LAYER(\d+)_LAYERID=([^|]*)', b))
    order = []
    for k in sorted(names, key=int):
        v = int(ids.get(k, 0))
        if v == 16842751:
            order.append((32, names[k]))
        elif v >> 16 == 256 and 1 <= (v & 0xFFFF) <= 31:
            order.append((v & 0xFF, names[k]))
    nets = [re.search(r'NAME=([^|]*)', s).group(1) for s in _text(get('Nets6/Data'))]
    comps = [m.group(1) if (m := re.search(r'SOURCEDESIGNATOR=([^|]*)', s)) else '?' for s in _text(get('Components6/Data'))]
    pnet = [int(m.group(1)) if (m := re.search(r'\|NET=(\d+)', s)) else -1 for s in _text(get('Polygons6/Data'))]

    pieces = collections.defaultdict(list)
    d = get('Regions6/Data')
    pos = 0
    while pos < len(d):
        n = int.from_bytes(d[pos + 1:pos + 5], 'little')
        r = d[pos + 5:pos + 5 + n]
        pos += 5 + n
        poly = int.from_bytes(r[5:7], 'little')
        pl = int.from_bytes(r[18:22], 'little')
        if poly >= len(pnet) or pnet[poly] < 0 or b'KIND=0' not in r[22:22 + pl]:
            continue
        q = 22 + pl
        nv = int.from_bytes(r[q:q + 4], 'little')
        q += 4
        pts = [_xy(r[q + 16 * i:q + 16 * i + 16], ox, oy) for i in range(nv)]
        q += 16 * nv
        holes = []
        while q + 4 <= len(r):
            hn = int.from_bytes(r[q:q + 4], 'little')
            q += 4
            if hn == 0 or q + hn * 16 > len(r):
                break
            holes.append([_xy(r[q + 16 * i:q + 16 * i + 16], ox, oy) for i in range(hn)])
            q += hn * 16
        if len(pts) > 2:
            pieces[(r[0], pnet[poly])].append((bbox(pts), pts, holes))

    rank = {lid: i for i, (lid, _) in enumerate(order)}
    all_ids = [lid for lid, _ in order]
    found = []
    d = get('Vias6/Data')
    pos = 0
    while pos < len(d):
        n = int.from_bytes(d[pos + 1:pos + 5], 'little')
        r = d[pos + 5:pos + 5 + n]
        pos += 5 + n
        x, y, dia, hole = struct.unpack('<iiii', r[13:29])
        lo, hi = sorted((rank.get(r[29], 0), rank.get(r[30], len(order) - 1)))
        found.append(Hole('비아', '', x * U - ox, y * U - oy, dia * U, hole * U, int.from_bytes(r[3:5], 'little'),
                          all_ids[lo:hi + 1], via_removed(r)))
    d = get('Pads6/Data')
    pos = 0
    while pos < len(d):
        pos += 1
        subs = []
        for _ in range(6):
            n = int.from_bytes(d[pos:pos + 4], 'little')
            subs.append(d[pos + 4:pos + 4 + n])
            pos += 4 + n
        g = subs[4]
        hole = struct.unpack('<i', g[45:49])[0]
        net = int.from_bytes(g[3:5], 'little')
        if g[0] != 74 or hole <= 0 or net >= len(nets):          # 74 = Multi-Layer
            continue
        x, y = struct.unpack('<ii', g[13:21])
        ci = int.from_bytes(g[7:9], 'little')
        name = (comps[ci] if ci < len(comps) else '') + '-' + subs[0][1:].decode('mbcs', 'replace')
        found.append(Hole('패드', name, x * U - ox, y * U - oy, min(struct.unpack('<ii', g[21:29])) * U, hole * U, net,
                          all_ids, pad_removed(subs[5])))
    return order, nets, pieces, found


def check(path):
    """-> (행 목록, 요약). 행: (판정, 종류, 이름, 층 이름, x, y, 넷, 홀, 덮인 비율)."""
    order, nets, pieces, found = read(path)
    lname = dict(order)
    rows = []
    for h in found:
        for lid, verdict, c in judge(h, pieces):
            rows.append((verdict, h.kind, h.name, lname[lid], round(h.x, 3), round(h.y, 3),
                         nets[h.net] if h.net < len(nets) else '', round(h.hole, 3), round(c * 100)))
    rows.sort(key=lambda r: (r[0] != '일부만 닿음', r[3], r[4], r[5]))
    blind = sum(1 for h in found if h.kind == '패드' and not h.removed)
    summary = dict(vias=sum(1 for h in found if h.kind == '비아'), pads=sum(1 for h in found if h.kind == '패드'),
                   unread_pads=blind, layers=[n for _, n in order])
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('pcbdoc')
    ap.add_argument('--csv')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    rows, s = check(a.pcbdoc)
    print('동박 층: ' + ', '.join(s['layers']))
    print('비아 %d개, 홀 있는 패드 %d개 (제거 표시를 읽을 수 없는 패드 %d개)' % (s['vias'], s['pads'], s['unread_pads']))
    if not rows:
        print('이상 없음')
        return 0
    for verdict in ('일부만 닿음', '덮여 있음'):
        part = [r for r in rows if r[0] == verdict]
        if part:
            print('\n[%s] %d곳' % (verdict, len(part)))
            for r in part:
                print('  %s %-10s %-16s (%.3f, %.3f) %s 홀 %.2f mm, 홀 둘레 %d%%' % (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['판정', '종류', '이름', '층', 'x(mm)', 'y(mm)', '넷', '홀(mm)', '홀 둘레 덮인 비율(%)'])
            w.writerows(rows)
    return 1


if __name__ == '__main__':
    sys.exit(main())
