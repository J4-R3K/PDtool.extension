# -*- coding: utf-8 -*-
"""The export record: PD-Sheets-export-<date>-<time>.csv, written beside the exported files.

UTF-8 with a byte order mark so Excel opens it with the right characters; Windows line endings; every field quoted.
Written by hand rather than with the csv module, whose text handling differs between IronPython 2.7 and CPython 3.
"""
import io
import os

COLUMNS = (
    (u"file", u"File"),
    (u"format", u"Format"),
    (u"number", u"Sheet number"),
    (u"name", u"Sheet name"),
    (u"revision", u"Revision"),
    (u"paper", u"Paper size"),
    (u"orientation", u"Orientation"),
    (u"raster_quality", u"Raster quality"),
    (u"rasterised", u"Views that may be rasterised"),
    (u"size_mb", u"File size (MB)"),
    (u"over_limit", u"Over the limit"),
    (u"result", u"Result"),
    (u"note", u"Note"),
    (u"time", u"Time"),
    (u"revit", u"Revit version"),
    (u"user", u"User"),
    (u"profile", u"Profile"),
    # Added 15/10/2026 at the end, so the columns before it stay where they were.
    (u"also_written", u"Files Revit also wrote"),
)


def file_name(when):
    """when: a datetime."""
    return u"PD-Sheets-export-{}.csv".format(when.strftime("%Y-%m-%d-%H%M%S"))


def _field(value):
    if value is None:
        text = u""
    elif isinstance(value, bool):
        text = u"yes" if value else u"no"
    elif isinstance(value, float):
        text = u"{:.2f}".format(value)
    elif isinstance(value, (list, tuple)):
        text = u"; ".join(u"{}".format(v) for v in value)
    else:
        text = u"{}".format(value)
    return u'"{}"'.format(text.replace(u'"', u'""'))


def lines(rows):
    out = [u",".join(_field(title) for _, title in COLUMNS)]
    for row in rows:
        out.append(u",".join(_field(row.get(key)) for key, _ in COLUMNS))
    return out


def write(folder, when, rows):
    """Write the record and return its path."""
    path = os.path.join(folder, file_name(when))
    with io.open(path, "w", encoding="utf-8-sig", newline=u"") as f:
        f.write(u"\r\n".join(lines(rows)) + u"\r\n")
    return path


def size_mb(path):
    try:
        return os.path.getsize(path) / (1024.0 * 1024.0)
    except OSError:
        return None


def renamed_summary(rows):
    """The sentence for the results when files were written under another name because the file of the right name
    could not be replaced (exporter.export_one), or "" when none was. The name written does not follow the naming
    rule, so the reader is told how to put it right."""
    renamed = [r for r in rows if r.get("renamed_from") and (r.get("result") or u"").startswith(u"written")]
    if not renamed:
        return u""
    in_use = all(r.get("in_use") for r in renamed)
    if len(renamed) == 1:
        r = renamed[0]
        if in_use:
            return (u"{0} is open in another program, so the new file is saved as {1}, which does not follow the "
                    u"naming rule. Close {0} and export again to replace it.").format(r["renamed_from"], r["file"])
        return (u"{0} could not be replaced, so the new file is saved as {1}, which does not follow the naming rule. "
                u"The Result column gives the reason.").format(r["renamed_from"], r["file"])
    if in_use:
        return (u"{} files are open in another program, so the new files are saved with (1) or a higher number added "
                u"to the name, which does not follow the naming rule. Close those files and export again to replace "
                u"them.").format(len(renamed))
    return (u"{} files could not be replaced, so the new files are saved with (1) or a higher number added to the "
            u"name, which does not follow the naming rule. The Result column gives the reason for each.").format(
        len(renamed))
