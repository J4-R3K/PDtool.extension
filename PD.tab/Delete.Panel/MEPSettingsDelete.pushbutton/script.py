# -*- coding: utf-8 -*-
__title__ = 'Delete Load Classifications'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *

from pyrevit import revit, forms, script

# ----------------------------------------------
doc = revit.doc
output = script.get_output()

if doc is None:
    forms.alert("No active document.")
    script.exit()

# ----------------------------------------------
# Collect only Load Classifications
elements = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
load_classes = [e for e in elements if e.GetType().Name == "ElectricalLoadClassification"]

if not load_classes:
    forms.alert("No Load Classifications found in this model.")
    script.exit()

# ----------------------------------------------
# Build UI list
items = []
label_map = {}
for lc in load_classes:
    label = "Load Classification: {}".format(lc.Name)
    items.append(label)
    label_map[label] = lc

selected = forms.SelectFromList.show(
    sorted(items),
    multiselect=True,
    title="Select Load Classifications to Delete",
    button_name="Delete Selected"
)

if not selected:
    script.exit("Nothing selected.")

# ----------------------------------------------
# Safe deletion
with Transaction(doc, "Delete Load Classifications") as t:
    t.Start()
    count = 0
    for label in selected:
        try:
            doc.Delete(label_map[label].Id)
            count += 1
        except Exception as e:
            output.print_md("*Could not delete `{}` – {}*".format(label, e))
    t.Commit()

forms.alert("✅ Deleted {} Load Classification(s).".format(count))
