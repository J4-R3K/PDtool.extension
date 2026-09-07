# -*- coding: utf-8 -*-
__title__   = "Scope Box\nfrom Section"
__doc__     = """Version = 1.0
Date    = 2026-08-07
________________________________________________________________
Description:

Creates a scope box matching the section box of a 3D view.

The Revit API cannot create or resize scope boxes (confirmed up
to Revit 2026 - only copy / move / rotate / rename are exposed).
This tool therefore automates everything EXCEPT the one two-click
draw that only the native Scope Box command can do:

PHASE 1 (first click, run from a 3D view with a section box):
1) Reads the section box extents, rotation and Z range
2) Asks for the target floor plan and the scope box name
3) Draws guide detail lines marking the EXACT rectangle
4) Switches to the plan, zooms to the rectangle
5) Posts the native Scope Box command
   -> set Height in the options bar to the value shown,
      then click the two marked opposite corners (snap!)

PHASE 2 (second click, after the box is drawn):
6) Finds the new scope box, renames it, rotates it to match
   the section box rotation, moves it to the correct position
7) Verifies achieved extents against the target (mm report)
8) Deletes the guide lines and clears the pending state

Undo = two steps (the native draw + the finish transaction).
________________________________________________________________
How-To:

1. Open a 3D view with an active section box, run the tool
2. Pick target plan, confirm name, read the height value
3. In the plan: type the Height into the options bar, then
   click the two marked corners (endpoint snap)
4. Run the tool AGAIN to finish and get the verification report
________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import os
import json
import math

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    View3D,
    ViewPlan,
    ViewType,
    XYZ,
    Line,
    Element,
    ElementId,
    ElementTransformUtils,
    StorageType,
)
from Autodesk.Revit.UI import RevitCommandId

from pyrevit import revit, forms, script, HOST_APP

doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

FT_TO_MM = 304.8
SIZE_WARN_MM = 5.0        # click accuracy warning threshold
POS_TOL_FT = 0.003        # ~1 mm, skip micro-moves below this
STATE_FILE = script.get_document_data_file("sb2sb", "json")
SCOPEBOX_CMD = "ID_VOLUME_OF_INTEREST"


def get_name(el):
    """el.Name is broken in pyRevit IronPython - use the static getter."""
    try:
        return Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return "<unnamed>"


def mm(feet):
    return feet * FT_TO_MM


def collect_scopebox_ids():
    ids = []
    col = (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
           .WhereElementIsNotElementType())
    for el in col:
        ids.append(el.Id.IntegerValue)
    return ids


# -----------------------------------------------------------
# PHASE 1 - read section box, place guides, post the command
# -----------------------------------------------------------

def pick_source_3d_view():
    """Active 3D view with section box, else pick from a list."""
    av = doc.ActiveView
    if isinstance(av, View3D) and not av.IsTemplate and av.IsSectionBoxActive:
        return av

    candidates = {}
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if not v.IsTemplate and v.IsSectionBoxActive:
                candidates[get_name(v)] = v
        except Exception:
            pass

    if not candidates:
        forms.alert(
            "No 3D view with an active section box found.\n\n"
            "Turn on a section box in a 3D view first.",
            exitscript=True)

    choice = forms.SelectFromList.show(
        sorted(candidates.keys()),
        title="Source 3D view (section box)",
        button_name="Use this section box")
    if not choice:
        script.exit()
    return candidates[choice]


def analyse_section_box(view3d):
    """Return dict describing the section box in world coordinates."""
    bb = view3d.GetSectionBox()
    t = bb.Transform

    # world-space corners
    zs = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                zs.append(t.OfPoint(XYZ(x, y, z)).Z)

    centroid = t.OfPoint(XYZ((bb.Min.X + bb.Max.X) * 0.5,
                             (bb.Min.Y + bb.Max.Y) * 0.5,
                             (bb.Min.Z + bb.Max.Z) * 0.5))

    vertical = abs(t.BasisZ.Z) > 0.9999
    if vertical:
        theta = math.atan2(t.BasisX.Y, t.BasisX.X)
        w = bb.Max.X - bb.Min.X
        d = bb.Max.Y - bb.Min.Y
    else:
        # tilted box (should not happen from the UI) - fall back to
        # the world axis-aligned envelope, no rotation
        theta = 0.0
        xs_w, ys_w = [], []
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    p = t.OfPoint(XYZ(x, y, z))
                    xs_w.append(p.X)
                    ys_w.append(p.Y)
        w = max(xs_w) - min(xs_w)
        d = max(ys_w) - min(ys_w)

    return {
        "w": w, "d": d,
        "zmin": min(zs), "zmax": max(zs),
        "h": max(zs) - min(zs),
        "cx": centroid.X, "cy": centroid.Y,
        "theta": theta,
        "vertical": vertical,
        "src": get_name(view3d),
    }


def pick_target_plan(zmin):
    """Floor / engineering plans, nearest level below the box first."""
    plans = []
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            if v.ViewType not in (ViewType.FloorPlan, ViewType.EngineeringPlan):
                continue
            elev = None
            if v.GenLevel is not None:
                elev = v.GenLevel.Elevation
            plans.append((v, elev))
        except Exception:
            pass

    if not plans:
        forms.alert("No floor plans found in the model.", exitscript=True)

    def sort_key(item):
        v, elev = item
        if elev is None:
            return 1e9
        delta = zmin - elev
        # prefer levels at/below the box bottom, closest first
        return delta if delta >= 0 else (1e6 - delta)

    plans.sort(key=sort_key)

    labels = []
    lookup = {}
    for v, elev in plans:
        label = "{} ({})".format(
            get_name(v),
            "level {:.0f} mm".format(mm(elev)) if elev is not None else "no level")
        labels.append(label)
        lookup[label] = v

    choice = forms.SelectFromList.show(
        labels,
        title="Target plan view (scope box will be drawn here)",
        button_name="Use this plan")
    if not choice:
        script.exit()
    return lookup[choice]


def make_guides(plan, c1x, c1y, c2x, c2y):
    """Draw the guide rectangle as detail lines in the plan view.
    Detail curves must lie exactly on the view plane - try the
    plausible Z planes until one is accepted."""
    z_candidates = []
    try:
        z_candidates.append(plan.Origin.Z)
    except Exception:
        pass
    try:
        if plan.GenLevel is not None:
            z_candidates.append(plan.GenLevel.Elevation)
    except Exception:
        pass
    z_candidates.append(0.0)

    last_err = None
    for z in z_candidates:
        pts = [XYZ(c1x, c1y, z), XYZ(c2x, c1y, z),
               XYZ(c2x, c2y, z), XYZ(c1x, c2y, z)]
        try:
            ids = []
            for i in range(4):
                ln = Line.CreateBound(pts[i], pts[(i + 1) % 4])
                dc = doc.Create.NewDetailCurve(plan, ln)
                ids.append(dc.Id.IntegerValue)
            return ids
        except Exception as ex:
            last_err = ex
    raise Exception("Could not place guide lines in '{}': {}".format(
        get_name(plan), last_err))


def phase1():
    view3d = pick_source_3d_view()
    info = analyse_section_box(view3d)

    if not info["vertical"]:
        forms.alert(
            "The section box is tilted (not plumb). Scope boxes are "
            "always plumb, so the world axis-aligned envelope will be "
            "used instead (no rotation).")

    plan = pick_target_plan(info["zmin"])

    default_name = "PD_SB_{}".format(info["src"])
    name = forms.ask_for_string(
        default=default_name,
        prompt="Name for the new scope box:",
        title="Scope Box from Section Box")
    if not name:
        script.exit()

    # axis-aligned rectangle centred on the box centroid;
    # rotation (if any) is applied in phase 2
    c1x = info["cx"] - info["w"] * 0.5
    c1y = info["cy"] - info["d"] * 0.5
    c2x = info["cx"] + info["w"] * 0.5
    c2y = info["cy"] + info["d"] * 0.5

    before_ids = collect_scopebox_ids()

    with revit.Transaction("Scope Box guides"):
        guide_ids = make_guides(plan, c1x, c1y, c2x, c2y)

    state = {
        "name": name,
        "w": info["w"], "d": info["d"], "h": info["h"],
        "zmin": info["zmin"], "zmax": info["zmax"],
        "cx": info["cx"], "cy": info["cy"],
        "theta": info["theta"],
        "src": info["src"],
        "plan_id": plan.Id.IntegerValue,
        "guide_ids": guide_ids,
        "before_ids": before_ids,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    # switch to the plan and zoom to the rectangle
    try:
        uidoc.ActiveView = plan
        pad = max(info["w"], info["d"]) * 0.35
        for uiv in uidoc.GetOpenUIViews():
            if uiv.ViewId == plan.Id:
                uiv.ZoomAndCenterRectangle(
                    XYZ(c1x - pad, c1y - pad, 0),
                    XYZ(c2x + pad, c2y + pad, 0))
                break
    except Exception:
        pass

    forms.alert(
        "Guide rectangle placed in '{plan}'.\n\n"
        "The Scope Box command will start when you close this:\n\n"
        "1. OPTIONS BAR: set Height = {h:.0f} mm\n"
        "2. Click the two OPPOSITE corners of the guide rectangle\n"
        "    (endpoint snap - bottom-left, then top-right)\n"
        "3. Run this button AGAIN to finish\n"
        "    (rename, rotate, position, verify, clean up)".format(
            plan=get_name(plan), h=mm(info["h"])),
        title="Draw the scope box now")

    cid = RevitCommandId.LookupCommandId(SCOPEBOX_CMD)
    if cid is not None:
        HOST_APP.uiapp.PostCommand(cid)
    else:
        forms.alert(
            "Could not post the Scope Box command automatically.\n"
            "Start it manually: View tab > Create > Scope Box, "
            "then follow the steps above.")


# -----------------------------------------------------------
# PHASE 2 - find the drawn box, fix it up, verify, clean up
# -----------------------------------------------------------

def cleanup(state):
    with revit.Transaction("Scope Box guides cleanup"):
        for gid in state.get("guide_ids", []):
            try:
                doc.Delete(ElementId(gid))
            except Exception:
                pass
    try:
        os.remove(STATE_FILE)
    except Exception:
        pass


def try_set_height_param(el, h_ft):
    """Height is API-writable from Revit 2025 - attempt it, else False."""
    try:
        for p in el.Parameters:
            try:
                if (p.StorageType == StorageType.Double
                        and not p.IsReadOnly
                        and "height" in p.Definition.Name.lower()):
                    p.Set(h_ft)
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def phase2():
    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    before = set(state["before_ids"])
    new_ids = [i for i in collect_scopebox_ids() if i not in before]

    if not new_ids:
        choice = forms.alert(
            "No new scope box found yet.\n\n"
            "Pending: '{}' from section box of '{}'.".format(
                state["name"], state["src"]),
            options=["Keep waiting (draw it, then run again)",
                     "Cancel and remove the guide lines"])
        if choice and choice.startswith("Cancel"):
            cleanup(state)
            forms.alert("Cancelled. Guides removed.")
        return

    sb = doc.GetElement(ElementId(max(new_ids)))
    theta = state["theta"]
    report = []
    warnings = []

    with revit.Transaction("Scope Box from Section Box (finish)"):

        # 1) size check BEFORE rotation (box is still axis-aligned)
        bb = sb.get_BoundingBox(None)
        err_w = mm((bb.Max.X - bb.Min.X) - state["w"])
        err_d = mm((bb.Max.Y - bb.Min.Y) - state["d"])
        err_h = mm((bb.Max.Z - bb.Min.Z) - state["h"])
        if abs(err_w) > SIZE_WARN_MM or abs(err_d) > SIZE_WARN_MM:
            warnings.append(
                "Plan size is off by {:.0f} x {:.0f} mm - a corner click "
                "missed the guide. The API cannot resize scope boxes: "
                "delete it, undo, and re-run if this matters.".format(
                    err_w, err_d))
        if abs(err_h) > SIZE_WARN_MM:
            warnings.append(
                "Height is {:.0f} mm vs target {:.0f} mm (options-bar "
                "value). Adjust the Z grips in a section/elevation if "
                "needed.".format(mm(bb.Max.Z - bb.Min.Z), mm(state["h"])))
            if try_set_height_param(sb, state["h"]):
                warnings[-1] = ("Height corrected via parameter "
                                "(API-writable in this Revit version).")

        # 2) rename
        try:
            Element.Name.SetValue(sb, state["name"])
        except Exception:
            try:
                Element.Name.SetValue(sb, "{} ({})".format(
                    state["name"], sb.Id.IntegerValue))
                warnings.append("Name was taken - suffixed with element id.")
            except Exception:
                warnings.append("Could not rename the scope box.")

        # 3) rotate to match the section box
        if abs(theta) > 1e-4:
            try:
                axis = Line.CreateBound(
                    XYZ(state["cx"], state["cy"], 0),
                    XYZ(state["cx"], state["cy"], 10))
                ElementTransformUtils.RotateElement(doc, sb.Id, axis, theta)
                report.append("Rotated {:.2f} deg to match the section box."
                              .format(math.degrees(theta)))
            except Exception as ex:
                warnings.append("Rotation failed: {}".format(ex))

        # 4) move to the correct centre / base level
        try:
            bb = sb.get_BoundingBox(None)
            dx = state["cx"] - (bb.Min.X + bb.Max.X) * 0.5
            dy = state["cy"] - (bb.Min.Y + bb.Max.Y) * 0.5
            dz = state["zmin"] - bb.Min.Z
            if (abs(dx) > POS_TOL_FT or abs(dy) > POS_TOL_FT
                    or abs(dz) > POS_TOL_FT):
                ElementTransformUtils.MoveElement(doc, sb.Id, XYZ(dx, dy, dz))
        except Exception as ex:
            warnings.append("Move failed: {}".format(ex))

        # 5) final verification
        bb = sb.get_BoundingBox(None)

        # 6) remove guides
        for gid in state.get("guide_ids", []):
            try:
                doc.Delete(ElementId(gid))
            except Exception:
                pass

    try:
        os.remove(STATE_FILE)
    except Exception:
        pass

    # ---- report ----
    out.print_md("## Scope Box from Section Box - result")
    out.print_md("* Scope box: **{}** (Id {})".format(
        get_name(sb), sb.Id.IntegerValue))
    out.print_md("* Source: section box of `{}`".format(state["src"]))
    out.print_md("* Target W x D x H: {:.0f} x {:.0f} x {:.0f} mm".format(
        mm(state["w"]), mm(state["d"]), mm(state["h"])))
    out.print_md(
        "* Achieved envelope: {:.0f} x {:.0f} x {:.0f} mm "
        "(world axis-aligned{})".format(
            mm(bb.Max.X - bb.Min.X), mm(bb.Max.Y - bb.Min.Y),
            mm(bb.Max.Z - bb.Min.Z),
            ", rotated box so envelope > face size" if abs(theta) > 1e-4
            else ""))
    out.print_md("* Base Z: {:.0f} mm (target {:.0f} mm)".format(
        mm(bb.Min.Z), mm(state["zmin"])))
    for r in report:
        out.print_md("* {}".format(r))
    for w in warnings:
        out.print_md("* **Warning:** {}".format(w))

    msg = "Scope box '{}' finished.".format(get_name(sb))
    if warnings:
        msg += "\n\n" + "\n".join(warnings)
    else:
        msg += "\n\nAll extents verified against the section box."
    forms.alert(msg, title="Scope Box from Section Box")


# -----------------------------------------------------------

def main():
    if os.path.exists(STATE_FILE):
        phase2()
    else:
        phase1()


if __name__ == "__main__":
    main()
