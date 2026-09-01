# -*- coding: utf-8 -*-
"""Read a .PcbDoc without opening Altium.

    python parse_pcbdoc.py <file.PcbDoc> <section> [filter]

    stackup      한 층씩 — 동박 두께(mm + oz), 유전체 재질/Er/두께, 총 두께
    components   지정자 -> 풋프린트
    rules        설계 룰. filter 로 RULEKIND 지정 (예: DiffPairsRouting)
    classes      넷/부품/차동 클래스와 멤버
    diffpairs    차동 페어와 +/- 넷
    summary      위를 한 번에 요약

Altium 을 거치지 않으므로 스크립트 실행기가 wedge 될 일이 없고, 열려 있지 않은
보드도 읽는다. 활성 문서가 무엇이냐에 결과가 좌우되지도 않는다 - MCP 쪽
`PCBServer.GetCurrentPCBBoard` 는 세션 전역이라 다른 보드를 읽어오는 사고가
실제로 있었다.

형식 메모
---------
`.PcbDoc` 은 OLE 복합 문서지만, 그 안의 레코드는 파이프로 구분된 평문이고
레코드 사이는 NUL 로 끊긴다. **반드시 NUL 로 먼저 쪼갠 뒤** 필드를 뽑을 것.
파일 전체에 정규식을 걸면 인접 레코드의 값이 섞여 들어온다 - 그렇게 해서
CAN-120 룰에 없는 값이 있는 것처럼 읽힌 적이 있다.

좌표·치수는 내부 단위(1/10000 mil)로 들어 있다. 여기서는 전부 mm 로 바꿔
내보낸다. 동박 두께만 관례상 oz 를 함께 적는다.
"""
import re
import sys

MM_PER_UNIT = 0.00000254        # 내부 단위(1/10000 mil) -> mm
MM_PER_MIL = 0.0254
OZ_MM = 0.03480                 # 동박 1 oz/ft^2 = 0.0348 mm

FIELD = re.compile(r'\|([A-Za-z0-9_. ]+)=([^|]*)')


def records(path):
    """NUL 로 끊긴 레코드를 하나씩 필드 딕셔너리로."""
    blob = open(path, 'rb').read()
    for chunk in blob.split(b'\x00'):
        text = chunk.decode('latin-1')
        if '=' not in text:
            continue
        yield dict(FIELD.findall('|' + text.lstrip('|')))


def _mm(value, default=0.0):
    """'4.1402mil' / '0.105mm' -> mm 실수."""
    if not value:
        return default
    s = str(value).strip().lower()
    try:
        if s.endswith('mm'):
            return float(s[:-2])
        if s.endswith('mil'):
            return float(s[:-3]) * MM_PER_MIL
        return float(s) * MM_PER_MIL          # 단위 없으면 mil 로 본다
    except ValueError:
        return default


def _slot(index):
    if index == 1:
        return 'Top'
    if index == 32:
        return 'Bottom'
    return 'MidLayer%d' % (index - 1)


def stackup(path):
    """실제로 쓰이는 층만 PREV/NEXT 연결 순서대로."""
    raw, mask = {}, {}
    for rec in records(path):
        for key, value in rec.items():
            m = re.fullmatch(r'LAYER(\d+)(NAME|PREV|NEXT|COPTHICK|DIELTYPE|'
                             r'DIELCONST|DIELHEIGHT|DIELMATERIAL)', key)
            if m:
                raw.setdefault(int(m.group(1)), {})[m.group(2)] = value
            elif key in ('TOPHEIGHT', 'TOPCONST', 'TOPMATERIAL'):
                mask[key] = value
    if not raw:
        return [], {}

    kinds = {'0': '없음', '1': 'Core', '2': 'PrePreg', '3': 'Surface'}
    out, index, seen = [], 1, set()
    while index and index not in seen:
        seen.add(index)
        layer = raw.get(index, {})
        copper = _mm(layer.get('COPTHICK'))
        out.append({
            'slot': _slot(index),
            'name': layer.get('NAME', '?'),
            'copper_mm': copper,
            'copper_oz': copper / OZ_MM if copper else 0.0,
            'dielectric': layer.get('DIELMATERIAL', ''),
            'dielectric_kind': kinds.get(layer.get('DIELTYPE'), layer.get('DIELTYPE', '')),
            'er': layer.get('DIELCONST', ''),
            'dielectric_mm': _mm(layer.get('DIELHEIGHT')),
        })
        nxt = layer.get('NEXT', '0')
        index = int(nxt) if nxt.isdigit() else 0
    return out, {'mask_mm': _mm(mask.get('TOPHEIGHT')),
                 'mask_er': mask.get('TOPCONST', ''),
                 'mask_material': mask.get('TOPMATERIAL', '')}


def components(path):
    """지정자 -> 풋프린트. 배치된 실물이 기준이므로 부품표보다 이쪽이 정답이다."""
    out = {}
    for rec in records(path):
        des = (rec.get('SOURCEDESIGNATOR') or '').strip()
        pat = (rec.get('PATTERN') or '').strip()
        if des and pat:
            out[des] = pat
    return out


def rules(path, kind=None):
    out = []
    for rec in records(path):
        rk = rec.get('RULEKIND')
        if not rk or (kind and rk.lower() != kind.lower()):
            continue
        out.append(rec)
    return out


def classes(path, kind=None):
    """KIND=1 부품, 6 차동 페어, 7 폴리곤. 멤버는 M0, M1, … 로 들어 있다."""
    out = []
    for rec in records(path):
        if 'KIND' not in rec or 'NAME' not in rec or 'SUPERCLASS' not in rec:
            continue
        if kind is not None and rec['KIND'] != str(kind):
            continue
        members = [v for k, v in sorted(rec.items(),
                                        key=lambda kv: int(kv[0][1:]) if re.fullmatch(r'M\d+', kv[0]) else 0)
                   if re.fullmatch(r'M\d+', k)]
        out.append({'name': rec['NAME'], 'kind': rec['KIND'], 'members': members})
    return out


def diffpairs(path):
    out = []
    for rec in records(path):
        pos = rec.get('POSITIVENETNAME') or rec.get('POSITIVENET')
        neg = rec.get('NEGATIVENETNAME') or rec.get('NEGATIVENET')
        if pos and neg:
            out.append({'name': rec.get('NAME', '?'), 'positive': pos, 'negative': neg})
    return out


def _print_stackup(path):
    layers, mask = stackup(path)
    if not layers:
        print('  (스택업 정보 없음)')
        return
    if mask.get('mask_mm'):
        print('  솔더마스크 %.4f mm  Er %s  (%s)'
              % (mask['mask_mm'], mask['mask_er'], mask['mask_material']))
    print('  %-12s %-16s %-22s %-24s %-6s %s'
          % ('슬롯', '층 이름', '동박', '유전체', 'Er', '유전체 두께'))
    total = 0.0
    for i, L in enumerate(layers):
        total += L['copper_mm']
        line = ('  %-12s %-16s %-22s' %
                (L['slot'], L['name'], '%.4f mm (%.2foz)' % (L['copper_mm'], L['copper_oz'])))
        if i < len(layers) - 1:
            total += L['dielectric_mm']
            line += (' %-24s %-6s %.4f mm'
                     % ('%s / %s' % (L['dielectric'], L['dielectric_kind']),
                        L['er'], L['dielectric_mm']))
        print(line)
    print('  합계(동박+유전체) %.4f mm   층 수 %d' % (total, len(layers)))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    path, section = sys.argv[1], sys.argv[2].lower()
    arg = sys.argv[3] if len(sys.argv) > 3 else None

    if section in ('stackup', 'summary'):
        print('=== 스택업 ===')
        _print_stackup(path)
        if section == 'stackup':
            return 0
        print()

    if section in ('components', 'summary'):
        comp = components(path)
        print('=== 부품 %d개 ===' % len(comp))
        for des in (sorted(comp)[:12] if section == 'summary' else sorted(comp)):
            print('  %-10s %s' % (des, comp[des]))
        if section == 'summary' and len(comp) > 12:
            print('  … 외 %d개' % (len(comp) - 12))
        if section == 'components':
            return 0
        print()

    if section in ('rules', 'summary'):
        found = rules(path, arg if section == 'rules' else None)
        kinds = {}
        for r in found:
            kinds.setdefault(r['RULEKIND'], []).append(r)
        print('=== 룰 %d개 / %d종 ===' % (len(found), len(kinds)))
        for kind, group in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
            for r in group:
                print('  %-22s %-24s scope=%s'
                      % (kind, r.get('NAME', '?'), r.get('SCOPE1EXPRESSION', '')))
            if section == 'summary':
                break
        if section == 'rules':
            if arg and found:
                print()
                for r in found:
                    print('--- %s' % r.get('NAME'))
                    for k in sorted(r):
                        if k in ('RULEKIND', 'NAME'):
                            continue
                        if re.search(r'GAP|WIDTH|LIMIT|CLEARANCE|LENGTH|TOLERANCE', k):
                            print('    %-24s %-12s %.4f mm' % (k, r[k], _mm(r[k])))
            return 0
        print()

    if section in ('classes', 'summary'):
        found = classes(path, int(arg) if (section == 'classes' and arg) else None)
        print('=== 클래스 %d개 ===' % len(found))
        for c in found:
            if c['members'] or section == 'classes':
                print('  KIND=%-3s %-26s %s' % (c['kind'], c['name'], c['members'][:10]))
        if section == 'classes':
            return 0
        print()

    if section in ('diffpairs', 'summary'):
        found = diffpairs(path)
        print('=== 차동 페어 %d개 ===' % len(found))
        for p in found:
            print('  %-14s +%-18s -%s' % (p['name'], p['positive'], p['negative']))
        return 0

    print('알 수 없는 section: %s' % section)
    return 1


if __name__ == '__main__':
    sys.exit(main())
