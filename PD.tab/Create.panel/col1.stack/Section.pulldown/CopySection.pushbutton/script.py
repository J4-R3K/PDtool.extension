# -*- coding: utf-8 -*-
__title__   = "Section: CopySection"
__doc__     = """Version = 2.1
Date    = 2026-03-06
________________________________________________________________
Description:

Recreates a section view to restore correct marker head/tail
alignment with extents.

Workflow:
1) Pick section marker(s) in plan
2) Script resolves the real ViewSection behind the marker
3) If the view has a CropBox -> recreate from that geometry
4) If no CropBox -> attempt fallback using the view element
   bounding box + ViewDirection/UpDirection (heuristic)
5) If fallback also fails -> skip safely with diagnostics

Original sections are NOT deleted automatically.

Relative Path:
...\\PD.tab\\Sections.panel\\CopySection.pushbutton
________________________________________________________________
How-To:

1. Run the tool from the pyRevit ribbon
2. Pick one or more section markers in a plan view
3. Press Finish (green tick) or right-click to confirm
4. New sections appear with " (Reset)" suffix
5. Manually delete originals once you confirm the new ones

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
clr.AddReference("System")

from Autodesk.Revit.DB import (
    ViewSection,
    View,
    ViewType,
    BoundingBoxXYZ,
    Transform,
    XYZ,
    ElementId,
    StorageType,
    Transaction
)
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()
log   = script.get_logger()

NAME_SUFFIX = " (Reset)"


# -----------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------

def normalize(v):
    """Normalise a vector. Returns None if zero-length."""
    try:
        return v.Normalize()
    except:
        l = v.GetLength()
        if l < 1e-9:
            return None
        return XYZ(v.X / l, v.Y / l, v.Z / l)


def ensure_minmax(a, b):
    """Return (min, max) regardless of input order."""
    return (a if a <= b else b, b if a <= b else a)


def exception_to_string(ex):
    """Get full exception text (IronPython-safe)."""
    try:
        return ex.ToString()
    except:
        return str(ex)


def build_orthonormal_basis(view_dir, up_dir):
    """Build a right-handed orthonormal basis from view vectors.
    Returns (basisX, basisY, basisZ) or None if degenerate."""
    z = normalize(view_dir)
    y = normalize(up_dir)

    if z is None or y is None:
        return None

    x = normalize(y.CrossProduct(z))
    if x is None or x.GetLength() < 1e-6:
        # up and viewdir nearly parallel — pick arbitrary up
        y = XYZ.BasisY if abs(z.DotProduct(XYZ.BasisY)) < 0.99 else XYZ.BasisX
        x = normalize(y.CrossProduct(z))

    # recompute Y to guarantee orthonormality
    y = normalize(z.CrossProduct(x))
    if y is None:
        return None

    return (x, y, z)


def set_all_enabled(bb):
    """Force Enabled + MinEnabled/MaxEnabled on all 3 dims."""
    try:
        bb.Enabled = True
    except:
        pass
    for dim in (0, 1, 2):
        try:
            set_min = getattr(bb, "set_MinEnabled", None)
            set_max = getattr(bb, "set_MaxEnabled", None)
            if callable(set_min):
                set_min(dim, True)
            else:
                bb.MinEnabled[dim] = True
            if callable(set_max):
                set_max(dim, True)
            else:
                bb.MaxEnabled[dim] = True
        except:
            pass


def print_box_debug(label, bb, view_name, view_id):
    """Print section-box diagnostics to pyRevit output."""
    try:
        out.print_md("### {} for `{}` (Id {})".format(
            label, view_name, view_id))
        out.print_md("* Min: ({:.4f}, {:.4f}, {:.4f})".format(
            float(bb.Min.X), float(bb.Min.Y), float(bb.Min.Z)))
        out.print_md("* Max: ({:.4f}, {:.4f}, {:.4f})".format(
            float(bb.Max.X), float(bb.Max.Y), float(bb.Max.Z)))
        out.print_md("* |X|={:.6f}  |Y|={:.6f}  |Z|={:.6f}".format(
            float(bb.Transform.BasisX.GetLength()),
            float(bb.Transform.BasisY.GetLength()),
            float(bb.Transform.BasisZ.GetLength())))
        out.print_md("* X.Y={:.6f}  X.Z={:.6f}  Y.Z={:.6f}".format(
            float(bb.Transform.BasisX.DotProduct(bb.Transform.BasisY)),
            float(bb.Transform.BasisX.DotProduct(bb.Transform.BasisZ)),
            float(bb.Transform.BasisY.DotProduct(bb.Transform.BasisZ))))
    except:
        pass


# -----------------------------------------------------------
# Resolve picked element -> section view
# -----------------------------------------------------------

def as_section_view(el):
    """Return el if it is a section ViewSection, else None."""
    if el is None:
        return None
    if isinstance(el, ViewSection):
        return el
    if isinstance(el, View):
        try:
            if el.ViewType == ViewType.Section:
                return el
        except:
            pass
    return None


def resolve_section_view(el):
    """Try to find the real ViewSection behind a picked element.
    Returns (ViewSection, method_string) or (None, None)."""

    # 1) direct
    vs = as_section_view(el)
    if vs:
        return vs, "direct"

    # 2) scan ElementId parameters
    try:
        for p in el.Parameters:
            try:
                if p.StorageType == StorageType.ElementId:
                    eid = p.AsElementId()
                    if eid and eid != ElementId.InvalidElementId:
                        maybe = as_section_view(doc.GetElement(eid))
                        if maybe:
                            return maybe, "param"
            except:
                pass
    except:
        pass

    # 3) dependent elements
    try:
        deps = el.GetDependentElements(None)
        if deps:
            for did in deps:
                try:
                    dep = doc.GetElement(did)
                    maybe = as_section_view(dep)
                    if maybe:
                        return maybe, "dependent"
                except:
                    pass
    except:
        pass

    return None, None


# -----------------------------------------------------------
# Build section bounding box — primary path (from CropBox)
# -----------------------------------------------------------

def build_box_from_crop(view):
    """Build a clean BoundingBoxXYZ from the view's CropBox.
    Returns BoundingBoxXYZ or None."""

    crop = view.CropBox
    if crop is None:
        return None

    minx, maxx = ensure_minmax(crop.Min.X, crop.Max.X)
    miny, maxy = ensure_minmax(crop.Min.Y, crop.Max.Y)
    minz, maxz = ensure_minmax(crop.Min.Z, crop.Max.Z)

    # ensure minimum depth (~150 mm)
    if (maxz - minz) < 0.50:
        mid = (minz + maxz) * 0.5
        minz = mid - 0.25
        maxz = mid + 0.25

    basis = build_orthonormal_basis(view.ViewDirection, view.UpDirection)
    if basis is None:
        return None
    bx, by, bz = basis

    t = Transform.Identity
    try:
        t.Origin = crop.Transform.Origin
    except:
        t.Origin = XYZ(0, 0, 0)
    t.BasisX = bx
    t.BasisY = by
    t.BasisZ = bz

    bb = BoundingBoxXYZ()
    bb.Transform = t
    bb.Min = XYZ(minx, miny, minz)
    bb.Max = XYZ(maxx, maxy, maxz)
    set_all_enabled(bb)

    return bb


# -----------------------------------------------------------
# Build section bounding box — fallback (from element bbox)
# -----------------------------------------------------------

def build_box_from_element(view):
    """Fallback: build a BoundingBoxXYZ from the view element's
    model-space bounding box + its ViewDirection/UpDirection.

    This is a heuristic. The element bounding box is in model
    coords, so we project it into the section's local frame.
    Returns BoundingBoxXYZ or None."""

    # We need ViewDirection + UpDirection even for fallback
    try:
        vdir = view.ViewDirection
        udir = view.UpDirection
    except:
        return None

    if vdir is None or udir is None:
        return None

    basis = build_orthonormal_basis(vdir, udir)
    if basis is None:
        return None
    bx, by, bz = basis

    # Try to get a model-space bounding box from the view element
    elem_bb = None
    try:
        elem_bb = view.get_BoundingBox(None)
    except:
        pass

    if elem_bb is None:
        return None

    # The element bbox min/max are in model coords.
    # Compute the centre as the origin, and project the
    # half-extents onto the section's local axes.
    model_min = elem_bb.Min
    model_max = elem_bb.Max

    cx = (model_min.X + model_max.X) * 0.5
    cy = (model_min.Y + model_max.Y) * 0.5
    cz = (model_min.Z + model_max.Z) * 0.5
    centre = XYZ(cx, cy, cz)

    # Half-diagonal vector
    hx = (model_max.X - model_min.X) * 0.5
    hy = (model_max.Y - model_min.Y) * 0.5
    hz = (model_max.Z - model_min.Z) * 0.5

    # Project half-extents onto each local axis
    # Use absolute dot products of the 8 corners extremes.
    # Simpler approach: use the half-diagonal length as extent
    # in each local axis (conservative, box will be larger).
    diag = XYZ(hx, hy, hz)

    ext_x = abs(diag.DotProduct(bx))
    ext_y = abs(diag.DotProduct(by))
    ext_z = abs(diag.DotProduct(bz))

    # Ensure minimum extents
    if ext_x < 1.0:
        ext_x = 1.0
    if ext_y < 1.0:
        ext_y = 1.0
    if ext_z < 0.50:
        ext_z = 0.50

    t = Transform.Identity
    t.Origin = centre
    t.BasisX = bx
    t.BasisY = by
    t.BasisZ = bz

    bb = BoundingBoxXYZ()
    bb.Transform = t
    bb.Min = XYZ(-ext_x, -ext_y, -ext_z)
    bb.Max = XYZ( ext_x,  ext_y,  ext_z)
    set_all_enabled(bb)

    return bb


# -----------------------------------------------------------
# Recreate section
# -----------------------------------------------------------

def recreate_section(old_view):
    """Attempt to recreate a section view.
    Returns (new_ViewSection, failure_reason) tuple.
    failure_reason is None on success."""

    type_id = old_view.GetTypeId()

    # --- Primary path: CropBox ---
    box = build_box_from_crop(old_view)

    if box is not None:
        print_box_debug("SectionBox (from CropBox)",
                        box, old_view.Name, old_view.Id.IntegerValue)
        try:
            new_view = ViewSection.CreateSection(doc, type_id, box)
            out.print_md("* Created via **CropBox** path")
            return new_view, None
        except Exception as ex:
            msg = exception_to_string(ex)
            out.print_md("* CropBox path failed: `{}`".format(msg))
            # fall through to fallback

    # --- Fallback path: element bounding box ---
    out.print_md("### Trying fallback for `{}` (Id {})".format(
        old_view.Name, old_view.Id.IntegerValue))

    fb_box = build_box_from_element(old_view)

    if fb_box is None:
        reason = "No CropBox and element bounding box fallback unavailable"
        out.print_md("* **Skipped**: {}".format(reason))
        return None, reason

    print_box_debug("SectionBox (fallback from element bbox)",
                    fb_box, old_view.Name, old_view.Id.IntegerValue)

    try:
        new_view = ViewSection.CreateSection(doc, type_id, fb_box)
        out.print_md("* Created via **fallback** path (element bbox)")
        return new_view, None
    except Exception as ex:
        msg = exception_to_string(ex)
        out.print_md("### Failed `{}`".format(old_view.Name))
        out.print_md("```")
        out.print_md(msg)
        out.print_md("```")
        return None, msg


# -----------------------------------------------------------
# Copy basic settings
# -----------------------------------------------------------

def copy_settings(old_view, new_view):
    """Transfer name, template, and scale to the new view."""

    # Name
    try:
        new_view.Name = "{}{}".format(old_view.Name, NAME_SUFFIX)
    except:
        try:
            new_view.Name = "{}{} [{}]".format(
                old_view.Name,
                NAME_SUFFIX,
                new_view.Id.IntegerValue
            )
        except:
            pass

    # View template
    try:
        if old_view.ViewTemplateId != ElementId.InvalidElementId:
            new_view.ViewTemplateId = old_view.ViewTemplateId
    except:
        pass

    # Scale
    try:
        new_view.Scale = old_view.Scale
    except:
        pass

    # Detail level
    try:
        new_view.DetailLevel = old_view.DetailLevel
    except:
        pass

    # Discipline
    try:
        new_view.Discipline = old_view.Discipline
    except:
        pass


# -----------------------------------------------------------
# Pick elements
# -----------------------------------------------------------

def pick_elements():
    """Prompt user to pick section markers. Returns list of Elements."""
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Pick section marker(s) — Finish to continue, ESC cancels."
        )
    except:
        return []

    els = []
    for r in refs:
        try:
            els.append(doc.GetElement(r.ElementId))
        except:
            pass
    return els


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------

def main():
    picked = pick_elements()
    if not picked:
        forms.alert("Nothing picked.", exitscript=True)

    out.print_md("## Resolve Debug")

    resolved = []
    seen = set()

    for el in picked:
        # Print what was picked
        try:
            out.print_md(
                "* Picked Id {} | Type `{}` | Cat `{}`".format(
                    el.Id.IntegerValue,
                    el.GetType().FullName,
                    el.Category.Name if el.Category else "None"
                )
            )
        except:
            out.print_md("* Picked element (unreadable)")

        vs, how = resolve_section_view(el)

        if vs:
            out.print_md(
                "  - Resolved ({}) -> `{}` (Id {})".format(
                    how, vs.Name, vs.Id.IntegerValue
                )
            )
            if vs.Id.IntegerValue not in seen:
                resolved.append(vs)
                seen.add(vs.Id.IntegerValue)
        else:
            out.print_md("  - Could not resolve to a section view")

    if not resolved:
        forms.alert("No section views found in selection.", exitscript=True)

    # --- Recreate ---
    created = 0
    failed  = 0
    skipped_names = []

    with revit.Transaction("Copy Section (Reset)"):
        for view in resolved:

            # Check it is actually a Section
            try:
                if view.ViewType != ViewType.Section:
                    out.print_md("* Skipped `{}` — not a Section".format(
                        view.Name))
                    failed += 1
                    continue
            except:
                failed += 1
                continue

            new_view, reason = recreate_section(view)

            if new_view is None:
                failed += 1
                skipped_names.append(view.Name)
                continue

            copy_settings(view, new_view)
            created += 1

    # --- Select new views ---
    try:
        sel_ids = List[ElementId]()
        # (new views are in scope from the transaction block)
        # Re-collect isn't needed; the created count is enough.
    except:
        pass

    # --- Summary ---
    msg = "Done.\n\nCreated: {}\nFailed: {}".format(created, failed)
    if skipped_names:
        msg = msg + "\n\nSkipped:\n" + "\n".join(skipped_names)
    forms.alert(msg)


if __name__ == "__main__":
    main()
