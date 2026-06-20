# -*- coding: utf-8 -*-
__title__   = "Layers: Hide Picked Layers"
__doc__     = """Version = 1.0
Date    = 2026-03-11
________________________________________________________________
Description:

Pick DWG elements directly in the view, and hide their
layers (subcategories) in the current view template.

This is the quick way to hide specific DWG content:
just click on what you don't want to see.

Works with both linked and imported DWG files.

________________________________________________________________
How-To:

1. Run the tool
2. Pick one or more DWG elements in the view
3. Press Finish (green tick) to confirm
4. The layers those elements belong to are hidden
   in the current view template

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
    ElementId,
    Transaction,
    View,
    Options,
    GeometryInstance,
    GraphicsStyle
)
from Autodesk.Revit.UI.Selection import ObjectType
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


def pick_elements():
    """Prompt user to pick DWG elements.
    Returns list of picked Elements."""
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Pick DWG elements to hide their layers. "
            "Finish to apply, ESC cancels."
        )
    except:
        return []

    els = []
    for r in refs:
        try:
            els.append(doc.GetElement(r.ElementId))
        except:
            pass
    return els


def get_layer_from_subelement(element):
    """Try to get the DWG layer (subcategory) from a picked element.
    When you pick a DWG sub-element, its GraphicsStyleId points
    to the layer. Returns (layer_name, category_id) or None."""

    # Method 1: Direct category subcategory check
    # If user picked the ImportInstance itself, get all its subcats
    try:
        cat = element.Category
        if cat and cat.SubCategories and cat.SubCategories.Size > 0:
            # This is the parent DWG category, not a specific layer
            # We'll handle this case differently
            return None
    except:
        pass

    # Method 2: Check GraphicsStyleId on geometry objects
    try:
        opts = Options()
        opts.ComputeReferences = False
        geo = element.get_Geometry(opts)
        if geo:
            for g_obj in geo:
                if isinstance(g_obj, GeometryInstance):
                    inst_geo = g_obj.GetInstanceGeometry()
                    if inst_geo:
                        for sub_obj in inst_geo:
                            try:
                                gs_id = sub_obj.GraphicsStyleId
                                if gs_id and gs_id != ElementId.InvalidElementId:
                                    gs = doc.GetElement(gs_id)
                                    if gs and isinstance(gs, GraphicsStyle):
                                        gs_cat = gs.GraphicsStyleCategory
                                        if gs_cat:
                                            return (gs_cat.Name, gs_cat.Id)
                            except:
                                continue
    except:
        pass

    return None


def get_layers_from_dwg_element(element):
    """Extract DWG layer subcategory IDs from a picked element.
    Returns list of (dwg_name, layer_name, cat_id) tuples."""

    results = []
    seen = set()

    # The picked element might be the ImportInstance itself
    try:
        cat = element.Category
        if cat is None:
            return results
    except:
        return results

    # Check if this is a DWG parent category (has subcategories)
    try:
        sub_cats = cat.SubCategories
        if sub_cats and sub_cats.Size > 0:
            # This is the parent ImportInstance - extract from geometry
            opts = Options()
            opts.ComputeReferences = False
            geo = element.get_Geometry(opts)
            if geo:
                for g_obj in geo:
                    if isinstance(g_obj, GeometryInstance):
                        inst_geo = g_obj.GetInstanceGeometry()
                        if inst_geo:
                            for sub_obj in inst_geo:
                                try:
                                    gs_id = sub_obj.GraphicsStyleId
                                    if gs_id and \
                                            gs_id != ElementId.InvalidElementId:
                                        gs = doc.GetElement(gs_id)
                                        if gs and isinstance(gs, GraphicsStyle):
                                            gs_cat = gs.GraphicsStyleCategory
                                            if gs_cat and \
                                                    gs_cat.Id.IntegerValue \
                                                    not in seen:
                                                results.append((
                                                    cat.Name,
                                                    gs_cat.Name,
                                                    gs_cat.Id
                                                ))
                                                seen.add(
                                                    gs_cat.Id.IntegerValue)
                                except:
                                    continue
    except:
        pass

    # If we got layers from geometry, return them
    if results:
        return results

    # Fallback: the element's own category might be the layer itself
    try:
        parent = cat.Parent
        if parent:
            # cat is a subcategory (layer), parent is the DWG
            if cat.Id.IntegerValue not in seen:
                results.append((parent.Name, cat.Name, cat.Id))
                seen.add(cat.Id.IntegerValue)
    except:
        pass

    return results


def main():

    active_view = doc.ActiveView
    view_template = get_view_template(active_view)

    if view_template is None:
        forms.alert(
            "No view template assigned to the active view.\n\n"
            "Please assign a view template first.",
            exitscript=True
        )

    out.print_md("## Hide Picked DWG Layers")
    out.print_md("* View template: `{}`".format(view_template.Name))

    # --- Pick elements ---
    picked = pick_elements()

    if not picked:
        forms.alert("Nothing picked.", exitscript=True)

    out.print_md("* Picked: {} element(s)".format(len(picked)))

    # --- Extract layers ---
    all_layers = []  # (dwg_name, layer_name, cat_id)
    seen_ids = set()

    for el in picked:
        layers = get_layers_from_dwg_element(el)
        for dwg_name, layer_name, cat_id in layers:
            if cat_id.IntegerValue not in seen_ids:
                all_layers.append((dwg_name, layer_name, cat_id))
                seen_ids.add(cat_id.IntegerValue)

    if not all_layers:
        forms.alert(
            "Could not identify DWG layers from the picked elements.\n\n"
            "Make sure you are picking elements inside a linked/imported "
            "DWG file.",
            exitscript=True
        )

    # --- Show what will be hidden ---
    out.print_md("### Layers to hide:")
    display_lines = []
    for dwg_name, layer_name, cat_id in sorted(
            all_layers, key=lambda x: (x[0], x[1])):
        line = "{} | {}".format(dwg_name, layer_name)
        display_lines.append(line)
        out.print_md("* `{}`".format(line))

    # --- Confirm with multi-select (user can deselect) ---
    layer_map = {}
    options = []
    for dwg_name, layer_name, cat_id in sorted(
            all_layers, key=lambda x: (x[0], x[1])):
        display = "{} | {}".format(dwg_name, layer_name)
        options.append(display)
        layer_map[display] = cat_id

    selected = forms.SelectFromList.show(
        options,
        title="Confirm Layers to HIDE",
        message="These layers were found on picked elements.\n"
                "Deselect any you want to keep visible:",
        multiselect=True,
        button_name="Hide Selected"
    )

    if not selected:
        return

    # --- Apply to view template ---
    t = Transaction(doc, "PD_pY Hide Picked DWG Layers")
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
