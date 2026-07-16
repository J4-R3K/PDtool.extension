# -*- coding: utf-8 -*-
"""Prepare a PROJECT COPY for sharing.

Keeps the minimum a recipient needs to LINK this model into theirs:
  - the 3D 'Dashboard' view and sheet E-00001 (the model dashboard),
  - every view that uses the view template PD_354000-05_SetUp_(coordinates)_v1,
  - all placed model geometry (used families), levels, grids,
  - project base point / survey point / shared coordinates, revisions, project info.

Deletes everything else: all other views, sheets, schedules, legends; RVT links and
point clouds; unplaced groups; then PURGES every unused family, material, line/fill
pattern, filter and view template.

Safety: hard-blocks on a live workshared model unless the file name carries a
share/copy token; shows a full dry-run report; requires typing DESTROY. The whole run
is ONE undo step and the file is NOT saved. Finishes by refreshing the Dashboard
health gauges (the HealthCheck > Status button).

IronPython 2.7 - no f-strings, use .format(); except Exception.
"""
import os

import clr
clr.AddReference("System.Core")  # HashSet<T> lives here, not preloaded by IronPython
from System.Collections.Generic import HashSet, List
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    ElementId,
    Element,
    View,
    ViewSheet,
    Viewport,
    ScheduleSheetInstance,
    RevitLinkInstance,
    RevitLinkType,
    GroupType,
    Level,
    Grid,
    Transaction,
    TransactionGroup,
)
from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc

# ----------------------------------------------------------------- config ----
# Project-specific keep rules (reusable: edit these for another project).
COORD_TEMPLATE_NAME = "PD_354000-05_SetUp_(coordinates)_v1"
KEEP_SHEET_NUMBERS = ["E-00001"]
KEEP_VIEW_NAMES = ["Dashboard"]  # named views kept regardless of type
# Filename tokens that mark a file as a safe-to-strip COPY.
ALLOW_TOKENS = [
    "to be shared", "to_be_shared", "_share", "_shared",
    "_copy", " copy", "-copy", "_clean", "purge", "detached",
]
CONFIRM_WORD = "DESTROY"


def gname(el):
    try:
        return Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return "<unnamed>"


# --------------------------------------------------- GATE 1: live-model block ----
title = doc.Title or ""
path = doc.PathName or ""
name_hay = (title + " " + os.path.basename(path)).lower()
has_token = any(tok in name_hay for tok in ALLOW_TOKENS)

if doc.IsWorkshared and not has_token:
    forms.alert(
        "SAFETY STOP - this looks like a LIVE model.\n\n"
        "File: {}\n\n"
        "'Prepare for Share' permanently strips views, sheets, links and all unused "
        "content. It must only run on a COPY.\n\n"
        "Do File > Save As a copy whose name contains one of:\n"
        "    'to be shared'   'copy'   'clean'   'share'\n"
        "then reopen that copy and run this again.".format(title),
        title="Prepare for Share - BLOCKED",
        warn_icon=True,
    )
    script.exit()

# ------------------------------------------------------------- build the plan ----
# Coordinate view template (the one whose users we keep).
coord_tpl = None
for v in FilteredElementCollector(doc).OfClass(View):
    if v.IsTemplate and gname(v) == COORD_TEMPLATE_NAME:
        coord_tpl = v
        break

# Sheets: keep only the named ones.
all_sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet))
keep_sheets = [s for s in all_sheets if s.SheetNumber in KEEP_SHEET_NUMBERS]
del_sheets = [s for s in all_sheets if s.SheetNumber not in KEEP_SHEET_NUMBERS]

# Views placed on kept sheets are protected (e.g. the Dashboard 3D + revision schedule).
placed_on_keep = set()
for s in keep_sheets:
    for vp in FilteredElementCollector(doc, s.Id).OfClass(Viewport):
        placed_on_keep.add(vp.ViewId.IntegerValue)
    for ssi in FilteredElementCollector(doc, s.Id).OfClass(ScheduleSheetInstance):
        placed_on_keep.add(ssi.ScheduleId.IntegerValue)

# Views to delete: every browsable view that is not a keeper.
SKIP_VIEWTYPES = ("ProjectBrowser", "SystemBrowser", "Internal", "Undefined")
del_views = []
for v in FilteredElementCollector(doc).OfClass(View):
    if v.IsTemplate:
        continue  # templates handled by the purge; coord template stays (in use)
    if isinstance(v, ViewSheet):
        continue  # sheets handled separately
    if v.ViewType.ToString() in SKIP_VIEWTYPES:
        continue
    idv = v.Id.IntegerValue
    if gname(v) in KEEP_VIEW_NAMES:
        continue
    if coord_tpl is not None and v.ViewTemplateId == coord_tpl.Id:
        continue
    if idv in placed_on_keep:
        continue
    del_views.append(v)

# Links + point clouds + unplaced groups.
link_insts = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
pc_insts = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_PointClouds)
    .WhereElementIsNotElementType()
)
del_groups = []
for gt in FilteredElementCollector(doc).OfClass(GroupType):
    try:
        if gt.Groups.Size == 0:
            del_groups.append(gt)
    except Exception:
        pass

# ---------------------------------------------------- GATE 2: dry-run report ----
report = (
    "PREPARE MODEL FOR SHARE - dry run\n"
    "File: {title}\n"
    "{ws}\n\n"
    "WILL DELETE\n"
    "  Sheets .............. {ns}  (keep {keep})\n"
    "  Views/schedules/legends {nv}  (keep Dashboard + {nc} coordinate view + kept-sheet views)\n"
    "  RVT links ........... {nli} instances / {nlt} types\n"
    "  Point clouds ........ {npc}\n"
    "  Unplaced groups ..... {ng}\n"
    "  then PURGE UNUSED families, materials, line/fill patterns, filters, view templates\n\n"
    "WILL KEEP UNTOUCHED\n"
    "  Project Information, Revisions\n"
    "  Coordinates: base point / survey point / shared site (recipient links to these)\n"
    "  Levels, Grids, and ALL placed model geometry (used families)\n\n"
    "One undo step (Ctrl+Z). The file is NOT saved."
).format(
    title=title,
    ws=("Workshared COPY (name token OK)" if doc.IsWorkshared else "Non-workshared file"),
    ns=len(del_sheets), keep=", ".join(KEEP_SHEET_NUMBERS),
    nv=len(del_views), nc=(1 if coord_tpl else 0),
    nli=len(link_insts), nlt=len(link_types), npc=len(pc_insts), ng=len(del_groups),
)

if coord_tpl is None:
    report = ("WARNING: coordinate template '{}' NOT FOUND - only 'Dashboard' and "
              "kept-sheet views will survive.\n\n").format(COORD_TEMPLATE_NAME) + report

if not forms.alert(report, title="Prepare for Share", ok=False, yes=True, no=True,
                   warn_icon=True):
    script.exit()

# ---------------------------------------------------- GATE 3: type to confirm ----
typed = forms.ask_for_string(
    default="",
    prompt="Type  {}  (capitals) to permanently clean this model copy:".format(CONFIRM_WORD),
    title="Final confirmation",
)
if typed != CONFIRM_WORD:
    forms.alert("Cancelled - nothing was changed.", title="Prepare for Share")
    script.exit()

# ---------------------------------------------------------------- do the work ----
# Move off any view we're about to delete.
if keep_sheets:
    try:
        uidoc.ActiveView = keep_sheets[0]
    except Exception:
        pass

res = {}


def _bulk_delete(elems):
    ids = List[ElementId]()
    for e in elems:
        if e.IsValidObject:
            ids.Add(e.Id)
    if ids.Count == 0:
        return 0
    doc.Delete(ids)
    return ids.Count


tg = TransactionGroup(doc, "Prepare Model for Share")
tg.Start()
try:
    # 1) sheets (except keepers) - removes viewports, not underlying views
    t = Transaction(doc, "PrepShare: sheets"); t.Start()
    res["sheets"] = _bulk_delete(del_sheets); t.Commit()

    # 2) views / schedules / legends - one by one (dependents cascade)
    t = Transaction(doc, "PrepShare: views"); t.Start()
    vdel = 0; vskip = 0
    for v in del_views:
        if not v.IsValidObject:
            continue
        try:
            doc.Delete(v.Id); vdel += 1
        except Exception:
            vskip += 1
    t.Commit()
    res["views"] = vdel; res["views_skipped"] = vskip

    # 3) RVT links (delete types -> instances follow), then any stragglers
    t = Transaction(doc, "PrepShare: links"); t.Start()
    res["link_types"] = _bulk_delete(link_types)
    res["link_insts"] = _bulk_delete(
        [e for e in link_insts if e.IsValidObject])
    t.Commit()

    # 4) point clouds
    t = Transaction(doc, "PrepShare: point clouds"); t.Start()
    res["point_clouds"] = _bulk_delete(pc_insts); t.Commit()

    # 5) unplaced groups
    t = Transaction(doc, "PrepShare: groups"); t.Start()
    res["groups"] = _bulk_delete(del_groups); t.Commit()

    # 6) purge unused - repeat until stable (cascades as families free materials etc.)
    protect = set()
    if coord_tpl is not None:
        protect.add(coord_tpl.Id.IntegerValue)
    t = Transaction(doc, "PrepShare: purge unused"); t.Start()
    total = 0; rounds = 0
    while rounds < 15:
        rounds += 1
        try:
            unused = doc.GetUnusedElements(HashSet[ElementId]())
        except Exception as ex:
            res["purge_error"] = str(ex); break
        ids = List[ElementId]()
        for eid in unused:
            if eid.IntegerValue in protect:
                continue
            el = doc.GetElement(eid)
            if el is None:
                continue
            if isinstance(el, (Level, Grid)):  # never drop a datum
                continue
            ids.Add(eid)
        if ids.Count == 0:
            break
        try:
            deleted = doc.Delete(ids)
            total += (deleted.Count if deleted is not None else ids.Count)
        except Exception:
            ok = 0
            for eid in ids:  # fall back: skip the few that refuse
                try:
                    if doc.GetElement(eid) is not None:
                        doc.Delete(eid); ok += 1
                except Exception:
                    pass
            total += ok
            if ok == 0:
                break
    t.Commit()
    res["purged"] = total; res["purge_rounds"] = rounds

    # 7) refresh the Dashboard health gauges (runs the HealthCheck > Status button,
    #    inside this group so the whole thing stays ONE undo step)
    hc_status = "not run"
    try:
        tab_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # PD.tab
        hc_path = os.path.join(tab_dir, "HealthCheck.panel", "Status.pushbutton",
                               "script.py")
        with open(hc_path, "r") as fh:
            _code = fh.read()
        exec(compile(_code, hc_path, "exec"), {"__name__": "__prepshare_hc__"})
        hc_status = "refreshed"
    except Exception as hcex:
        hc_status = "skipped ({})".format(hcex)

    tg.Assimilate()  # collapse everything into ONE undo step
except Exception as ex:
    try:
        tg.RollBack()
    except Exception:
        pass
    forms.alert("FAILED and rolled back - model unchanged.\n\n{}".format(ex),
                title="Prepare for Share", warn_icon=True)
    script.exit()

# ------------------------------------------------------------------- summary ----
forms.alert(
    "DONE - model prepared for share.\n\n"
    "Deleted\n"
    "  Sheets ................ {sheets}\n"
    "  Views/schedules/legends {views}  (skipped {vskip})\n"
    "  Link types/instances .. {lt} / {li}\n"
    "  Point clouds .......... {pc}\n"
    "  Unplaced groups ....... {grp}\n"
    "  Purged unused ......... {purged}  (in {rounds} passes)\n\n"
    "Kept: Dashboard, coordinate set-up view, sheet E-00001, all model geometry, "
    "levels, grids, coordinates, revisions, project info.\n\n"
    "Dashboard health gauges: {hc}.\n\n"
    "File NOT saved - review, then File > Save As your share copy.\n"
    "Ctrl+Z once reverts the entire clean-up.".format(
        sheets=res.get("sheets", 0),
        views=res.get("views", 0), vskip=res.get("views_skipped", 0),
        lt=res.get("link_types", 0), li=res.get("link_insts", 0),
        pc=res.get("point_clouds", 0), grp=res.get("groups", 0),
        purged=res.get("purged", 0), rounds=res.get("purge_rounds", 0),
        hc=hc_status,
    ),
    title="Prepare for Share",
)
