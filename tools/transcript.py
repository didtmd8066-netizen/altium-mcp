# -*- coding: utf-8 -*-
"""지난 세션의 대화를 찾아본다.

    python transcript.py list
    python transcript.py user   [--session <id 일부>] [--last N]
    python transcript.py grep   <정규식> [--session <id 일부>] [--role user|assistant]

Claude Code 는 세션마다 `~/.claude/projects/<프로젝트>/<uuid>.jsonl` 을 남긴다.
새 세션은 이걸 자동으로 읽지 않으므로, 지난 대화를 참조하려면 직접 뒤져야 한다.
진행 중인 세션 파일은 100 MB 를 넘기도 해서 통째로 읽을 수 없다 - 여기서는 한
줄씩 흘려 읽는다.

세션 간 인계의 정식 경로는 메모리(`memory/`)다. 이 도구는 메모리에 안 남긴 것을
뒤늦게 찾아야 할 때 쓴다. 실제로 반복 지적을 추리려고 사용자 메시지 559 건을
훑은 적이 있고, 거기서 나온 규칙이 CLAUDE.md 로 들어갔다.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

ROOT = os.path.join(os.path.expanduser('~'), '.claude', 'projects')


def project_dir(name=None):
    if name:
        hits = glob.glob(os.path.join(ROOT, '*%s*' % name))
        if hits:
            return hits[0]
    cwd = os.path.basename(os.getcwd())
    hits = glob.glob(os.path.join(ROOT, '*%s*' % cwd)) or glob.glob(os.path.join(ROOT, '*'))
    return hits[0] if hits else None


def sessions(folder, match=None):
    out = sorted(glob.glob(os.path.join(folder, '*.jsonl')),
                 key=os.path.getmtime, reverse=True)
    return [p for p in out if not match or match in os.path.basename(p)]


def text_of(entry):
    """대화 한 줄에서 사람이 읽을 텍스트만. tool_result·시스템 알림은 버린다."""
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, str):
        body = content
    elif isinstance(content, list):
        body = ' '.join(b.get('text', '') for b in content
                        if isinstance(b, dict) and b.get('type') == 'text')
    else:
        return ''
    body = body.strip()
    if not body or body.startswith('<') or body.startswith('Caveat:'):
        return ''
    # 컨텍스트가 넘칠 때 삽입되는 요약은 사용자가 쓴 말이 아니다
    if body.startswith('This session is being continued from a previous conversation'):
        return ''
    return body


def walk(path, role=None):
    """(순번, 역할, 텍스트) 를 흘려 준다."""
    n = 0
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            kind = entry.get('type')
            if kind not in ('user', 'assistant'):
                continue
            if role and kind != role:
                continue
            body = text_of(entry)
            if not body:
                continue
            n += 1
            yield n, kind, body


def cmd_list(folder):
    print(os.path.basename(folder))
    print('  %-38s %10s  %-16s %s' % ('세션', '크기', '최종 수정', '대화'))
    for path in sessions(folder):
        counts = {'user': 0, 'assistant': 0}
        for _, kind, _ in walk(path):
            counts[kind] += 1
        print('  %-38s %9.1fMB  %-16s 사용자 %d / 응답 %d'
              % (os.path.basename(path)[:37],
                 os.path.getsize(path) / 1048576,
                 time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path))),
                 counts['user'], counts['assistant']))


def cmd_user(folder, match, last):
    for path in sessions(folder, match):
        rows = [(n, b) for n, kind, b in walk(path, 'user')]
        if not rows:
            continue
        print('### %s — 사용자 메시지 %d건' % (os.path.basename(path)[:36], len(rows)))
        for n, body in (rows[-last:] if last else rows):
            print('%5d. %s' % (n, ' '.join(body.split())[:160]))
        print()


def cmd_grep(folder, pattern, match, role):
    rx = re.compile(pattern, re.I)
    total = 0
    for path in sessions(folder, match):
        hits = [(n, kind, b) for n, kind, b in walk(path, role) if rx.search(b)]
        if not hits:
            continue
        print('### %s — %d건' % (os.path.basename(path)[:36], len(hits)))
        for n, kind, body in hits:
            tag = '사용자' if kind == 'user' else '응답  '
            print('%5d %s %s' % (n, tag, ' '.join(body.split())[:170]))
        print()
        total += len(hits)
    print('총 %d건' % total)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('command', choices=['list', 'user', 'grep'])
    ap.add_argument('pattern', nargs='?')
    ap.add_argument('--project')
    ap.add_argument('--session')
    ap.add_argument('--role', choices=['user', 'assistant'])
    ap.add_argument('--last', type=int)
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    a = ap.parse_args()

    folder = project_dir(a.project)
    if not folder:
        print('트랜스크립트 폴더를 찾지 못했다: %s' % ROOT)
        return 1

    if a.command == 'list':
        cmd_list(folder)
    elif a.command == 'user':
        cmd_user(folder, a.session, a.last)
    else:
        if not a.pattern:
            print('검색할 정규식을 지정할 것')
            return 1
        cmd_grep(folder, a.pattern, a.session, a.role)
    return 0


if __name__ == '__main__':
    sys.exit(main())
