# -*- coding: utf-8 -*-
"""The workbook: a Contents sheet first, then one sheet for each schedule and one or two for each panel schedule.
Plain Python: it takes what revitread has read, so the tests build workbooks without Revit.

An item, as revitread gives it:
    {"name": name in Revit, "kind": "schedule" (or "sheet list", "view list", ...) or "panel schedule",
     "schedule": {"header": Section, "body": Section, "heading_rows": n, "notes": [...]}      for a schedule
     "panel": {"sections": [Section], "notes": [...]}                                          for a panel schedule
     "chart": {"board": {...}, "slots": [...], "notes": [...]} or None, "chart_problem": text or None}
"""
from pdtool.schedx import dbchart, grid, names
from pdtool.schedx.xlsx import MAX_TEXT, Num, Style, Workbook

CONTENTS = u"Contents"
AS_IN_REVIT = u" (as in Revit)"
BOLD = Style(bold=True)
LINK = Style(colour=u"0563C1", underline=True, valign=u"top")
HEAD = Style(bold=True, border=True, fill=u"D9D9D9", wrap=True)
CELL = Style(border=True, wrap=True)
CONTENTS_HEADINGS = (u"Sheet", u"Name in Revit", u"Kind", u"Layout", u"Rows", u"Columns", u"Notes")
CONTENTS_WIDTHS = (34, 50, 16, 16, 8, 9, 70)


def build(items, title, made, panel_revit=True, panel_chart=True):
    """A Workbook of the items, in their order. title: the model's title; made: the date and time as text.
    Returns (workbook, [(sheet name, item name, layout, rows, columns, notes)])."""
    wb = Workbook()
    contents = wb.add_sheet(CONTENTS)
    taken = [CONTENTS]
    listed = []

    def new_sheet(text, suffix=u""):
        name = names.sheet_name(text, taken, suffix)
        taken.append(name)
        return wb.add_sheet(name)

    for item in items:
        if item.get("schedule"):
            sched = item["schedule"]
            sheet = new_sheet(item["name"])
            notes = list(sched.get("notes") or [])
            notes += grid.schedule_sheet(sheet, sched["header"], sched["body"], sched["heading_rows"])
            listed.append((sheet, item, u"As in Revit", notes))
            continue
        if panel_chart:
            chart = item.get("chart")
            if chart:
                board = chart["board"]
                sheet = new_sheet(board.get("name") or item["name"])
                dbchart.chart_sheet(sheet, board, chart["slots"])
                listed.append((sheet, item, u"DB chart", list(chart.get("notes") or [])))
            else:
                listed.append((None, item, u"DB chart", [item.get("chart_problem") or u"The DB chart is not made."]))
        if panel_revit and item.get("panel"):
            panel = item["panel"]
            sheet = new_sheet(item["name"], AS_IN_REVIT)
            notes = list(panel.get("notes") or [])
            notes += grid.panel_sheet(sheet, panel["sections"])
            listed.append((sheet, item, u"As in Revit", notes))

    for sheet, _, _, notes in listed:
        long_cells = sheet and sum(1 for v, _ in sheet.cells.values()
                                   if v is not None and not isinstance(v, (Num, int, float)) and len(v) > MAX_TEXT)
        if long_cells:
            notes.append(u"Cells longer than {:,} characters, the most Excel allows in one cell, are cut at that "
                         u"length. The number of cells cut is {}.".format(MAX_TEXT, long_cells))

    contents.set(0, 0, u"{}: schedules exported from Revit".format(title), BOLD)
    line = u"The schedules were exported on {} with PD Schedules. Click a sheet name to open the sheet.".format(made)
    if any(layout == u"DB chart" for _, _, layout, _ in listed):
        # the first use of DB on the Contents sheet, so the full term is written here (acronym rule for tools)
        line += (u" A sheet in the layout of PD's distribution board (DB) charts is listed as \"DB chart\" in the "
                 u"Layout column.")
    contents.set(1, 0, line)
    for c, heading in enumerate(CONTENTS_HEADINGS):
        contents.set(3, c, heading, HEAD)
    for c, w in enumerate(CONTENTS_WIDTHS):
        contents.widths[c] = w
    contents.freeze_rows = 4
    out = []
    for i, (sheet, item, layout, notes) in enumerate(listed):
        r = 4 + i
        rows, cols = sheet.size() if sheet else (0, 0)
        if sheet:
            contents.set(r, 0, sheet.name, LINK.but(border=True))
            contents.links.append((r, 0, sheet.name))
        else:
            contents.set(r, 0, u"(not made)", CELL)
        text = u" ".join(notes)
        for c, value in enumerate((item["name"], item.get("kind") or u"", layout, rows, cols, text)):
            contents.set(r, c + 1, value, CELL)
        out.append((sheet.name if sheet else u"", item["name"], layout, rows, cols, text))
    contents.print_titles = (3, 3)
    return wb, out
