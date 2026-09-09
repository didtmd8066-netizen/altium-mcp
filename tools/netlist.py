# -*- coding: utf-8 -*-
"""핀-넷 연결을 오프라인으로 조회한다.

    python netlist.py script                     # 덤프용 DelphiScript 를 찍는다
    python netlist.py pin   <부품> <핀>          # 그 핀의 넷
    python netlist.py net   <넷>                 # 그 넷에 붙은 핀
    python netlist.py trace <부품> <핀>          # 직렬 소자를 건너 경로 전체
    python netlist.py comp  <부품[,부품...]>     # 부품의 핀-넷 목록
    python netlist.py block <시드[,시드...]>     # 시드(Q/U)에 딸린 수동소자 묶음
    python netlist.py swap  <시드A> <시드B> --pcbdoc <file>   # 두 블록 맞바꾸는 이동량
    python netlist.py clone <기준> <대상[,대상...]> --pcbdoc <file> --wires <dump>
                                                 # 기준 블록의 배선을 대상에 복제할 계획

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

`clone` 은 기준 블록의 트랙·비아를 대상 블록 위치로 옮긴 좌표와, 대상의
기존 배선을 지울 키 목록을 만든다. 넷 이름은 역할(gate/drain/in/out)로
대응시켜 치환하고, 공유 넷(SB_24V 등)은 그대로 둔다. 블록 **경계 안**에
양 끝이 들어오는 것만 대상이라, 커넥터로 빠져나가는 긴 배선은 건드리지
않는다. 출력한 create.txt / delete.txt 를 run_altium_script 에 넘긴다.
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
MM_PER_UNIT = 0.00000254        # .PcbDoc 내부 단위(1/10000 mil) -> mm
by_net_global = {}


def origin_of(pcbdoc):
    from parse_pcbdoc import origin
    return origin(pcbdoc)

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


def roles_of(by_comp, block, seed):
    """블록 안에서 각 부품의 역할과 넷을 식별한다."""
    d = dict(by_comp[seed])
    gate, drain = d.get('1'), d.get('3')
    r = {'gate': gate, 'drain': drain}
    for c in block:
        if c == seed:
            continue
        nets = [n for _, n in by_comp[c]]
        if c.startswith('C'):
            r['C'] = c
        elif gate in nets:
            r['Rg'] = c
            r['in'] = next((n for n in nets if n != gate), None)
        elif any(POWER.match(n) or len(by_net_global[n]) >= FANOUT_STOP for n in nets):
            r['Rpu'] = c
        else:
            r['Ro'] = c
            r['out'] = next((n for n in nets if n != drain), None)
    return r


def cmd_clone(by_net, by_comp, ref, targets, pcbdoc, wires, outdir):
    from parse_pcbdoc import positions
    global by_net_global
    by_net_global = by_net

    rows = [l.strip().split('|') for l in open(wires, encoding='latin-1') if l.strip()]
    blocks = {s: block_of(by_net, by_comp, s)[0] for s in [ref] + targets}
    pos = positions(pcbdoc, [d for g in blocks.values() for d in g])
    R = {s: roles_of(by_comp, blocks[s], s) for s in blocks}

    def bbox(s, pad=1.5):
        xs = [pos[d]['x'] for d in blocks[s]]
        ys = [pos[d]['y'] for d in blocks[s]]
        return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad

    ox, oy = origin_of(pcbdoc)

    def inside(s, r):
        x0, x1, y0, y1 = bbox(s)
        pts = [(int(r[4]) * MM_PER_UNIT - ox, int(r[5]) * MM_PER_UNIT - oy)]
        if r[0] == 'T':
            pts.append((int(r[6]) * MM_PER_UNIT - ox, int(r[7]) * MM_PER_UNIT - oy))
        return all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts)

    own = {R[ref][k] for k in ('gate', 'drain', 'in', 'out')}
    # 공유 넷(SB_24V·GND 같은 전원·버스)은 복제도 삭제도 하지 않는다. 블록
    # 사이를 잇는 배선이라 블록마다 형상이 다르고 이미 깔려 있어서, 대상마다
    # 사본이 하나씩 더 생기면 같은 자리에 트랙·비아가 여러 겹으로 쌓인다.
    # 판정은 넷 이름이 아니라 전원 패턴 또는 팬아웃 기준으로 한다 - 덤프에
    # 다른 블록의 넷이 섞여 있으면 "내 넷이 아닌 것"은 전부 공유로 잡힌다.
    shared = {n for n in {r[1] for r in rows}
              if POWER.match(n) or len(by_net[n]) >= FANOUT_STOP}
    src = [r for r in rows if r[1] in own and inside(ref, r)]
    rn = {R[ref][k]: k for k in ('gate', 'drain', 'in', 'out')}

    dele, crea = [], []
    for t in targets:
        dx = int(round((pos[t]['x'] - pos[ref]['x']) / MM_PER_UNIT))
        dy = int(round((pos[t]['y'] - pos[ref]['y']) / MM_PER_UNIT))
        tn = {k: R[t][k] for k in ('gate', 'drain', 'in', 'out')}
        for r in rows:
            if r[1] in set(tn.values()) and inside(t, r):
                key = [r[0], r[1], r[4], r[5], r[6] if r[0] == 'T' else '0']
                dele.append('|'.join(key))
        for r in src:
            net = tn[rn[r[1]]]
            if r[0] == 'T':
                crea.append(('T', net, r[2], r[3], int(r[4]) + dx, int(r[5]) + dy,
                             int(r[6]) + dx, int(r[7]) + dy))
            elif r[0] == 'V':
                crea.append(('V', net, r[2], r[3], int(r[4]) + dx, int(r[5]) + dy, r[6], 0))

    crea.sort(key=lambda c: (c[1], c[0]))          # 넷 조회를 넷당 1회로
    cpath = os.path.join(outdir, 'create.txt')
    dpath = os.path.join(outdir, 'delete.txt')
    with open(cpath, 'w', encoding='latin-1') as fh:                 # 한 필드 한 줄
        fh.write(chr(10).join(str(v) for row in crea for v in row))
    with open(dpath, 'w', encoding='latin-1') as fh:                 # IndexOf 매칭용 한 줄
        fh.write(chr(10).join(dele))
    print('기준 %s  블록 고유 넷의 트랙 %d · 비아 %d   (공유 넷 %d종은 제외)'
          % (ref, len([r for r in src if r[0] == 'T']),
             len([r for r in src if r[0] == 'V']), len(shared)))
    print('대상 %s' % ', '.join(targets))
    print('  생성 %d개 -> %s   (%d줄, 넷 %d종)'
          % (len(crea), cpath, len(crea) * 8, len({c[1] for c in crea})))
    print('  삭제 %d개 -> %s' % (len(dele), dpath))


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
    ap.add_argument('command', choices=['script', 'pin', 'net', 'trace', 'comp', 'block', 'swap', 'clone'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--dump', default=DEFAULT)
    ap.add_argument('--pcbdoc')
    ap.add_argument('--wires', help='트랙·비아 덤프 파일 (clone 전용)')
    ap.add_argument('--outdir', default='.', help='create.txt/delete.txt 출력 폴더')
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
    elif a.command == 'clone':
        if not (a.pcbdoc and a.wires):
            print('--pcbdoc 와 --wires 가 필요하다'); return 1
        cmd_clone(by_net, by_comp, a.args[0],
                  [x.strip() for x in a.args[1].split(',') if x.strip()],
                  a.pcbdoc, a.wires, a.outdir)
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
