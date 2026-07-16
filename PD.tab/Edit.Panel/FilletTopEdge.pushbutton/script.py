# -*- coding: utf-8 -*-
__title__   = "Fillet\nTop Edge"
__doc__     = """Version = 1.0
Date    = 2026-07-10
________________________________________________________________
Description:

Rounds (fillets) the top edge of a solid extrusion in the
Family Editor WITHOUT using a void cut.

Revit's solid kernel cannot reliably cut a true fillet:
a fillet is tangent to both faces it rounds, and tangent
(grazing) boolean contact is exactly what makes Revit throw
"Can't keep elements joined". This tool builds the same shape
additively from 3 solids instead, which always regenerates:

  1. the original extrusion, shrunk down by the fillet radius
  2. an inset extrusion (outline offset inward by the radius)
     at full height
  3. a solid quarter-round sweep along the top edge

________________________________________________________________
How-To:

1. Open a Family document in Revit
2. Select ONE solid extrusion (flat plate style, horizontal
   sketch plane)
3. Run this tool and enter the fillet radius in mm
4. The three solids replace the sharp-edged single extrusion

Rules the tool enforces / you should know:
- radius must be SMALLER than the smallest corner arc of the
  sketch (r < R), or the sweep self-intersects at corners
- works best when plan corners are already filleted arcs;
  sharp corners are attempted with a mitre
- the outline must be a single closed loop (no holes)

________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import math
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Extrusion, Options, ViewDetailLevel, Solid, XYZ, Line, Arc,
    Curve, CurveLoop, SketchPlane, Plane, Transaction,
    BuiltInParameter, ProfilePlaneLocation, Transform, ElementId,
    IFailuresPreprocessor, FailureProcessingResult, FailureSeverity,
)
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

from pyrevit import revit, forms, script

doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

MM = 1.0 / 304.8
TOL = 1e-6


# ------------------------------------------------------------------
# failure preprocessor: auto-resolves "Can't keep elements joined"
# (= failed boolean on tangent contact) by taking the default
# resolution (Unjoin Elements) and swallowing warnings
# ------------------------------------------------------------------
class SilentResolve(IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        resolved = False
        for f in fa.GetFailureMessages():
            try:
                if f.GetSeverity() == FailureSeverity.Warning:
                    fa.DeleteWarning(f)
                elif f.HasResolutions():
                    fa.ResolveFailure(f)
                    resolved = True
            except Exception:
                pass
        if resolved:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def set_silent(t):
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SilentResolve())
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def chain_curves(curves):
    """Order sketch curves into one contiguous loop (reversing where
    needed). Returns ordered list or None if it cannot chain."""
    remaining = list(curves)
    ordered = [remaining.pop(0)]
    while remaining:
        tail = ordered[-1].GetEndPoint(1)
        found = None
        for c in remaining:
            if c.GetEndPoint(0).DistanceTo(tail) < TOL:
                found = (c, c)
                break
            if c.GetEndPoint(1).DistanceTo(tail) < TOL:
                found = (c, c.CreateReversed())
                break
        if found is None:
            return None
        remaining.remove(found[0])
        ordered.append(found[1])
    # closed?
    if ordered[-1].GetEndPoint(1).DistanceTo(
            ordered[0].GetEndPoint(0)) > TOL:
        return None
    return ordered


def loop_length(loop):
    total = 0.0
    for c in loop:
        total += c.Length
    return total


def world_bbox(curves):
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    for c in curves:
        for p in c.Tessellate():
            v = (p.X, p.Y, p.Z)
            for i in range(3):
                if v[i] < lo[i]:
                    lo[i] = v[i]
                if v[i] > hi[i]:
                    hi[i] = v[i]
    return lo, hi


def wedge_profile(app, r, sx, sy):
    """Quarter-round wedge profile around local origin. sx/sy flip
    the local axes so orientation self-check can retry."""
    A   = XYZ(-r * sx, 0, 0)
    B   = XYZ(0, -r * sy, 0)
    ctr = XYZ(-r * sx, -r * sy, 0)
    mid = ctr + XYZ(sx / math.sqrt(2.0), sy / math.sqrt(2.0), 0) * r
    ca = app.NewCurveArray()
    ca.Append(Arc.Create(A, B, mid))
    ca.Append(Line.CreateBound(B, ctr))
    ca.Append(Line.CreateBound(ctr, A))
    caa = app.NewCurveArrArray()
    caa.Append(ca)
    return app.NewCurveLoopsProfile(caa)


# ------------------------------------------------------------------
# 0. checks and inputs
# ------------------------------------------------------------------
if not doc.IsFamilyDocument:
    forms.alert("This tool only works in the Family Editor.",
                exitscript=True)

selected = [doc.GetElement(eid)
            for eid in uidoc.Selection.GetElementIds()]
extrusions = [e for e in selected
              if isinstance(e, Extrusion) and e.IsSolid]

if not extrusions:
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, "Pick a solid extrusion to fillet")
        e = doc.GetElement(ref)
        if isinstance(e, Extrusion) and e.IsSolid:
            extrusions = [e]
    except Exception:
        pass

if len(extrusions) != 1:
    forms.alert("Select exactly ONE solid extrusion first.",
                exitscript=True)

ext = extrusions[0]

r_str = forms.ask_for_string(
    default="2",
    prompt="Fillet radius in mm (must be smaller than the smallest "
           "corner arc of the sketch):",
    title="Fillet Top Edge")
if not r_str:
    script.exit()
try:
    r_mm = float(r_str)
except Exception:
    forms.alert("'{}' is not a number.".format(r_str), exitscript=True)
if r_mm <= 0:
    forms.alert("Radius must be positive.", exitscript=True)
r = r_mm * MM

# ------------------------------------------------------------------
# 1. read the extrusion
# ------------------------------------------------------------------
sketch = ext.Sketch
plane  = sketch.SketchPlane.GetPlane()
n      = plane.Normal
z0     = ext.StartOffset
z1     = ext.EndOffset
if z1 < z0:
    z0, z1 = z1, z0
height = z1 - z0

if height <= r:
    forms.alert("Extrusion is only {:.1f} mm thick; the {} mm fillet "
                "does not fit.".format(height * 304.8, r_mm),
                exitscript=True)

if abs(abs(n.Z) - 1.0) > 0.01:
    if not forms.alert(
            "The sketch plane is not horizontal. This tool is tested "
            "on flat plates (horizontal sketch). Continue anyway?",
            yes=True, no=True):
        script.exit()

loops_raw = []
for ca in sketch.Profile:
    loops_raw.append([c for c in ca])
if len(loops_raw) != 1:
    forms.alert("The sketch has {} loops. Only single-loop outlines "
                "(no holes) are supported.".format(len(loops_raw)),
                exitscript=True)

outline = chain_curves(loops_raw[0])
if outline is None:
    forms.alert("Could not chain the sketch curves into one closed "
                "loop.", exitscript=True)

# rule: r < smallest corner arc radius
min_arc = None
for c in outline:
    if isinstance(c, Arc):
        if min_arc is None or c.Radius < min_arc:
            min_arc = c.Radius
if min_arc is not None and r >= min_arc - TOL:
    forms.alert(
        "Fillet radius {} mm must be SMALLER than the smallest plan "
        "corner arc ({:.2f} mm).\n\nAt r = R the swept fillet's inner "
        "radius hits zero at the corners and the sweep self-"
        "intersects. Reduce the radius or enlarge the plan "
        "corners.".format(r_mm, min_arc * 304.8),
        exitscript=True)

app = doc.Application.Create
lo_out, hi_out = world_bbox(outline)

# ------------------------------------------------------------------
# 2. build
# ------------------------------------------------------------------
t = Transaction(doc, "PD Fillet Top Edge")
set_silent(t)
t.Start()
try:
    # -- 2a. shrink the source extrusion by r at the top
    if ext.EndOffset >= ext.StartOffset:
        ext.EndOffset = ext.EndOffset - r
    else:
        ext.StartOffset = ext.StartOffset - r

    # -- 2b. inset extrusion at full height
    base_loop = CurveLoop.Create(List[Curve](outline))
    inset = CurveLoop.CreateViaOffset(base_loop, -r, n)
    if loop_length(inset) > loop_length(base_loop):
        inset = CurveLoop.CreateViaOffset(base_loop, r, n)
    inset_arr = app.NewCurveArray()
    for c in inset:
        inset_arr.Append(c)
    inset_loops = app.NewCurveArrArray()
    inset_loops.Append(inset_arr)
    sk_in = SketchPlane.Create(doc, plane)
    inset_ext = doc.FamilyCreate.NewExtrusion(
        True, inset_loops, sk_in, z1)
    inset_ext.StartOffset = z0
    inset_ext.EndOffset   = z1

    # -- 2c. quarter-round wedge sweep along the top edge
    lift = Transform.CreateTranslation(n * z1)
    path = app.NewCurveArray()
    for c in outline:
        path.Append(c.CreateTransformed(lift))
    sp = outline[0].CreateTransformed(lift).GetEndPoint(0)
    sk_path = SketchPlane.Create(
        doc, Plane.CreateByNormalAndOrigin(n, sp))

    wedge = None
    top_lvl = None
    for p in [c.CreateTransformed(lift) for c in outline]:
        for q in p.Tessellate():
            d = q.X * n.X + q.Y * n.Y + q.Z * n.Z
            if top_lvl is None or d > top_lvl:
                top_lvl = d

    for sx, sy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
        prof = wedge_profile(app, r, sx, sy)
        try:
            w = doc.FamilyCreate.NewSweep(
                True, path, sk_path, prof, 0,
                ProfilePlaneLocation.Start)
            doc.Regenerate()
        except Exception:
            continue
        # orientation self-check: wedge must sit below the top plane
        # and inside the outline bbox (never outside/above it)
        bb = w.get_BoundingBox(None)
        d_max = (bb.Max.X * n.X + bb.Max.Y * n.Y + bb.Max.Z * n.Z)
        ok_v = d_max <= top_lvl + 0.1 * MM
        ok_h = (bb.Min.X >= lo_out[0] - 0.1 * MM and
                bb.Max.X <= hi_out[0] + 0.1 * MM and
                bb.Min.Y >= lo_out[1] - 0.1 * MM and
                bb.Max.Y <= hi_out[1] + 0.1 * MM)
        if ok_v and ok_h:
            wedge = w
            break
        doc.Delete(w.Id)

    if wedge is None:
        raise Exception(
            "Could not create the fillet sweep. If the plan corners "
            "are sharp, add small corner arcs (radius > fillet "
            "radius) to the sketch first.")

    # -- 2d. copy material + subcategory from the source
    mat = ext.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
    for new_el in (inset_ext, wedge):
        if mat is not None and \
                mat.AsElementId() != ElementId.InvalidElementId:
            p = new_el.get_Parameter(
                BuiltInParameter.MATERIAL_ID_PARAM)
            if p is not None and not p.IsReadOnly:
                p.Set(mat.AsElementId())
        try:
            if ext.Subcategory is not None:
                new_el.Subcategory = ext.Subcategory
        except Exception:
            pass

    doc.Regenerate()
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert("Fillet failed, nothing changed:\n\n{}".format(ex),
                exitscript=True)

out.print_md("**Fillet Top Edge - done**")
out.print_md(
    "- source extrusion shrunk by {} mm\n"
    "- inset extrusion created (outline offset {} mm inward)\n"
    "- quarter-round sweep created along the top edge\n\n"
    "The three solids read as one filleted plate. To resize the "
    "plate later, edit all three sketches together.\n\n"
    "*Why not a void? A true fillet is tangent to both faces and "
    "Revit's kernel fails tangent boolean cuts with \"Can't keep "
    "elements joined\". Chamfers cut fine; fillets are built "
    "additively.*".format(r_mm, r_mm))
