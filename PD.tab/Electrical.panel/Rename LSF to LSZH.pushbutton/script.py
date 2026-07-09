# -*- coding: utf-8 -*-
"""Rename existing LSF wiring types to LSZH (terminology fix).

'LSF' (Low Smoke & Fume) is a modified PVC and is still halogenated; the cables
in question (BS 7211 / BS 6724) are actually LSZH / halogen-free. This renames the
wiring TYPES so the code matches the cable:
    LSF/LSF (...)  ->  LSZH/LSZH (...)
    SWA/LSF (...)  ->  SWA/LSZH (...)
    LSF (...)      ->  LSZH (...)

Renaming a wire type updates every circuit that uses it (circuits reference the
element, not the name) - so nothing is disconnected. Safe to RE-RUN and reversible.
Run on a COPY first and check Electrical Settings > Wiring > Wiring Types.
"""
__title__ = "Rename LSF\nto LSZH"
__author__ = "Project Design"

from pyrevit import revit, script
from Autodesk.Revit.DB import (FilteredElementCollector, Transaction,
                               Element, BuiltInParameter)
from Autodesk.Revit.DB.Electrical import WireType

doc = revit.doc
output = script.get_output()

OLD = "LSF"     # substring to replace in the wire-type NAME
NEW = "LSZH"


def get_name(el):
    """Robust element-name read (IronPython 'Name' attribute quirk)."""
    try:
        return Element.Name.GetValue(el)
    except Exception:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        return p.AsString() if p else None


def set_name(el, new_name):
    """Robust element rename."""
    try:
        el.Name = new_name
        return True
    except Exception:
        try:
            Element.Name.SetValue(el, new_name)
            return True
        except Exception:
            return False


wire_types = FilteredElementCollector(doc).OfClass(WireType).ToElements()
names = set()
items = []
for wt in wire_types:
    nm = get_name(wt)
    if nm:
        names.add(nm)
        items.append((wt, nm))

renamed = []
conflicts = []
errors = []

t = Transaction(doc, "Rename LSF wiring types to LSZH")
t.Start()
for wt, nm in items:
    if OLD not in nm:
        continue
    new_name = nm.replace(OLD, NEW)   # handles LSF, LSF/LSF and SWA/LSF
    if new_name == nm:
        continue
    if new_name in names:
        conflicts.append("{0} -> {1} (target already exists)".format(nm, new_name))
        continue
    if set_name(wt, new_name):
        names.discard(nm)
        names.add(new_name)
        renamed.append("{0} -> {1}".format(nm, new_name))
    else:
        errors.append(nm)
t.Commit()

output.print_md("## Rename LSF wiring types to LSZH")
output.print_md("**Renamed ({0}):** {1}".format(len(renamed), "; ".join(renamed) or "none"))
if conflicts:
    output.print_md("**Conflicts, left unchanged ({0}):** {1}".format(len(conflicts), "; ".join(conflicts)))
if errors:
    output.print_md("**Could not rename ({0}):** {1}".format(len(errors), ", ".join(errors)))
if not (renamed or conflicts or errors):
    output.print_md("No wiring types containing 'LSF' found - nothing to do.")
