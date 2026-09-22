# -*- coding: utf-8 -*-
"""부어진 구리에서 떠 있는 섬(island)과 약하게 붙은 조각을 찾는다.

    python copper_islands.py <file.PcbDoc> [넷이름] [--max 2] [--min-area 0.5]

Altium 을 거치지 않고 `.PcbDoc` 만 읽는다.

**폴리곤 하나는 `Regions6` 에 수십~수백 개 조각으로 쪼개져 저장된다.** 맞닿은
조각들이 모여 하나의 구리 덩어리를 이루므로, 조각을 따로따로 보면 이웃과 붙어
있는 멀쩡한 조각까지 섬으로 세게 된다. 그래서 먼저 **겹치거나 맞닿은 조각을
union-find 로 묶어 덩어리를 만든 뒤**, 덩어리마다 그 넷의 연결점(비아·패드·
트랙)이 몇 개 닿는지 센다.

  연결점 0개  = 떠 있는 섬. 넷 이름만 같고 전기적으로 끊겨 있다.
  연결점 1~2개 = 붙어는 있지만 리턴 경로로 쓸 수 없는 덩어리.

`Remove Dead Copper` 가 켜져 있으면 0개짜리는 Altium 이 이미 지운다. 그래서
실제로 쓸모 있는 것은 **1~2개짜리**다 - 비아 하나로 간신히 매달린 큰 덩어리가
슬롯 안테나가 되고, 리턴 전류는 그 목을 통과하지 못한다.

레코드 형식 메모
----------------
Regions6 / Vias6 / Pads6 은 앞부분 배치가 같다.
  [0]      층 번호 (1=Top, 32=Bottom, 74=Multi-layer)
  [3:5]    넷 인덱스 (0xFFFF = 넷 없음)
  [7:9]    부품 인덱스
  [13:21]  X, Y (내부 단위 1/10000 mil)
Regions6 만 그 뒤에 `V7_LAYER=...` 평문 헤더와 꼭짓점 배열이 붙는다.
  [18:22]  헤더 길이, 그 뒤 4바이트가 꼭짓점 개수, 이어서 double×2 배열.
"""
import argparse
import collections
import math
import os
import re
import struct
import sys

try:
    import olefile
except ImportError:
    raise SystemExit('olefile 이 필요하다:  pip install olefile')

try:
    from shapely.geometry import Polygon, Point, LineString
    from shapely.strtree import STRtree
    from shapely import unary_union
except ImportError:
    raise SystemExit('shapely 가 필요하다:  pip install shapely')

MM_PER_UNIT = 0.00000254
MULTILAYER = 74

LAYER_NAMES = {1: 'Top Layer', 32: 'Bottom Layer'}
for _i in range(2, 32):
    LAYER_NAMES[_i] = 'Mid Layer %d' % (_i - 1)


def _blocks(ole, name):
    """길이 접두 블록을 하나씩."""
    data = ole.openstream(name).read()
    off = 0
    while off + 4 <= len(data):
        size = struct.unpack('<I', data[off:off + 4])[0]
        yield data[off + 4:off + 4 + size]
        off += 4 + size


def _records(ole, name):
    """타입 1바이트 + 길이 4바이트로 끊긴 레코드를 하나씩."""
    data = ole.openstream(name).read()
    off = 0
    while off + 5 <= len(data):
        size = struct.unpack('<I', data[off + 1:off + 5])[0]
        yield data[off + 5:off + 5 + size]
        off += 5 + size


def net_names(ole):
    out = []
    for payload in _blocks(ole, 'Nets6/Data'):
        text = payload.decode('latin-1').strip('\x00')
        fields = dict(x.split('=', 1) for x in text.split('|') if '=' in x)
        out.append(fields.get('NAME', '?'))
    return out


def origin(ole):
    """사용자가 설정한 원점. 좌표를 보드 기준으로 옮기는 데 쓴다."""
    for payload in _blocks(ole, 'Board6/Data'):
        text = payload.decode('latin-1')
        mx = re.search(r'\|ORIGINX=([\d.]+)mil', text)
        my = re.search(r'\|ORIGINY=([\d.]+)mil', text)
        if mx and my:
            return float(mx.group(1)) * 0.0254, float(my.group(1)) * 0.0254
    return 0.0, 0.0


def regions(ole, nets):
    """[(층, 넷, [(x, y), ...])] - 좌표는 mm, 절대 기준."""
    out = []
    for payload in _records(ole, 'Regions6/Data'):
        if len(payload) < 30:
            continue
        layer = payload[0]
        net = struct.unpack('<H', payload[3:5])[0]
        head = struct.unpack('<I', payload[18:22])[0]
        pos = 22 + head
        if pos + 4 > len(payload):
            continue
        count = struct.unpack('<I', payload[pos:pos + 4])[0]
        pos += 4
        if count <= 2 or pos + 16 * count > len(payload):
            continue
        verts = []
        for _ in range(count):
            x, y = struct.unpack('<dd', payload[pos:pos + 16])
            pos += 16
            verts.append((x * MM_PER_UNIT, y * MM_PER_UNIT))
        out.append((layer, nets[net] if net < len(nets) else '?', verts))
    return out


def vias(ole, nets):
    """[(넷, 도형)] - 비아는 관통이라 모든 층을 잇는다고 본다."""
    out = []
    for payload in _records(ole, 'Vias6/Data'):
        if len(payload) < 25:
            continue
        net = struct.unpack('<H', payload[3:5])[0]
        x, y = struct.unpack('<ii', payload[13:21])
        dia = struct.unpack('<i', payload[21:25])[0] * MM_PER_UNIT
        disc = Point(x * MM_PER_UNIT, y * MM_PER_UNIT).buffer(max(dia, 0.05) / 2)
        out.append((nets[net] if net < len(nets) else '?', disc))
    return out


def pads(ole, nets):
    """[(넷, 층, 도형)] - 층 74 는 관통 패드.

    **패드는 점이 아니라 면적을 가진다.** 중심만 보면 SOT-223 탭처럼 큰 패드가
    조각 밖에 중심을 두고 있을 때 연결을 놓친다. 실제로 그렇게 오탐이 났다.

    레코드는 `타입(2) + 이름길이 + 이름` 뒤에 길이 접두 블록이 이어지는데,
    **블록 개수가 패드마다 다르다.** 형상이 복잡한 패드는 블록이 더 붙는다.
    고정 개수로 읽으면 12번째쯤에서 어긋나 12개만 파싱되고 끝난다. 그래서
    본문(100바이트 이상)을 찾은 뒤 **다음 레코드 헤더가 보이면 멈추는** 방식을 쓴다.
    """
    data = ole.openstream('Pads6/Data').read()
    size = len(data)
    out = []
    off = 0
    while off + 5 <= size:
        if data[off] != 2:
            break
        namelen = struct.unpack('<I', data[off + 1:off + 5])[0]
        if not 1 <= namelen <= 20:
            break
        pos = off + 5 + namelen
        body = None
        while pos + 4 <= size:
            blocklen = struct.unpack('<I', data[pos:pos + 4])[0]
            if blocklen > 100000:
                break
            block = data[pos + 4:pos + 4 + blocklen]
            pos += 4 + blocklen
            if blocklen >= 100 and body is None:
                body = block
            if body is not None and pos + 5 <= size and data[pos] == 2:
                nxt = struct.unpack('<I', data[pos + 1:pos + 5])[0]
                if 1 <= nxt <= 20:
                    break
            if blocklen == 0:
                break
        off = pos
        if not body or len(body) < 45:
            continue
        layer = body[0]
        net = struct.unpack('<H', body[3:5])[0]
        x, y = struct.unpack('<ii', body[13:21])
        # 크기는 면마다 따로 들어 있다. Top 것만 읽으면 Bottom SMD 패드가
        # 0 으로 나와 통째로 걸러진다 - 그 탓에 SOT-223 연결을 놓쳤다.
        if layer == 1:
            sx, sy = struct.unpack('<ii', body[21:29])
        elif layer == 32:
            sx, sy = struct.unpack('<ii', body[37:45])
        else:
            sx, sy = struct.unpack('<ii', body[29:37])
            if sx <= 0:
                sx, sy = struct.unpack('<ii', body[21:29])
        x, y = x * MM_PER_UNIT, y * MM_PER_UNIT
        sx, sy = sx * MM_PER_UNIT / 2, sy * MM_PER_UNIT / 2
        if sx <= 0 or sy <= 0:
            continue
        box = Polygon([(x - sx, y - sy), (x + sx, y - sy),
                       (x + sx, y + sy), (x - sx, y + sy)])
        out.append((nets[net] if net < len(nets) else '?', layer, box))
    return out


def fills(ole, nets):
    """[(넷, 층, 도형)] - 사각 필과 원호. 이것도 구리를 잇는다."""
    out = []
    for payload in _records(ole, 'Fills6/Data'):
        if len(payload) < 29:
            continue
        net = struct.unpack('<H', payload[3:5])[0]
        x1, y1, x2, y2 = struct.unpack('<iiii', payload[13:29])
        x1, y1 = x1 * MM_PER_UNIT, y1 * MM_PER_UNIT
        x2, y2 = x2 * MM_PER_UNIT, y2 * MM_PER_UNIT
        if x1 == x2 or y1 == y2:
            continue
        out.append((nets[net] if net < len(nets) else '?', payload[0],
                    Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])))
    for payload in _records(ole, 'Arcs6/Data'):
        if len(payload) < 33:
            continue
        net = struct.unpack('<H', payload[3:5])[0]
        cx, cy, radius = struct.unpack('<iii', payload[13:25])
        width = struct.unpack('<I', payload[29:33])[0] * MM_PER_UNIT
        ring = Point(cx * MM_PER_UNIT, cy * MM_PER_UNIT).buffer(
            radius * MM_PER_UNIT + max(width, 0.01) / 2)
        out.append((nets[net] if net < len(nets) else '?', payload[0], ring))
    return out


def track_shapes(ole, nets):
    """[(넷, 층, 도형)] - 트랙은 선분이다. 끝점만 보면 조각을 관통하는 배선을
    놓친다. GND 가드 트레이스가 그렇게 오탐이 났다."""
    out = []
    for payload in _records(ole, 'Tracks6/Data'):
        if len(payload) < 33:
            continue
        layer = payload[0]
        net = struct.unpack('<H', payload[3:5])[0]
        x1, y1, x2, y2 = struct.unpack('<iiii', payload[13:29])
        width = struct.unpack('<I', payload[29:33])[0] * MM_PER_UNIT
        line = LineString([(x1 * MM_PER_UNIT, y1 * MM_PER_UNIT),
                           (x2 * MM_PER_UNIT, y2 * MM_PER_UNIT)])
        out.append((nets[net] if net < len(nets) else '?', layer,
                    line.buffer(max(width, 0.01) / 2)))
    return out


class Union:
    """union-find. 맞닿은 조각을 한 덩어리로 묶는 데 쓴다."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, i, j):
        a, b = self.find(i), self.find(j)
        if a != b:
            self.parent[a] = b


def clump(shapes, tol):
    """서로 tol 이내로 닿는 도형들을 묶어 [[인덱스, ...], ...] 로.

    Altium 의 pour 결과는 인접 조각이 꼭짓점을 정확히 공유하기도 하고 미세하게
    떨어져 있기도 하다. tol 을 두어 둘 다 같은 덩어리로 본다.
    """
    union = Union(len(shapes))
    tree = STRtree(shapes)
    for i, shape in enumerate(shapes):
        for j in tree.query(shape.buffer(tol)):
            if i != j:
                union.join(i, int(j))
    groups = collections.defaultdict(list)
    for i in range(len(shapes)):
        groups[union.find(i)].append(i)
    return list(groups.values())


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('pcbdoc')
    ap.add_argument('net', nargs='?', default='GND')
    ap.add_argument('--max', type=int, default=2,
                    help='연결점이 이 수 이하인 덩어리를 보고한다 (기본 2)')
    ap.add_argument('--min-area', type=float, default=0.0,
                    help='이 면적(mm2) 미만인 덩어리는 무시한다')
    ap.add_argument('--tol', type=float, default=0.001,
                    help='이 거리(mm) 이내로 닿은 조각은 한 덩어리로 본다')
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    a = ap.parse_args()

    ole = olefile.OleFileIO(a.pcbdoc)
    nets = net_names(ole)
    ox, oy = origin(ole)

    regs = [r for r in regions(ole, nets) if r[1] == a.net and r[0] in LAYER_NAMES]
    if not regs:
        print('%s 넷의 구리 조각이 없다' % a.net)
        return 0

    # 연결체를 층별로 모은다. 전부 점이 아니라 실제 도형으로 다룬다.
    probes = collections.defaultdict(list)
    layers = sorted({r[0] for r in regs})
    for name, disc in vias(ole, nets):
        if name == a.net:
            for layer in layers:
                probes[layer].append(disc)
    for name, layer, box in pads(ole, nets):
        if name != a.net:
            continue
        if layer == MULTILAYER:
            for each in layers:
                probes[each].append(box)
        elif layer in LAYER_NAMES:
            probes[layer].append(box)
    for name, layer, band in track_shapes(ole, nets):
        if name == a.net and layer in LAYER_NAMES:
            probes[layer].append(band)
    for name, layer, shape in fills(ole, nets):
        if name != a.net:
            continue
        if layer == MULTILAYER:
            for each in layers:
                probes[each].append(shape)
        elif layer in LAYER_NAMES:
            probes[layer].append(shape)

    print('=== %s / 넷 %s ===' % (os.path.basename(a.pcbdoc), a.net))
    print('구리 조각 %d개, 연결체 %d개 (원점 %.3f, %.3f 기준으로 좌표 표기)'
          % (len(regs), sum(len(v) for v in probes.values()), ox, oy))

    weak = []
    counts = {}
    for layer in layers:
        shapes = [Polygon(verts) for lay, _, verts in regs if lay == layer]
        shapes = [s if s.is_valid else s.buffer(0) for s in shapes]
        groups = clump(shapes, a.tol)
        counts[layer] = (len(shapes), len(groups))
        touch = probes[layer]
        tree = STRtree(touch) if touch else None
        for members in groups:
            blob = unary_union([shapes[i] for i in members])
            hits = 0
            if tree is not None:
                for idx in tree.query(blob):
                    if blob.intersects(touch[int(idx)]):
                        hits += 1
                        if hits > a.max:
                            break
            if hits <= a.max and blob.area >= a.min_area:
                x0, y0, x1, y1 = blob.bounds
                cx, cy = blob.representative_point().coords[0]
                weak.append((hits, blob.area, layer, cx - ox, cy - oy,
                             x1 - x0, y1 - y0, len(members)))

    print('\n%-14s %-9s %s' % ('층', '조각', '덩어리'))
    for layer in layers:
        print('  %-12s %-9d %d' % (LAYER_NAMES[layer], counts[layer][0], counts[layer][1]))

    weak.sort(key=lambda t: (t[0], -t[1]))
    print('\n=== 연결점 %d개 이하인 덩어리 %d개 ===' % (a.max, len(weak)))
    if not weak:
        print('  없음')
        return 0
    print('%-4s %-10s %-6s %-13s %-20s %s'
          % ('연결', '면적mm2', '조각', '층', '위치(x, y)', '크기'))
    for hits, size, layer, cx, cy, w, h, parts in weak:
        print('%-4d %10.3f %-6d %-13s (%7.3f, %7.3f)  %.2f x %.2f'
              % (hits, size, parts, LAYER_NAMES[layer], cx, cy, w, h))
    return 0


if __name__ == '__main__':
    sys.exit(main())
