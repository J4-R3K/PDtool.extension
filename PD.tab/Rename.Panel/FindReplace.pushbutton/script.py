# coding: utf-8
"""
Rename Text Types & Dimension Styles (System Families)
• Find & replace in type names (case-insensitive).
• Ensures unique names (_1, _2, ... if needed).
• Duplicate ➜ Swap ➜ Delete for safety.
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
from pyrevit import forms, revit, script

doc = revit.doc
output = script.get_output()

# 1️⃣ User input
CATEGORY_MAP = {
    "Text Types":        TextNoteType,
    "Dimension Styles":  DimensionType,
}

cat_choice = forms.SelectFromList.show(
    sorted(CATEGORY_MAP.keys()),
    title="Select Type Category to Rename"
)
if not cat_choice:
    script.exit()

find_text = forms.ask_for_string(prompt="Find text in type names:")
replace_text = forms.ask_for_string(prompt="Replace with:")
if not (find_text and replace_text):
    script.exit()

target_class = CATEGORY_MAP[cat_choice]
f_lc = find_text.lower()

# 2️⃣ Collect all elements of the selected class
elements = list(FilteredElementCollector(doc).OfClass(target_class))

def get_name(el):
    param = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return param.AsString() if param else ""

# All existing names
all_names = [get_name(el) for el in elements if get_name(el)]
name_set = set(n.lower() for n in all_names)

# Find matches
matches = []
for el in elements:
    name = get_name(el)
    if name and f_lc in name.lower():
        matches.append((el.Id, name))

if not matches:
    output.print_md("_No matching names for **{}**_".format(find_text))
    script.exit()

# 3️⃣ Collect instances to swap
INSTANCE_CLASSES = {
    "Text Types": TextNote,
    "Dimension Styles": Dimension
}
instance_class = INSTANCE_CLASSES.get(cat_choice)
inst_elems = list(FilteredElementCollector(doc).OfClass(instance_class).WhereElementIsNotElementType()) if instance_class else []

renamed = []
skipped = []

# 4️⃣ Rename via duplicate ➜ swap ➜ delete
with revit.Transaction("Rename {} (Safe Rename)".format(cat_choice)):
    for old_id, oldname in matches:
        old_type = doc.GetElement(old_id)
        if not old_type:
            continue

        base_new = oldname.replace(find_text, replace_text)
        new_name = base_new
        suffix = 1
        name_set.discard(oldname.lower())

        while new_name.lower() in name_set:
            new_name = "{}_{}".format(base_new, suffix)
            suffix += 1

        try:
            dup = old_type.Duplicate(new_name)
            new_id = dup if isinstance(dup, ElementId) else dup.Id

            for inst in inst_elems:
                if inst.GetTypeId() == old_id:
                    inst.ChangeTypeId(new_id)

            doc.Delete(old_id)
            name_set.add(new_name.lower())
            renamed.append((oldname, new_name))

        except Exception as err:
            skipped.append((oldname, str(err)))

# 5️⃣ Output results
if renamed:
    output.print_md("### ✅ Renamed:")
    for oldn, newn in renamed:
        output.print_md("* `{}` ➜ `{}`".format(oldn, newn))

if skipped:
    output.print_md("\n### ⚠️ Skipped:")
    for oldn, msg in skipped:
        output.print_md("* `{}` – {}".format(oldn, msg))
