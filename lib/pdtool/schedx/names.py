# -*- coding: utf-8 -*-
"""Sheet names and file names for PD Schedules.

Excel's rules for a sheet name: 1 to 31 characters; none of [ ] : * ? / \\; not starting or ending with '; not
"History" (Excel keeps that name); no two sheets with the same name, ignoring capitals. A board name such as
DB/GF/01 becomes DB-GF-01 on its tab (choice C4 of the plan, approved 15/10/2026); the full name is always on the
Contents sheet and, for the DB chart layout, in cell C5.
"""
import re

from pdtool.sheets import names as file_names

MAX_SHEET = 31
_NOT_IN_SHEET = re.compile(u"[\\[\\]:*?/\\\\\x00-\x1f]")


def sheet_name(text, taken=(), suffix=u""):
    """A sheet name made from text, with suffix kept whole at the end, cut to 31 characters and made different from
    every name in taken (ignoring capitals) by adding " (2)", " (3)" and so on."""
    base = _NOT_IN_SHEET.sub(u"-", u"{}".format(text or u"")).strip()
    base = base.strip(u"'").strip() or u"Sheet"
    low = set(t.lower() for t in taken)
    n = 1
    while True:
        tail = suffix + (u" ({})".format(n) if n > 1 else u"")
        name = (_shorten(base, MAX_SHEET - len(tail)) + tail).strip(u"'")
        if name.lower() == u"history":
            name = name + u" (sheet)"
        if name.lower() not in low:
            return name
        n += 1


def _shorten(text, room):
    """text cut to room characters. A long name keeps its start and its end with "\u2026" between them, because the
    schedules of a model often share a long start and differ at the end ("Electrical Circuit Schedule_DB-GF-01"
    gives "Electrical\u2026Schedule_DB-GF-01")."""
    if len(text) <= room:
        return text
    if room < 12:
        return text[:room].rstrip()
    head = room // 3
    return text[:head].rstrip() + u"\u2026" + text[-(room - head - 1):].lstrip()


def file_name(text):
    """A file name made from text, with the characters Windows refuses replaced by "-" (as PD Sheets does)."""
    return file_names.clean(text)


def unique_files(stems):
    """File names made different from each other, ignoring capitals, by adding " (2)" and so on: Windows treats two
    names that differ only in capitals as the same file. Returns the new list in the same order."""
    out = []
    seen = set()
    for stem in stems:
        name, n = stem, 1
        while name.lower() in seen:
            n += 1
            name = u"{} ({})".format(stem, n)
        seen.add(name.lower())
        out.append(name)
    return out


def copy_name(stem, existing):
    """"<stem> (1).xlsx" or the first number free in the folder, for a workbook open in Excel."""
    return file_names.copy_name(stem, existing, extension=u".xlsx")
