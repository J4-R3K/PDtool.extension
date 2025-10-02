# -*- coding: utf-8 -*-
__title__ = 'Rename Text Styles (Regex)'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
import re, tempfile, os

from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ---------------------------------------
# 1. Collect all TextNoteTypes
text_types = list(FilteredElementCollector(doc).OfClass(TextNoteType).ToElements())
if not text_types:
    forms.alert("No Text Styles found.")
    script.exit()

# Build name map
name_map = {}
all_names = []
for t in text_types:
    name = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if name:
        name_map[name] = t
        all_names.append(name)

# ---------------------------------------
# 2. Show all names in a copyable file
temp_path = os.path.join(tempfile.gettempdir(), "text_styles_list.txt")
with open(temp_path, "w") as f:
    f.write("Current Text Styles:\n\n")
    for n in sorted(all_names):
        f.write("  - {}\n".format(n))

os.startfile(temp_path)


# ---------------------------------------
# 3. Select styles to rename
selected_names = forms.SelectFromList.show(
    sorted(all_names),
    multiselect=True,
    title="Select Text Styles to Rename (see text list for help)",
    button_name="Next"
)

if not selected_names:
    script.exit("Nothing selected.")

# ---------------------------------------
# 4. Ask for RegEx pattern + replacement
pattern = forms.ask_for_string(
    title="Regex Rename",
    prompt="RegEx pattern to match in style names:",
    default=""
)

replacement = forms.ask_for_string(
    title="Regex Replace",
    prompt="Replacement pattern (use \\1, \\2, etc.):",
    default=""
)

if not (pattern and replacement):
    script.exit("No pattern or replacement entered.")

# ---------------------------------------
# 5. Prepare renaming
renamed = []
skipped = []
existing_names = [n.lower() for n in all_names]
notes = list(FilteredElementCollector(doc).OfClass(TextNote).WhereElementIsNotElementType().ToElements())

with revit.Transaction("Rename Text Styles (Regex)"):

    for old_name in selected_names:
        try:
            new_name = re.sub(pattern, replacement, old_name)
        except Exception as e:
            skipped.append((old_name, "Regex failed: {}".format(e)))
            continue

        if new_name == old_name:
            skipped.append((old_name, "No change"))
            continue
        if new_name.lower() in existing_names:
            skipped.append((old_name, "Name already exists"))
            continue

        try:
            old_type = name_map[old_name]
            dup = old_type.Duplicate(new_name)
            new_id = dup if isinstance(dup, ElementId) else dup.Id

            # Reassign notes
            for note in notes:
                if note.GetTypeId() == old_type.Id:
                    note.ChangeTypeId(new_id)

            doc.Delete(old_type.Id)
            renamed.append((old_name, new_name))
            existing_names.append(new_name.lower())

        except Exception as e:
            skipped.append((old_name, str(e)))

# ---------------------------------------
# 6. Print summary
if renamed:
    output.print_md("### ✅ Renamed:")
    for oldn, newn in renamed:
        output.print_md("* `{}` ➜ `{}`".format(oldn, newn))

if skipped:
    output.print_md("### ⚠️ Skipped:")
    for oldn, msg in skipped:
        output.print_md("* `{}` – {}".format(oldn, msg))
