# -*- coding: utf-8 -*-
__title__ = "Copy: Trays by Level"
__doc__   = """Version = 1.0
Date    = 09.07.2026
________________________________________________________________
Description:

Copy STRAIGHT cable trays (NO fittings) from a selected Revit Link,
filtered to the link levels you choose.

For each run it will:
  - copy only OST_CableTray straight segments (fittings are ignored)
  - remap every source tray TYPE to a host type from THIS project
  - preserve each segment's own Width / Height
  - keep the exact position via the link transform (0 mm drift)
  - HOME each straight to the matching host level (nearest elevation),
    so schedules / view filters by level pick them up

Built to mirror the manual API workflow used on 26183 (LG_FFL / 00_FFL
-> LEVEL LG / LEVEL 00).
________________________________________________________________
How-To:

1. Pick the Revit Link to copy FROM.
2. Tick the link levels to copy (e.g. LG_FFL, 00_FFL).
3. Map each source tray type to a host type (or Skip).
4. Confirm the level mapping. Done.
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference('RevitAPI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, RevitLinkInstance, ElementId,
    Transaction, BuiltInParameter, StorageType, Line, Level
)
from Autodesk.Revit.DB.Electrical import CableTray
from pyrevit import revit, forms, script

doc = revit.doc
out = script.get_output()
MM  = 304.8

if doc is None:
    forms.alert("No active Revit document.", exitscript=True)

# ------------------------------------------------------------------ helpers
def _bic(*names):
    for n in names:
        try:    return getattr(BuiltInCategory, n)
        except Exception: pass
    return None

CAT_TRAY = _bic('OST_CableTray', 'OST_CableTrays')
if CAT_TRAY is None:
    forms.alert("Could not resolve the Cable Tray category.", exitscript=True)

def safe_type_name(t):
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = t.get_Parameter(bip)
            if p:
                s = p.AsString()
                if s: return s
        except Exception: pass
    try:
        n = t.Name
        if n: return n
    except Exception: pass
    return u"<Type {}>".format(t.Id.IntegerValue)

def safe_family_name(t):
    try:
        fn = getattr(t, "FamilyName", None)
        if fn: return fn
    except Exception: pass
    try:
        p = t.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        if p:
            s = p.AsString()
            if s: return s
    except Exception: pass
    return "Cable Tray"

def _pdouble(el, bips):
    for bn in bips:
        try:
            p = el.get_Parameter(getattr(BuiltInParameter, bn))
            if p and p.StorageType == StorageType.Double:
                return p.AsDouble()
        except Exception: pass
    return None

def tray_w(el): return _pdouble(el, ["RBS_CABLETRAY_WIDTH_PARAM"])
def tray_h(el): return _pdouble(el, ["RBS_CABLETRAY_HEIGHT_PARAM"])

def src_level_id(el):
    try:
        p = el.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
        if p:
            eid = p.AsElementId()
            if eid and eid != ElementId.InvalidElementId:
                return eid
    except Exception: pass
    return None

# ------------------------------------------------------------------ pick link
links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
if not links:
    forms.alert("No Revit Links found in this model.", exitscript=True)

lmap = {}
for li in links:
    ld = li.GetLinkDocument()
    label = u"{}  -  {}".format(li.Name, ld.Title if ld else "(unloaded)")
    lmap[label] = li

sel = forms.SelectFromList.show(sorted(lmap.keys()), multiselect=False,
        title="Select Revit Link to copy FROM", button_name="Use Link")
if not sel:
    script.exit()

link_inst = lmap[sel]
link_doc  = link_inst.GetLinkDocument()
if link_doc is None:
    forms.alert("The selected link is unloaded or inaccessible.", exitscript=True)
xform = link_inst.GetTotalTransform()

# ------------------------------------------------------------------ link levels + straights
link_levels = {}   # id(int) -> (name, elevation_ft)
for lv in FilteredElementCollector(link_doc).OfClass(Level):
    link_levels[lv.Id.IntegerValue] = (lv.Name, lv.Elevation)

straights = list(FilteredElementCollector(link_doc).OfCategory(CAT_TRAY).WhereElementIsNotElementType())
if not straights:
    forms.alert("No cable tray straights found in the selected link.", exitscript=True)

levels_with = {}   # level name -> id(int)   (only levels that actually carry straights)
for e in straights:
    sid = src_level_id(e)
    if sid and sid.IntegerValue in link_levels:
        levels_with[link_levels[sid.IntegerValue][0]] = sid.IntegerValue
if not levels_with:
    forms.alert("Cable tray straights in the link have no reference level assigned.", exitscript=True)

lvl_sel = forms.SelectFromList.show(sorted(levels_with.keys()), multiselect=True,
        title="Select link LEVELS to copy trays from", button_name="Use Levels")
if not lvl_sel:
    script.exit()
sel_level_ids = set(levels_with[n] for n in lvl_sel)

# straights on the chosen levels, grouped by source type
chosen = []
for e in straights:
    sid = src_level_id(e)
    if sid and sid.IntegerValue in sel_level_ids:
        chosen.append(e)
if not chosen:
    forms.alert("No straights on the selected levels.", exitscript=True)

groups = {}   # typeUid -> {'type':t, 'name':str, 'elems':[e,...]}
for e in chosen:
    tid = e.GetTypeId()
    if tid == ElementId.InvalidElementId:
        continue
    t = link_doc.GetElement(tid)
    if t is None:
        continue
    k = t.UniqueId
    if k not in groups:
        groups[k] = {'type': t, 'name': safe_type_name(t), 'elems': []}
    groups[k]['elems'].append(e)

# ------------------------------------------------------------------ host tray types
host_types = {}   # label -> ElementType
for t in FilteredElementCollector(doc).OfCategory(CAT_TRAY).WhereElementIsElementType():
    host_types[u"{} : {}".format(safe_family_name(t), safe_type_name(t))] = t
if not host_types:
    forms.alert("No cable tray types found in this project.", exitscript=True)

SKIP = u"<< Skip this type (don't copy) >>"

# ------------------------------------------------------------------ type mapping
forms.alert("Map each SOURCE tray type (found on the chosen levels) to a host "
            "type in this project.\nChoose Skip to leave a type out.",
            title="Tray Type Mapping", warn_icon=False)

type_map = {}   # typeUid -> host ElementId or None(skip)
for k in sorted(groups.keys(), key=lambda x: groups[x]['name']):
    g = groups[k]
    title = u"Map source type:  {}   ({} straights)".format(g['name'], len(g['elems']))
    pick = forms.SelectFromList.show([SKIP] + sorted(host_types.keys()),
            multiselect=False, title=title, button_name="Use Type")
    if not pick:
        script.exit()
    type_map[k] = None if pick == SKIP else host_types[pick].Id

# ------------------------------------------------------------------ level mapping (nearest elevation)
host_levels = list(FilteredElementCollector(doc).OfClass(Level))
if not host_levels:
    forms.alert("No levels in the current project.", exitscript=True)

def nearest_host_level(elev_ft):
    best, bestd = None, None
    for hl in host_levels:
        d = abs(hl.Elevation - elev_ft)
        if bestd is None or d < bestd:
            best, bestd = hl, d
    return best, bestd

level_map = {}   # src level id(int) -> host Level
conf = []
for lid in sel_level_ids:
    nm, elev = link_levels[lid]
    hl, d = nearest_host_level(elev)
    level_map[lid] = hl
    conf.append(u"{}  ->  {}   (delta {} mm)".format(nm, hl.Name, round(d * MM, 1)))

if not forms.alert("Each straight will be homed to its floor:\n\n" + "\n".join(sorted(conf)) +
                   "\n\nProceed?", title="Confirm Level Mapping", yes=True, no=True):
    script.exit()

# ------------------------------------------------------------------ create
created = skipped_type = skipped_geo = 0
per = {}
errors = []

with Transaction(doc, "Copy Tray Straights by Level") as tx:
    tx.Start()
    for k in groups:
        htid = type_map.get(k)
        if htid is None:
            skipped_type += len(groups[k]['elems'])
            continue
        htype = doc.GetElement(htid)
        for e in groups[k]['elems']:
            try:
                loc = e.Location
                crv = getattr(loc, "Curve", None)
                if crv is None or not isinstance(crv, Line):
                    skipped_geo += 1
                    continue
                p0 = xform.OfPoint(crv.GetEndPoint(0))
                p1 = xform.OfPoint(crv.GetEndPoint(1))
                if p0.DistanceTo(p1) < 1e-6:
                    skipped_geo += 1
                    continue
                sid = src_level_id(e)
                hl = level_map.get(sid.IntegerValue) if sid else None
                if hl is None:
                    skipped_geo += 1
                    continue

                nt = CableTray.Create(doc, htid, p0, p1, hl.Id)

                w = tray_w(e)
                if w is not None:
                    pw = nt.get_Parameter(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
                    if pw and not pw.IsReadOnly:
                        pw.Set(w)
                h = tray_h(e)
                if h is not None:
                    ph = nt.get_Parameter(BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
                    if ph and not ph.IsReadOnly:
                        ph.Set(h)

                created += 1
                key = u"{} | {}".format(safe_type_name(htype), hl.Name)
                per[key] = per.get(key, 0) + 1
            except Exception as ex:
                errors.append((groups[k]['name'], str(ex)))
    tx.Commit()

# ------------------------------------------------------------------ report
out.print_md("### Copy complete - straights only, no fittings")
out.print_md("* Created: **{}**".format(created))
if skipped_type:
    out.print_md("* Skipped (type set to Skip): **{}**".format(skipped_type))
if skipped_geo:
    out.print_md("* Skipped (non-line / zero length / no level): **{}**".format(skipped_geo))
if per:
    out.print_md("\n**Breakdown (host type | level):**")
    for key in sorted(per.keys()):
        out.print_md("* {} x  {}".format(per[key], key))
if errors:
    out.print_md("\n### Errors")
    for nm, r in errors:
        out.print_md("* {} - {}".format(nm, r))
out.print_md("\n---")
out.print_md("*Position preserved via the link transform; each straight homed to the "
             "nearest host level; per-segment sizes copied. Fittings are intentionally skipped.*")
