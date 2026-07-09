# -*- coding: utf-8 -*-
"""CableID: Set FedTo from Destination.

Step 1 (Origin):      pick ONE OR MORE PD_DET_SC_CableID tag instances.
Step 2 (Destination): pick ONE Detail Item family (any family) that has
                      'PD_DATe_ID1'.

Writes 'PD_DATe_ID1' from the destination -> 'PD_DATe_FedTo' on each tag.

Tested with pyRevit 5.1.x.
Author: Jarek Wityk
"""

import re

from Autodesk.Revit.DB import (
    Transaction, FamilyInstance, BuiltInCategory,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit, script

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

TAG_FAMILY_BASE   = "PD_DET_SC_CableID"
SOURCE_PARAM_NAME = "PD_DATe_ID1"
TARGET_PARAM_NAME = "PD_DATe_FedTo"
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


def read_param_string(elem, name):
    p = lookup_param_anywhere(elem, name)
    if p is None:
        return None, "missing"
    if not p.HasValue:
        return "", "empty"
    v = p.AsString()
    if v is None:
        v = p.AsValueString()
    return (v if v is not None else ""), "ok"


def set_text_param(elem, name, value):
    p = elem.LookupParameter(name)
    if p is None:
        return False, "parameter not found"
    if p.IsReadOnly:
        return False, "parameter is read-only"
    try:
        p.Set(value if value is not None else "")
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
    output.print_md("## CableID: Set FedTo from Destination")

    # ---- Step 1: origin tags ------------------------------------------------
    info("Step 1 of 2 - Origin",
         "Pick ONE OR MORE {} tags.\n\nFinish on the ribbon ('Finish').".format(TAG_FAMILY_BASE))

    tag_refs = pick_many(
        "Step 1/2: Pick {} tags (multi-select, then click Finish).".format(TAG_FAMILY_BASE)
    )
    if tag_refs is None:
        output.print_md("*Cancelled by user.*")
        return

    good = []
    skipped = 0
    for r in tag_refs:
        e = doc.GetElement(r.ElementId)
        if isinstance(e, FamilyInstance) and \
           strip_version(get_family_name(e)).lower() == TAG_FAMILY_BASE.lower():
            good.append(e)
        else:
            skipped += 1
    if skipped:
        output.print_md("*Skipped {} non-CableID element(s).*".format(skipped))
    if not good:
        info("Nothing to update",
             "Your selection contained no {} tags.".format(TAG_FAMILY_BASE))
        return

    # ---- Step 2: destination -----------------------------------------------
    info("Step 2 of 2 - Destination",
         "Pick the DESTINATION Detail Item (any family).\n\n"
         "It must expose the parameter '{}'.".format(SOURCE_PARAM_NAME))

    dest_elem = None
    while dest_elem is None:
        ref = pick_one("Step 2/2: Pick DESTINATION Detail Item. Esc to cancel.")
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
                 "That is a {} tag; pick a destination family instead.".format(TAG_FAMILY_BASE))
            continue
        if lookup_param_anywhere(elem, SOURCE_PARAM_NAME) is None:
            info("Missing parameter",
                 "Family '{}' has no parameter '{}'.\n\nPick a different destination.".format(
                     get_family_name(elem), SOURCE_PARAM_NAME))
            continue
        dest_elem = elem

    src_value, status = read_param_string(dest_elem, SOURCE_PARAM_NAME)
    if status == "missing":
        info("Aborted", "Destination parameter disappeared. Aborting.")
        return

    output.print_md("**Destination family:** `{}`".format(get_family_name(dest_elem)))
    output.print_md("**`{}` = `{}`**".format(SOURCE_PARAM_NAME, src_value))

    # ---- Write --------------------------------------------------------------
    ok_count = 0
    fail = []
    t = Transaction(doc, "PD: Set FedTo from Destination")
    t.Start()
    try:
        for tag in good:
            ok, msg = set_text_param(tag, TARGET_PARAM_NAME, src_value)
            if ok:
                ok_count += 1
            else:
                fail.append((tag.Id.IntegerValue, msg))
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        output.print_md("**Transaction failed:** {}".format(ex))
        return

    output.print_md("**Updated `{}` on {} tag(s).**".format(TARGET_PARAM_NAME, ok_count))
    if fail:
        output.print_md("**Skipped {}:**".format(len(fail)))
        for eid, m in fail:
            output.print_md("- ElementId `{}` - {}".format(eid, m))


main()
