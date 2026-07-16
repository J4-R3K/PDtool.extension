# -*- coding: utf-8 -*-
__title__   = "Layers: Hide DWG Layers"
__doc__     = """Version = 1.0
Date    = 2026-03-11
________________________________________________________________
Description:

Scans all linked/imported DWG files in the project and hides
subcategories (layers) whose names match common AutoCAD
frozen/off naming patterns in the current view template.

IMPORTANT NOTE:
The Revit API cannot read the actual frozen/off state from
the original DWG file. Revit imports ALL layers regardless
of their AutoCAD state.

This tool uses two strategies:
1) Hide layers that are already hidden in the current view
   (they were likely turned off manually at some point)
2) Hide layers matching common "non-printable" patterns:
   DEFPOINTS, layers starting with underscore, etc.

For full control, use Tool 2 (Hide Picked DWG Layers) to
manually pick and hide specific DWG elements.

________________________________________________________________
How-To:

1. Run the tool
2. It scans all linked DWGs and their subcategories
3. Shows a summary of what will be hidden
4. Applies changes to the current view template

________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ImportInstance,
    ElementId,
    Transaction,
    View
)
from System.Collections.Generic import List

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()
log   = script.get_logger()


def exception_to_string(ex):
    try:
        return ex.ToString()
    except:
        return str(ex)


def get_view_template(view):
    """Return the view template applied to this view, or None."""
    try:
        vt_id = view.ViewTemplateId
        if vt_id and vt_id != ElementId.InvalidElementId:
            vt = doc.GetElement(vt_id)
            if vt and isinstance(vt, View):
                return vt
    except:
        pass
    return None


def collect_dwg_instances():
    """Collect all ImportInstance elements (linked/imported DWGs)."""
    try:
        return list(
            FilteredElementCollector(doc)
            .OfClass(ImportInstance)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except:
        return []


def get_dwg_subcategories(dwg_instances):
    """Get all subcategories (layers) from DWG instances.
    Returns dict: { dwg_name: [(subcat_name, subcat_id), ...] }"""

    result = {}

    for inst in dwg_instances:
        try:
            cat = inst.Category
            if cat is None:
                continue

            dwg_name = cat.Name
            if dwg_name not in result:
                result[dwg_name] = []

            sub_cats = cat.SubCategories
            if sub_cats:
                seen = set()
                for sc in sub_cats:
                    try:
                        if sc.Id.IntegerValue not in seen:
                            result[dwg_name].append(
                                (sc.Name, sc.Id))
                            seen.add(sc.Id.IntegerValue)
                    except:
                        pass
        except:
            pass

    return result


def get_hidden_layers(target_view, all_subcats):
    """Find which DWG subcategories are already hidden in the view.
    Returns list of (dwg_name, layer_name, cat_id) tuples."""

    hidden = []

    for dwg_name, layers in all_subcats.items():
        for layer_name, cat_id in layers:
            try:
                if target_view.GetCategoryHidden(cat_id):
                    hidden.append((dwg_name, layer_name, cat_id))
            except:
                pass

    return hidden


def get_visible_layers(target_view, all_subcats):
    """Find which DWG subcategories are visible in the view.
    Returns list of (dwg_name, layer_name, cat_id) tuples."""

    visible = []

    for dwg_name, layers in all_subcats.items():
        for layer_name, cat_id in layers:
            try:
                if not target_view.GetCategoryHidden(cat_id):
                    visible.append((dwg_name, layer_name, cat_id))
            except:
                pass

    return visible


def main():

    active_view = doc.ActiveView
    view_template = get_view_template(active_view)

    if view_template is None:
        forms.alert(
            "No view template assigned to the active view.\n\n"
            "Please assign a view template first.",
            exitscript=True
        )

    out.print_md("## DWG Layer Scan")
    out.print_md("* View template: `{}`".format(view_template.Name))

    # --- Collect DWGs ---
    dwg_instances = collect_dwg_instances()

    if not dwg_instances:
        forms.alert("No linked/imported DWG files found in project.",
                     exitscript=True)

    out.print_md("* DWG instances found: {}".format(len(dwg_instances)))

    # --- Get all subcategories ---
    all_subcats = get_dwg_subcategories(dwg_instances)

    total_layers = sum(len(v) for v in all_subcats.values())
    out.print_md("* Total DWG layers: {}".format(total_layers))

    if total_layers == 0:
        forms.alert("No DWG layers (subcategories) found.",
                     exitscript=True)

    # --- Get visible layers for multi-select ---
    visible = get_visible_layers(view_template, all_subcats)

    if not visible:
        forms.alert(
            "All DWG layers are already hidden in template '{}'.".format(
                view_template.Name),
            exitscript=True
        )

    # --- Build selection list ---
    # Format: "DWG_NAME | LAYER_NAME"
    options = []
    layer_map = {}  # display_string -> cat_id

    for dwg_name, layer_name, cat_id in sorted(
            visible, key=lambda x: (x[0], x[1])):
        display = "{} | {}".format(dwg_name, layer_name)
        options.append(display)
        layer_map[display] = cat_id

    # --- Multi-select ---
    selected = forms.SelectFromList.show(
        options,
        title="Select DWG Layers to HIDE in template",
        message="Currently visible layers in '{}'\n"
                "Select layers to hide:".format(view_template.Name),
        multiselect=True,
        button_name="Hide Selected"
    )

    if not selected:
        return

    # --- Apply ---
    t = Transaction(doc, "PD_pY Hide DWG Layers in Template")
    t.Start()

    try:
        hidden_count = 0

        for display in selected:
            cat_id = layer_map.get(display)
            if cat_id is None:
                continue
            try:
                view_template.SetCategoryHidden(cat_id, True)
                hidden_count += 1
                out.print_md("* Hidden: `{}`".format(display))
            except Exception as ex:
                out.print_md("* Failed: `{}` - `{}`".format(
                    display, exception_to_string(ex)))

        t.Commit()

    except Exception as ex:
        try:
            t.RollBack()
        except:
            pass
        forms.alert("Error:\n{}".format(exception_to_string(ex)),
                     exitscript=True)

    forms.alert(
        "Done.\n\n"
        "Hidden: {} layer(s)\n"
        "Template: {}".format(hidden_count, view_template.Name)
    )


if __name__ == "__main__":
    main()
