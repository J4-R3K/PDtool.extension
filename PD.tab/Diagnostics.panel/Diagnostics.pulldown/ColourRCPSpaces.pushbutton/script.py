# -*- coding: utf-8 -*-
__title__  = 'Colour RCP Spaces'
__author__ = 'PD'
__doc__    = """Bake Space colour (driven by the PD_IsSpace_Litecom view filters)
into plottable Filled Regions, so it prints in a Reflected Ceiling Plan - where
Colour Schemes are unavailable and filter surface-overrides on Spaces do not plot.

For each Space it finds the matching Litecom filter, reads that filter's colour,
remaps it to a light pastel of the same hue, and draws a transparent Filled Region
on the Space boundary. Prompts to run on the active view or ALL RCP views sharing
its template. Re-runnable: deletes its own previous output (Comments='PD_RCP_COLOUR').

IMPORTANT: export via Revit's NATIVE PDF (File > Export > PDF). PDF24 / PostScript
drivers flatten the transparency and darken it. Tune PASTEL_SAT / TRANSPARENCY at
the top of the script.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms
from System.Collections.Generic import List

doc   = revit.doc
uidoc = revit.uidoc
view  = revit.active_view
out   = script.get_output()

TAG = "PD_RCP_COLOUR"

# Remap every colour to a uniform LIGHT pastel of the same hue, so dark sources
# (black, maroon, pure blue/magenta) come out as light as the pale ones and all
# zones sit at the same soft level - distinguishable by hue only.
PASTELISE      = True
PASTEL_SAT     = 0.35   # pastel colour strength (higher = more colour, 0.25-0.45)
PASTEL_VAL     = 1.00   # pastel brightness (keep near 1.0)
ACHROMATIC_VAL = 0.82   # black/grey sources -> this grey level (lower = darker grey)

# Fallback tint-toward-white if PASTELISE is False (0.0 full .. 1.0 white)
TINT = 0.4

# Real surface transparency so lighting, annotations and services show through.
# This DOES render - but you must export via Revit's NATIVE PDF exporter. PDF24
# (a PostScript driver) flattens transparency and darkens it; native PDF keeps it.
TRANSPARENCY = 70

# Give spaces that are in NO Litecom filter a fallback colour so nothing is blank.
COLOUR_UNMATCHED = True
DEFAULT_RGB = (200, 200, 200)   # light grey

def tint_colour(col):
    if TINT <= 0.0:
        return Color(col.Red, col.Green, col.Blue)
    def mix(c):
        v = int(round(c * (1.0 - TINT) + 255.0 * TINT))
        return max(0, min(255, v))
    return Color(mix(col.Red), mix(col.Green), mix(col.Blue))

def _rgb_to_hsv(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    df = mx - mn
    if df == 0:
        h = 0.0
    elif mx == r:
        h = (60.0 * ((g - b) / df) + 360.0) % 360.0
    elif mx == g:
        h = (60.0 * ((b - r) / df) + 120.0) % 360.0
    else:
        h = (60.0 * ((r - g) / df) + 240.0) % 360.0
    s = 0.0 if mx == 0 else df / mx
    return h, s, mx

def _hsv_to_rgb(h, s, v):
    if s == 0:
        return v, v, v
    h = h / 60.0
    i = int(h) % 6
    f = h - int(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]

def pastelize(col):
    h, s, v = _rgb_to_hsv(col.Red / 255.0, col.Green / 255.0, col.Blue / 255.0)
    if s < 0.08:                      # achromatic (black/grey) -> light grey
        ns, nv = 0.0, ACHROMATIC_VAL
    else:
        ns, nv = PASTEL_SAT, PASTEL_VAL
    nr, ng, nb = _hsv_to_rgb(h, ns, nv)
    def c(x):
        y = int(round(x * 255))
        return 0 if y < 0 else (255 if y > 255 else y)
    return Color(c(nr), c(ng), c(nb))

def colour_transform(col):
    return pastelize(col) if PASTELISE else tint_colour(col)

# --- guards ------------------------------------------------------------
if isinstance(view, ViewSheet):
    forms.alert("Active view is a sheet. Open the RCP view itself and re-run.", exitscript=True)

# --- solid fill pattern (must be a DRAFTING solid fill for detail regions)
def find_solid_fill_id():
    drafting = None
    anysolid = None
    for fpe in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            fp = fpe.GetFillPattern()
            if fp.IsSolidFill:
                if anysolid is None:
                    anysolid = fpe.Id
                if fp.Target == FillPatternTarget.Drafting:
                    drafting = fpe.Id
                    break
        except:
            pass
    if drafting is not None:
        return drafting
    if anysolid is not None:
        return anysolid
    return ElementId.InvalidElementId

solid_id = find_solid_fill_id()

# --- base filled region type -------------------------------------------
base_frt = FilteredElementCollector(doc).OfClass(FilledRegionType).FirstElement()
if base_frt is None:
    forms.alert("No FilledRegionType exists in this project to base new types on.", exitscript=True)

# --- invisible line style ----------------------------------------------
def invisible_line_style_id():
    # primary: find the GraphicsStyle element named "Invisible lines"
    for gs in FilteredElementCollector(doc).OfClass(GraphicsStyle):
        try:
            if gs.Name == "Invisible lines":
                return gs.Id
        except:
            pass
    for gs in FilteredElementCollector(doc).OfClass(GraphicsStyle):
        try:
            if "Invisible" in gs.Name:
                return gs.Id
        except:
            pass
    # fallback: traverse the Lines category subcategories
    try:
        cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
        for sc in cat.SubCategories:
            try:
                if "Invisible" in sc.Name:
                    g = sc.GetGraphicsStyle(GraphicsStyleType.Projection)
                    if g:
                        return g.Id
            except:
                pass
    except:
        pass
    return ElementId.InvalidElementId

INVIS = invisible_line_style_id()

# --- collect the Litecom filters (selection sets or param filters) -----
def collect_litecom(v):
    """List of {name, col, ids, ef, type, count} for the Litecom filters in v."""
    out_list = []
    for fid in v.GetFilters():
        fel = doc.GetElement(fid)
        if not fel:
            continue
        nm = fel.Name
        if ("IsSpace" not in nm) and ("Litecom" not in nm):
            continue
        try:
            col = v.GetFilterOverrides(fid).SurfaceForegroundPatternColor
        except:
            col = None
        if not (col and col.IsValid):
            continue
        entry = {"name": nm, "col": col, "ids": None, "ef": None,
                 "type": fel.GetType().Name, "count": 0}
        if isinstance(fel, SelectionFilterElement):
            try:
                entry["ids"] = set(i.IntegerValue for i in fel.GetElementIds())
            except:
                entry["ids"] = set()
        else:
            try:
                entry["ef"] = fel.GetElementFilter()
            except:
                entry["ef"] = None
        out_list.append(entry)
    return out_list

def match_colour(space, litecom):
    for e in litecom:
        matched = False
        if e["ids"] is not None:
            if space.Id.IntegerValue in e["ids"]:
                matched = True
        elif e["ef"] is not None:
            try:
                matched = e["ef"].PassesFilter(space)
            except:
                try:
                    matched = e["ef"].PassesFilter(doc, space.Id)
                except:
                    matched = False
        if matched:
            e["count"] += 1
            return e["col"], e["name"]
    return None, None

def sp_label(sp):
    num, nm = "?", "?"
    try:
        num = sp.Number
    except:
        pass
    try:
        nm = sp.Name
    except:
        pass
    return "{0} {1}".format(num, nm)

# --- geometry helpers --------------------------------------------------
# Boundaries are tessellated to a clean, closed polygon (robust to arcs, tiny
# segments and messy loops) so FilledRegion.Create rarely fails.
MIN_SEG = 0.01   # ft (~3 mm): merge points closer than this (Revit short-curve limit)

def flat(p):
    return XYZ(p.X, p.Y, 0.0)

def loop_to_points(seglist):
    pts = []
    for seg in seglist:
        try:
            c = seg.GetCurve()
        except:
            continue
        try:
            tess = list(c.Tessellate())
        except:
            try:
                tess = [c.GetEndPoint(0), c.GetEndPoint(1)]
            except:
                tess = []
        for p in tess:
            fp = flat(p)
            if not pts or pts[-1].DistanceTo(fp) > 1e-7:
                pts.append(fp)
    return pts

def clean_close(pts):
    # merge points closer than MIN_SEG; keep the loop open (no dup end point)
    out = []
    for p in pts:
        if not out or out[-1].DistanceTo(p) >= MIN_SEG:
            out.append(p)
    while len(out) >= 2 and out[0].DistanceTo(out[-1]) < MIN_SEG:
        out.pop()
    return out

def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        a += p1.X * p2.Y - p2.X * p1.Y
    return abs(a) / 2.0

def loop_stats(pl):
    if not pl:
        return "empty"
    xs = [p.X for p in pl]
    ys = [p.Y for p in pl]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    return "pts={0} area={1:.2f}ft2 bbox={2:.2f}x{3:.2f}ft".format(
        len(pl), poly_area(pl), w, h)

def points_to_curveloop(pts):
    if len(pts) < 3:
        return None
    cl = CurveLoop()
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        cl.Append(Line.CreateBound(a, b))
    return cl

def space_loops(space):
    """Return list of cleaned point-lists, outer boundary first."""
    try:
        loops = space.GetBoundarySegments(opt)
    except:
        return []
    result = []
    if loops:
        for seglist in loops:
            p = clean_close(loop_to_points(seglist))
            if len(p) >= 3:
                result.append(p)
    result.sort(key=poly_area, reverse=True)
    return result

# --- filled region type cache (per RGB) --------------------------------
type_cache = {}
def get_type_id(col):
    tc = colour_transform(col)
    key = (int(tc.Red), int(tc.Green), int(tc.Blue))
    if key in type_cache:
        return type_cache[key]
    name = "PD_RCP_{0}-{1}-{2}".format(key[0], key[1], key[2])
    found = None
    for t in FilteredElementCollector(doc).OfClass(FilledRegionType):
        if Element.Name.GetValue(t) == name:
            found = t
            break
    if found is None:
        found = doc.GetElement(base_frt.Duplicate(name))
    # (re)assert graphics on every run so existing/broken types get repaired.
    # Order matters: pattern MUST be set before the colour will take.
    try:
        found.IsMasking = False
    except:
        pass
    if solid_id != ElementId.InvalidElementId:
        try:
            found.ForegroundPatternId = solid_id
        except:
            pass
    try:
        found.ForegroundPatternColor = tc
    except:
        pass
    try:
        found.BackgroundPatternId = ElementId.InvalidElementId
    except:
        pass
    type_cache[key] = found.Id
    return found.Id

# --- per-region / per-view processing ----------------------------------
opt = SpatialElementBoundaryOptions()
DEFAULT_COL = Color(DEFAULT_RGB[0], DEFAULT_RGB[1], DEFAULT_RGB[2])

def make_region(v, col, profile):
    region = FilledRegion.Create(doc, get_type_id(col), v.Id, profile)
    p = region.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p and not p.IsReadOnly:
        p.Set(TAG)
    if INVIS != ElementId.InvalidElementId:
        try:
            region.SetLineStyleId(INVIS)
        except:
            pass
    try:
        ov = OverrideGraphicSettings()
        ov.SetSurfaceTransparency(int(TRANSPARENCY))
        v.SetElementOverrides(region.Id, ov)
    except:
        pass
    return region

def build_regions(v, col, loops_pts):
    """Return list of created region ids. Tries full profile, then outer-only,
    then one region per loop (handles disjoint islands / bad holes)."""
    try:
        prof = List[CurveLoop]()
        for pl in loops_pts:
            cl = points_to_curveloop(pl)
            if cl is not None:
                prof.Add(cl)
        if prof.Count > 0:
            return [make_region(v, col, prof).Id]
    except:
        pass
    try:
        only = List[CurveLoop]()
        only.Add(points_to_curveloop(loops_pts[0]))
        return [make_region(v, col, only).Id]
    except:
        pass
    ids = []
    for pl in loops_pts:
        try:
            one = List[CurveLoop]()
            one.Add(points_to_curveloop(pl))
            ids.append(make_region(v, col, one).Id)
        except:
            pass
    return ids

def wipe_previous(v):
    old = []
    for fr in FilteredElementCollector(doc, v.Id).OfClass(FilledRegion):
        p = fr.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and p.AsString() == TAG:
            old.append(fr.Id)
    for oid in old:
        try:
            doc.Delete(oid)
        except:
            pass

def process_view(v):
    """Colour one view. Returns a stats dict."""
    litecom = collect_litecom(v)
    spaces = FilteredElementCollector(doc, v.Id)\
        .OfCategory(BuiltInCategory.OST_MEPSpaces)\
        .WhereElementIsNotElementType().ToElements()
    st = {"view": v.Name, "spaces": len(spaces), "created": 0,
          "default": 0, "nogeo": 0, "errors": 0, "error_labels": [],
          "no_filters": (len(litecom) == 0)}

    wipe_previous(v)
    if not litecom:
        return st

    for sp_el in spaces:
        try:
            if sp_el.Area <= 0:
                st["nogeo"] += 1
                continue
        except:
            pass
        col, fname = match_colour(sp_el, litecom)
        if col is None:
            if COLOUR_UNMATCHED:
                col = DEFAULT_COL
                st["default"] += 1
            else:
                continue
        loops_pts = space_loops(sp_el)
        if not loops_pts:
            st["nogeo"] += 1
            continue
        ids = build_regions(v, col, loops_pts)
        if not ids:
            st["errors"] += 1
            st["error_labels"].append("{0} [{1}]".format(sp_label(sp_el), v.Name))
            continue
        st["created"] += len(ids)
    return st

# --- pick target views -------------------------------------------------
def rcp_views_on_template(tid):
    res = []
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.IsTemplate:
                continue
            if v.ViewType != ViewType.CeilingPlan:
                continue
            if v.ViewTemplateId == tid:
                res.append(v)
        except:
            pass
    return res

tid = view.ViewTemplateId
same_tpl = []
if tid and tid.IntegerValue != -1:
    same_tpl = rcp_views_on_template(tid)

targets = [view]
if len(same_tpl) > 1:
    opt_active = "Active view only"
    opt_all = "All {0} RCP views on this template".format(len(same_tpl))
    choice = forms.alert("Colour which views?",
                         title="Colour RCP Spaces",
                         options=[opt_active, opt_all])
    if choice is None:
        script.exit()
    if choice == opt_all:
        targets = same_tpl

# --- run over targets in one transaction -------------------------------
all_stats = []
last_created = []
t = Transaction(doc, "PD Colour RCP Spaces")
t.Start()
for v in targets:
    st = process_view(v)
    all_stats.append(st)
t.Commit()

# --- report ------------------------------------------------------------
tot_c = sum(s["created"] for s in all_stats)
tot_d = sum(s["default"] for s in all_stats)
tot_e = sum(s["errors"] for s in all_stats)
tot_g = sum(s["nogeo"] for s in all_stats)

out.print_md("### Colour RCP Spaces - done ({0} view(s))".format(len(all_stats)))
out.print_md("- Total Filled Regions created: **{0}**".format(tot_c))
out.print_md("- Colour types used: **{0}**".format(len(type_cache)))
out.print_md("- Transparency: **{0}%**  |  Pastelise: **{1}** (sat {2})".format(
    TRANSPARENCY, PASTELISE, PASTEL_SAT))
out.print_md("- Default grey (no Litecom group): {0}".format(tot_d))
out.print_md("- Skipped (no boundary): {0}   Errors: {1}".format(tot_g, tot_e))
out.print_md("---")
out.print_md("**Per view:**")
for s in all_stats:
    note = " (NO Litecom filters in this view)" if s["no_filters"] else ""
    out.print_md("- {0}: {1} created, {2} default, {3} nogeo, {4} err{5}".format(
        s["view"], s["created"], s["default"], s["nogeo"], s["errors"], note))
errs = [lbl for s in all_stats for lbl in s["error_labels"]]
if errs:
    out.print_md("---")
    out.print_md("**Region build FAILED ({0}):** {1}".format(len(errs), ", ".join(errs[:80])))
out.print_md("---")
out.print_md("**Export via Revit NATIVE PDF** (File > Export > PDF) so the 70% "
             "transparency renders. PDF24 / PostScript drivers flatten it and darken it.")
