# -*- coding: utf-8 -*-
__title__   = "FreeForm 2\nNative"
__doc__     = """Version = 1.0
Date    = 2026-07-19
________________________________________________________________
Description:

Convert Free Form Elements in the Family Editor to native
Extrusions (a real "Revit object" family).

For each Free Form solid the tool finds the best planar base
face (largest area, tried in descending order), takes its exact
edge profile (lines and arcs preserved) and extrudes it through
the full depth of the solid. Material and subcategory are
carried over. The original Free Form is deleted only when its
replacement was created successfully.

This is a silhouette-level conversion: sculpted faces, fillets
and surface detail are flattened. The report shows the volume
of the native solid against the original so you can judge the
fidelity per element.

________________________________________________________________
How-To:

1. Open the family in the Family Editor
2. Select the Free Form element(s) - or select nothing to
   convert every Free Form in the family
3. Run the tool and pick "Outer silhouette" (solid body) or
   "Keep holes" (inner loops become through-holes)
4. Review the report, then save the family if happy

________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

import math

from Autodesk.Revit.DB import (
    FreeFormElement,
    Options,
    ViewDetailLevel,
    Solid,
    PlanarFace,
    Plane,
    SketchPlane,
    CurveArray,
    CurveArrArray,
    Transaction,
    FilteredElementCollector,
    BuiltInParameter,
    ElementId,
    XYZ
)

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

MM = 304.8  # ft -> mm
CM3 = 28316.8  # ft3 -> cm3

if not doc.IsFamilyDocument:
    forms.alert("This tool only works in the Family Editor.",
                exitscript=True)

# ---------------------------------------------------------------
# Collect targets: selection first, else every FreeForm in the doc
# ---------------------------------------------------------------
selected = [doc.GetElement(eid)
            for eid in uidoc.Selection.GetElementIds()]
targets = [el for el in selected if isinstance(el, FreeFormElement)]

if not targets:
    all_ff = list(FilteredElementCollector(doc)
                  .OfClass(FreeFormElement)
                  .ToElements())
    if not all_ff:
        forms.alert("No Free Form Elements in this family.",
                    exitscript=True)
    if not forms.alert(
            "Nothing selected.\n\nConvert ALL {} Free Form "
            "element(s) in the family?".format(len(all_ff)),
            yes=True, no=True):
        script.exit()
    targets = all_ff

mode = forms.CommandSwitchWindow.show(
    ["Outer silhouette (solid body)", "Keep holes"],
    message="Profile mode for the base face:")
if not mode:
    script.exit()
keep_holes = mode.startswith("Keep")


# ---------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------
def get_solids(element):
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    solids = []
    geom = element.get_Geometry(opt)
    if geom:
        for g in geom:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                solids.append(g)
    return solids


def solid_points(solid):
    """Tessellated vertices of every edge of the solid."""
    pts = []
    for edge in solid.Edges:
        try:
            for p in edge.Tessellate():
                pts.append(p)
        except Exception:
            pass
    return pts


def loop_extent(loop):
    """3D bounding-box diagonal of a curve loop (outer-loop test)."""
    mn = [1e12, 1e12, 1e12]
    mx = [-1e12, -1e12, -1e12]
    for c in loop:
        for p in c.Tessellate():
            vals = (p.X, p.Y, p.Z)
            for i in range(3):
                if vals[i] < mn[i]:
                    mn[i] = vals[i]
                if vals[i] > mx[i]:
                    mx[i] = vals[i]
    dx, dy, dz = mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def try_extrude(solid, face, points):
    """Extrude the face profile through the solid depth.
    Returns the new Extrusion or None."""
    n = face.FaceNormal
    origin = face.Origin
    base = origin.DotProduct(n)
    # Solid material lies on the -n side of an outward face
    min_proj = min(p.DotProduct(n) for p in points)
    max_proj = max(p.DotProduct(n) for p in points)
    depth = base - min_proj
    if depth < 0.1 / MM:
        # face is on the far side; extrude the other way
        depth = max_proj - base
        if depth < 0.1 / MM:
            return None
        direction = n
    else:
        direction = n.Negate()

    loops = list(face.GetEdgesAsCurveLoops())
    if not loops:
        return None
    if not keep_holes and len(loops) > 1:
        loops.sort(key=loop_extent, reverse=True)
        loops = [loops[0]]

    profile = CurveArrArray()
    for loop in loops:
        ca = CurveArray()
        for c in loop:
            ca.Append(c)
        profile.Append(ca)

    plane = Plane.CreateByNormalAndOrigin(direction, origin)
    sp = SketchPlane.Create(doc, plane)
    return doc.FamilyCreate.NewExtrusion(True, profile, sp, depth)


def convert_solid(solid):
    """Try planar faces largest-first; return (extrusion, face_note)."""
    faces = [f for f in solid.Faces if isinstance(f, PlanarFace)]
    faces.sort(key=lambda f: f.Area, reverse=True)
    points = solid_points(solid)
    for face in faces[:6]:
        try:
            ext = try_extrude(solid, face, points)
            if ext:
                return ext, face
        except Exception:
            # unsupported curve types on this face - try the next
            continue
    return None, None


def copy_appearance(src, dst):
    try:
        mp = src.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
        if mp and mp.AsElementId() != ElementId.InvalidElementId:
            dp = dst.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
            if dp and not dp.IsReadOnly:
                dp.Set(mp.AsElementId())
    except Exception:
        pass
    try:
        if src.Subcategory:
            dst.Subcategory = src.Subcategory
    except Exception:
        pass


# ---------------------------------------------------------------
# Convert
# ---------------------------------------------------------------
converted = 0
skipped = 0

t = Transaction(doc, "FreeForm to Native")
t.Start()
try:
    for ffe in targets:
        out.print_md("### Free Form Id {}".format(ffe.Id.IntegerValue))
        solids = get_solids(ffe)
        if not solids:
            out.print_md("* No solids - skipped")
            skipped += 1
            continue

        made = []
        for solid in solids:
            ext, face = convert_solid(solid)
            if not ext:
                continue
            copy_appearance(ffe, ext)
            doc.Regenerate()
            new_vol = 0
            for g in get_solids(ext):
                new_vol += g.Volume
            made.append(ext)
            out.print_md(
                "* Extrusion `{}`: {:.1f} cm3 native vs "
                "{:.1f} cm3 original ({:.0f}% volume)".format(
                    ext.Id.IntegerValue,
                    new_vol * CM3, solid.Volume * CM3,
                    100.0 * new_vol / solid.Volume
                    if solid.Volume > 0 else 0))

        if len(made) == len(solids):
            doc.Delete(ffe.Id)
            out.print_md("* Original Free Form deleted")
            converted += 1
        elif made:
            out.print_md(
                "* PARTIAL: {}/{} solids converted - original "
                "KEPT, delete manually after review".format(
                    len(made), len(solids)))
            skipped += 1
        else:
            out.print_md("* Could not convert - original kept")
            skipped += 1

    t.Commit()
except Exception as ex:
    try:
        t.RollBack()
    except Exception:
        pass
    forms.alert("Error:\n{}".format(str(ex)), exitscript=True)

forms.alert(
    "Done.\n\nConverted: {}\nKept as Free Form: {}\n\n"
    "Volume percentages are in the report window.\n"
    "Nothing is saved - review, then save the family.".format(
        converted, skipped))
