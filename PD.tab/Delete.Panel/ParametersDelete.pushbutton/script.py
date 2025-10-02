# -*- coding: utf-8 -*-
__title__ = 'Delete Parameters (Safe)'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms

doc = revit.doc
if doc is None:
    forms.alert("No active Revit document.")
    script.exit()

# ------------------------------------------------------------
# Collect all project parameters
def get_project_parameters():
    binding_map = doc.ParameterBindings
    it = binding_map.ForwardIterator()
    it.Reset()

    params = []
    while it.MoveNext():
        definition = it.Key
        binding = it.Current
        is_inst = isinstance(binding, InstanceBinding)
        category_names = ", ".join([c.Name for c in binding.Categories])
        params.append({
            'name': definition.Name,
            'type': 'Instance' if is_inst else 'Type',
            'categories': category_names,
            'definition': definition
        })
    return params

# ------------------------------------------------------------
# Main Logic
def main():
    param_data = get_project_parameters()

    if not param_data:
        forms.alert("No project parameters found.")
        return

    # Build list for UI selection
    items = [
        "{} [{}] - {}".format(p['name'], p['type'], p['categories'])
        for p in param_data
    ]

    selected = forms.SelectFromList.show(
        items,
        multiselect=True,
        title="Select Parameters to Delete",
        button_name="Delete Selected"
    )

    if not selected:
        forms.alert("No parameters selected.")
        return

    selected_defs = []
    for label in selected:
        for p in param_data:
            match = "{} [{}] - {}".format(p['name'], p['type'], p['categories'])
            if match == label:
                selected_defs.append((p['definition'], p['name']))
                break

    if not selected_defs:
        forms.alert("No matching definitions found.")
        return

    with Transaction(doc, "Delete Parameters") as t:
        t.Start()
        count = 0
        for definition, name in selected_defs:
            try:
                # Step 1: Remove binding
                doc.ParameterBindings.Remove(definition)

                # Step 2: Delete ParameterElement by Id
                param_elem = doc.GetElement(definition.Id)
                if param_elem:
                    doc.Delete(param_elem.Id)

                count += 1
            except Exception as e:
                script.get_output().print_md("*Could not delete `{}` – {}*".format(name, e))
        t.Commit()

    forms.alert("✅ Deleted {} parameter(s).".format(count))

# ------------------------------------------------------------
main()
