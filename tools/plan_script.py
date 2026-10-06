# -*- coding: utf-8 -*-
"""덤프·계획 적용 스크립트를 조립한다 (snippets/dump_copper.pas, snippets/apply_plan.pas).

MCP 도구 `dump_copper` / `apply_plan` 이 이 모듈을 쓴다. 그 도구들이 없는 세션에서는
여기서 찍은 스크립트를 `run_altium_script` 에 넣는다 (timeout_seconds: 45).

    python plan_script.py dump <out.txt> [--board 보드]
    python plan_script.py apply [--new new.txt] [--del del.txt] [--delete-first] [--max-delete N] [--board 보드]

--board
-------
안 주면 지금 포커스된 보드를 쓴다. 주면 **그 보드에만** 한다:
  - 전체 경로를 주면 포커스와 상관없이 그 문서를 쓴다 (Altium 에 열려 있어야 한다).
    사용자가 다른 보드를 보고 있어도 된다.
  - 파일 이름 일부(예: HEAD_RIGHT)를 주면 포커스된 보드의 경로에 그 글자가 들어 있을 때만 한다.
어느 쪽도 아니면 아무것도 하지 않고 'NO BOARD' 를 돌려준다. 사용자가 중간에 다른 보드로
넘어갔는데 계획을 엉뚱한 보드에 적용하는 사고를 막는 장치다 - 보드를 고치는 적용에는 꼭 준다.
한글 경로는 스크립트 원문에 넣으면 깨지므로 ANSI 파일에 적어 두고 스크립트가 읽는다.
"""
import argparse
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SNIPPETS = os.path.join(HERE, 'snippets')


def _q(path):
    """파스칼 문자열에 넣을 절대 경로."""
    return os.path.abspath(path).replace("'", "''")


def _body(name):
    with open(os.path.join(SNIPPETS, name), encoding='utf-8') as f:
        return f.read().splitlines()


def _blocks(lines):
    """//## 이름 으로 나뉜 블록들. 주석 줄은 버린다 (스크립트를 짧게)."""
    out, cur = {}, None
    for ln in lines:
        if ln.startswith('//## '):
            cur = ln[5:].strip(); out[cur] = []
        elif ln.strip().startswith('//'):
            continue
        elif cur is not None:
            out[cur].append(ln)
    return out


def board_block(board=None, workdir=None):
    """Brd1 을 정하는 문장들. board 가 있으면 그 보드가 아닐 때 Brd1 이 nil 이 된다."""
    if not board:
        return ['Brd1 := PCBServer.GetCurrentPCBBoard;']
    workdir = workdir or tempfile.gettempdir()
    # 줄 1: 경로로 찾을 때 쓸 글자 (Altium 이 아는 꼴 = 긴 이름의 절대 경로)
    # 줄 2: 경로로 못 찾았을 때 포커스된 보드의 경로에 들어 있어야 하는 글자 (파일 이름)
    if os.path.exists(board):
        full = _long(os.path.abspath(board)); frag = os.path.basename(full)
    else:
        full = frag = board
    name = os.path.join(workdir, 'altium_board_%s.txt' % hashlib.md5(full.encode('utf-8')).hexdigest()[:10])
    with open(name, 'w', encoding='mbcs' if sys.platform == 'win32' else 'utf-8') as f:
        f.write(full + '\n' + frag + '\n')
    return [f"List1.LoadFromFile('{_q(name)}');",
            'S1 := List1[0];',
            'S2 := List1[1];',
            'List1.Clear;',
            'Brd1 := PCBServer.GetPCBBoardByPath(S1);',
            'if Brd1 = nil then',
            'begin',
            '  Brd1 := PCBServer.GetCurrentPCBBoard;',
            '  if Brd1 <> nil then',
            '    if Pos(UpperCase(S2), UpperCase(Brd1.FileName)) = 0 then Brd1 := nil;',
            'end;']


def _long(path):
    """8.3 짧은 이름(ADMINI~1)을 긴 이름으로. Altium 은 긴 이름으로 문서를 안다."""
    if sys.platform != 'win32':
        return path
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetLongPathNameW(path, buf, 1024)
    return buf.value if 0 < n < 1024 else path


def dump_script(out, board=None, workdir=None):
    lines = [ln for ln in _body('dump_copper.pas') if not ln.strip().startswith('//')]
    text = '\n'.join(lines)
    return text.replace('{BOARD}', '\n'.join(board_block(board, workdir))).replace('{OUT}', _q(out))


def count_new(new):
    """new.txt 의 객체 수 (8줄에 하나)."""
    with open(new, encoding='utf-8') as f:
        return sum(1 for ln in f if ln.strip() != '') // 8


def count_keys(dele):
    with open(dele, encoding='utf-8') as f:
        return sum(1 for ln in f if ln.strip())


def apply_script(new=None, dele=None, delete_first=False, max_delete=None, board=None, workdir=None):
    """계획 적용 스크립트. new / dele 중 없는 쪽(또는 빈 파일)은 그 블록을 통째로 뺀다."""
    b = _blocks(_body('apply_plan.pas'))
    has_new = bool(new) and os.path.exists(new) and count_new(new) > 0
    has_del = bool(dele) and os.path.exists(dele) and count_keys(dele) > 0
    if not (has_new or has_del):
        raise ValueError('적용할 것이 없다 (new, del 둘 다 비었다)')
    order = (['DELETE'] if has_del else []) + (['CREATE'] if has_new else [])
    if not delete_first:
        order.reverse()
    text = '\n'.join(b['HEAD'] + [ln for k in order for ln in b[k]] + b['TAIL'])
    text = text.replace('{BOARD}', '\n'.join(board_block(board, workdir)))
    if has_new:
        text = text.replace('{NEW}', _q(new))
    if has_del:
        # 키는 객체 하나에 여러 개(반올림 후보·양방향)라 줄 수가 객체 수의 상한이다
        text = text.replace('{DEL}', _q(dele)).replace('{MAXDEL}', str(max_delete if max_delete is not None else count_keys(dele)))
    return text


def parse_result(text):
    """'created 3 / removed 2 | 보드.PcbDoc' -> dict. 형식이 다르면 raw 만."""
    out = {'raw': text}
    try:
        counts, _, name = text.partition('|')
        c, r = counts.split('/')
        out.update(created=int(c.split()[1]), removed=int(r.split()[1]), board=name.strip())
    except (ValueError, IndexError):
        pass
    return out


def main():
    ap = argparse.ArgumentParser(description='덤프·적용 스크립트 조립')
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dump'); d.add_argument('out'); d.add_argument('--board')
    a = sub.add_parser('apply')
    a.add_argument('--new'); a.add_argument('--del', dest='dele'); a.add_argument('--delete-first', action='store_true')
    a.add_argument('--max-delete', type=int); a.add_argument('--board')
    args = ap.parse_args()
    if args.cmd == 'dump':
        print(dump_script(args.out, args.board))
    else:
        print(apply_script(args.new, args.dele, args.delete_first, args.max_delete, args.board))


if __name__ == '__main__':
    main()
