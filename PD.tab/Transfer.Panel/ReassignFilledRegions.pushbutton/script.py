# -*- coding: utf-8 -*-
__title__ = 'Reassign Filled Regions'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ---------------------------------------
# 1. Collect all FilledRegionTypes
type_elements = list(FilteredElementCollector(doc).OfClass(FilledRegionType).ToElements())
type_name_map = {}
for t in type_elements:
    name = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if name:
        type_name_map[name] = t

# 2. Collect placed FilledRegions and find used types
regions = list(FilteredElementCollector(doc).OfClass(FilledRegion).WhereElementIsNotElementType().ToElements())
used_type_ids = set(r.GetTypeId().IntegerValue for r in regions)

# Map used types to names
used_type_names = [n for n, t in type_name_map.items() if t.Id.IntegerValue in used_type_ids]
used_type_names_sorted = sorted(used_type_names)

# 3. Prompt user: select type(s) to reassign
selected_sources = forms.SelectFromList.show(
    used_type_names_sorted,
    multiselect=True,
    title="Select Filled Region Types to Replace",
    button_name="Next"
)

if not selected_sources:
    script.exit("Nothing selected.")

# 4. Prompt user: target type
available_targets = sorted([n for n in type_name_map if n not in selected_sources])
target_type_name = forms.SelectFromList.show(
    available_targets,
    multiselect=False,
    title="Select Target Filled Region Type",
    button_name="Reassign To"
)

if not target_type_name:
    script.exit("No target selected.")

# Resolve ElementIds
source_ids = [type_name_map[n].Id for n in selected_sources]
target_id = type_name_map[target_type_name].Id

# ---------------------------------------
# 5. Perform reassignment
count = 0
with Transaction(doc, "Reassign Filled Region Types") as t:
    t.Start()
    for r in regions:
        if r.GetTypeId() in source_ids:
            r.ChangeTypeId(target_id)
            count += 1
    t.Commit()

forms.alert("✅ Reassigned {} filled region(s) to: {}".format(count, target_type_name))
