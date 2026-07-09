# -*- coding: utf-8 -*-
__title__   = "Viewport: Audit All Viewport Types"
__doc__     = """Version = 1.0
Date    = 20.12.2025
________________________________________________________________
Description:

Lists all used viewport types with counts for safe manual reassignment and purging.

Relative Path:
...\
________________________________________________________________
How-To:

1. Click on...

________________________________________________________________
Get Free:
________________________________________________________________
Author: Jarek Wityk"""

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import *
from pyrevit import revit, script

doc = revit.doc
output = script.get_output()
output.print_md("## 📊 Viewport Type Usage Audit\n")

# 1. Collect all Viewport ElementTypes (no usage filter)
all_types = FilteredElementCollector(doc).OfClass(ElementType).ToElements()

viewport_types = []
for t in all_types:
    if t.Category and t.Category.Id.IntegerValue == int(BuiltInCategory.OST_Viewports):
        viewport_types.append(t)

if not viewport_types:
    output.print_md("_No viewport types found in model._")
    script.exit()

# 2. Track used types by Viewport elements
used_ids = set(
    vp.GetTypeId().IntegerValue
    for vp in FilteredElementCollector(doc).OfClass(Viewport).ToElements()
)

# 3. Output all types with usage tag
output.print_md("Found **{}** viewport type(s):\n".format(len(viewport_types)))


def _type_name(t):
    name_param = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    name = name_param.AsString() if name_param else None
    return name if name else "(Unnamed)"


for t in sorted(viewport_types, key=lambda x: _type_name(x).lower()):
    name = _type_name(t)
    is_used = "✔ In Use" if t.Id.IntegerValue in used_ids else "❌ Not Used"
    output.print_md("- **{}** — `{}`".format(name, is_used))

output.print_md("\n### What to Do:\n")
output.print_md("1. _Reassign instances of types you want to remove_")
output.print_md("2. _Use **Purge Unused** to delete unused types (marked ❌)_")
output.print_md("3. _You can’t delete types in use unless you reassign them_")
