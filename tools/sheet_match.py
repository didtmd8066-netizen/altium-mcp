# -*- coding: utf-8 -*-
"""Pair up components between two schematic sheets drawn from the same circuit.

Emits the source/destination lists that layout_duplicator_apply takes, so a
repeated block can be replicated in ONE bridge call instead of one per channel.

    python sheet_match.py <source.SchDoc> <dest.SchDoc> [--skip TP,J]

Matching runs in stages and labels each pair with the stage that produced it,
because the later stages are weaker evidence:

  exact  - identical schematic coordinates. Trustworthy.
  near   - same LibReference, nearest neighbour, and the runner-up is at least
           `gap` units further away. Worth a glance before committing.
  amb    - everything else. Resolve these by netlist (which pin of which
           transistor each part hangs off), never by designator arithmetic:
           sheet numbering offsets are not constant, and identical passives
           cannot be told apart by value.

Gotcha that costs an afternoon if missed: in a .SchDoc, OwnerIndex refers to a
record's ORDINAL POSITION in the file, not its IndexInSheet. Resolve designator
records to their owning component through that ordinal, and read the position
off the component body - a designator label carries its own offset and does not
sit where the part does.
"""
import re
import sys
import json
import os
import collections


def load(path):
    """Return {designator: (x, y, libref)} using component body positions."""
    text = open(path, 'rb').read().decode('latin-1')
    records = [m.group(0) for m in re.finditer(r'\|RECORD=\d+\|[^\x00]*', text)]

    bodies = {}
    for ordinal, rec in enumerate(records):
        if not rec.startswith('|RECORD=1|'):
            continue
        x = re.search(r'\|Location\.X=(-?\d+)', rec)
        y = re.search(r'\|Location\.Y=(-?\d+)', rec)
        lib = re.search(r'\|LibReference=([^|]*)', rec)
        if x and y:
            bodies[ordinal] = (int(x.group(1)), int(y.group(1)),
                               lib.group(1) if lib else '')

    found = {}
    for rec in records:
        if not rec.startswith('|RECORD=34|') or '|Name=Designator|' not in rec:
            continue
        text_field = re.search(r'\|Text=([^|]*)', rec)
        owner = re.search(r'\|OwnerIndex=(-?\d+)', rec)
        if text_field and owner and int(owner.group(1)) in bodies:
            found[text_field.group(1).strip()] = bodies[int(owner.group(1))]
    return found


def prefix(designator):
    return re.match(r'([A-Za-z]+)', designator).group(1)


def sort_key(designator):
    digits = re.sub(r'\D', '', designator)
    return (prefix(designator), int(digits) if digits else 0)


def match(source, dest, gap=40.0):
    by_position = collections.defaultdict(list)
    for designator, (x, y, _lib) in dest.items():
        by_position[(x, y)].append(designator)

    taken = set()
    exact, near, ambiguous = [], [], []

    for designator in sorted(source, key=sort_key):
        x, y, lib = source[designator]

        same_spot = [d for d in by_position.get((x, y), [])
                     if d not in taken and prefix(d) == prefix(designator)]
        if len(same_spot) == 1:
            exact.append((designator, same_spot[0]))
            taken.add(same_spot[0])
            continue

        candidates = sorted(
            (((dest[d][0] - x) ** 2 + (dest[d][1] - y) ** 2) ** 0.5, d)
            for d in dest
            if d not in taken and prefix(d) == prefix(designator)
            and dest[d][2] == lib)

        if not candidates:
            ambiguous.append((designator, 'no candidate of the same part type'))
            continue

        best_distance, best = candidates[0]
        runner_up = candidates[1][0] if len(candidates) > 1 else float('inf')
        if runner_up - best_distance >= gap:
            near.append((designator, best, round(best_distance, 1)))
            taken.add(best)
        else:
            ambiguous.append((designator, '1st=%s(%.0f) 2nd=%s(%.0f)' % (
                best, best_distance, candidates[1][1], runner_up)))

    return exact, near, ambiguous


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    source_path, dest_path = sys.argv[1], sys.argv[2]
    skip = set()
    if '--skip' in sys.argv:
        skip = {p.strip() for p in sys.argv[sys.argv.index('--skip') + 1].split(',')}

    source = {d: v for d, v in load(source_path).items() if prefix(d) not in skip}
    dest = {d: v for d, v in load(dest_path).items() if prefix(d) not in skip}
    exact, near, ambiguous = match(source, dest)
    pairs = [(d, e) for d, e in exact] + [(d, e) for d, e, _ in near]

    out = sys.stdout.write
    out('source : %s  (%d)\n' % (os.path.basename(source_path), len(source)))
    out('dest   : %s  (%d)\n\n' % (os.path.basename(dest_path), len(dest)))
    out('exact %d  |  near %d  |  ambiguous %d\n' % (len(exact), len(near), len(ambiguous)))

    if near:
        out('\n[near - same part type, nearest match, runner-up well behind]\n')
        for designator, partner, distance in near:
            out('  %-6s -> %-6s  distance %s\n' % (designator, partner, distance))
    if ambiguous:
        out('\n[ambiguous - resolve by netlist, not by numbering]\n')
        for designator, reason in ambiguous:
            out('  %-6s  %s\n' % (designator, reason))

    out('\n=== layout_duplicator_apply arguments ===\n')
    out('source_designators=%s\n\n' % json.dumps([d for d, _ in pairs]))
    out('destination_designators=%s\n' % json.dumps([e for _, e in pairs]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
