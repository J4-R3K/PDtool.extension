# -*- coding: utf-8 -*-
__title__   = "Section: Reset"
__doc__     = """Version = 1.7
Date    = 2026-01-17
________________________________________________________________
Description:

Recreate section views to restore marker head/tail alignment with extents.

Key:
- Picking the section marker returns an internal Element (Cat: Views).
- We resolve the real ViewSection via GetDependentElements().
- CreateSection is strict about BoundingBoxXYZ.
  We build a NEW BoundingBoxXYZ using the VIEW's ViewDirection and UpDirection
  (not the CropBox transform), and force MinEnabled/MaxEnabled using setter
  methods (IronPython-safe).

________________________________________________________________
Author: Jarek Wityk
"""

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
DELETE_OLD  = False


# ----------------------------
# Helpers
# ----------------------------
def _safe_str(x):
    try:
        return str(x)
    except:
        return "<unreadable>"


def _ex_str(ex):
    # In IronPython/Revit, str(ex) can be empty. ToString() usually has the message.
    try:
        return ex.ToString()
    except:
        return _safe_str(ex)


def _is_view(el):
    try:
        return isinstance(el, View)
    except:
        return False


def _is_viewsection(el):
    try:
        return isinstance(el, ViewSection)
    except:
        return False


def _as_section_view(el):
    if el is None:
        return None
    if _is_viewsection(el):
        return el
    if _is_view(el):
        try:
            if el.ViewType == ViewType.Section:
                return el
        except:
            pass
    return None


def resolve_section_view(el):
    # 1) direct
    vs = _as_section_view(el)
    if vs:
        return vs, "direct"

    # 2) scan ElementId params
    try:
        for p in el.Parameters:
            try:
                if p.StorageType == StorageType.ElementId:
                    eid = p.AsElementId()
                    if eid and eid != ElementId.InvalidElementId:
                        maybe = _as_section_view(doc.GetElement(eid))
                        if maybe:
                            return maybe, "param"
            except:
                pass
    except:
        pass

    # 3) dependent elements (works for your case)
    try:
        dep_ids = el.GetDependentElements(None)
        if dep_ids:
            for did in dep_ids:
                try:
                    dep = doc.GetElement(did)
                    maybe = _as_section_view(dep)
                    if maybe:
                        return maybe, "dependent"
                except:
                    pass
    except Exception as ex:
        log.warning("GetDependentElements failed on {}: {}".format(el.Id.IntegerValue, _ex_str(ex)))

    return None, None


def pick_elements():
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Pick section marker(s) (Finish to continue). ESC cancels."
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


def _normalize(v):
    try:
        return v.Normalize()
    except:
        l = v.GetLength()
        if l < 1e-9:
            return None
        return XYZ(v.X / l, v.Y / l, v.Z / l)


def _ensure_minmax(a, b):
    return (a if a <= b else b, b if a <= b else a)


def _set_dim_enabled(bb, dim, val):
    """
    BoundingBoxXYZ MinEnabled/MaxEnabled are not reliably index-settable in IronPython.
    Prefer set_MinEnabled/set_MaxEnabled if present.
    """
    try:
        set_min = getattr(bb, "set_MinEnabled", None)
        set_max = getattr(bb, "set_MaxEnabled", None)
        if callable(set_min):
            set_min(dim, val)
        else:
            # fallback (might work in some builds)
            bb.MinEnabled[dim] = val
        if callable(set_max):
            set_max(dim, val)
        else:
            bb.MaxEnabled[dim] = val
        return True
    except:
        return False


def build_clean_sectionbox(old_vs):
    """
    Build BoundingBoxXYZ that CreateSection accepts:
    - Use view's ViewDirection + UpDirection for orthonormal basis
    - Use old cropbox min/max values (in that section coordinate space)
    - Force Enabled + MinEnabled/MaxEnabled for all dims
    """
    crop = old_vs.CropBox
    if crop is None:
        return None

    # min/max in local section coords
    minx, maxx = _ensure_minmax(crop.Min.X, crop.Max.X)
    miny, maxy = _ensure_minmax(crop.Min.Y, crop.Max.Y)
    minz, maxz = _ensure_minmax(crop.Min.Z, crop.Max.Z)

    # ensure some depth
    min_depth = 0.10  # ~30mm in feet-ish; avoids "too close" complaints
    if (maxz - minz) < min_depth:
        maxz = minz + min_depth

    # Use view vectors (most stable)
    try:
        z = _normalize(old_vs.ViewDirection)
        y = _normalize(old_vs.UpDirection)
    except:
        z = None
        y = None

    if z is None or y is None:
        # fallback to crop transform
        try:
            z = _normalize(crop.Transform.BasisZ)
            y = _normalize(crop.Transform.BasisY)
        except:
            z = XYZ.BasisZ
            y = XYZ.BasisY

    # Right-handed basis
    x = _normalize(y.CrossProduct(z))
    if x is None or x.GetLength() < 1e-6:
        # if up and viewdir are parallel, pick arbitrary up
        y = XYZ.BasisY if abs(z.DotProduct(XYZ.BasisY)) < 0.99 else XYZ.BasisX
        x = _normalize(y.CrossProduct(z))

    # Recompute y to guarantee orthonormality
    y = _normalize(z.CrossProduct(x))

    # Origin: keep from cropbox transform if possible
    origin = None
    try:
        origin = crop.Transform.Origin
    except:
        origin = XYZ(0, 0, 0)

    t = Transform.Identity
    t.Origin = origin
    t.BasisX = x
    t.BasisY = y
    t.BasisZ = z

    bb = BoundingBoxXYZ()
    bb.Transform = t
    bb.Min = XYZ(minx, miny, minz)
    bb.Max = XYZ(maxx, maxy, maxz)

    try:
        bb.Enabled = True
    except:
        pass

    ok_flags = True
    for dim in (0, 1, 2):
        if not _set_dim_enabled(bb, dim, True):
            ok_flags = False

    # Debug info (so we can see why CreateSection rejects it)
    try:
        out.print_md("### SectionBox Debug for `{}` (Id {})".format(old_vs.Name, old_vs.Id.IntegerValue))
        out.print_md("* Min: ({:.4f}, {:.4f}, {:.4f})".format(float(bb.Min.X), float(bb.Min.Y), float(bb.Min.Z)))
        out.print_md("* Max: ({:.4f}, {:.4f}, {:.4f})".format(float(bb.Max.X), float(bb.Max.Y), float(bb.Max.Z)))
        out.print_md("* Basis lengths: |X|={:.6f} |Y|={:.6f} |Z|={:.6f}".format(
            float(bb.Transform.BasisX.GetLength()),
            float(bb.Transform.BasisY.GetLength()),
            float(bb.Transform.BasisZ.GetLength())
        ))
        out.print_md("* Dot products: X·Y={:.6f} X·Z={:.6f} Y·Z={:.6f}".format(
            float(bb.Transform.BasisX.DotProduct(bb.Transform.BasisY)),
            float(bb.Transform.BasisX.DotProduct(bb.Transform.BasisZ)),
            float(bb.Transform.BasisY.DotProduct(bb.Transform.BasisZ))
        ))
        out.print_md("* Enabled flags set ok: `{}`".format(ok_flags))
    except:
        pass

    return bb


def recreate_section(old_vs):
    try:
        type_id = old_vs.GetTypeId()
        clean_box = build_clean_sectionbox(old_vs)
        if clean_box is None:
            return None
        return ViewSection.CreateSection(doc, type_id, clean_box)
    except Exception as ex:
        log.warning("CreateSection failed for {}: {}".format(old_vs.Id.IntegerValue, _ex_str(ex)))
        return None


def copy_basic_settings(old_vs, new_vs):
    # Name
    try:
        new_vs.Name = u"{}{}".format(old_vs.Name, NAME_SUFFIX)
    except:
        try:
            new_vs.Name = u"{}{} [{}]".format(old_vs.Name, NAME_SUFFIX, new_vs.Id.IntegerValue)
        except:
            pass

    # View template
    try:
        if old_vs.ViewTemplateId and old_vs.ViewTemplateId != ElementId.InvalidElementId:
            new_vs.ViewTemplateId = old_vs.ViewTemplateId
    except:
        pass

    # Scale
    try:
        new_vs.Scale = old_vs.Scale
    except:
        pass


def main():
    picked = pick_elements()
    if not picked:
        forms.alert("Nothing picked.", exitscript=True)

    out.print_md("## Resolve Debug")
    resolved = []
    seen = set()

    for el in picked:
        try:
            tname = el.GetType().FullName
            cname = el.Category.Name if el.Category else "<no category>"
            out.print_md("* Picked Id {} | Type `{}` | Cat `{}`".format(el.Id.IntegerValue, tname, cname))
        except:
            out.print_md("* Picked <unreadable>")

        vs, how = resolve_section_view(el)
        if vs:
            out.print_md("  - ✅ Resolved ({}) → `{}` (Id {})".format(how, vs.Name, vs.Id.IntegerValue))
            if vs.Id.IntegerValue not in seen:
                resolved.append(vs)
                seen.add(vs.Id.IntegerValue)
        else:
            out.print_md("  - ❌ Resolved → None")

    if not resolved:
        forms.alert("Could not resolve selection to any section views.", exitscript=True)

    created = []
    failed = []

    t = Transaction(doc, "Reset Section (Recreate)")
    t.Start()
    try:
        for old_vs in resolved:
            try:
                if old_vs.ViewType != ViewType.Section:
                    failed.append((old_vs, "Not a Section view"))
                    continue
            except:
                failed.append((old_vs, "ViewType unreadable"))
                continue

            new_vs = recreate_section(old_vs)
            if not new_vs:
                failed.append((old_vs, "CreateSection failed"))
                continue

            copy_basic_settings(old_vs, new_vs)
            created.append(new_vs)

            if DELETE_OLD:
                try:
                    doc.Delete(old_vs.Id)
                except:
                    pass

        t.Commit()
    except Exception as big_ex:
        try:
            t.RollBack()
        except:
            pass
        forms.alert("Failed:\n{}".format(_ex_str(big_ex)), exitscript=True)

    # Select new sections
    try:
        ids = List[ElementId]()
        for v in created:
            ids.Add(v.Id)
        if ids.Count > 0:
            uidoc.Selection.SetElementIds(ids)
    except:
        pass

    forms.alert("Done.\n\nCreated: {}\nFailed: {}".format(len(created), len(failed)))


if __name__ == "__main__":
    main()
