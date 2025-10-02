# -*- coding: utf-8 -*-
__title__ = 'Audit Parameters'
__author__ = 'Jarek Wityk @ PD'

import clr
import os
from collections import defaultdict

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from pyrevit import revit, script

# Get document
doc = revit.doc
uidoc = revit.uidoc

if doc is None:
    script.exit("No active Revit document. Open a model and try again.")

# Group parameters by (name, type, origin) -> [categories]
grouped_params = defaultdict(list)

# --- 1. Collect from all elements in all categories ---
collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
for el in collector:
    try:
        for param in el.Parameters:
            if param is None or param.Definition is None:
                continue

            defn = param.Definition
            name = defn.Name
            is_inst = param.IsInstance
            origin = "Built-In" if defn.BuiltInParameter != BuiltInParameter.INVALID else \
                     "Shared" if param.IsShared else "Family/Project"
            cat = el.Category.Name if el.Category else "No Category"

            key = (name, is_inst, origin)
            grouped_params[key].append(cat)
    except:
        continue

# --- 2. Add Project Parameters via BindingMap ---
binding_map = doc.ParameterBindings
it = binding_map.ForwardIterator()
it.Reset()
while it.MoveNext():
    try:
        definition = it.Key
        binding = it.Current
        is_inst = isinstance(binding, InstanceBinding)
        categories = [cat.Name for cat in binding.Categories]

        key = (definition.Name, is_inst, "Project")
        grouped_params[key].extend(categories)
    except:
        continue

# --- 3. Output results to pyRevit console ---
output = script.get_output()
output.print_md("## 🔍 Parameter Audit Results")
output.print_md("Showing all parameters grouped by name, type, and origin.\n")

summary = set()
for (name, is_inst, origin), cats in grouped_params.items():
    # Convert list to tuple to make hashable
    summary.add((name, "Instance" if is_inst else "Type", origin, tuple(sorted(set(cats)))))

sorted_output = sorted(list(summary), key=lambda x: (x[2], x[0].lower()))

for name, inst_type, origin, cats in sorted_output:
    output.print_md("- **{0}** ({1}) — _{2}_ in categories: `{3}`".format(
        name, inst_type, origin, ", ".join(cats)
    ))
