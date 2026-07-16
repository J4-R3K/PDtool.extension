# -*- coding: utf-8 -*-
"""Create FP200+, FP400 and FP100 fire-rated wiring types in Electrical Settings
by cloning existing wire types and renaming them.

Cloning copies the source type's Material/ampacity, temperature rating, insulation,
max size, neutral settings and conduit - which is correct, because a fire variant
has the same current-carrying capacity as its base cable; only the fire-survival
rating differs.

ADDS-ONLY (never edits or deletes existing types). Safe to RE-RUN (skips any that
already exist). REVERSIBLE (just delete the new types). Run on a COPY of the model
first and verify the new rows in Electrical Settings > Wiring > Wiring Types.
"""
__title__ = "Add Fire\nWire Types"
__author__ = "Project Design"

from pyrevit import revit, script
from Autodesk.Revit.DB import (FilteredElementCollector, Transaction,
                               Element, BuiltInParameter)
from Autodesk.Revit.DB.Electrical import WireType

doc = revit.doc
output = script.get_output()


def get_name(el):
    """Robust element-name read (IronPython 'Name' attribute quirk in Revit API)."""
    try:
        return Element.Name.GetValue(el)
    except Exception:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        return p.AsString() if p else None

# ---------------------------------------------------------------------------
# EDIT HERE.  (new_base, source_base_to_clone, [phase_ref combos])
#   new type name = "<new_base> (<combo>)"   source = "<source_base> (<combo>)"
#
# Basis verified against the library (BS 8519 + FP datasheets):
#   FP200+ (FP PLUS / FP200 enhanced) -> clone FP200
#         same 4D2 70 deg multicore ampacity; PH120 survival. NB BS 8519 datasheet
#         class is still "Control - Cat 2" (FP500 is the Cat 3 control cable).
#   FP400 (BS 7846 F2, ~60 min / Cat 2) -> clone FP600S
#         same armoured 90 deg XLPE/SWA construction & ampacity; only survival differs.
#   FP100 (single-core fire cable IN STEEL CONDUIT, Cat 3/120 min in its system) -> clone PVC
#         ampacity = standard single core in conduit (4D1, 70 deg, ref methods A & B).
#
# Combos: SP_x = single phase, TP_x = three phase, x = installation reference method.
# ---------------------------------------------------------------------------
CLONE_PLAN = [
    ("FP200+", "FP200",  ["SP_A", "SP_B", "SP_C", "SP_E", "TP_A", "TP_B", "TP_C", "TP_E"]),
    ("FP400",  "FP600S", ["SP_C", "SP_D", "SP_E", "TP_C", "TP_D", "TP_E"]),
    ("FP100",  "PVC",    ["SP_A", "SP_B", "TP_A", "TP_B"]),
]
# ---------------------------------------------------------------------------

wire_types = FilteredElementCollector(doc).OfClass(WireType).ToElements()
by_name = {}
for wt in wire_types:
    nm = get_name(wt)
    if nm:
        by_name[nm] = wt

output.print_md("## Add fire-rated wiring types")
output.print_md("**Existing wire types ({0}):**".format(len(wire_types)))
output.print_md(", ".join(sorted(by_name.keys())))

created = []
skipped = []
missing_src = []
errors = []

t = Transaction(doc, "Add fire-rated wiring types")
t.Start()
for new_base, src_base, combos in CLONE_PLAN:
    for combo in combos:
        src_name = "{0} ({1})".format(src_base, combo)
        new_name = "{0} ({1})".format(new_base, combo)
        if new_name in by_name:
            skipped.append(new_name)
            continue
        src = by_name.get(src_name)
        if src is None:
            missing_src.append(src_name)
            continue
        try:
            new_wt = src.Duplicate(new_name)   # inherits all electrical settings
            by_name[new_name] = new_wt
            created.append(new_name)
        except Exception as ex:
            errors.append("{0}: {1}".format(new_name, ex))
t.Commit()

output.print_md("## Result")
output.print_md("**Created ({0}):** {1}".format(len(created), ", ".join(created) or "none"))
output.print_md("**Skipped, already existed ({0}):** {1}".format(len(skipped), ", ".join(skipped) or "none"))
if missing_src:
    output.print_md("**Source type NOT found ({0}):** {1}".format(len(missing_src), ", ".join(missing_src)))
    output.print_md("> Fix the source names in CLONE_PLAN to match the 'Existing wire types' list above.")
if errors:
    output.print_md("**Errors ({0}):** {1}".format(len(errors), "; ".join(errors)))
if not (created or skipped or missing_src or errors):
    output.print_md("Nothing to do - check CLONE_PLAN.")
