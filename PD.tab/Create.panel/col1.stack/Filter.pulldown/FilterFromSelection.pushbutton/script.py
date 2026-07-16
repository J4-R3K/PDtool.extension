# -*- coding: utf-8 -*-
__title__   = "Create: Filter\nfrom Selection"
__doc__     = """Version = 1.3
Date    = 2026-03-08
________________________________________________________________
Description:

Create a visibility filter from a selected element (works with
elements in linked models too).

Workflow:
1) Pick an element (use TAB to reach linked elements)
2) Script reads the element's parameters
3) Defaults to 'Family and Type' - or pick any other parameter
4) If 'Family and Type' chosen, pick sub-option:
   - Family and Type (full string)
   - Family Name only
   - Type Name only
5) Type the text string to filter by (pre-filled from the value)
6) Filter is created with a 'contains' rule
6) Filter is added to the current view template (if assigned)
   with RED line override and visibility ON
7) If no view template is assigned, filter is added to the view

Filter naming: PD_pY_<CategoryShort>_<SearchString>

________________________________________________________________
How-To:

1. Run the tool from the pyRevit ribbon
2. Pick one element (TAB into links if needed)
3. Choose parameter (default: Family and Type)
4. Confirm or edit the filter string
5. Filter is created and applied with red lines

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
    ParameterFilterElement,
    ElementParameterFilter,
    ParameterFilterRuleFactory,
    ElementId,
    BuiltInParameter,
    OverrideGraphicSettings,
    Color,
    Transaction,
    Category,
    View
)
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()
log   = script.get_logger()


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------

def _create_contains_rule(param_id, value):
    """Version-safe 'contains' rule: Revit 2023+ removed the
    3-arg (caseSensitive) overload of CreateContainsRule."""
    try:
        return ParameterFilterRuleFactory.CreateContainsRule(
            param_id, value)
    except Exception:
        return ParameterFilterRuleFactory.CreateContainsRule(
            param_id, value, False)


def exception_to_string(ex):
    try:
        return ex.ToString()
    except:
        return str(ex)


def get_element_from_pick():
    """Pick an element, handling linked elements.
    Returns (element, is_from_link) tuple."""
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Pick an element (TAB into links). ESC cancels."
        )
    except:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                "Pick an element. ESC cancels."
            )
        except:
            return None, False

    if ref is None:
        return None, False

    # Linked element
    try:
        link_instance = doc.GetElement(ref.ElementId)
        linked_ref = ref.LinkedElementId
        if linked_ref and linked_ref != ElementId.InvalidElementId:
            link_doc = link_instance.GetLinkDocument()
            if link_doc:
                linked_el = link_doc.GetElement(linked_ref)
                return linked_el, True
    except:
        pass

    # Regular element
    try:
        el = doc.GetElement(ref.ElementId)
        return el, False
    except:
        return None, False


def get_family_type_parts(element):
    """Read Family Name and Type Name separately.
    Returns (family_name, type_name, combined) tuple."""
    fname = ""
    tname = ""
    combined = ""

    # Try reading combined value first
    try:
        p = element.get_Parameter(
            BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM)
        if p and p.HasValue:
            val = p.AsValueString()
            if val:
                combined = val
    except:
        pass

    # Read individual parts from the element type
    try:
        el_doc = element.Document
        el_type = el_doc.GetElement(element.GetTypeId())
        if el_type:
            try:
                fp = el_type.get_Parameter(
                    BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if fp and fp.HasValue:
                    fname = fp.AsString() or ""
            except:
                pass
            try:
                tp = el_type.get_Parameter(
                    BuiltInParameter.ALL_MODEL_TYPE_NAME)
                if tp and tp.HasValue:
                    tname = tp.AsString() or ""
            except:
                pass

            # If combined still empty, try SYMBOL_FAMILY_AND_TYPE
            if not combined:
                try:
                    sp = el_type.get_Parameter(
                        BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM)
                    if sp and sp.HasValue:
                        combined = sp.AsString() or ""
                except:
                    pass
    except:
        pass

    # Build combined from parts if still empty
    if not combined and (fname or tname):
        combined = "{} : {}".format(fname, tname).strip(" :")

    return fname, tname, combined


def get_string_params(element):
    """Get all readable parameters.
    Returns list of (display_name, value, param_name) tuples."""
    results = []
    seen = set()

    fname, tname, combined = get_family_type_parts(element)
    if combined:
        results.append(("Family and Type", combined, "Family and Type"))
        seen.add("Family and Type")

    try:
        for p in element.Parameters:
            try:
                name = p.Definition.Name
                if name in seen:
                    continue
                if p.HasValue:
                    val = None
                    storage = p.StorageType.ToString()
                    if storage == "String":
                        val = p.AsString()
                    else:
                        val = p.AsValueString()
                    if val and len(val.strip()) > 0:
                        results.append((name, val, name))
                        seen.add(name)
            except:
                pass
    except:
        pass

    return results


def get_host_category_id(element):
    """Get category Id usable in the host document."""
    cat = None
    try:
        cat = element.Category
    except:
        return None

    if cat is None:
        return None

    cat_id = cat.Id

    try:
        host_cat = Category.GetCategory(doc, cat_id)
        if host_cat:
            return cat_id
    except:
        pass

    try:
        cat_name = cat.Name
        for c in doc.Settings.Categories:
            try:
                if c.Name == cat_name:
                    return c.Id
            except:
                pass
    except:
        pass

    return cat_id


def find_filterable_param_id(param_name, element, cat_id):
    """Find a parameter ElementId that is valid for filter rules
    on the given category."""

    cat_ids = List[ElementId]()
    cat_ids.Add(cat_id)

    if param_name in ("Family and Type", "Family Name", "Type Name"):
        if param_name == "Family Name":
            candidates = [
                "ALL_MODEL_FAMILY_NAME",
                "ELEM_FAMILY_AND_TYPE_PARAM",
                "SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM",
            ]
        elif param_name == "Type Name":
            candidates = [
                "ALL_MODEL_TYPE_NAME",
                "SYMBOL_NAME_PARAM",
                "ELEM_FAMILY_AND_TYPE_PARAM",
                "SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM",
            ]
        else:
            candidates = [
                "ELEM_FAMILY_AND_TYPE_PARAM",
                "SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM",
                "ELEM_TYPE_PARAM",
                "SYMBOL_NAME_PARAM",
                "ALL_MODEL_FAMILY_NAME",
                "ALL_MODEL_TYPE_NAME",
            ]
        for bip_name in candidates:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            param_id = ElementId(bip)
            try:
                rule = _create_contains_rule(param_id, "test")
                test_filter = ElementParameterFilter(rule)
                if ParameterFilterElement.AllRuleParametersApplicable(
                        doc, cat_ids, test_filter):
                    return param_id
            except:
                continue
        return None

    # Other parameters
    try:
        for p in element.Parameters:
            try:
                if p.Definition.Name == param_name:
                    # Try BuiltInParameter
                    try:
                        bip = p.Definition.BuiltInParameter
                        if bip and str(bip) != "INVALID":
                            param_id = ElementId(bip)
                            try:
                                rule = _create_contains_rule(
                                    param_id, "test")
                                tf = ElementParameterFilter(rule)
                                if ParameterFilterElement \
                                        .AllRuleParametersApplicable(
                                            doc, cat_ids, tf):
                                    return param_id
                            except:
                                pass
                    except:
                        pass
                    # Try param Id directly
                    try:
                        param_id = p.Id
                        rule = _create_contains_rule(
                            param_id, "test")
                        tf = ElementParameterFilter(rule)
                        if ParameterFilterElement \
                                .AllRuleParametersApplicable(
                                    doc, cat_ids, tf):
                            return param_id
                    except:
                        pass
            except:
                pass
    except:
        pass

    return None


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


def shorten_category(cat_name):
    """Make a short abbreviation from category name."""
    if not cat_name:
        return "El"
    # Take first letters of each word, max 8 chars
    parts = cat_name.replace("-", " ").split()
    if len(parts) == 1:
        return cat_name[:8]
    abbr = "".join([w[0].upper() for w in parts if w])
    return abbr[:8]


def generate_filter_name(cat_name, search_string):
    """Generate filter name: PD_pY_<CatShort>_<SearchString>"""
    cat_short = shorten_category(cat_name)
    s = search_string.replace(" ", "_").replace(":", "")
    # Remove characters not allowed in Revit names
    allowed = []
    for c in s:
        if c.isalnum() or c in ("_", "-"):
            allowed.append(c)
    s = "".join(allowed)
    if len(s) > 40:
        s = s[:40]
    return "PD_pY_{}_{}".format(cat_short, s)


def add_filter_to_target(target_view, filter_element, is_template):
    """Add filter to a view or view template with red line override.
    Returns True on success."""

    label = "view template" if is_template else "view"

    # Check if already applied
    try:
        existing_filters = target_view.GetFilters()
        for fid in existing_filters:
            if fid.IntegerValue == filter_element.Id.IntegerValue:
                # Already there — just update override
                ogs = OverrideGraphicSettings()
                red = Color(255, 0, 0)
                try:
                    ogs.SetProjectionLineColor(red)
                except:
                    pass
                try:
                    ogs.SetCutLineColor(red)
                except:
                    pass
                target_view.SetFilterOverrides(filter_element.Id, ogs)
                out.print_md("* Filter already on {} — updated override"
                             .format(label))
                return True
    except:
        pass

    # Add new
    try:
        target_view.AddFilter(filter_element.Id)
        target_view.SetFilterVisibility(filter_element.Id, True)

        ogs = OverrideGraphicSettings()
        red = Color(255, 0, 0)
        try:
            ogs.SetProjectionLineColor(red)
        except:
            pass
        try:
            ogs.SetCutLineColor(red)
        except:
            pass
        target_view.SetFilterOverrides(filter_element.Id, ogs)
        return True
    except Exception as ex:
        out.print_md("* Failed to add filter to {}: `{}`".format(
            label, exception_to_string(ex)))
        return False


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------

def main():

    # --- 1) Pick element ---
    element, is_linked = get_element_from_pick()
    if element is None:
        forms.alert("Nothing picked.", exitscript=True)

    link_note = " (from link)" if is_linked else ""

    cat_name = "None"
    try:
        cat_name = element.Category.Name if element.Category else "None"
    except:
        pass

    out.print_md("## Picked element{}".format(link_note))
    try:
        out.print_md("* Id: {}".format(element.Id.IntegerValue))
        out.print_md("* Category: `{}`".format(cat_name))
    except:
        pass

    # --- 2) Read parameters ---
    params = get_string_params(element)
    if not params:
        forms.alert("No readable parameters on this element.",
                     exitscript=True)

    # --- 3) Pick parameter ---
    param_options = []
    for display_name, val, filter_name in params:
        line = "{} = {}".format(display_name, val)
        if len(line) > 100:
            line = line[:100] + "..."
        param_options.append(line)

    selected = forms.CommandSwitchWindow.show(
        param_options,
        message="Pick parameter for filter:"
    )
    if not selected:
        return

    sel_index = param_options.index(selected)
    param_display = params[sel_index][0]
    param_value   = params[sel_index][1]
    param_filter  = params[sel_index][2]

    # --- 3b) If Family and Type, offer sub-choice ---
    if param_filter == "Family and Type":
        fname, tname, combined = get_family_type_parts(element)

        ft_options = []
        if combined:
            ft_options.append(
                "Family and Type = {}".format(combined))
        if fname:
            ft_options.append(
                "Family Name = {}".format(fname))
        if tname:
            ft_options.append(
                "Type Name = {}".format(tname))

        if len(ft_options) > 1:
            ft_selected = forms.CommandSwitchWindow.show(
                ft_options,
                message="Filter by which part?"
            )
            if not ft_selected:
                return

            if ft_selected.startswith("Family Name"):
                param_display = "Family Name"
                param_value = fname
                param_filter = "Family Name"
            elif ft_selected.startswith("Type Name"):
                param_display = "Type Name"
                param_value = tname
                param_filter = "Type Name"
            # else keep Family and Type as-is

    # --- 4) Confirm/edit string ---
    search_string = forms.ask_for_string(
        default=param_value,
        prompt="Filter string ('contains', case-insensitive).\n"
               "Edit for partial match:",
        title="Filter String"
    )
    if not search_string:
        return

    # --- 5) Category ---
    cat_id = get_host_category_id(element)
    if cat_id is None:
        forms.alert("Cannot determine element category.",
                     exitscript=True)

    cat_ids = List[ElementId]()
    cat_ids.Add(cat_id)

    # --- 6) Parameter ---
    param_id = find_filterable_param_id(param_filter, element, cat_id)
    if param_id is None:
        forms.alert(
            "Parameter '{}' cannot be used in a filter\n"
            "for category '{}'.\n\n"
            "Try a different parameter.".format(
                param_display, cat_name),
            exitscript=True
        )

    out.print_md("* Parameter: `{}`".format(param_display))
    out.print_md("* Search: `{}`".format(search_string))

    # --- 7) Filter name ---
    filter_name = generate_filter_name(cat_name, search_string)

    existing = FilteredElementCollector(doc) \
        .OfClass(ParameterFilterElement) \
        .ToElements()

    existing_filter = None
    for ef in existing:
        try:
            if ef.Name == filter_name:
                existing_filter = ef
                break
        except:
            pass

    # --- 8) Determine target: view template or view ---
    active_view = doc.ActiveView
    view_template = get_view_template(active_view)

    if view_template:
        target = view_template
        target_name = view_template.Name
        target_label = "view template"
    else:
        target = active_view
        target_name = active_view.Name
        target_label = "view"

    out.print_md("* Target: `{}` ({})".format(target_name, target_label))

    # --- 9) Create and apply ---
    t = Transaction(doc, "PD_pY Create Filter from Selection")
    t.Start()

    try:
        if existing_filter:
            use_it = forms.alert(
                "Filter '{}' already exists.\n\n"
                "Apply existing filter to {}?".format(
                    filter_name, target_label),
                yes=True, no=True
            )
            if use_it:
                filter_el = existing_filter
            else:
                counter = 2
                while True:
                    new_name = "{}_{}".format(filter_name, counter)
                    found = False
                    for ef in existing:
                        try:
                            if ef.Name == new_name:
                                found = True
                                break
                        except:
                            pass
                    if not found:
                        filter_name = new_name
                        break
                    counter += 1
                filter_el = None
        else:
            filter_el = None

        # Create if needed
        if filter_el is None:
            filter_el = ParameterFilterElement.Create(
                doc,
                filter_name,
                cat_ids,
                ElementParameterFilter(
                    _create_contains_rule(param_id, search_string)
                )
            )

        if filter_el is None:
            t.RollBack()
            forms.alert("Failed to create filter.", exitscript=True)

        out.print_md("* Filter: `{}`".format(filter_name))

        # Add to target (template or view)
        ok = add_filter_to_target(target, filter_el,
                                  view_template is not None)

        if not ok and view_template is not None:
            # Fallback: try adding to view directly
            out.print_md("* Falling back to active view...")
            ok = add_filter_to_target(active_view, filter_el, False)
            target_name = active_view.Name
            target_label = "view"

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
        "Filter: {}\n"
        "Parameter: {}\n"
        "Contains: '{}'\n"
        "Category: {}\n"
        "Applied to: {} ({})".format(
            filter_name,
            param_display,
            search_string,
            cat_name,
            target_name,
            target_label
        )
    )


if __name__ == "__main__":
    main()
