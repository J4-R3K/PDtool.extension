# -*- coding: utf-8 -*-
"""A schedule or a panel schedule laid out on a sheet as it reads in Revit. Plain Python: revitread reads the cells
from Revit into Section objects, and the tests make Sections by hand.

What Revit gives (read-only probe of a project model, Revit 2024, 15/10/2026):
- A schedule has a header section (the title) and a body (headings, then the rows). The body leaves out fields that
  are hidden in the schedule, as Revit's own view does. The header section may be split into more columns than the
  body (23 against 13 on PD_Spaces - Engineering Dashboard), with the title merged across all of them, so the body's
  columns are the sheet's columns and the header is placed on them by position.
- A panel schedule has a header, a body, a summary and a footer, each with its own columns and widths. "As in Revit"
  places all of them on one set of columns made from every section's column edges, so each cell sits where it does
  in Revit.
- Group headings: the first body row holds them, merged across the columns of the group; a field outside any group
  is merged down over both heading rows.
"""
import math
import re

from pdtool.schedx.xlsx import Num, Style

MM_PER_FOOT = 304.8
# Excel measures a column in characters of its standard font (Calibri 11, about 1.9 mm wide on screen). Revit's
# schedule text is smaller (2.5 mm text on the sheet), so a Revit column holds more characters than the same width
# in Excel. 1.4 mm of Revit width for each Excel character keeps the text of a full Revit cell on one line.
MM_PER_CHAR = 1.4
MIN_CHARS, MAX_CHARS = 2.0, 100.0
DEFAULT_WIDTH = 25.4 / MM_PER_FOOT  # feet, used where Revit gives no width
SNAP = 0.6 / MM_PER_FOOT  # column edges closer than 0.6 mm are taken as the same edge
LINE_HEIGHT = 15.0  # points, one line of Calibri 11

TITLE = Style(bold=True, border=True, wrap=True, align=u"center")
HEAD = Style(bold=True, border=True, wrap=True, align=u"center")
BODY = Style(border=True, wrap=True)

_PLAIN = re.compile(u"^-?(0|[1-9][0-9]*)(\\.[0-9]*[1-9])?$")


def plain_number(text):
    """A Num when text is a plain number written as Excel would show it, else None.

    Plain: digits with an optional "-" and decimal part; no unit, no leading zero ("007"), no thousands comma, no
    trailing zero in the decimals ("1.50" shows as 1.5 in Excel), no exponent, "-0" excluded, at most 15 digits
    (Excel keeps 15). Everything else stays text, so the cell reads exactly as Revit shows it."""
    if not text:
        return None
    t = u"{}".format(text)
    if not _PLAIN.match(t) or t == u"-0":
        return None
    if len(t.replace(u"-", u"").replace(u".", u"")) > 15:
        return None
    return Num(t)


def number(value, places=4):
    """A Num for a number from the model, rounded to places and written plainly: 1.5, 10, 0.75."""
    text = u"{0:.{1}f}".format(round(float(value), places), places)
    if u"." in text:
        text = text.rstrip(u"0").rstrip(u".")
    if text in (u"-0", u"", u"-"):
        text = u"0"
    return Num(text)


def chars(width_feet):
    """An Excel column width in characters for a Revit column width in feet."""
    if not width_feet or width_feet <= 0:
        width_feet = DEFAULT_WIDTH
    return max(MIN_CHARS, min(MAX_CHARS, round(width_feet * MM_PER_FOOT / MM_PER_CHAR, 1)))


class Section(object):
    """One section of a Revit table as it was read.

    name        "Header", "Body", "Summary" or "Footer"
    rows, cols  the row and column numbers Revit could read, in order
    text        {(row, col): text}; a cell inside a merged area other than its top left reads ""
    merges      [(top, left, bottom, right)] of each merged area larger than one cell
    widths      {col: width in feet}
    bold_rows   rows shown in bold (headings)
    number_rows rows whose plain numbers become Excel numbers
    title       True for a schedule's title rows (bold and centred)
    """

    def __init__(self, name, rows, cols, text, merges=(), widths=None, bold_rows=(), number_rows=()):
        self.name = name
        self.rows = list(rows)
        self.cols = list(cols)
        self.text = dict(text)
        self.widths = dict(widths or {})
        self.bold_rows = set(bold_rows)
        self.number_rows = set(number_rows)
        self.title = False
        self.merges = []
        rows_set, cols_set = set(self.rows), set(self.cols)
        for top, left, bottom, right in merges:
            # keep the part of each merged area that Revit could read
            rs = [r for r in self.rows if top <= r <= bottom]
            cs = [c for c in self.cols if left <= c <= right]
            if rs and cs and (len(rs) > 1 or len(cs) > 1) and rs[0] in rows_set and cs[0] in cols_set:
                self.merges.append((rs[0], cs[0], rs[-1], cs[-1]))

    def edges(self):
        """The x position of each column edge in feet, from 0 at the left: one more than the columns."""
        out = [0.0]
        for c in self.cols:
            w = self.widths.get(c)
            out.append(out[-1] + (w if w and w > 0 else DEFAULT_WIDTH))
        return out

    def areas(self):
        """[(top, left, bottom, right)] for every cell to place: the merged areas, and each cell outside them."""
        covered = set()
        out = []
        for m in self.merges:
            top, left, bottom, right = m
            for r in self.rows:
                if top <= r <= bottom:
                    for c in self.cols:
                        if left <= c <= right:
                            covered.add((r, c))
        anchors = dict(((m[0], m[1]), m) for m in self.merges)
        for r in self.rows:
            for c in self.cols:
                if (r, c) in anchors:
                    out.append(anchors[(r, c)])
                elif (r, c) not in covered:
                    out.append((r, c, r, c))
        return out


def heading_rows(body, headings, show_headers=True):
    """How many rows at the top of the body are headings.

    headings: the heading of each column of the body, in order (the visible fields' headings). The row that holds a
    column's own heading ends the headings for that column; group headings sit above it. Without a match (a heading
    changed since), 1 row is taken when Revit shows headings."""
    if not show_headers or not body.rows:
        return 0
    cover = {}
    for m in body.merges:
        for r in body.rows:
            if m[0] <= r <= m[2]:
                for c in body.cols:
                    if m[1] <= c <= m[3]:
                        cover[(r, c)] = m
    found = 0
    for i, c in enumerate(body.cols[:len(headings)]):
        want = (headings[i] or u"").strip()
        for r in body.rows[:6]:
            top, left, bottom, right = cover.get((r, c), (r, c, r, c))
            if left == right == c and (body.text.get((top, c)) or u"").strip() == want and want:
                found = max(found, body.rows.index(bottom) + 1 if bottom in body.rows else 1)
                break
    return found or 1


def union_edges(sections):
    """One set of column edges holding every section's edges, with edges closer than SNAP taken as one."""
    xs = sorted(x for s in sections for x in s.edges())
    out = []
    for x in xs:
        if not out or x - out[-1] > SNAP:
            out.append(x)
    if len(out) < 2:
        out = [0.0, DEFAULT_WIDTH]
    return out


def _nearest(edges, x):
    best, gap = 0, None
    for i, e in enumerate(edges):
        if gap is None or abs(e - x) < gap:
            best, gap = i, abs(e - x)
    return best


def _span(edges, x0, x1):
    """The first and last sheet columns between x0 and x1, by the nearest edges."""
    n = len(edges) - 1
    first = min(_nearest(edges, x0), n - 1)
    last = max(_nearest(edges, x1) - 1, first)
    return first, min(last, n - 1)


def _lines(text, width_chars):
    """Lines a text takes in a column of width_chars characters, wrapped, roughly."""
    total = 0
    for line in (text or u"").split(u"\n"):
        total += max(1, int(math.ceil(len(line) * 1.1 / max(width_chars, 1.0))))
    return total


def place(sheet, sections, edges, first_row=0, by_index=None):
    """Place the sections one under the other on sheet, from first_row, on the columns given by edges (feet).

    by_index: a section placed column by column (the schedule body, whose columns are the sheet's) instead of by
    position. Returns (next free row, notes). A cell whose area would overlap one already placed (columns that do not
    line up) keeps its text in the first free cell of its area, so no text is lost and Excel opens the file with no
    repair."""
    notes = []
    owner = {}  # sheet cell -> top left sheet cell of the area that holds it
    widths = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
    row = first_row
    for sec in sections:
        rmap = dict((r, row + i) for i, r in enumerate(sec.rows))
        cidx = dict((c, i) for i, c in enumerate(sec.cols))
        sec_edges = sec.edges()
        clashes = 0
        for top, left, bottom, right in sec.areas():
            if sec is by_index:
                g0, g1 = cidx[left], cidx[right]
            else:
                g0, g1 = _span(edges, sec_edges[cidx[left]], sec_edges[cidx[right] + 1])
            r0, r1 = rmap[top], rmap[bottom]
            value = sec.text.get((top, left)) or u""
            if top in sec.number_rows:
                value = plain_number(value) or value
            style = TITLE if sec.title else HEAD if top in sec.bold_rows else BODY
            cells = [(r, c) for r in range(r0, r1 + 1) for c in range(g0, g1 + 1)]
            if any(x in owner for x in cells):
                clashes += 1
                free = [x for x in cells if x not in owner]
                if free:
                    sheet.set(free[0][0], free[0][1], value, style)
                    owner[free[0]] = free[0]
                elif value != u"":
                    at = owner[(r0, g0)]
                    old = sheet.get(*at)
                    joined = u"{} {}".format(old.text if isinstance(old, Num) else (old or u""), value).strip()
                    sheet.set(at[0], at[1], joined, sheet.cells[at][1])
                continue
            for x in cells:
                sheet.set(x[0], x[1], u"", style)
                owner[x] = (r0, g0)
            sheet.set(r0, g0, value, style)
            if len(cells) > 1:
                sheet.merge(r0, g0, r1, g1)
                # Excel does not fit a row to the text of a merged cell, so a one-row merged cell gets its height here
                if r0 == r1 and isinstance(value, type(u"")) and value:
                    width = sum(chars(widths[c]) for c in range(g0, g1 + 1))
                    lines = _lines(value, width)
                    if lines > 1:
                        sheet.heights[r0] = max(sheet.heights.get(r0, 0), LINE_HEIGHT * lines)
        if clashes:
            notes.append(u"{}: the text of cells that do not line up with the columns above and below is put in "
                         u"the nearest cell. The number of cells affected is {}.".format(sec.name, clashes))
        row += len(sec.rows)
    for i, w in enumerate(widths):
        sheet.widths[i] = chars(w)
    return row, notes


def schedule_sheet(sheet, header, body, n_heading_rows):
    """A schedule: the title from the header section, then the body, on the body's columns. Heading rows are bold and
    stay in view (frozen) and print on every page. Returns notes."""
    body.bold_rows = set(body.rows[:n_heading_rows])
    body.number_rows = set(body.rows[n_heading_rows:])
    header.title = True
    sections = [s for s in (header, body) if s.rows and s.cols]
    if not body.cols:
        return [u"The schedule shows no columns in Revit."]
    edges = body.edges()
    _, notes = place(sheet, sections, edges, by_index=body)
    top = len(header.rows) if header.cols else 0
    frozen = top + n_heading_rows
    if 0 < frozen < 30:
        sheet.freeze_rows = frozen
        sheet.print_titles = (0, frozen - 1)
    return notes


def panel_sheet(sheet, sections):
    """A panel schedule as it reads in Revit: the sections given (hidden ones already left out), one under the
    other, each cell where it sits in Revit. Returns notes."""
    sections = [s for s in sections if s.rows and s.cols]
    if not sections:
        return [u"The panel schedule shows no cells in Revit."]
    _, notes = place(sheet, sections, union_edges(sections))
    return notes
