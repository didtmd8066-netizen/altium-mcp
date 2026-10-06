# -*- coding: utf-8 -*-
"""저장된 .PcbDoc 에서 동박 덤프를 만든다 - Altium 을 거치지 않는다.

    python pcbdoc_dump.py <file.PcbDoc> <dump.txt>

출력은 `snippets/dump_copper.pas` 와 같은 형식이라 `route_lib.load_board()` 가 그대로 읽는다.
보드가 Altium 에 열려 있지 않아도 되고, 사용자가 다른 보드를 작업 중이어도 방해하지 않는다.
스크립트 호출이 없으니 실행기가 wedge 될 일도 없다.

**디스크에 저장된 상태**를 읽는다. 사용자가 저장하지 않은 변경은 보이지 않는다 - 보드를
고치는 계획을 세울 때는 저장 시각을 확인하거나, 적용 직전에 dump_copper 로 다시 뜬다.
읽기 전용 용도(대칭 보드의 기준 쪽, 검토, 비교)에는 이쪽이 빠르다.

dump_copper.pas 와 다른 점
--------------------------
- 선택 여부는 파일에 없다. 항상 0 으로 나온다 ("선택한 것만" 작업에는 못 쓴다).
- 패드 줄 끝에 층이 붙고, 폴리곤이 부은 것이 아닌 리전·필이 `R|넷|0|층|x1|y1|x2|y2|종류` 로 나온다
  (외접 사각형, 종류는 copper / cutout / keepout, 풋프린트에 속한 구리 리전은 패드 모양이므로 padshape).
  dump_copper.pas 도 같다. 여기서는 리전의 실제
  꼭짓점을 끝에 `x,y;x,y;...` 로 더 붙인다 - Altium 덤프에는 외접 사각형만 있다.
- 폴리곤이 부은 선·아크(해치)와 풋프린트에 속한 선·아크는 뺀다. 배선이 아니기 때문이다.
  dump_copper.pas 도 같은 기준으로 뺀다 (HEAD_RIGHT_BLOOD 에서 같은 파일로 대조: 비아 515/515,
  패드 90/90, 트랙 383 중 381 · 아크 217 중 216 이 소수 3 자리까지 일치, 나머지는 반올림 경계).
- 좌표는 파일의 정수(1/10000 mil)에서 바로 환산한다. Altium 이 FloatToStr 로 찍은 값과
  소수 5~6 자리에서 다를 수 있다 (um 미만).

형식 메모 (AD24 로 저장한 파일에서 확인, 2026-10-06)
---------------------------------------------------
Tracks6 / Arcs6 / Vias6 의 Data 스트림은 [종류 1바이트][길이 u32][본문] 의 반복이다.
본문 공통 머리:  [0] 층  [3:5] 넷 번호  [5:7] 폴리곤 번호  [7:9] 부품 번호   (없으면 0xFFFF)
  트랙(4)  [13] x1 [17] y1 [21] x2 [25] y2 [29] 폭                 (i32, 1/10000 mil)
  아크(1)  [13] cx [17] cy [21] 반지름 [25] 시작각 [33] 끝각 (double, 도) [41] 폭
  비아(3)  [13] x  [17] y  [21] 지름  [25] 홀
Pads6 는 패드 하나가 [종류 2] 뒤에 길이 붙은 블록 6개다: 이름, ?, ?, ?, 본문, 층별 크기.
  본문  [0] 층 [3:5] 넷 [7:9] 부품 [13] x [17] y [21] 윗면 / [29] 중간 / [37] 아랫면 x·y 크기 [52] 회전(double)
  패드 템플릿을 쓰는 패드는 크기가 1mil 자리표시로만 들어 있다 (NEW_BASE_MOTOR 1871개 중 105개).
Regions6 (종류 11): 공통 머리 뒤 [18] 속성 글자 길이, 속성(KIND=1 이면 폴리곤 컷아웃), 꼭짓점 수, double x·y.
  [1] 의 0x10 비트는 티어드롭 리전이다 (넷이 있는 진짜 구리 - 빼면 안 된다). [2] == 2 면 keepout.
층 번호: 1 Top, 32 Bottom, 74 Multi. 넷 번호는 Nets6 의 순서, 부품 번호는 Components6 의 순서.
외곽은 Board6 의 VXn / VYn / KINDn (1 이면 아크: CXn CYn Rn SAn EAn), 원점은 ORIGINX / ORIGINY.
"""
import re
import struct
import sys

import olefile

U = 0.00000254                                    # 1/10000 mil -> mm
MIL = 0.0254
LAYERS = {1: 'Top Layer', 32: 'Bottom Layer', 74: 'Multi Layer'}
NONE = 0xFFFF
FIELD = re.compile(r'\|([A-Za-z0-9_. ]+)=([^|]*)')


def _mil(text):
    return float(text.strip().lower().replace('mil', '')) * MIL


def _stream(ole, name):
    return ole.openstream([name, 'Data']).read()


def _text_records(data):
    """[길이 u32][파이프 구분 평문] 의 반복 (Nets6, Components6)."""
    out, i = [], 0
    while i + 4 <= len(data):
        n = struct.unpack_from('<I', data, i)[0]
        out.append(dict(FIELD.findall(data[i + 4:i + 4 + n].decode('latin-1'))))
        i += 4 + n
    return out


def _bin_records(data):
    i = 0
    while i + 5 <= len(data):
        n = struct.unpack_from('<I', data, i + 1)[0]
        yield data[i], data[i + 5:i + 5 + n]
        i += 5 + n


def _pads(data):
    """패드마다 (이름, 본문)."""
    i = 0
    while i < len(data):
        if data[i] != 2:
            raise ValueError(f'Pads6: 종류 바이트가 2 가 아니다 (위치 {i}, 값 {data[i]})')
        i += 1
        blocks = []
        for _ in range(6):
            n = struct.unpack_from('<I', data, i)[0]
            blocks.append(data[i + 4:i + 4 + n])
            i += 4 + n
        name = blocks[0][1:1 + blocks[0][0]].decode('latin-1') if blocks[0] else ''
        yield name, blocks[4]


def read(path):
    """(원점 뺀 줄 목록, 요약 dict)."""
    ole = olefile.OleFileIO(path)
    try:
        board = dict(FIELD.findall(_stream(ole, 'Board6').decode('latin-1')))
        ox, oy = _mil(board.get('ORIGINX', '0')), _mil(board.get('ORIGINY', '0'))
        nets = [r.get('NAME', '') for r in _text_records(_stream(ole, 'Nets6'))]
        comps = _text_records(_stream(ole, 'Components6'))
        net = lambda k: nets[k] if k != NONE and k < len(nets) else ''
        X = lambda v: v * U - ox
        Y = lambda v: v * U - oy
        f = lambda v: '%.6f' % v
        lines, count = [], dict(O=0, C=0, V=0, T=0, A=0, P=0, R=0, skipped=0, padsize=0)

        k = 0
        while f'VX{k}' in board:
            x, y = _mil(board[f'VX{k}']) - ox, _mil(board[f'VY{k}']) - oy
            if board.get(f'KIND{k}', '0').strip() == '1':
                lines.append('|'.join(['O', 'A', f(x), f(y), f(_mil(board[f'CX{k}']) - ox), f(_mil(board[f'CY{k}']) - oy),
                                       f(_mil(board[f'R{k}'])), '%.6f' % float(board[f'SA{k}']), '%.6f' % float(board[f'EA{k}'])]))
            else:
                lines.append('|'.join(['O', 'L', f(x), f(y)]))
            k += 1
        count['O'] = k
        # Altium 은 닫힌 외곽의 첫 점을 끝에 한 번 더 적는다 - dump_copper.pas 는 그 점을 내지 않는다
        if k > 1 and lines[0].split('|')[2:4] == lines[-1].split('|')[2:4] and lines[-1].split('|')[1] == 'L':
            lines.pop(); count['O'] -= 1

        names = []
        for c in comps:
            name = (c.get('SOURCEDESIGNATOR') or '').strip()
            names.append(name)
            lines.append('|'.join(['C', name, '0', f(_mil(c.get('X', '0')) - ox), f(_mil(c.get('Y', '0')) - oy),
                                   '%.6f' % float(c.get('ROTATION', 0) or 0), (c.get('PATTERN') or '').strip()]))
            count['C'] += 1
        crot = [float(c.get('ROTATION', 0) or 0) for c in comps]

        def head(b):
            return b[0], struct.unpack_from('<H', b, 3)[0], struct.unpack_from('<H', b, 5)[0], struct.unpack_from('<H', b, 7)[0]

        for _, b in _bin_records(_stream(ole, 'Vias6')):
            lay, n, poly, comp = head(b)
            x, y, size = struct.unpack_from('<iii', b, 13)
            lines.append('|'.join(['V', net(n), '0', f(X(x)), f(Y(y)), f(size * U)])); count['V'] += 1
        for _, b in _bin_records(_stream(ole, 'Tracks6')):
            lay, n, poly, comp = head(b)
            if lay not in LAYERS:
                continue
            if poly != NONE or comp != NONE:
                count['skipped'] += 1; continue
            x1, y1, x2, y2, w = struct.unpack_from('<iiiii', b, 13)
            lines.append('|'.join(['T', net(n), '0', LAYERS[lay], f(X(x1)), f(Y(y1)), f(X(x2)), f(Y(y2)), f(w * U)])); count['T'] += 1
        for _, b in _bin_records(_stream(ole, 'Arcs6')):
            lay, n, poly, comp = head(b)
            if lay not in LAYERS:
                continue
            if poly != NONE or comp != NONE:
                count['skipped'] += 1; continue
            cx, cy, r = struct.unpack_from('<iii', b, 13)
            a1, a2 = struct.unpack_from('<dd', b, 25)
            w = struct.unpack_from('<i', b, 41)[0]
            lines.append('|'.join(['A', net(n), '0', LAYERS[lay], f(X(cx)), f(Y(cy)), f(r * U), '%.6f' % a1, '%.6f' % a2, f(w * U)])); count['A'] += 1
        for name, b in _pads(_stream(ole, 'Pads6')):
            lay, n, poly, comp = head(b)
            if lay not in LAYERS:
                continue
            x, y = struct.unpack_from('<ii', b, 13)
            # 크기는 윗면 / 중간 / 아랫면 순으로 들어 있다. 아랫면 SMD 패드는 윗면 값이 1mil 짜리 자리표시다
            sx, sy = struct.unpack_from('<ii', b, 37 if lay == 32 else 21)
            if lay == 74 and sx <= 300:
                sx, sy = struct.unpack_from('<ii', b, 29)
            rot = struct.unpack_from('<d', b, 52)[0]
            owner = names[comp] if comp != NONE and comp < len(names) else ''
            if sx <= 10000:                       # 1mil 자리표시: 실제 모양은 패드 템플릿·리전에 있다
                count['padsize'] += 1
            lines.append('|'.join(['P', net(n), '0', f'{owner}-{name}', f(X(x)), f(Y(y)),
                                   '%.6f' % (crot[comp] if comp != NONE and comp < len(crot) else 0.0),
                                   f(sx * U), f(sy * U), '%.6f' % rot, LAYERS[lay]])); count['P'] += 1
        for kind, b in _bin_records(_stream(ole, 'Regions6')):
            if len(b) < 26:
                continue
            lay, n, poly, comp = head(b)
            if lay not in LAYERS or poly != NONE:                     # 폴리곤이 부은 조각은 뺀다
                continue
            hlen = struct.unpack_from('<I', b, 18)[0]
            props = dict(FIELD.findall(b[22:22 + hlen].decode('latin-1')))
            pos = 22 + hlen
            nv = struct.unpack_from('<I', b, pos)[0]
            if nv < 3 or pos + 4 + 16 * nv > len(b):
                continue
            pts = [struct.unpack_from('<dd', b, pos + 4 + 16 * i) for i in range(nv)]
            xs, ys = [X(p[0]) for p in pts], [Y(p[1]) for p in pts]
            what = 'keepout' if b[2] == 2 else ('cutout' if props.get('KIND', '0').strip() == '1' else
                                                ('padshape' if 'PADINDEX' in props or comp != NONE else 'copper'))
            lines.append('|'.join(['R', net(n), '0', LAYERS[lay], f(min(xs)), f(min(ys)), f(max(xs)), f(max(ys)), what,
                                   ';'.join('%.6f,%.6f' % (x, y) for x, y in zip(xs, ys))])); count['R'] += 1
        for kind, b in _bin_records(_stream(ole, 'Fills6')):
            if len(b) < 29:
                continue
            lay, n, poly, comp = head(b)
            if lay not in LAYERS or poly != NONE:
                continue
            x1, y1, x2, y2 = struct.unpack_from('<iiii', b, 13)
            lines.append('|'.join(['R', net(n), '0', LAYERS[lay], f(min(X(x1), X(x2))), f(min(Y(y1), Y(y2))),
                                   f(max(X(x1), X(x2))), f(max(Y(y1), Y(y2))), 'keepout' if b[2] == 2 else 'copper'])); count['R'] += 1
        return lines, count
    finally:
        ole.close()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    lines, count = read(sys.argv[1])
    with open(sys.argv[2], 'w', encoding='latin-1') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('외곽 {O}, 부품 {C}, 비아 {V}, 트랙 {T}, 아크 {A}, 패드 {P}, 리전·필 {R} / 폴리곤·풋프린트 소속이라 뺀 것 {skipped}'.format(**count))
    if count['padsize']:
        print('크기를 파일에서 못 읽은 패드 {padsize}개 (패드 템플릿을 쓰는 패드 - 0.025mm 로 나온다). '
              '이 패드의 간격은 믿지 말고 dump_copper 덤프를 쓴다.'.format(**count))


if __name__ == '__main__':
    main()
