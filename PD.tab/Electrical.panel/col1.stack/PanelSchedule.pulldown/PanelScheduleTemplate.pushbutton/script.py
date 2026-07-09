# -*- coding: utf-8 -*-
__title__   = "Update: Panel Schedule Template"
__doc__     = """Version = 1.1
Date    = 20.12.2025
________________________________________________________________
Description:

Select multiple Panel Schedules (PanelScheduleView) and apply one PanelScheduleTemplate
to all of them using PanelScheduleView.GenerateInstanceFromTemplate(templateId).

Notes:
- Some templates are only compatible with certain panel schedule types (Branch/Data/Switchboard).
  Incompatible schedules are skipped and reported.
- Uses SubTransaction per schedule for safety.

Author: Jarek Wityk
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import FilteredElementCollector, Transaction, SubTransaction
from Autodesk.Revit.DB.Electrical import PanelScheduleView, PanelScheduleTemplate

from pyrevit import revit, forms, script


doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

if doc is None:
    forms.alert("No active Revit document.", exitscript=True)


# ------------------------------------------------------------
# Helpers
def _safe_str(x):
    try:
        return str(x)
    except:
        return "<unreadable>"


def make_unique_label(base_label, existing_map):
    """
    Ensure label uniqueness WITHOUT showing ElementId.
    If base_label already exists, append ' (2)', ' (3)', ...
    """
    if base_label not in existing_map:
        return base_label

    idx = 2
    while True:
        candidate = "{} ({})".format(base_label, idx)
        if candidate not in existing_map:
            return candidate
        idx += 1


def get_panel_name(ps_view):
    """Try to get the associated electrical panel element name."""
    try:
        panel_id = ps_view.GetPanel()  # returns ElementId
        if panel_id and panel_id.IntegerValue > 0:
            panel_el = doc.GetElement(panel_id)
            if panel_el:
                return panel_el.Name
    except:
        pass
    return "Unknown"


def get_template_elem_from_view(ps_view):
    """Get the PanelScheduleTemplate element currently used by this panel schedule view."""
    try:
        tid = ps_view.GetTemplate()  # returns ElementId
        if tid and tid.IntegerValue > 0:
            return doc.GetElement(tid)
    except:
        pass
    return None


def get_template_type_str(tmpl):
    """Return human-friendly template type."""
    if tmpl is None:
        return "Unknown"
    try:
        # Newer API exposes these as properties (bool)
        if hasattr(tmpl, "IsBranchPanelSchedule") and tmpl.IsBranchPanelSchedule:
            return "Branch"
        if hasattr(tmpl, "IsDataPanelSchedule") and tmpl.IsDataPanelSchedule:
            return "Data"
        if hasattr(tmpl, "IsSwitchboardSchedule") and tmpl.IsSwitchboardSchedule:
            return "Switchboard"
    except:
        pass

    # Fallback: try method GetPanelScheduleType()
    try:
        if hasattr(tmpl, "GetPanelScheduleType"):
            return _safe_str(tmpl.GetPanelScheduleType())
    except:
        pass

    return "Unknown"


def make_view_label(ps_view):
    """
    Build a readable label for SelectFromList WITHOUT showing element ids.
    (Uniqueness handled separately by make_unique_label)
    """
    vname = ps_view.Name
    pname = get_panel_name(ps_view)

    tmpl = get_template_elem_from_view(ps_view)
    tname = tmpl.Name if tmpl else "Unknown"
    ttype = get_template_type_str(tmpl)

    return "{}  |  Panel: {}  |  Template: {} ({})".format(
        vname, pname, tname, ttype
    )


def make_template_label(tmpl):
    """
    Build a readable label for template selection WITHOUT showing element ids.
    (Uniqueness handled separately by make_unique_label)
    """
    tname = tmpl.Name
    ttype = get_template_type_str(tmpl)

    is_default = ""
    try:
        if hasattr(tmpl, "IsDefault") and tmpl.IsDefault:
            is_default = " (Default)"
    except:
        pass

    return "{}{}  |  Type: {}".format(tname, is_default, ttype)


# ------------------------------------------------------------
# Collect panel schedules (instances)
all_ps_views = list(FilteredElementCollector(doc).OfClass(PanelScheduleView).ToElements())
if not all_ps_views:
    forms.alert("No Panel Schedules found in this project.", exitscript=True)

panel_schedules = []
for v in all_ps_views:
    # Some API versions allow panel schedule templates to appear as PanelScheduleView;
    # exclude them if possible.
    try:
        if hasattr(v, "IsPanelScheduleTemplate") and v.IsPanelScheduleTemplate():
            continue
    except:
        pass
    panel_schedules.append(v)

if not panel_schedules:
    forms.alert("No Panel Schedule instances found (only templates were found).", exitscript=True)

# Build selection list (no IDs, but guaranteed-unique labels)
view_label_map = {}
view_items = []
for v in panel_schedules:
    base_lbl = make_view_label(v)
    lbl = make_unique_label(base_lbl, view_label_map)
    view_items.append(lbl)
    view_label_map[lbl] = v

selected_view_labels = forms.SelectFromList.show(
    sorted(view_items),
    multiselect=True,
    title="Select Panel Schedules (multi-select)",
    button_name="Next"
)

if not selected_view_labels:
    script.exit()

selected_views = [view_label_map[lbl] for lbl in selected_view_labels if lbl in view_label_map]
if not selected_views:
    forms.alert("Nothing selected.", exitscript=True)

# Detect selected schedule types (based on their current template)
selected_types = set()
for v in selected_views:
    tmpl = get_template_elem_from_view(v)
    ttype = get_template_type_str(tmpl)
    if ttype:
        selected_types.add(ttype)

# ------------------------------------------------------------
# Collect templates
templates = list(FilteredElementCollector(doc).OfClass(PanelScheduleTemplate).ToElements())
if not templates:
    forms.alert("No Panel Schedule Templates found in this project.", exitscript=True)

tmpl_data = []
for t in templates:
    base_label = make_template_label(t)
    tmpl_data.append((base_label, t, get_template_type_str(t)))

# If all selected schedules share the same known type, filter templates to that type
known_types = [t for t in list(selected_types) if t and t != "Unknown"]
filter_type = known_types[0] if len(known_types) == 1 else None

if filter_type:
    filtered = [x for x in tmpl_data if x[2] == filter_type]
    if filtered:
        tmpl_data = filtered

# Build template selection list (no IDs, but guaranteed-unique labels)
tmpl_label_map = {}
tmpl_items = []
for (base_lbl, t, ttype) in tmpl_data:
    lbl = make_unique_label(base_lbl, tmpl_label_map)
    tmpl_items.append(lbl)
    tmpl_label_map[lbl] = t

selected_tmpl_label = forms.SelectFromList.show(
    sorted(tmpl_items),
    multiselect=False,
    title="Select Target Panel Schedule Template",
    button_name="Apply"
)

if not selected_tmpl_label:
    script.exit()

target_template = tmpl_label_map.get(selected_tmpl_label)
if target_template is None:
    forms.alert("Could not resolve selected template.", exitscript=True)

# Check API availability
if not hasattr(PanelScheduleView, "GenerateInstanceFromTemplate"):
    forms.alert(
        "Your Revit API does not expose PanelScheduleView.GenerateInstanceFromTemplate().\n"
        "This tool requires that method to apply templates to existing schedules.",
        exitscript=True
    )

# ------------------------------------------------------------
# Apply template
changed = 0
skipped = []

t = Transaction(doc, "Apply Panel Schedule Template (Batch)")
t.Start()
try:
    for v in selected_views:
        st = SubTransaction(doc)
        st.Start()
        try:
            v.GenerateInstanceFromTemplate(target_template.Id)
            st.Commit()
            changed += 1
        except Exception as ex:
            try:
                st.RollBack()
            except:
                pass
            skipped.append((v.Name, _safe_str(ex)))
    t.Commit()
except Exception as big_ex:
    try:
        t.RollBack()
    except:
        pass
    forms.alert("Batch apply failed:\n{}".format(_safe_str(big_ex)), exitscript=True)

# ------------------------------------------------------------
# Report
msg = "✅ Applied template:\n{}\n\nUpdated: {}\nSkipped: {}".format(
    target_template.Name, changed, len(skipped)
)
forms.alert(msg)

output.print_md("## Panel Schedule Template Batch Apply")
output.print_md("- **Template:** `{}`".format(target_template.Name))
output.print_md("- **Updated:** `{}`".format(changed))
output.print_md("- **Skipped:** `{}`".format(len(skipped)))

if skipped:
    output.print_md("\n### ⚠️ Skipped schedules (likely incompatible template type/config):")
    for name, err in skipped:
        output.print_md("* `{}` — {}".format(name, err))
