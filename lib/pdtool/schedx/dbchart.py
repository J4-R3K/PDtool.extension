# -*- coding: utf-8 -*-
"""A panel schedule laid out as a PD DB chart: the layout of the chart workbooks in pd-db-chart-audit
references/rules.md (PD's standard layout, choice C6 of the plan, approved 15/10/2026). Plain Python: revitread reads the
board and its circuits from Revit, and the tests make them by hand.

Every value comes from the model. Nothing is worked out except the way number and phase of each slot and the device
names below (choice C2), and every mapping is exact: a value not in the list is written as Revit holds it. Values the
model does not hold (Ics, RCD, design length, the load summary) are written "-" or left blank (choice C5). A spare
reads SPARE with no wire type and no points, as Revit's own panel schedule shows it (rules.md R19: never half-fill a
spare).

Rows 1 to 7: the board. Row 8: the column headings. From row 9: one row per slot, so a three-phase board has three
rows per way, L1 then L2 then L3 (R21). Print area A1 to O(8 + rows) (R16), rows 1 to 8 repeated on every page (R23),
column O hidden (R15).
"""
import re

from pdtool.schedx.grid import number
from pdtool.schedx.xlsx import Style

DASH = u"-"
HEADINGS = (u"Circuit No", u"Phase", u"Circuit/Equipment", u"Wiring Type", u"Phase csa (mm\u00b2)",
            u"CPC csa (mm\u00b2)", u"Type", u"In Rating (A)", u"Ics (kA)", u"RCD (mA)", u"Circuit Type",
            u"Instal. method", u"AFDD", u"No of Points", u"Design length")
WIDTHS = (8, 7, 45, 22, 10, 10, 10, 10, 8, 8, 12, 14, 8, 9, 10)
HIDDEN = (14,)  # column O, Design length (R15)
FIRST_ROW = 8  # row 9, counted from 0

# Device names as the chart writes them (choice C2): exact matches only.
DEVICE_NAMES = {u"MCB Type B": u"MCB-B", u"MCB Type C": u"MCB-C", u"RCBO Type B": u"RCBO-B", u"RCBO Type C": u"RCBO-C"}

LABEL = Style(bold=True, valign=u"center")
VALUE = Style(valign=u"center")
HEAD = Style(bold=True, border=True, wrap=True, align=u"center", valign=u"center", fill=u"D9D9D9")
ROW = Style(border=True, wrap=True, valign=u"center")
ROW_MID = Style(border=True, wrap=True, valign=u"center", align=u"center")


def _text(value):
    """Text as the model holds it, or "-" when there is none."""
    if value is None:
        return DASH
    text = u"{}".format(value)
    return text if text.strip() else DASH


def _number(value):
    """A number from the model as a plain number, text kept as it is, "-" when there is none."""
    if value is None or value == u"":
        return DASH
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return number(value)
    return _text(value)


def way_of(slot, phases):
    return (slot - 1) // max(phases, 1) + 1


def phase_of(slot, phases):
    """L1, L2 or L3 on a three-phase board; L on a single-phase board."""
    if phases == 1:
        return u"L"
    return u"L{}".format((slot - 1) % max(phases, 1) + 1)


def cpc_slot(slots, phases):
    """The slot of a circuit that shows its CPC: on a three-pole circuit the slot on L2 (R4), else its first slot."""
    slots = sorted(slots)
    if len(slots) == 3:
        for s in slots:
            if phase_of(s, phases) == u"L2":
                return s
        return slots[1]
    return slots[0]


def ways(board):
    phases = max(board.get("phases") or 1, 1)
    slots = board.get("slots") or 0
    return -(-slots // phases)


WAYS_LABEL = re.compile(u"^\\s*(?:number|no\\.?)\\s+of\\s+ways\\s*:?\\s*(\\S*)\\s*$", re.IGNORECASE)
WHOLE = re.compile(u"^\\d+$")


def stated_ways(header):
    """The number of ways Revit's panel schedule header states ("22"), or None when it states no whole number.

    header: the panel's Header Section. The number is in the label's own cell ("Number of Ways: 22") or in the first
    cell to its right that holds text; a blank value followed by the next label ("Type:") gives None. Found on a
    project model (15/10/2026): one board states 22 ways while it has 66 slots on one phase, and Revit's own panel
    schedule lists all 66."""
    if header is None:
        return None
    for (r, c), text in sorted(header.text.items()):
        m = WAYS_LABEL.match(u"{}".format(text or u""))
        if not m:
            continue
        value = m.group(1)
        if not value:
            later = sorted((cc, u"{}".format(t).strip()) for (rr, cc), t in header.text.items()
                           if rr == r and cc > c and t and u"{}".format(t).strip())
            value = later[0][1] if later else u""
        return value if WHOLE.match(value) else None
    return None


def ways_note(board, header):
    """A note for the Contents sheet when the panel schedule states a number of ways that is not the number of ways
    the chart lists, or None. The chart keeps one row for every slot Revit has, so no circuit is left out, and the
    note asks the designer to check the board size in the model."""
    stated = stated_ways(header)
    if stated is None or int(stated) == ways(board):
        return None
    phases = max(board.get("phases") or 1, 1)
    return (u"The number of ways in the DB chart is {}, not the {} stated in Revit's panel schedule, because the "
            u"board has {} phase{} and the number of slots is {}. Check the board size in the model.".format(
                ways(board), stated, phases, u"" if phases == 1 else u"s", board.get("slots") or 0))


def header_cells(board):
    """[(row, col, value, style)] of rows 1 to 7, counted from 0."""
    phases = board.get("phases")
    rating = board.get("incoming_rating")
    out = [
        (0, 0, u"Project Name", LABEL), (0, 2, _text(board.get("project")), VALUE),
        (1, 0, u"Status:", LABEL), (1, 2, u"", VALUE),
        (2, 0, u"Date:", LABEL), (2, 2, u"", VALUE),
        (3, 0, u"DB Description:", LABEL), (3, 2, _text(board.get("description")), VALUE),
        (4, 0, u"DB Name:", LABEL), (4, 2, _text(board.get("name")), VALUE),
        (5, 0, u"DB Location:", LABEL), (5, 2, _text(board.get("location")), VALUE),
        (6, 0, u"Fed From:", LABEL), (6, 2, _text(board.get("fed_from")), VALUE),
        (0, 7, u"DB Type", LABEL), (0, 8, u"{} WAY".format(ways(board)), VALUE),
        (0, 9, u"TPN" if phases == 3 else u"SPN" if phases == 1 else _text(phases), VALUE),
        (2, 7, u"Device Type", LABEL), (2, 9, _text(board.get("incoming_type")), VALUE),
        (3, 7, u"Current Rating (A)", LABEL), (3, 9, _number(rating), VALUE),
        (4, 7, u"Ics (kA)", LABEL), (4, 9, DASH, VALUE),
        (5, 7, u"No of Poles", LABEL), (5, 9, DASH, VALUE),
    ]
    return out


def slot_rows(board, slots):
    """The rows from row 9 down, one per slot in slot order: a list of 15 values each (columns A to O).

    slots: [{"slot": n, "circuit": dict or None, "space": bool}] for slots 1 to board["slots"]. A circuit dict holds
    "id", "load_name", "spare", "wire_type", "size_line", "size_cpc", "device_type", "device_rating", "circuit_type",
    "install", "afdd", "points" as the model holds them (numbers as numbers in square millimetres and amps, or text where the model
    gives text). A slot missing from the list reads as an empty slot."""
    phases = max(board.get("phases") or 1, 1)
    by_slot = dict((s["slot"], s) for s in slots)
    held = {}
    for s in slots:
        c = s.get("circuit")
        if c is not None:
            held.setdefault(c.get("id"), []).append(s["slot"])
    out = []
    for n in range(1, (board.get("slots") or 0) + 1):
        s = by_slot.get(n) or {}
        c = s.get("circuit")
        way, phase = way_of(n, phases), phase_of(n, phases)
        if c is None:
            out.append([number(way), phase, u"SPACE" if s.get("space") else DASH] + [DASH] * 12)
            continue
        spare = bool(c.get("spare"))
        device = c.get("device_type")
        points = c.get("points")
        out.append([
            number(way), phase,
            u"SPARE" if spare else _text(c.get("load_name")),
            # Revit keeps a wire type on a spare but shows none in its own panel schedule; a spare has no cable
            DASH if spare else _text(c.get("wire_type")),
            _number(c.get("size_line")),
            _number(c.get("size_cpc")) if n == cpc_slot(held[c.get("id")], phases) else DASH,
            _text(DEVICE_NAMES.get(device, device)),
            _number(c.get("device_rating")),
            DASH, DASH,
            _text(c.get("circuit_type")),
            _text(c.get("install")),
            _text(c.get("afdd")),
            DASH if spare else (number(points) if points else u"TBC"),
            DASH,
        ])
    return out


def chart_sheet(sheet, board, slots):
    """Lay the DB chart out on sheet. Returns the rows written from row 9."""
    for r, c, value, style in header_cells(board):
        sheet.set(r, c, value, style)
    for c, heading in enumerate(HEADINGS):
        sheet.set(FIRST_ROW - 1, c, heading, HEAD)
    rows = slot_rows(board, slots)
    for i, values in enumerate(rows):
        for c, value in enumerate(values):
            sheet.set(FIRST_ROW + i, c, value, ROW if c in (2, 3) else ROW_MID)
    for c, w in enumerate(WIDTHS):
        sheet.widths[c] = w
    sheet.hidden_cols.update(HIDDEN)
    sheet.freeze_rows = FIRST_ROW
    sheet.print_titles = (0, FIRST_ROW - 1)
    sheet.print_area = (0, 0, FIRST_ROW - 1 + len(rows), len(HEADINGS) - 1)
    sheet.landscape = True
    sheet.fit_width = True
    return rows
