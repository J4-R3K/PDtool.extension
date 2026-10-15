# -*- coding: utf-8 -*-
"""The files Revit writes beside a DGN or DWG file, and how they are found.

A DGN export of one sheet or view writes more than <name>.dgn (a project model, Revit 2024, 15/10/2026):
- <name>-<linked model file>-<n>-<view name>.dgn for each linked model shown in each view, with the dot of ".rvt"
  written as "-" ("dgn-plan-Architecture-rvt-1-LEVEL 00.dgn"). One sheet wrote 10, the largest
  83.5 MB.
- <name>-<view type> - <view name>.dgn for each view placed on a sheet ("dgn-sheet-Elevation - EL-01D.dgn").
- <CAD file name>.dgn for each linked CAD file shown, under the CAD file's own name, not the export's
  (15 MB, from two plans that show the same CAD file). Revit replaces it without asking
  when it is already in the folder.

A DWG export writes the same files for linked models and for the views on a sheet, with .dwg, and the plot settings
file <name>.pcp (pen weights by colour); no file for a linked CAD file (15/10/2026). With merged views
(MergedViews in the DGN or DWG options) Revit writes one file only: the DGN of one plan took 52.7 s and
wrote one file of 7.0 MB, against 87.3 s and five files without (15/10/2026).

The exporter lists the folder before and after each DGN and DWG export (snapshot, changes), so the files written are
known rather than predicted. Before the export, companions and cad_file predict the files already in the folder that
the export would replace, for the window's question "already in the folder".

The size check (too_large, large_note) is for views with no crop region. Revit draws a view for an export at
10 pixels to the millimetre on paper, up to 128,000 pixels: the journal of the DGN export of plan LEVEL 00
(15/10/2026) has "Occlusion BMP width 59639614, reset to 128000", and 59,639,614 pixels is that plan's width on paper,
19,566.8 ft, at 10 pixels to the millimetre. So 12.8 m on paper is the most Revit draws. Found in the same tests:
- LEVEL 00 (crop off, 5,964 m by 1,618 m on paper): the PNG was blank, the DWF 4 KB, and after the DGN Revit showed
  "The view boundaries for the identified views are too large to export", with Cancel as the only button.
- Section 20 (crop off, 42.8 m by 3.1 m): the PNG, 2,048 pixels wide, was drawn in its right-hand 28% only;
  12.8 m is 30% of 42.8 m.
- Site_01 (crop off, 7.5 m by 3.8 m): drawn in full.
The limit is read from one journal line and these three views, not from Autodesk's documents.

Plain Python, so the library tests run without Revit.
"""
import os
import re


# The most Revit draws of a view in an export, on paper (see above), in feet as View.Outline gives it.
LIMIT_MM = 12800.0
LIMIT_FT = LIMIT_MM / 304.8

# The extension of the plot settings file Revit writes beside a DWG.
SETTINGS_EXTENSION = u".pcp"


def snapshot(folder):
    """{name in lower case: (name, size, time last written)} for each file in the folder."""
    out = {}
    try:
        listing = os.listdir(folder)
    except OSError:
        return out
    for f in listing:
        p = os.path.join(folder, f)
        try:
            if not os.path.isfile(p):
                continue
            st = os.stat(p)
        except OSError:
            continue
        out[f.lower()] = (f, st.st_size, st.st_mtime)
    return out


def sort_names(items):
    """File names in order, ignoring capitals."""
    return sorted(items, key=lambda n: n.lower())


def changes(before, after, leave_out=()):
    """(new, replaced) between two snapshots: the files that were not in the folder before, and the files that were
    and have since been written again (size or time last written changed). leave_out: names not to list, such as the
    file the export is for. Capitals are ignored, as Windows ignores them."""
    skip = set(n.lower() for n in leave_out)
    new, replaced = [], []
    for low, (name, size, mtime) in after.items():
        if low in skip:
            continue
        if low not in before:
            new.append(name)
        elif tuple(before[low][1:]) != (size, mtime):
            replaced.append(name)
    return sort_names(new), sort_names(replaced)


def _is_link_file(rest, view):
    return re.match(u"^.+-rvt-\\d+-" + re.escape(view) + u"$", rest) is not None


def _is_view_file(rest, view):
    return len(rest) > len(view) + 3 and rest.endswith(u" - " + view)


def companions(name, views, listing, others=(), extension=u".dgn"):
    """The files in listing that a DGN export named name writes again: for each view (the view exported, or each view
    placed on the sheet), the file for each linked model and the file for the view.

    others: the other names exported in the same run. Where one starts with this name and "-" ("E-1" and "E-1-A"),
    its own files are left out. A name exported in an earlier run is not known, so its files may be listed here when
    it starts with this name and shows the same view."""
    stem = (name or u"").lower() + u"-"
    ext = extension.lower()
    views = [(v or u"").lower() for v in views if v]
    theirs = [o.lower() for o in others if o and o.lower().startswith(stem)]
    out = []
    for f in listing:
        low = f.lower()
        if not (low.startswith(stem) and low.endswith(ext)):
            continue
        if any(low == t + ext or low.startswith(t + u"-") for t in theirs):
            continue
        rest = low[len(stem):len(low) - len(ext)]
        if any(_is_link_file(rest, v) or _is_view_file(rest, v) for v in views):
            out.append(f)
    return sort_names(out)


def cad_file(cad_name, extension=u".dgn"):
    """The file Revit writes for a linked CAD file shown in a DGN export: the CAD file's name with .dgn in place of
    its own extension ("Site plan.dwg" gives "Site plan.dgn"), or None for no name."""
    if not cad_name:
        return None
    stem, ext = os.path.splitext(cad_name)
    if ext.lower() not in (u".dwg", u".dxf", u".dgn", u".sat", u".skp", u".3dm", u".axm", u".rvt", u".ifc", u".pdf"):
        stem = cad_name
    return stem + extension


def kind(name, extra_file):
    """What one extra file of the export named name is for: "link" (a linked model), "view" (a view on the sheet),
    "settings" (the plot settings file of a DWG) or "cad" (anything else, which in the tests was a linked CAD
    file)."""
    low = extra_file.lower()
    if low.endswith(SETTINGS_EXTENSION):
        return u"settings"
    stem = (name or u"").lower() + u"-"
    if low.startswith(stem):
        rest = os.path.splitext(low[len(stem):])[0]
        if re.match(u"^.+-rvt-\\d+-.", rest):
            return u"link"
        if u" - " in rest:
            return u"view"
    return u"cad"


def _count(n, one, many):
    return u"{} {}".format(n, one if n == 1 else many)


def note(name, new, replaced, label=u"DGN"):
    """The row's note on the files Revit wrote beside the file named name, or "" when there were none.

    new: files that were not in the folder; replaced: files that were in the folder and Revit wrote again (written
    earlier in the same export are left out by the caller)."""
    every = sort_names(list(new) + list(replaced))
    if not every:
        return u""
    kinds = dict((f, kind(name, f)) for f in every)
    files = [f for f in every if kinds[f] != u"settings"]
    settings = [f for f in every if kinds[f] == u"settings"]
    sentences = []
    if files:
        links = len([f for f in files if kinds[f] == u"link"])
        views = len([f for f in files if kinds[f] == u"view"])
        cads = [f for f in files if kinds[f] == u"cad"]
        # (count, what they are for); the count is left out where all the files are of one kind
        parts = []
        if links:
            parts.append((links, u"for a linked model" if links == 1 else u"for linked models"))
        if views:
            parts.append((views, u"for a view on the sheet" if views == 1 else u"for the views on the sheet"))
        if cads:
            parts.append((len(cads), u"under {} own name ({})".format(u"its" if len(cads) == 1 else u"their",
                                                                       u", ".join(cads))))
        head = _count(len(files), label + u" file", label + u" files")
        if len(parts) == 1:
            sentences.append(u"Revit also wrote {} {}.".format(head, parts[0][1]))
        else:
            each = [u"{} {}".format(n, what) for n, what in parts]
            sentences.append(u"Revit also wrote {}: {} and {}.".format(head, u", ".join(each[:-1]), each[-1]))
    if settings:
        sentences.append(u"{} also wrote the plot settings file {}.".format(u"It" if files else u"Revit",
                                                                            u", ".join(settings)))
    if replaced:
        if len(every) == 1:
            first = u"It was"
        else:
            first = _count(len(replaced), u"of them was", u"of them were")
        sentences.append(u"{} already in the folder and Revit replaced {}: {}.".format(
            first, u"it" if len(replaced) == 1 else u"them", u", ".join(sort_names(replaced))))
    return u" ".join(sentences)


def already_text(existing, beside, labels=()):
    """The question asked before an export when files are already in the folder. existing: how many of the files to
    export are there; beside: how many other files Revit would write again beside a DWG or DGN; labels: the formats
    of those ("DGN", "DWG")."""
    parts = []
    if existing:
        parts.append(_count(existing, u"file", u"files"))
    if beside:
        which = u" or ".join(sorted(set(labels))) or u"DWG or DGN"
        parts.append(u"{} that Revit writes beside a {} file".format(
            _count(beside, u"other file", u"other files") if existing else _count(beside, u"file", u"files"), which))
    if not parts:
        return u""
    return u"{} {} already in the folder. Replace them, or skip the sheets and views they belong to?".format(
        u" and ".join(parts), u"is" if existing + beside == 1 else u"are")


# ---- views too large to export ------------------------------------------------------------------------------------

# The formats the size check is made for: images and DWF (a blank or part-drawn file of LEVEL 00 and Section 20),
# DGN (Revit's message), and DWG, which Revit exports in the same way as DGN (not tested with a large view). PDF was
# not tested with a large view, so it is not checked.
SIZE_CHECKED = (u"dwg", u"dgn", u"dwf", u"img")


def too_large(width_ft, height_ft, crop_active):
    """True when a view with no crop region is larger on paper than LIMIT_FT across or up (View.Outline, in feet
    on paper). A view with its crop region on is never listed: the largest in the test model was 1.3 m."""
    if crop_active or width_ft is None or height_ft is None:
        return False
    return max(width_ft, height_ft) > LIMIT_FT


def metres(feet):
    """A size on paper in metres as the window shows it: whole metres from 100 m ("5,964 m"), else to 0.1 m."""
    m = feet * 0.3048
    if m >= 100:
        return u"{:,.0f} m".format(m)
    return u"{:.1f} m".format(m)


def large_note(found, most=6):
    """The check step's sentences on views with no crop region that are larger than Revit draws, or "" for none.

    found: [(view name, width ft, height ft, sheet label or None)], with the sheet label where the view is placed on
    a ticked sheet. Views past the first most are counted, not named."""
    if not found:
        return u""
    shown = []
    for view, w, h, sheet in found[:most]:
        where = u"on sheet {}, ".format(sheet) if sheet else u""
        shown.append(u"{} ({}{} by {})".format(view, where, metres(w), metres(h)))
    if len(found) > most:
        shown.append(u"{} more".format(len(found) - most))
    listed = (u", ".join(shown[:-1]) + u" and " + shown[-1]) if len(shown) > 1 else shown[0]
    limit = metres(LIMIT_FT)
    if len(found) == 1:
        return (u"View {} has no crop region and is larger on paper than the {} that Revit draws. Revit may write a "
                u"blank or part-drawn file of it, or show a message at the end of the export that the view is too "
                u"large to export. Set a crop region in the view first.").format(listed, limit)
    return (u"{} views have no crop region and are larger on paper than the {} that Revit draws: {}. Revit may write "
            u"blank or part-drawn files of them, or show a message at the end of the export that the views are too "
            u"large to export. Set a crop region in each view first.").format(len(found), limit, listed)
