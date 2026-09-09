# -*- coding: utf-8 -*-
"""핀-넷 연결을 오프라인으로 조회한다.

    python netlist.py script                     # 덤프용 DelphiScript 를 찍는다
    python netlist.py pin   <부품> <핀>          # 그 핀의 넷
    python netlist.py net   <넷>                 # 그 넷에 붙은 핀
    python netlist.py trace <부품> <핀>          # 직렬 소자를 건너 경로 전체
    python netlist.py comp  <부품[,부품...]>     # 부품의 핀-넷 목록
    python netlist.py block <시드[,시드...]>     # 시드(Q/U)에 딸린 수동소자 묶음
    python netlist.py swap  <시드A> <시드B> --pcbdoc <file>   # 두 블록 맞바꾸는 이동량

패드와 넷의 연결은 `.PcbDoc` 안에 바이너리로 들어 있어 parse_pcbdoc 로는 못
읽는다. 그래서 Altium 에서 한 번만 덤프를 받아(`script` 가 그 스크립트를
내준다) 그 텍스트로 이후 조회를 전부 오프라인 처리한다. Altium 왕복 1회면
경로 추적을 몇 번을 하든 추가 호출이 없다.

`trace` 는 2핀 수동소자(R/C/L)만 통과시킨다. RF 매칭망이나 직렬 커플링처럼
넷이 소자마다 끊기는 경로를 한 덩어리로 보기 위한 것이고, IC·커넥터에
닿으면 거기서 멈춘다. 전원·GND 넷으로는 넘어가지 않는다 - 안 그러면 보드
전체가 한 경로로 이어져 버린다.

`block` 은 반복 회로(레벨 시프터·채널 회로)를 한 덩어리로 잡는다. 시드
부품에서 넷을 따라 2핀 수동소자만 흡수하고, 다른 능동소자나 전원·GND 를
만나면 멈춘다. `swap` 은 두 블록을 맞바꾸는 데 필요한 move_components 인자를
바로 계산해 준다 - 블록 내부 배치가 같으면 평행이동 두 번으로 끝난다.
"""
import argparse
import collections
import os
import re
import sys

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pads.txt')
POWER = re.compile(r'^(GND|VCC|VDD|VIN|VBAT|VBUS|\+?\d+V\d*|.*_\d+V\d*|MAIN_POWER|BACKUP)', re.I)
# 이름만으로는 전원 넷을 다 못 거른다(SB_24V 처럼 보드마다 다르다).
# 붙은 부품이 이 수 이상이면 전원·버스로 보고 블록 확장을 멈춘다.
FANOUT_STOP = 6
PASSIVE = 'RCL'
MM_PER_MIL = 0.0254

DUMP_SCRIPT = r"""Obj1 := PCBServer.GetCurrentPCBBoard;
Obj2 := Obj1.BoardIterator_Create;
Obj2.AddFilter_ObjectSet(MkSet(ePadObject));
Obj2.AddFilter_LayerSet(AllLayers);
Obj2.AddFilter_Method(eProcessAll);
Obj3 := Obj2.FirstPCBObject;
I1 := 0;
while (Obj3 <> Nil) do
begin
    Obj4 := Obj3.Component;
    if (Obj4 <> Nil) then
    begin
        S1 := Obj4.Name.Text;
        S2 := Obj3.Name;
        if (Obj3.Net <> Nil) then S3 := Obj3.Net.Name else S3 := '-';
        List1.Add(S1 + '|' + S2 + '|' + S3);
        I1 := I1 + 1;
    end;
    Obj3 := Obj2.NextPCBObject;
end;
Obj1.BoardIterator_Destroy(Obj2);
List1.SaveToFile('%s');
ResultText := 'pads=' + IntToStr(I1);"""


def load(path):
    if not os.path.exists(path):
        raise SystemExit('덤프가 없다: %s\n  netlist.py script 로 스크립트를 받아 '
                         'run_altium_script 로 한 번 돌릴 것' % path)
    by_net, by_comp = collections.defaultdict(list), collections.defaultdict(list)
    for line in open(path, encoding='latin-1'):
        parts = line.rstrip('\n').split('|')
        if len(parts) == 3 and parts[2] != '-':
            comp, pin, net = parts
            by_net[net].append((comp, pin))
            by_comp[comp].append((pin, net))
    return by_net, by_comp


def pins_of(by_net, net):
    return ' , '.join('%s.%s' % (c, p) for c, p in sorted(by_net[net]))


def sort_key(des):
    digits = re.sub(r'\D', '', des)
    return (re.sub(r'\d', '', des), int(digits) if digits else 0)


def block_of(by_net, by_comp, seed):
    """시드에 딸린 2핀 수동소자를 모아 한 블록으로. 시드 자신도 포함."""
    def is_rail(n):
        return POWER.match(n) or len(by_net[n]) >= FANOUT_STOP

    seen = {seed}
    queue = [n for _, n in by_comp[seed] if not is_rail(n)]
    nets = set(queue)
    while queue:
        net = queue.pop(0)
        for c, _ in by_net[net]:
            if c in seen:
                continue
            pins = by_comp[c]
            if len(pins) != 2 or c[0].upper() not in PASSIVE:
                continue                      # 다른 능동소자에서 멈춘다
            seen.add(c)
            for _, n2 in pins:
                if n2 not in nets and not is_rail(n2):
                    nets.add(n2)
                    queue.append(n2)
    return sorted(seen, key=sort_key), sorted(nets)


def cmd_block(by_net, by_comp, seeds):
    for seed in seeds:
        if seed not in by_comp:
            print('%s : 없음' % seed)
            continue
        parts, nets = block_of(by_net, by_comp, seed)
        print('%-6s 부품 %d개  %s' % (seed, len(parts), ', '.join(parts)))
        print('       넷 %d개  %s' % (len(nets), ', '.join(nets)))


def cmd_swap(by_net, by_comp, a, b, pcbdoc):
    from parse_pcbdoc import positions
    pa, _ = block_of(by_net, by_comp, a)
    pb, _ = block_of(by_net, by_comp, b)
    pos = positions(pcbdoc, pa + pb)
    missing = [d for d in pa + pb if d not in pos]
    if missing:
        print('배치 정보 없음: %s' % ', '.join(missing))
        return

    def bbox(grp):
        xs = [pos[d]['x'] for d in grp]
        ys = [pos[d]['y'] for d in grp]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)

    cax, cay, aw, ah = bbox(pa)
    cbx, cby, bw, bh = bbox(pb)
    for name, grp, c in ((a, pa, (cax, cay, aw, ah)), (b, pb, (cbx, cby, bw, bh))):
        print('=== %s 블록  부품 %d개  중심 (%.3f, %.3f)  범위 %.3f x %.3f'
              % (name, len(grp), c[0], c[1], c[2], c[3]))
        for d in grp:
            q = pos[d]
            print('    %-6s (%8.3f, %8.3f) %-7s 회전 %-4g %s'
                  % (d, q['x'], q['y'], q['layer'][:6], q['rotation'], q['footprint']))
    dx, dy = cbx - cax, cby - cay
    print()
    print('중심 차이  dX %+.3f mm  dY %+.3f mm' % (dx, dy))
    if abs(aw - bw) > 0.01 or abs(ah - bh) > 0.01:
        print('※ 두 블록의 크기가 다르다 - 평행이동만으로는 자리가 정확히 맞지 않는다')
    print()
    print('move_components 인자 (x_offset/y_offset 은 mil)')
    for name, grp, sx, sy in ((a, pa, dx, dy), (b, pb, -dx, -dy)):
        print('  %-6s x_offset=%9.4f  y_offset=%9.4f   %s'
              % (name, sx / MM_PER_MIL, sy / MM_PER_MIL, ', '.join(grp)))


def cmd_trace(by_net, by_comp, comp, pin):
    start = dict(by_comp[comp]).get(pin)
    if not start:
        raise SystemExit('%s 핀 %s 의 넷을 못 찾음' % (comp, pin))

    seen, queue, hops = {start}, [start], []
    while queue:
        net = queue.pop(0)
        for c, p in by_net[net]:
            if c == comp:
                continue
            pins = by_comp[c]
            if len(pins) != 2 or c[0].upper() not in PASSIVE:
                continue                      # IC·커넥터에서 멈춘다
            other = [n for q, n in pins if q != p]
            if other and other[0] not in seen and not POWER.match(other[0]):
                seen.add(other[0])
                queue.append(other[0])
                hops.append((net, c, other[0]))

    print('%s 핀 %s  ->  %s\n' % (comp, pin, start))
    print('경로 넷 %d개' % len(seen))
    for n in sorted(seen):
        print('  %-14s %s' % (n, pins_of(by_net, n)))
    ends = sorted({'%s.%s' % (c, p) for n in seen for c, p in by_net[n]
                   if not (len(by_comp[c]) == 2 and c[0].upper() in PASSIVE)})
    print('\n끝점 %s' % ' , '.join(ends))
    if hops:
        print('\n통과한 직렬 소자')
        for a, c, b in hops:
            print('  %-14s --%-5s--> %s' % (a, c, b))
    print('\n넷 클래스에 넣을 목록')
    print('  %s' % ', '.join('"%s"' % n for n in sorted(seen)))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('command', choices=['script', 'pin', 'net', 'trace', 'comp', 'block', 'swap'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--dump', default=DEFAULT)
    ap.add_argument('--pcbdoc')
    ap.add_argument('--fanout', type=int, default=FANOUT_STOP,
                    help='이 수 이상 부품이 붙은 넷은 전원·버스로 보고 확장을 멈춘다')
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    a = ap.parse_args()

    if a.command == 'script':
        print(DUMP_SCRIPT % os.path.abspath(a.dump).replace('/', chr(92)))
        return 0

    globals()['FANOUT_STOP'] = a.fanout
    by_net, by_comp = load(a.dump)

    if a.command == 'comp':
        for comp in [x.strip() for x in a.args[0].split(',') if x.strip()]:
            print('%s' % comp)
            for pin, net in sorted(by_comp[comp], key=lambda t: (len(t[0]), t[0])):
                print('  %-6s %s' % (pin, net))
    elif a.command == 'block':
        cmd_block(by_net, by_comp, [x.strip() for x in a.args[0].split(',') if x.strip()])
    elif a.command == 'swap':
        if not a.pcbdoc:
            print('--pcbdoc 로 .PcbDoc 경로를 지정할 것'); return 1
        cmd_swap(by_net, by_comp, a.args[0], a.args[1], a.pcbdoc)
    elif a.command == 'pin':
        comp, pin = a.args[0], a.args[1]
        net = dict(by_comp[comp]).get(pin)
        print(net or '(넷 없음)')
    elif a.command == 'net':
        print(pins_of(by_net, a.args[0]) or '(그런 넷 없음)')
    else:
        cmd_trace(by_net, by_comp, a.args[0], a.args[1])
    return 0


if __name__ == '__main__':
    sys.exit(main())
