# -*- coding: utf-8 -*-
"""두 .PcbDoc 의 부품을 대조한다 - 회로가 바뀐 뒤 무엇이 달라졌는지 본다. Altium 을 부르지 않는다.

    python pcb_diff.py <이전.PcbDoc> <이후.PcbDoc>

이전 파일은 보통 History 폴더의 `<이름>.~(번호).PcbDoc.Zip` 을 풀어서 쓴다 (회로 반영 직전 저장본).
지정자 기준으로 짝을 짓는다. 회로도를 새로 그리면 UniqueId 가 바뀌어 UniqueId 로는 짝이 안 맞는다.

보는 것
-------
- 지정자가 한쪽에만 있는 부품
- 풋프린트(PATTERN)가 바뀐 부품  - 사이즈 변경
- Comment 가 바뀐 부품           - 값·품번 변경 (대소문자만 다른 것은 뺀다)
- 핀별 넷이 바뀐 곳. 2핀 부품의 두 넷이 서로 맞바뀐 것은 따로 모은다 - 배선이 끝난 부품이면
  패드와 배선의 넷이 엇갈리므로 180도 돌려야 한다. 넷 이름만 _2 -> _1 처럼 바뀐 것도 여기 걸린다.

Texts6 형식 메모 (AD24, 2026-10-14 NEW_BASE_MOTOR 에서 확인)
-------------------------------------------------------------
[종류 5][길이 u32][본문][길이 u32][파스칼 문자열] 의 반복. 본문 [7:9] 부품 번호, [40] Comment 표시,
[41] 지정자 표시, [115:119] WideStrings6 번호 (그쪽 글자가 있으면 그쪽이 원문).
772 부품 보드 두 개에서 지정자 글자가 Components6 의 SOURCEDESIGNATOR 와 전부 일치했다.
"""
import struct
import sys

import olefile

from pcbdoc_dump import NONE, _pads, _stream, _text_records


def _wide(ole):
    try:
        data = _stream(ole, 'WideStrings6')
    except OSError:
        return {}
    n = struct.unpack_from('<I', data, 0)[0]
    out = {}
    for kv in data[4:4 + n].rstrip(b'\x00').decode('latin-1').split('|'):
        if kv.startswith('ENCODEDTEXT') and '=' in kv:
            k, v = kv.split('=', 1)
            out[int(k[11:])] = ''.join(chr(int(c)) for c in v.split(',') if c)
    return out


def read(path):
    """{지정자: {'fp': 풋프린트, 'com': Comment, 'pins': {핀: 넷}}}."""
    ole = olefile.OleFileIO(path)
    try:
        comps = _text_records(_stream(ole, 'Components6'))
        nets = [r.get('NAME', '') for r in _text_records(_stream(ole, 'Nets6'))]
        names = [(c.get('SOURCEDESIGNATOR') or '').strip() for c in comps]
        out = {d: {'fp': (c.get('PATTERN') or '').strip(), 'com': None, 'pins': {}} for d, c in zip(names, comps)}
        wide = _wide(ole)
        data, i = _stream(ole, 'Texts6'), 0
        while i < len(data):
            n = struct.unpack_from('<I', data, i + 1)[0]
            body = data[i + 5:i + 5 + n]
            i += 5 + n
            m = struct.unpack_from('<I', data, i)[0]
            s = data[i + 4:i + 4 + m]
            i += 4 + m
            k = struct.unpack_from('<H', body, 7)[0]
            if k == NONE or k >= len(names) or not body[40]:
                continue
            text = s[1:1 + s[0]].decode('cp949', 'replace') if s else ''
            w = struct.unpack_from('<I', body, 115)[0] if len(body) >= 119 else None
            out[names[k]]['com'] = wide.get(w) or text
        for pin, body in _pads(_stream(ole, 'Pads6')):
            k, n = struct.unpack_from('<H', body, 7)[0], struct.unpack_from('<H', body, 3)[0]
            if k != NONE and k < len(names):
                out[names[k]]['pins'][pin] = nets[n] if n != NONE and n < len(nets) else ''
        return out
    finally:
        ole.close()


def _key(d):
    head = d.rstrip('0123456789')
    tail = d[len(head):]
    return head, int(tail) if tail else 0


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding='utf-8')
    a, b = read(sys.argv[1]), read(sys.argv[2])
    gone, new = sorted(set(a) - set(b), key=_key), sorted(set(b) - set(a), key=_key)
    both = sorted(set(a) & set(b), key=_key)
    fp = [(d, a[d]['fp'], b[d]['fp']) for d in both if a[d]['fp'] != b[d]['fp']]
    com = [(d, a[d]['com'], b[d]['com'], b[d]['fp']) for d in both
           if (a[d]['com'] or '').lower() != (b[d]['com'] or '').lower()]
    flip, nets = [], []
    for d in both:
        pa, pb = a[d]['pins'], b[d]['pins']
        ch = [(p, pa.get(p), pb.get(p)) for p in sorted(set(pa) | set(pb)) if pa.get(p) != pb.get(p)]
        if not ch:
            continue
        # 한쪽 넷이 반대 핀으로 옮겨 갔으면 맞바뀐 것이다 (다른 쪽은 이름만 바뀌었을 수 있다)
        if set(pa) == set(pb) == {'1', '2'} and (pa['1'] == pb['2'] or pa['2'] == pb['1']):
            flip.append((d, pa.get('1'), pa.get('2'), pb.get('1'), pb.get('2')))
        else:
            nets += [(d,) + c for c in ch]
    print(f'부품 {len(a)} -> {len(b)}')
    for title, rows in (('없어진 부품', [(d, a[d]['fp'], a[d]['com']) for d in gone]),
                        ('새 부품', [(d, b[d]['fp'], b[d]['com']) for d in new]),
                        ('풋프린트 변경 (이전 -> 이후)', fp),
                        ('Comment 변경 (이전 -> 이후, 풋프린트)', com),
                        ('2핀 부품의 넷이 맞바뀜 (이전 1·2번 -> 이후 1·2번) - 배선했으면 180도', flip),
                        ('핀 넷 변경 (부품, 핀, 이전 -> 이후)', nets)):
        print(f'== {title}: {len(rows)}')
        for r in rows:
            print('   ' + ' | '.join('' if v is None else str(v) for v in r))


if __name__ == '__main__':
    main()
