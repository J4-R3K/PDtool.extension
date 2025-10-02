# -*- coding: utf-8 -*-
__title__ = 'List Filters in View'
__author__ = 'Jarek Wityk @ PD'

import clr
import os
import tempfile

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc

# ----------------------------------------
# 1. Collect views
views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
named_views = sorted([v for v in views if v.Name], key=lambda v: v.Name)

view_map = {}
view_labels = []
for v in named_views:
    label = "{}{}".format(v.Name, " [TEMPLATE]" if v.IsTemplate else "")
    view_labels.append(label)
    view_map[label] = v

selected_label = forms.SelectFromList.show(
    view_labels,
    multiselect=False,
    title="Select View or Template to List Filters"
)

if not selected_label:
    script.exit("No view selected.")

view = view_map[selected_label]

# ----------------------------------------
# 2. List filter names
filter_ids = view.GetFilters()
if not filter_ids:
    forms.alert("Selected view has no filters.")
    script.exit()

lines = []
lines.append("Filters applied to view '{}':\n".format(view.Name))

for fid in filter_ids:
    fe = doc.GetElement(fid)
    lines.append("- {}".format(fe.Name if fe else "Unknown Filter"))

# ----------------------------------------
# 3. Save to text file
temp_path = os.path.join(tempfile.gettempdir(), "filters_in_{}.txt".format(view.Name.replace(" ", "_")))
with open(temp_path, "w") as f:
    f.write("\n".join(lines))

forms.alert("Exported filter list to:\n{}".format(temp_path))
os.startfile(temp_path)
