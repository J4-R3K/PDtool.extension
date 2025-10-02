# -*- coding: utf-8 -*-
__title__ = 'Delete Unused Text Styles'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ---------------------------------------
# 1. Collect all TextNoteTypes
text_types = list(FilteredElementCollector(doc).OfClass(TextNoteType).ToElements())

if not text_types:
    forms.alert("No Text Styles (TextNoteTypes) found.")
    script.exit()

# 2. Collect all TextNotes and track used types
used_type_ids = set(
    tn.GetTypeId().IntegerValue
    for tn in FilteredElementCollector(doc).OfClass(TextNote).WhereElementIsNotElementType()
)

# 3. Build selection list
items = []
unused_map = {}

for ttype in text_types:
    name = ttype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if not name:
        continue

    type_id = ttype.Id.IntegerValue
    if type_id in used_type_ids:
        label = "{}  —  (in use)".format(name)
    else:
        label = "{}  —  [UNUSED]".format(name)
        unused_map[label] = ttype

    items.append(label)

# 4. Prompt user to select unused styles
selectable = sorted([label for label in items if label in unused_map])
if not selectable:
    forms.alert("No unused Text Styles found.")
    script.exit()

selected = forms.SelectFromList.show(
    selectable,
    multiselect=True,
    title="Select Unused Text Styles to Delete",
    button_name="Delete Selected"
)

if not selected:
    script.exit("Nothing selected.")

# 5. Safe deletion
with Transaction(doc, "Delete Unused Text Styles") as t:
    t.Start()
    count = 0
    for label in selected:
        try:
            doc.Delete(unused_map[label].Id)
            count += 1
        except Exception as e:
            output.print_md("*Could not delete `{}` – {}*".format(label, e))
    t.Commit()

forms.alert("✅ Deleted {} unused Text Style(s).".format(count))
