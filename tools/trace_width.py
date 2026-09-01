# -*- coding: utf-8 -*-
"""전류에 필요한 선폭을, 그 보드의 실제 동박 두께로 계산한다.

    python trace_width.py <file.PcbDoc> 5A,3A,2A,500mA [--dt 10]
    python trace_width.py <file.PcbDoc> --width 0.5mm      # 역산: 이 선폭이 견디는 전류

IPC-2221:  I = k · ΔT^0.44 · A^0.725   (A: mil², k 외층 0.048 / 내층 0.024)

**내층과 외층을 항상 함께 낸다.** 한쪽만 답해서 다시 묻게 하지 않기 위한 것이고,
동박 두께는 보드마다 다르므로 스택업에서 직접 읽는다. 같은 2A라도
HK_BLE_Receiver(외층 1.15oz)는 0.684 mm, Safety Carrier(0.95oz)는 0.828 mm다.

내층 계수 k=0.024 는 외층의 절반이라 결과가 매우 보수적으로 나온다. 여기 나온
내층 값은 배선으로 뽑기 어려운 경우가 많으니, 전원은 폴리곤/플레인으로
처리하는 쪽이 현실적이다. 그 판단은 사람이 한다.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_pcbdoc import stackup, OZ_MM                      # noqa: E402

MM_PER_MIL = 0.0254
K_OUTER, K_INNER = 0.048, 0.024


def amps(text):
    """'5A' / '500mA' / '2.5' -> 암페어."""
    m = re.fullmatch(r'\s*([\d.]+)\s*(m?)A?\s*', str(text), re.I)
    if not m:
        raise ValueError('전류를 읽을 수 없다: %r' % text)
    value = float(m.group(1))
    return value / 1000 if m.group(2) else value


def millimetres(text):
    m = re.fullmatch(r'\s*([\d.]+)\s*(mm|mil)?\s*', str(text), re.I)
    if not m:
        raise ValueError('선폭을 읽을 수 없다: %r' % text)
    value = float(m.group(1))
    return value * MM_PER_MIL if (m.group(2) or '').lower() == 'mil' else value


def width_mm(current, k, copper_mm, dt):
    """필요 선폭(mm)."""
    area = (current / (k * dt ** 0.44)) ** (1 / 0.725)        # mil²
    return area / (copper_mm / MM_PER_MIL) * MM_PER_MIL


def current_a(width, k, copper_mm, dt):
    """이 선폭이 견디는 전류(A)."""
    area = (width / MM_PER_MIL) * (copper_mm / MM_PER_MIL)    # mil²
    return k * dt ** 0.44 * area ** 0.725


def copper(path):
    """외층/내층 동박 두께(mm). 층마다 다르면 가장 얇은 쪽을 쓴다 - 안전측."""
    layers, _ = stackup(path)
    if not layers:
        raise SystemExit('스택업을 읽지 못했다: %s' % path)
    outer = [L for L in layers if L['slot'] in ('Top', 'Bottom')]
    inner = [L for L in layers if L['slot'] not in ('Top', 'Bottom')]
    return (min(L['copper_mm'] for L in outer),
            min(L['copper_mm'] for L in inner) if inner else None,
            layers)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('pcbdoc')
    ap.add_argument('currents', nargs='?', default='')
    ap.add_argument('--width')
    ap.add_argument('--dt', type=float, default=10.0)
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    a = ap.parse_args()

    out_mm, in_mm, layers = copper(a.pcbdoc)
    print('%s' % os.path.basename(a.pcbdoc))
    print('  동박  외층 %.4f mm (%.2foz)%s   ΔT %g℃'
          % (out_mm, out_mm / OZ_MM,
             '   내층 %.4f mm (%.2foz)' % (in_mm, in_mm / OZ_MM) if in_mm else '',
             a.dt))
    print()

    if a.width:
        w = millimetres(a.width)
        print('  선폭 %.3f mm 가 견디는 전류' % w)
        print('    외층 %.2f A' % current_a(w, K_OUTER, out_mm, a.dt))
        if in_mm:
            print('    내층 %.2f A' % current_a(w, K_INNER, in_mm, a.dt))
        return 0

    if not a.currents:
        print('  전류를 지정하거나 --width 를 쓸 것')
        return 1

    print('  %-8s %-14s %s' % ('전류', '외층', '내층'))
    for token in a.currents.split(','):
        token = token.strip()
        if not token:
            continue
        i = amps(token)
        wo = width_mm(i, K_OUTER, out_mm, a.dt)
        wi = width_mm(i, K_INNER, in_mm, a.dt) if in_mm else None
        print('  %-8s %-14s %s' % (token,
                                   '%.3f mm' % wo,
                                   '%.3f mm' % wi if wi else '-'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
