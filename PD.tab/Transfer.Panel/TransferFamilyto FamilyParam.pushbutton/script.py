# -*- coding: utf-8 -*-
__title__  = 'Transfer Params from\nOther Open Family'
__author__ = 'Jarek Wityk @ PD  |  2022-2025'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *           # noqa
from RevitServices.Persistence import DocumentManager
from pyrevit import revit, forms, script

# --- helpers -----------------------------------------------------------------
def safe_parameter_type(defn):
    """Return classic ParameterType where available, else fall back to Text (1)."""
    try:
        return defn.ParameterType
    except Exception:                       # Revit 2024+ parameters don’t expose it
        try:
            from Autodesk.Revit.DB import ParameterType  # late import for IronPy
            return ParameterType.Text
        except Exception:
            return 1                        # int enum value for Text

def add_param(host_mgr, name, is_inst, p, rev_major):
    """
    Add a parameter to host family using the correct overload for the Revit version.
    Returns True if added, raises on error so caller can catch & record.
    """
    # Revit 2024+ => ForgeTypeId overload
    if rev_major >= 2024 and hasattr(p.Definition, 'GetDataType'):
        group_id = p.Definition.GetGroupTypeId()   # GroupTypeId (ForgeTypeId)
        data_id  = p.Definition.GetDataType()      # SpecTypeId  (ForgeTypeId)
        host_mgr.AddParameter(name, group_id, data_id, is_inst)
        return True

    # Revit 2023- => classic enum overload
    group_enum = p.Definition.ParameterGroup
    ptype_enum = safe_parameter_type(p.Definition)
    host_mgr.AddParameter(name, group_enum, ptype_enum, is_inst)
    return True

# --- setup -------------------------------------------------------------------
host_doc   = revit.doc
app        = revit.uidoc.Application.Application
rev_major  = int(app.VersionNumber)              # e.g. 2024, 2023 …
output     = script.get_output()

# --- 1 | choose source family -------------------------------------------------
open_docs = [d for d in app.Documents
             if d.IsFamilyDocument and d.PathName != host_doc.PathName]

if not open_docs:
    forms.alert("No other open family documents found.")
    script.exit()

choices = [d.Title for d in open_docs]
chosen  = forms.SelectFromList.show(choices,
                                    title="Select Source Family",
                                    button_name="Transfer")

if not chosen:
    script.exit()

source_doc  = next(d for d in open_docs if d.Title == chosen)
source_mgr  = source_doc.FamilyManager
source_params = list(source_mgr.Parameters)

# --- 2 | let user pick parameters -------------------------------------------
labels, pmap = [], {}
for p in source_params:
    try:
        grp = LabelUtils.GetLabelFor(p.Definition.ParameterGroup)
    except Exception:
        grp = "ForgeTypeId"
    kind   = "Instance" if p.IsInstance else "Type"
    label  = u"{0} [{1}] – {2}".format(p.Definition.Name, kind, grp)
    labels.append(label)
    pmap[label] = p

picked = forms.SelectFromList.show(sorted(labels),
                                   multiselect=True,
                                   title="Select Parameters to Transfer",
                                   button_name="Transfer Selected")

if not picked:
    forms.alert("No parameters selected.")
    script.exit()

selected_params = [pmap[l] for l in picked]

# --- 3 | host prep -----------------------------------------------------------
host_mgr   = host_doc.FamilyManager
host_names = {p.Definition.Name for p in host_mgr.Parameters}
host_map   = {p.Definition.Name: p for p in host_mgr.Parameters}

added, overwritten, skipped = [], [], []

# --- 4 | transaction ---------------------------------------------------------
t = Transaction(host_doc, "Transfer Parameters from Source Family")
try:
    t.Start()
    for p in selected_params:
        name     = p.Definition.Name
        is_inst  = p.IsInstance
        formula  = p.Formula if p.IsDeterminedByFormula else None

        # skip built-ins
        if p.Definition.BuiltInParameter != BuiltInParameter.INVALID:
            skipped.append((name, "Built-in"))
            continue

        # overwrite if exists
        if name in host_names:
            try:
                host_mgr.RemoveParameter(host_map[name])
                overwritten.append(name)
            except Exception as e:
                skipped.append((name, "Could not remove: {}".format(e)))
                continue

        # add parameter
        try:
            add_param(host_mgr, name, is_inst, p, rev_major)
            if formula:
                try:
                    host_mgr.SetFormula(host_mgr.Parameters[name], formula)
                except Exception:
                    skipped.append((name, "Formula skipped"))
            added.append(name)
        except Exception as e:
            skipped.append((name, "Add failed: {}".format(e)))

    t.Commit()

except Exception as err:
    t.RollBack()
    forms.alert("Transfer failed.\n\n{}".format(err))
    script.exit()

# --- 5 | report --------------------------------------------------------------
output.print_md("## 🧬 Parameter Transfer Complete")

if added:
    output.print_md("### ✅ Added")
    for n in added:
        output.print_md("- `{}`".format(n))

if overwritten:
    output.print_md("### ♻️ Overwritten")
    for n in overwritten:
        output.print_md("- `{}`".format(n))

if skipped:
    output.print_md("### ⚠️ Skipped")
    for n, msg in skipped:
        output.print_md("* `{}` — {} *".format(n, msg))
