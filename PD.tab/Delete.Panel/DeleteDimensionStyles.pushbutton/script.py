# -*- coding: utf-8 -*-
__title__ = 'Delete Dimension Styles'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# 1. Collect all DimensionTypes
dim_styles = list(FilteredElementCollector(doc).OfClass(DimensionType).ToElements())

if not dim_styles:
    forms.alert("No Dimension Styles found.")
    script.exit()

# 2. Collect all Dimensions to identify used styles
used_type_ids = set(
    d.GetTypeId().IntegerValue
    for d in FilteredElementCollector(doc).OfClass(Dimension).WhereElementIsNotElementType()
)

# 3. Build selection list
items = []
unused_map = {}

for dstyle in dim_styles:
    name_param = dstyle.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if not name_param:
        continue
    name = name_param.AsString()
    if not name:
        continue

    type_id = dstyle.Id.IntegerValue
    if type_id in used_type_ids:
        label = "{}  —  (in use)".format(name)
    else:
        label = "{}  —  [UNUSED]".format(name)
        unused_map[label] = dstyle

    items.append(label)

# 4. Prompt user to select unused styles
selectable = sorted([label for label in items if label in unused_map])
if not selectable:
    forms.alert("No unused Dimension Styles found.")
    script.exit()

selected = forms.SelectFromList.show(
    selectable,
    multiselect=True,
    title="Select Unused Dimension Styles to Delete",
    button_name="Delete Selected"
)

if not selected:
    script.exit("Nothing selected.")

# 5. Safe deletion
with Transaction(doc, "Delete Unused Dimension Styles") as t:
    t.Start()
    count = 0
    for label in selected:
        try:
            doc.Delete(unused_map[label].Id)
            count += 1
        except Exception as e:
            output.print_md("*Could not delete `{}` – {}*".format(label, e))
    t.Commit()

forms.alert("✅ Deleted {} unused Dimension Style(s).".format(count))
