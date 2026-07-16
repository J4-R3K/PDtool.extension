# -*- coding: utf-8 -*-
__title__   = "Copy: Copy Filters"
__doc__     = """Version = 1.1
Date    = 12.07.2026
________________________________________________________________
Description:

Transfers specific filters and their settings from selected views
or view templates to other views or view templates.

If a target view has a view template applied that controls
V/G Overrides Filters, the filters are applied to that view
template instead (updating every view that uses it) - filters
added to the view itself would be ignored.
________________________________________________________________
How-To:

1. Select source views/templates to copy filters from.
2. Select target views/templates to copy filters to.
3. Review the report - it lists any redirects to view templates.

________________________________________________________________
Get Free:
________________________________________________________________
Author: Jarek Wityk"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View,
    Transaction,
    Element,
    ElementId,
    BuiltInParameter,
)
from pyrevit import revit, forms

# Get the current document
doc = revit.doc


# Select views and view templates from the current model
def select_views(prompt_title="Select Views"):
    views = (
        FilteredElementCollector(doc)
        .OfClass(View)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    # Map a unique label to each view; templates are marked and listed too
    view_map = {}
    for view in views:
        try:
            name = view.Name
        except Exception:
            continue
        if not name:
            continue
        label = "{} [TEMPLATE]".format(name) if view.IsTemplate else name
        view_map[label] = view

    if not view_map:
        forms.alert("No views found in the current model.")
        return []

    selected_labels = forms.SelectFromList.show(
        sorted(view_map.keys()), multiselect=True, title=prompt_title, button_name="Select"
    )
    if not selected_labels:
        return []
    return [view_map[label] for label in selected_labels]


# True if the view template controls V/G Overrides Filters
def template_controls_filters(template):
    try:
        non_controlled = template.GetNonControlledTemplateParameterIds()
        return ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS) not in non_controlled
    except Exception:
        # If it cannot be read, assume the template is in control
        return True


# Resolve where the filters must actually be written for a target view.
# Returns (element_to_modify, redirect_note_or_None).
def resolve_target(view):
    if view.IsTemplate:
        return view, None
    template_id = view.ViewTemplateId
    if template_id != ElementId.InvalidElementId:
        template = doc.GetElement(template_id)
        if template is not None and template_controls_filters(template):
            note = "View '{}' uses template '{}' which controls filters - applied to the template instead.".format(
                view.Name, template.Name
            )
            return template, note
    return view, None


# Copy filters from source views to target views
def transfer_filters(source_views, target_views):
    skipped_filters = []  # Track skipped filters
    copied_filters = []  # Track successfully copied filters
    redirect_notes = []  # Track view -> template redirects
    failed_targets = []  # Track targets that do not accept filters

    # Resolve real targets first, deduplicated by element id so a template
    # shared by several selected views is only processed once
    resolved = []
    seen_ids = set()
    for target_view in target_views:
        target, note = resolve_target(target_view)
        if note and note not in redirect_notes:
            redirect_notes.append(note)
        if target.Id.IntegerValue in seen_ids:
            continue
        seen_ids.add(target.Id.IntegerValue)
        resolved.append(target)

    with Transaction(doc, "Transfer View Filters") as trans:
        trans.Start()

        for target_view in resolved:
            for source_view in source_views:
                if source_view.Id.IntegerValue == target_view.Id.IntegerValue:
                    continue
                for filter_id in source_view.GetFilters():
                    # Add the filter to the target if not already present
                    try:
                        if filter_id not in target_view.GetFilters():
                            target_view.AddFilter(filter_id)
                            target_view.SetFilterVisibility(
                                filter_id, source_view.GetFilterVisibility(filter_id)
                            )

                            # Copy override settings
                            override_settings = source_view.GetFilterOverrides(filter_id)
                            try:
                                target_view.SetFilterOverrides(filter_id, override_settings)
                            except Exception:
                                # If override fails, skip this filter
                                skipped_filters.append(Element.Name.GetValue(doc.GetElement(filter_id)))
                                continue

                            copied_filters.append(Element.Name.GetValue(doc.GetElement(filter_id)))
                    except Exception:
                        # Target does not accept filters at all (e.g. schedules)
                        try:
                            failed_name = target_view.Name
                        except Exception:
                            failed_name = str(target_view.Id)
                        if failed_name not in failed_targets:
                            failed_targets.append(failed_name)
                        break

        trans.Commit()

    # Output results
    if redirect_notes:
        print("View template redirects:")
        for note in redirect_notes:
            print("- {}".format(note))
        print("")
    if copied_filters:
        print("The following filters were successfully copied:")
        for filter_name in set(copied_filters):
            print("- {}".format(filter_name))
    if skipped_filters:
        print("The following filters were skipped due to incompatibility:")
        for filter_name in set(skipped_filters):
            print("- {}".format(filter_name))
    if failed_targets:
        print("The following targets do not accept filters and were skipped:")
        for target_name in failed_targets:
            print("- {}".format(target_name))
    print("Filter transfer completed.")


# Main function
def transfer_filters_from_views():
    # Select source views
    source_views = select_views(prompt_title="Select Views to Copy Filters From")
    if not source_views:
        forms.alert("No source views selected. Exiting.")
        return

    # Select target views
    target_views = select_views(prompt_title="Select Target Views to Copy Filters To")
    if not target_views:
        forms.alert("No target views selected. Exiting.")
        return

    # Transfer filters
    transfer_filters(source_views, target_views)


# Execute the function
transfer_filters_from_views()
