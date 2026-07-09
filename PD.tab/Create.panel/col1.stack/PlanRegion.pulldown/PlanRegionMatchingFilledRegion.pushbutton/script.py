# -*- coding: utf-8 -*-
__title__   = "Plan Region: Boundary from Filled Region"
__doc__     = """Version = 1.0
Date    = 20.12.2025
________________________________________________________________
Description:

This script is pointles it does not work as wanted - left it here as a placeholder to be replaced in the future 

Relative Path:
...\
________________________________________________________________
How-To:

1) Run in a PLAN view (Floor Plan / Structural Plan / etc.)
2) Select 1 filled region
3) Tool draws detail lines along the outer boundary (and groups them)
4) Plan Region command starts -> use "Pick Lines" and select the new boundary -> Finish
5) Set the Plan Region's View Range in properties to hide whatever you want.

________________________________________________________________
Get Free:
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

import math

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import RevitCommandId, PostableCommand
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List

from pyrevit import revit, forms, script

doc   = revit.doc
uidoc = revit.uidoc

# Robust UIApplication getter (works across pyRevit versions)
try:
    uiapp = getattr(revit, 'uiapp', None)
except:
    uiapp = None
if uiapp is None:
    try:
        uiapp = uidoc.Application
    except:
        uiapp = None
if uiapp is None:
    try:
        uiapp = __revit__  # pyRevit provides this in most environments
    except:
        uiapp = None


# ------------------------------------------------------------
# Selection filter
class _FilledRegionFilter(ISelectionFilter):
    def AllowElement(self, e):
        try:
            return isinstance(e, FilledRegion)
        except:
            return False

    def AllowReference(self, ref, pt):
        return True


# ------------------------------------------------------------
# Boundary extraction
def _get_boundaries_curveloops(fr):
    """Return python list of CurveLoop objects (outer/inner loops)."""
    loops = []

    # Modern API
    try:
        b = fr.GetBoundaries()  # IList[CurveLoop]
        if b:
            for cl in b:
                loops.append(cl)
            if loops:
                return loops
    except:
        pass

    # Fallback: BoundarySegments
    try:
        segs_per_loop = fr.GetBoundarySegments()
        if segs_per_loop:
            for segs in segs_per_loop:
                cl = CurveLoop()
                for bs in segs:
                    try:
                        c = bs.Curve
                        if c:
                            cl.Append(c)
                    except:
                        pass
                try:
                    if cl and cl.Count > 0:
                        loops.append(cl)
                except:
                    pass
    except:
        pass

    return loops


def _curve_loop_area_in_view(loop, view):
    """Approx area using tessellated points projected to view plane."""
    # model -> viewlocal transform (u=Right, v=Up)
    v2m = Transform.Identity
    v2m.Origin = view.Origin
    v2m.BasisX = view.RightDirection
    v2m.BasisY = view.UpDirection
    v2m.BasisZ = view.ViewDirection
    m2v = v2m.Inverse

    pts2d = []
    for c in loop:
        try:
            pts = c.Tessellate()
        except:
            pts = None
        if not pts:
            continue
        for p in pts:
            pv = m2v.OfPoint(p)
            pts2d.append((pv.X, pv.Y))

    if len(pts2d) < 3:
        return 0.0

    # simple shoelace
    area = 0.0
    for i in range(len(pts2d)):
        x1, y1 = pts2d[i]
        x2, y2 = pts2d[(i + 1) % len(pts2d)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) * 0.5


def _pick_outer_loop(loops, view):
    """Pick largest loop as outer boundary."""
    best = None
    best_a = -1.0
    for cl in loops:
        a = _curve_loop_area_in_view(cl, view)
        if a > best_a:
            best_a = a
            best = cl
    return best


# ------------------------------------------------------------
# Create detail curves along loop
def _draw_detail_boundary(view, loop):
    new_ids = []

    # CurveLoop is iterable in IronPython on most builds
    try:
        curves = [c for c in loop]
    except:
        curves = []
        try:
            it = loop.GetEnumerator()
            while it.MoveNext():
                curves.append(it.Current)
        except:
            pass

    for c in curves:
        # Try direct curve
        try:
            dc = doc.Create.NewDetailCurve(view, c)
            if dc:
                new_ids.append(dc.Id)
                continue
        except:
            pass

        # Fallback: tessellate to lines
        try:
            pts = c.Tessellate()
            if pts and len(pts) >= 2:
                for i in range(len(pts) - 1):
                    ln = Line.CreateBound(pts[i], pts[i + 1])
                    dc2 = doc.Create.NewDetailCurve(view, ln)
                    if dc2:
                        new_ids.append(dc2.Id)
        except:
            pass

    return new_ids


def _group_elements(ids, name):
    """Optional: group for easy selection."""
    if not ids:
        return None
    try:
        idlist = List[ElementId]()
        for eid in ids:
            idlist.Add(eid)
        g = doc.Create.NewGroup(idlist)
        if g:
            try:
                g.GroupType.Name = name
            except:
                pass
        return g
    except:
        return None


def _start_plan_region_command():
    """Starts the native Plan Region command."""
    if uiapp is None:
        return False
    try:
        cmd_id = RevitCommandId.LookupPostableCommandId(PostableCommand.PlanRegion)
        if cmd_id:
            uiapp.PostCommand(cmd_id)
            return True
    except:
        pass
    return False


# ------------------------------------------------------------
# Main
view = uidoc.ActiveView
if not isinstance(view, ViewPlan):
    forms.alert("Open a PLAN view (Floor Plan / Structural Plan) and run again.", exitscript=True)

# Pick ONE filled region
try:
    ref = uidoc.Selection.PickObject(
        ObjectType.Element,
        _FilledRegionFilter(),
        "Select ONE Filled Region to generate a Plan Region boundary from"
    )
except:
    forms.alert("Selection cancelled.", exitscript=True)

fr = doc.GetElement(ref.ElementId)
if not fr:
    forms.alert("Could not read selected Filled Region.", exitscript=True)

loops = _get_boundaries_curveloops(fr)
if not loops:
    forms.alert("Couldn't extract Filled Region boundaries.", exitscript=True)

outer = _pick_outer_loop(loops, view)
if not outer:
    forms.alert("Couldn't determine an outer boundary loop.", exitscript=True)

t = Transaction(doc, "Plan Region Boundary from Filled Region")
t.Start()
new_ids = []
grp = None
try:
    new_ids = _draw_detail_boundary(view, outer)
    if not new_ids:
        raise Exception("No detail curves were created from the boundary.")

    grp_name = "PlanRegionBoundary_from_FR_{}".format(fr.Id.IntegerValue)
    grp = _group_elements(new_ids, grp_name)

    t.Commit()
except Exception as ex:
    try:
        t.RollBack()
    except:
        pass
    forms.alert("Failed:\n{}".format(ex), exitscript=True)

# Select created lines for convenience
try:
    idlist = List[ElementId]()
    for eid in new_ids:
        idlist.Add(eid)
    uidoc.Selection.SetElementIds(idlist)
except:
    pass

started = _start_plan_region_command()

msg = []
msg.append("Boundary created as Detail Lines{}.".format(" (grouped)" if grp else ""))
msg.append("Next: In Plan Region, use 'Pick Lines' and select the new boundary, then Finish.")
msg.append("Then set the Plan Region View Range in Properties to hide items (push above/below).")
if not started:
    msg.append("")
    msg.append("Note: Could not auto-start Plan Region command here. Start it manually: View > Plan Views > Plan Region.")

forms.alert("\n".join(msg))
