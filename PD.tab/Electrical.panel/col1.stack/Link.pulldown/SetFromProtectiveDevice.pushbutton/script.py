# -*- coding: utf-8 -*-
"""CableID: Set from Protective Device (or any matching Detail Item).

Step 1: pick ONE PD_DET_SC_CableID tag instance.
Step 2: pick ONE source Detail Item family carrying PD_DATe_* parameters
        (e.g. PD_DET_SC_ProtectiveDevice).

Copies up to 12 PD_DATe_* parameters source -> tag (only those present on
the source). The tag's own 'PD_DATe_ID1' is NEVER overwritten - it stays
as the CableID's own identifier. Storage types are matched automatically.

Tested with pyRevit 5.1.x.
Author: Jarek Wityk
"""

import re

from Autodesk.Revit.DB import (
    Transaction, StorageType, ElementId, FamilyInstance, BuiltInCategory,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit, script

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()


def eid_int(eid):
    """Return ElementId integer in a way that works for Revit 2023 (IntegerValue)
    and Revit 2024+ (Value)."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

TAG_FAMILY_BASE = "PD_DET_SC_CableID"
# NOTE: 'PD_DATe_ID1' is intentionally EXCLUDED - that parameter is the
# CableID tag's own identifier and must not be overwritten by the source.
PARAM_NAMES = [
    "PD_DATe_Rating",
    "PD_DATe_Description1",
    "PD_DATe_DeviceNo1",
    "PD_DATe_DeviceType1",
    "PD_DATe_FaultRating1",
    "PD_DATe_FrameRating1",
    "PD_DATe_ID2",
    "PD_DATe_IsMeter",
    "PD_DATe_NoOfPolesINT1",
    "PD_DATe_TripRating1",
    "PD_DATe_TripSetting1",
    "PD_DATe_TripType1",
]
VERSION_SUFFIX_RE = re.compile(r"_v\d+(?:\.\d+)*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def strip_version(name):
    if not name:
        return ""
    return VERSION_SUFFIX_RE.sub("", name).strip()


def get_family_name(elem):
    if elem is None:
        return ""
    try:
        sym = getattr(elem, "Symbol", None)
        if sym is not None and getattr(sym, "Family", None) is not None:
            return sym.Family.Name
    except Exception:
        pass
    try:
        fam = getattr(elem, "Family", None)
        if fam is not None:
            return fam.Name
    except Exception:
        pass
    return ""


def is_detail_item(elem):
    """Permissive: any FamilyInstance counts.
    The parameter-existence check downstream is the real gate."""
    try:
        return isinstance(elem, FamilyInstance)
    except Exception:
        return False



def lookup_param_anywhere(elem, name):
    p = elem.LookupParameter(name)
    if p is not None:
        return p
    try:
        sym = getattr(elem, "Symbol", None)
        if sym is not None:
            return sym.LookupParameter(name)
    except Exception:
        pass
    return None


def read_param(elem, name):
    p = lookup_param_anywhere(elem, name)
    if p is None:
        return None, None, "missing"
    st = p.StorageType
    if not p.HasValue:
        return None, st, "empty"
    if st == StorageType.String:
        v = p.AsString()
        return (v if v is not None else ""), st, "ok"
    if st == StorageType.Integer:
        return p.AsInteger(), st, "ok"
    if st == StorageType.Double:
        return p.AsDouble(), st, "ok"
    if st == StorageType.ElementId:
        return p.AsElementId(), st, "ok"
    return None, st, "empty"


def write_param(elem, name, value, source_storage):
    p = elem.LookupParameter(name)
    if p is None:
        return False, "target parameter not found"
    if p.IsReadOnly:
        return False, "target parameter is read-only"
    tst = p.StorageType
    if source_storage is not None and tst != source_storage:
        return False, "storage mismatch (source {}, target {})".format(source_storage, tst)
    try:
        if value is None:
            if tst == StorageType.String:
                p.Set("")
            elif tst == StorageType.Integer:
                p.Set(0)
            elif tst == StorageType.Double:
                p.Set(0.0)
            elif tst == StorageType.ElementId:
                p.Set(ElementId.InvalidElementId)
            return True, "cleared"
        p.Set(value)
        return True, "OK"
    except Exception as ex:
        return False, "set failed: {}".format(ex)


def pick_one(prompt):
    try:
        return uidoc.Selection.PickObject(ObjectType.Element, prompt)
    except OperationCanceledException:
        return None


def pick_many(prompt):
    try:
        return uidoc.Selection.PickObjects(ObjectType.Element, prompt)
    except OperationCanceledException:
        return None


def info(title, msg):
    TaskDialog.Show(title, msg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    output.print_md("## CableID: Set from Protective Device")

    # ---- Step 1: origin tag (single) ----------------------------------------
    info("Step 1 of 2 - CableID tag",
         "Pick ONE {} tag.".format(TAG_FAMILY_BASE))

    tag_elem = None
    while tag_elem is None:
        ref = pick_one("Step 1/2: Pick ONE {} tag. Esc to cancel.".format(TAG_FAMILY_BASE))
        if ref is None:
            output.print_md("*Cancelled by user.*")
            return
        e = doc.GetElement(ref.ElementId)
        if not (isinstance(e, FamilyInstance) and
                strip_version(get_family_name(e)).lower() == TAG_FAMILY_BASE.lower()):
            info("Wrong element",
                 "That is not a {} tag. Please pick the cable tag.".format(TAG_FAMILY_BASE))
            continue
        tag_elem = e

    # ---- Step 2: source -----------------------------------------------------
    info("Step 2 of 2 - Source",
         "Pick the SOURCE Detail Item (e.g. PD_DET_SC_ProtectiveDevice).\n\n"
         "It must expose at least one PD_DATe_* parameter.")

    src_elem = None
    while src_elem is None:
        ref = pick_one("Step 2/2: Pick SOURCE Detail Item. Esc to cancel.")
        if ref is None:
            output.print_md("*Cancelled by user.*")
            return
        elem = doc.GetElement(ref.ElementId)
        if not isinstance(elem, FamilyInstance) or not is_detail_item(elem):
            info("Wrong element",
                 "That is not a family instance. Please pick a Family Instance (Detail Item).")
            continue
        if strip_version(get_family_name(elem)).lower() == TAG_FAMILY_BASE.lower():
            info("Wrong element",
                 "That is a {} tag; pick a source family instead.".format(TAG_FAMILY_BASE))
            continue
        has_any = any(lookup_param_anywhere(elem, n) is not None for n in PARAM_NAMES)
        if not has_any:
            info("Missing parameters",
                 "Family '{}' has none of the PD_DATe_* parameters.\n\nPick a different source.".format(
                     get_family_name(elem)))
            continue
        src_elem = elem

    src_name = get_family_name(src_elem) or "<unknown>"
    output.print_md("**Source family:** `{}`".format(src_name))
    output.print_md("**Target tag:** `{}` (ElementId `{}`)".format(
        get_family_name(tag_elem), eid_int(tag_elem.Id)))
    output.print_md("*Note: `PD_DATe_ID1` on the tag is preserved (not overwritten).*")

    src_values = {}
    for n in PARAM_NAMES:
        src_values[n] = read_param(src_elem, n)

    available = [n for n, (_, _, s) in src_values.items() if s in ("ok", "empty")]
    missing   = [n for n, (_, _, s) in src_values.items() if s == "missing"]
    if missing:
        output.print_md("*Source has no parameter (skipped):* `{}`".format("`, `".join(missing)))
    if not available:
        info("Nothing to write",
             "Source has none of the expected parameters.")
        return

    # ---- Write --------------------------------------------------------------
    written = []
    issues  = []
    t = Transaction(doc, "PD: Set CableID from Protective Device")
    t.Start()
    try:
        for n in available:
            value, sst, status = src_values[n]
            ok, msg = write_param(
                tag_elem, n,
                None if status == "empty" else value,
                sst,
            )
            if ok:
                written.append(n)
            else:
                issues.append((n, msg))
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        output.print_md("**Transaction failed:** {}".format(ex))
        return

    output.print_md(
        "**Updated {} parameter(s) on tag `{}`.**".format(
            len(written), eid_int(tag_elem.Id)
        )
    )
    if written:
        output.print_md("Written: `{}`".format("`, `".join(written)))
    if issues:
        output.print_md("**Issues ({}):**".format(len(issues)))
        for n, m in issues:
            output.print_md("- `{}` - {}".format(n, m))


main()
