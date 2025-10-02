# coding: utf-8
# Export Selected Revit Data to CSV
# Author: Jarek Wityk @ PD

import os
import csv
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BuiltInCategory
from Autodesk.Revit.DB.Electrical import WireType  # ✅ required for wiring types

from pyrevit import forms, revit, DB, script

# Ensure a Revit document is open
doc = revit.doc
if not doc:
    forms.alert('No Revit document is open.', exitscript=True)

# ------------------------------------------------------------
# Data collection functions

def get_view_templates(doc):
    return [v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if v.IsTemplate]

def get_filters(doc):
    return [f.Name for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)]

def get_schedules(doc):
    return [s.Name for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule)]

def get_project_parameters(doc):
    params = []
    binding_map = doc.ParameterBindings
    it = binding_map.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        definition = it.Key
        param_type = "Shared Parameter" if hasattr(definition, "IsShared") and definition.IsShared else "Project Parameter"
        params.append((definition.Name, param_type))
    return params

def get_line_styles(doc):
    lines_category = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    subcats = lines_category.SubCategories
    return [sc.Name for sc in subcats]

def get_line_patterns(doc):
    return [lp.Name for lp in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement)]

def get_fill_patterns(doc):
    return [fp.Name for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)]

def get_worksets(doc):
    return [ws.Name for ws in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)]

def get_text_types(doc):
    return [tt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            for tt in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType)]

def get_dimension_styles(doc):
    return [dt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            for dt in DB.FilteredElementCollector(doc).OfClass(DB.DimensionType)]

def get_load_classifications(doc):
    elems = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
    return [e.Name for e in elems if e.GetType().Name == "ElectricalLoadClassification"]

def get_wiring_types(doc):
    wiring_types = DB.FilteredElementCollector(doc)\
        .OfClass(WireType)\
        .WhereElementIsElementType()\
        .ToElements()
    return [wt.Name for wt in wiring_types if wt.Name]
    
def get_loaded_families(doc):
    families = DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements()
    return sorted(set([fam.Name for fam in families if fam.Name]))


# ------------------------------------------------------------
# UI Selection: category ➜ function map

category_functions = {
    "View Templates": get_view_templates,
    "Filters": get_filters,
    "Schedules": get_schedules,
    "Project Parameters": get_project_parameters,
    "Line Styles": get_line_styles,
    "Line Patterns": get_line_patterns,
    "Fill Patterns": get_fill_patterns,
    "Worksets": get_worksets,
    "Text Types": get_text_types,
    "Dimension Styles": get_dimension_styles,
    "Electrical Load Classifications": get_load_classifications,
    "Electrical Wiring Types": get_wiring_types,
    "Loaded Families": get_loaded_families
}

# Ask user to select categories
selected = forms.SelectFromList.show(category_functions.keys(),
                                     multiselect=True,
                                     title='Select Data Categories to Export')
if not selected:
    forms.alert('No categories selected.', exitscript=True)

# ------------------------------------------------------------
# Ask where to save CSV
save_path = forms.save_file(file_ext='csv', title='Save Exported Data As')
if not save_path:
    forms.alert('No file selected to save.', exitscript=True)

# ------------------------------------------------------------
# Collect selected data

export_data = []

for category in selected:
    try:
        if category == "Project Parameters":
            items = category_functions[category](doc)
            for name, param_type in items:
                export_data.append([category, name, param_type])
        else:
            names = category_functions[category](doc)
            for name in names:
                export_data.append([category, name, ""])
    except Exception as e:
        export_data.append([category, 'Error collecting: {}'.format(str(e)), ""])

# Ensure folder exists
folder = os.path.dirname(save_path)
if not os.path.exists(folder):
    os.makedirs(folder)

# ------------------------------------------------------------
# Write to CSV (IronPython-safe)
try:
    with open(save_path, 'wb') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Category', 'Name', 'Type'])
        for row in export_data:
            writer.writerow(row)
except IOError as e:
    forms.alert("⚠️ Could not save the file.\n\n{}\n\nClose the file if it is open.".format(str(e)), exitscript=True)

# ------------------------------------------------------------
forms.alert('✅ Export complete!\nSaved to:\n{}'.format(save_path))
