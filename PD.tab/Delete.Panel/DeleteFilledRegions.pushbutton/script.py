# -*- coding: utf-8 -*-
__title__ = 'Delete Unused Filled Regions'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ---------------------------------------
# 1. Collect all FilledRegionTypes
region_types = list(FilteredElementCollector(doc).OfClass(FilledRegionType).ToElements())
if not region_types:
    forms.alert("No Filled Region Types found.")
    script.exit()

# 2. Collect used FilledRegion type Ids
used_ids = set(
    r.GetTypeId().IntegerValue
    for r in FilteredElementCollector(doc).OfClass(FilledRegion).WhereElementIsNotElementType()
)

# 3. Build selection list for unused types
items = []
unused_map = {}

for frt in region_types:
    name_param = frt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    name = name_param.AsString() if name_param else None
    if not name:
        continue

    label = "{}  —  [UNUSED]".format(name) if frt.Id.IntegerValue not in used_ids else "{}  —  (in use)"
    if frt.Id.IntegerValue not in used_ids:
        unused_map[label] = frt
    items.append(label)

# 4. Filter only deletable ones
selectable = sorted([label for label in items if label in unused_map])
if not selectable:
    forms.alert("No unused Filled Region Types found.")
    script.exit()

selected = forms.SelectFromList.show(
    selectable,
    multiselect=True,
    title="Select Unused Filled Region Types to Delete",
    button_name="Delete Selected"
)

if not selected:
    script.exit("Nothing selected.")

# ---------------------------------------
# 5. Delete selected unused types
with Transaction(doc, "Delete Unused Filled Region Types") as t:
    t.Start()
    count = 0
    for label in selected:
        try:
            doc.Delete(unused_map[label].Id)
            count += 1
        except Exception as e:
            output.print_md("*Could not delete `{}` – {}*".format(label, e))
    t.Commit()

forms.alert("✅ Deleted {} unused Filled Region Type(s).".format(count))
