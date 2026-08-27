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

The leftmost column names the layer each row belongs to. It is not optional in
practice: without it the rows carry impedance figures that nobody can tie to a
layer, which is exactly how the first generated version came out and why it
had to be redrawn by hand.

Geometry is measured off the table on Safety Carrier Board_A0.

Recipe format
-------------
{
  "origin_mm": [334.5142, 241.4419],    # lower-left corner of the grid
  "units_note": "mm",                   # printed above the top-right corner
  "label_column": {"width_mm": 22.0, "caption": "Layer"},
  "groups": [                           # left to right
    {"kind": "Zs",    "ohm": "50"},     # -> columns W | Ohm
    {"kind": "ZDiff", "ohm": "100"}     # -> columns W | d | Ohm
  ],
  "rows": [                             # TOP row first, one per signal layer
    {"label": "Top Layer",    "cells": [["0.113", "50"], ["0.13", "0.185", "100"]]},
    {"label": "Bottom Layer", "cells": [["0.113", "50"], ["0.13", "0.185", "100"]]}
  ]
}

Give one row per signal layer and no more: a 4-layer board gets four rows,
with no spacer bands between them and none padding the bottom. A group with
"ohm": "" still draws its columns but carries no values - that is how the
spare groups on the reference table are left.
"""
import json
import sys

# Altium internal units are 1/10000 mil.
PER_MM = 393700.7874

LAYER = "Drill Drawing"

LINE_W_MM = 0.2032      # 8 mil, the grid lines
TEXT_H_MM = 2.1         # glyph height
TEXT_W_MM = 0.4         # stroke width

# Altium's stroke font is proportional. These advances, as a fraction of the
# glyph height, are fitted to strings measured off the board; they leave
# centring within about 0.4 mm in an 11 mm column, which reads as centred.
ADVANCE = 0.80          # digits, and anything not listed below
ADVANCE_BY_CHAR = dict(
    [(".", 0.40), (",", 0.40), ("-", 0.55), (" ", 0.45)]
    + [(c, 0.45) for c in "iljft"]
    + [(c, 0.95) for c in "mw"]
    + [(c, 0.65) for c in "abcdeghknopqrsuvxyz"]
    + [(c, 0.95) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
)

# Column widths within a group. Both kinds come to a round total - 22 mm and
# 33 mm - so group boundaries land on the same grid either way; the uneven
# split of a ZDiff group buys width for the W column, whose values run longest.
COLS_MM = {"Zs": [11.0, 11.0], "ZDiff": [11.5, 11.0, 10.5]}

ROW_MM = 5.0            # every row, headings included
NOTE_GAP_MM = 1.66      # units note above the top edge


def u(mm):
    return int(round(mm * PER_MM))


def text_width(s):
    return sum(ADVANCE_BY_CHAR.get(c, ADVANCE) for c in s) * TEXT_H_MM


def columns(recipe):
    """Every column width left to right, each group's range, and the label
    column's index if the recipe asks for one."""
    widths, spans = [], []
    label = recipe.get("label_column")
    if label:
        widths.append(label["width_mm"])
    for g in recipe["groups"]:
        start = len(widths)
        widths.extend(COLS_MM[g["kind"]])
        spans.append((start, len(widths)))
    return widths, spans, (0 if label else None)


def build(recipe):
    ox, oy = recipe["origin_mm"]
    groups = recipe["groups"]
    rows = recipe["rows"]
    label_col = recipe.get("label_column")

    widths, spans, label_idx = columns(recipe)
    xs = [ox]
    for w in widths:
        xs.append(xs[-1] + w)

    # Two heading bands, then one band per row. Rows are given top-first.
    nbands = 2 + len(rows)
    ys = [oy + (nbands - i) * ROW_MM for i in range(nbands + 1)]

    out = []
    add = out.append
    add("SandboxLog('impedance table: start');")
    add("Obj1 := PCBServer.GetCurrentPCBBoard;")
    add("PCBServer.PreProcess;")
    # Hoist the constants: one object per emitted line keeps the script small
    # enough to hand to run_altium_script without it dominating the request.
    add("I1 := String2Layer('%s');" % LAYER)
    add("I2 := %d; I3 := %d; B1 := %d;" % (u(LINE_W_MM), u(TEXT_H_MM), u(TEXT_W_MM)))

    def track(x1, y1, x2, y2):
        add("Obj2 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default); "
            "Obj2.X1 := %d; Obj2.Y1 := %d; Obj2.X2 := %d; Obj2.Y2 := %d; "
            "Obj2.Width := I2; Obj2.Layer := I1; Obj1.AddPCBObject(Obj2);"
            % (u(x1), u(y1), u(x2), u(y2)))

    def label(s, x, y):
        if s == "":
            return
        add("Obj3 := PCBServer.PCBObjectFactory(eTextObject, eNoDimension, eCreate_Default); "
            "Obj3.XLocation := %d; Obj3.YLocation := %d; Obj3.Text := '%s'; "
            "Obj3.Size := I3; Obj3.Width := B1; Obj3.Layer := I1; Obj1.AddPCBObject(Obj3);"
            % (u(x), u(y), s.replace("'", "''")))

    def centred(s, col_lo, col_hi, band):
        """Centre s across columns [col_lo, col_hi) in band index `band`."""
        x = xs[col_lo] + ((xs[col_hi] - xs[col_lo]) - text_width(s)) / 2.0
        y = ys[band + 1] + (ROW_MM - TEXT_H_MM) / 2.0
        label(s, x, y)

    # Grid. Horizontals span the full width.
    for y in ys:
        track(xs[0], y, xs[-1], y)
    # Verticals: the outer edges and the group boundaries run the full height;
    # the separators inside a group stop below the Zs/ZDiff heading band. The
    # label column has no separator of its own - it is one cell wide.
    boundaries = {0, len(widths)} | {lo for lo, _ in spans} | {hi for _, hi in spans}
    for i, x in enumerate(xs):
        track(x, ys[0], x, ys[-1] if i in boundaries else ys[1])

    # Heading band 1: one string per group. The label column stays empty.
    for g, (lo, hi) in zip(groups, spans):
        centred(g["kind"], lo, hi, 0)

    # Heading band 2: the column captions, and the label column's own.
    if label_col:
        centred(label_col.get("caption", "Layer"), label_idx, label_idx + 1, 1)
    for g, (lo, _) in zip(groups, spans):
        caps = ["W", "d", "Ohm"] if g["kind"] == "ZDiff" else ["W", "Ohm"]
        for n, cap in enumerate(caps):
            centred(cap, lo + n, lo + n + 1, 1)

    # Data bands: the layer name, then the figures.
    for r, row in enumerate(rows):
        if label_col:
            centred(row.get("label", ""), label_idx, label_idx + 1, 2 + r)
        for (lo, _), cells in zip(spans, row.get("cells", []) or []):
            for n, cell in enumerate(cells):
                centred(str(cell), lo + n, lo + n + 1, 2 + r)

    # Units note, right-aligned just above the top edge.
    note = "-Units: %s" % recipe.get("units_note", "mm")
    label(note, xs[-1] - text_width(note), ys[0] + NOTE_GAP_MM)

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
