# -*- coding: utf-8 -*-
"""Generate the in-PcbDoc impedance table that fabricators read off the drawing.

Altium has no native impedance table that lives inside a .PcbDoc: the PCB
editor's Layer Stack Table carries layers/materials/thickness/Er but no
impedance, and Draftsman's Transmission Line Table is a separate document.
So the table is drawn by hand - grid lines as tracks, values as strings, all
on Drill Drawing. This builds that same table from a recipe instead.

    python impedance_table.py recipe.json > table.pas

The output is a DelphiScript body for the run_altium_script MCP tool. It only
ADDS objects; clear an old table by selecting and deleting it first.

Geometry below was measured off the table on Safety Carrier Board_A0 so a
generated table sits beside a hand-drawn one without looking different. Text
placement is the one deliberate departure: the hand-placed strings sit at
offsets between 0.98 and 2.77 mm inside their cells, and this centres them.

Recipe format
-------------
{
  "origin_mm": [334.799, 241.322],      # lower-left corner of the grid
  "units_note": "mm",                   # printed above the top-right corner
  "groups": [                           # left to right
    {"kind": "Zs",    "ohm": "50"},     # -> columns W | Ohm
    {"kind": "ZDiff", "ohm": "100"}     # -> columns W | d | Ohm
  ],
  "rows": [                             # TOP row first
    {"cells": [["0.113", "50"], ["0.13", "0.185", "100"]]},
    {"cells": []},                      # blank band (dielectric)
    {"cells": [["0.128", "50"], ["0.102", "0.203", "100"]]}
  ]
}

A group with "ohm": "" still draws its columns but prints no heading value -
that is how the spare columns on the reference table were left.
"""
import json
import sys

# Altium internal units are 1/10000 mil.
PER_MM = 393700.7874

LAYER = "Drill Drawing"

LINE_W_MM = 0.2032      # 8 mil, the grid lines
TEXT_H_MM = 2.1         # glyph height
TEXT_W_MM = 0.4         # stroke width
ADVANCE = 0.6           # stroke-font advance per char, as a fraction of height

COL_VALUE_MM = 12.7     # W and d columns
COL_UNIT_MM = 8.89      # the Ohm column
ROW_HEAD1_MM = 5.715    # Zs / ZDiff band
ROW_HEAD2_MM = 4.445    # W / d / Ohm band
ROW_DATA_MM = 5.08
ROW_FOOT_MM = 8.06      # taller empty band along the bottom

SUB_DROP_MM = 0.127     # how far the s/Diff subscript sits below the Z


def u(mm):
    return int(round(mm * PER_MM))


def text_width(s):
    return len(s) * TEXT_H_MM * ADVANCE


def columns(groups):
    """Widths of every column, left to right, plus each group's column span."""
    widths, spans = [], []
    for g in groups:
        start = len(widths)
        widths.append(COL_VALUE_MM)                    # W
        if g["kind"] == "ZDiff":
            widths.append(COL_VALUE_MM)                # d
        widths.append(COL_UNIT_MM)                     # Ohm
        spans.append((start, len(widths)))
    return widths, spans


def build(recipe):
    ox, oy = recipe["origin_mm"]
    groups = recipe["groups"]
    rows = recipe["rows"]

    widths, spans = columns(groups)
    xs = [ox]
    for w in widths:
        xs.append(xs[-1] + w)

    # Rows are given top-first; lay them out downward from the top edge.
    heights = [ROW_HEAD1_MM, ROW_HEAD2_MM] + [ROW_DATA_MM] * len(rows) + [ROW_FOOT_MM]
    total_h = sum(heights)
    ys = [oy + total_h]
    for h in heights:
        ys.append(ys[-1] - h)

    out = []
    add = out.append
    add("SandboxLog('impedance table: start');")
    add("Obj1 := PCBServer.GetCurrentPCBBoard;")
    add("PCBServer.PreProcess;")

    def track(x1, y1, x2, y2):
        add("Obj2 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);")
        add("Obj2.X1 := %d; Obj2.Y1 := %d; Obj2.X2 := %d; Obj2.Y2 := %d;"
            % (u(x1), u(y1), u(x2), u(y2)))
        add("Obj2.Width := %d; Obj2.Layer := String2Layer('%s');" % (u(LINE_W_MM), LAYER))
        add("Obj1.AddPCBObject(Obj2);")

    def label(s, x, y):
        if s == "":
            return
        add("Obj3 := PCBServer.PCBObjectFactory(eTextObject, eNoDimension, eCreate_Default);")
        add("Obj3.XLocation := %d; Obj3.YLocation := %d;" % (u(x), u(y)))
        add("Obj3.Text := '%s';" % s.replace("'", "''"))
        add("Obj3.Size := %d; Obj3.Width := %d;" % (u(TEXT_H_MM), u(TEXT_W_MM)))
        add("Obj3.Layer := String2Layer('%s');" % LAYER)
        add("Obj1.AddPCBObject(Obj3);")

    def centred(s, col_lo, col_hi, row_top, row_bot):
        """Place s centred across columns [col_lo, col_hi) in one row band."""
        x = xs[col_lo] + ((xs[col_hi] - xs[col_lo]) - text_width(s)) / 2.0
        y = row_bot + ((row_top - row_bot) - TEXT_H_MM) / 2.0
        label(s, x, y)
        return x, y

    # Grid: every horizontal line spans the full width.
    for y in ys:
        track(xs[0], y, xs[-1], y)
    # Verticals stop at the foot band, except the two outer edges and the
    # group boundaries, which run the whole height - as on the reference table.
    foot_top = ys[-2]
    boundaries = {0, len(widths)} | {s for s, _ in spans} | {e for _, e in spans}
    for i, x in enumerate(xs):
        track(x, ys[0], x, ys[0] - total_h if i in boundaries else foot_top)

    # Heading line 1: Z with a subscript, centred over each group.
    for g, (lo, hi) in zip(groups, spans):
        sub = "s" if g["kind"] == "Zs" else "Diff"
        whole = "Z" + sub
        x = xs[lo] + ((xs[hi] - xs[lo]) - text_width(whole)) / 2.0
        y = ys[1] + ((ys[0] - ys[1]) - TEXT_H_MM) / 2.0
        label("Z", x, y)
        label(sub, x + text_width("Z") + 0.15, y - SUB_DROP_MM)

    # Heading line 2: the column captions.
    for g, (lo, hi) in zip(groups, spans):
        caps = ["W", "d", "Ohm"] if g["kind"] == "ZDiff" else ["W", "Ohm"]
        for n, cap in enumerate(caps):
            centred(cap, lo + n, lo + n + 1, ys[1], ys[2])

    # Data rows.
    for r, row in enumerate(rows):
        top, bot = ys[2 + r], ys[3 + r]
        for g, (lo, _), cells in zip(groups, spans, row.get("cells", []) or []):
            for n, cell in enumerate(cells):
                centred(str(cell), lo + n, lo + n + 1, top, bot)

    # The units note sits just above the top-right corner.
    note = "-Units: %s" % recipe.get("units_note", "mm")
    label(note, xs[-1] - text_width(note), ys[0] + 1.4)

    add("PCBServer.PostProcess;")
    add("Obj1.ViewManager_FullUpdate;")
    add("ResultText := 'impedance table placed';")
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    with open(sys.argv[1], encoding="utf-8") as fh:
        recipe = json.load(fh)
    print(build(recipe))
    return 0


if __name__ == "__main__":
    sys.exit(main())
