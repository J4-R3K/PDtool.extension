# -*- coding: utf-8 -*-
__title__ = 'Delete Subcategories'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ------------------------------------------------------
# 1. Collect all subcategories from all top-level categories
subcat_map = {}

for cat in doc.Settings.Categories:
    if not cat.SubCategories:
        continue
    for subcat in cat.SubCategories:
        # Format: "Parent ➜ Subcategory"
        label = "{} ➜ {}".format(cat.Name, subcat.Name)
        subcat_map[label] = subcat

if not subcat_map:
    forms.alert("No subcategories found.")
    script.exit()

# ------------------------------------------------------
# 2. Check if each subcategory is used
label_usage = {}
for label, subcat in subcat_map.items():
    collector = FilteredElementCollector(doc).WhereElementIsNotElementType().OfCategoryId(subcat.Id)
    is_used = any(collector)
    status = "(in use)" if is_used else "[UNUSED]"
    full_label = "{}  —  {}".format(label, status)
    label_usage[full_label] = subcat

# ------------------------------------------------------
# 3. Prompt user to select subcategories to delete
selected = forms.SelectFromList.show(
    sorted(label_usage.keys()),
    multiselect=True,
    title="Select Subcategories to Delete",
    button_name="Delete Selected"
)

if not selected:
    script.exit("Nothing selected.")

# ------------------------------------------------------
# 4. Attempt deletion
with Transaction(doc, "Delete Subcategories") as t:
    t.Start()
    count = 0
    for label in selected:
        subcat = label_usage[label]
        try:
            doc.Delete(subcat.Id)
            count += 1
        except Exception as e:
            output.print_md("*Could not delete `{}` – {}*".format(subcat.Name, e))
    t.Commit()

forms.alert("✅ Attempted to delete {} subcategory(ies).".format(count))
