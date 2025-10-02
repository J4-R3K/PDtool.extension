# -*- coding: utf-8 -*-
__title__ = 'Reassign Text Styles'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# -----------------------------------
# 1. Collect all text styles (TextNoteTypes)
text_types = list(FilteredElementCollector(doc).OfClass(TextNoteType).ToElements())
type_name_map = {}
for t in text_types:
    name = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if name:
        type_name_map[name] = t

# 2. Collect all text notes and map styles in use
notes = list(FilteredElementCollector(doc).OfClass(TextNote).WhereElementIsNotElementType().ToElements())
used_type_ids = set(note.GetTypeId().IntegerValue for note in notes)

# Build in-use style list
used_styles = [name for name, t in type_name_map.items() if t.Id.IntegerValue in used_type_ids]
used_styles_sorted = sorted(used_styles)

# 3. Ask user: which styles to replace
selected_sources = forms.SelectFromList.show(
    used_styles_sorted,
    multiselect=True,
    title="Select Text Styles to Replace",
    button_name="Next"
)

if not selected_sources:
    script.exit("Nothing selected.")

# 4. Ask user: what style to switch to
available_targets = sorted([n for n in type_name_map if n not in selected_sources])
target_style_name = forms.SelectFromList.show(
    available_targets,
    multiselect=False,
    title="Select Target Text Style",
    button_name="Reassign To"
)

if not target_style_name:
    script.exit("No target selected.")

# Resolve IDs
source_type_ids = [type_name_map[name].Id for name in selected_sources]
target_type = type_name_map[target_style_name]
target_id = target_type.Id

# -----------------------------------
# 5. Reassign all matching notes
count = 0
with Transaction(doc, "Reassign Text Styles") as t:
    t.Start()
    for note in notes:
        if note.GetTypeId() in source_type_ids:
            note.ChangeTypeId(target_id)
            count += 1
    t.Commit()

forms.alert("✅ Reassigned {} text note(s) to style: {}".format(count, target_style_name))
