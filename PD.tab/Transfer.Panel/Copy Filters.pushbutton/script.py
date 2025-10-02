from Autodesk.Revit.DB import FilteredElementCollector, View, Transaction, OverrideGraphicSettings
from pyrevit import revit, forms

# Get the current document
doc = revit.doc

# Select views from the current model
def select_views(prompt_title="Select Views"):
    views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    view_names = [view.Name for view in views if not view.IsTemplate]
    
    if not view_names:
        forms.alert("No views found in the current model.")
        return []
    
    selected_views = forms.SelectFromList.show(sorted(view_names), multiselect=True, title=prompt_title, button_name="Select")
    return [view for view in views if view.Name in selected_views]

# Copy filters from source views to target views
def transfer_filters(source_views, target_views):
    skipped_filters = []  # Track skipped filters
    copied_filters = []  # Track successfully copied filters

    with Transaction(doc, "Transfer View Filters") as trans:
        trans.Start()

        for target_view in target_views:
            for source_view in source_views:
                for filter_id in source_view.GetFilters():
                    # Add the filter to the target view if not already present
                    if filter_id not in target_view.GetFilters():
                        target_view.AddFilter(filter_id)
                        target_view.SetFilterVisibility(filter_id, source_view.GetFilterVisibility(filter_id))

                        # Copy override settings
                        override_settings = source_view.GetFilterOverrides(filter_id)
                        try:
                            target_view.SetFilterOverrides(filter_id, override_settings)
                        except:
                            # If override fails, skip this filter
                            skipped_filters.append(doc.GetElement(filter_id).Name)
                            continue
                        
                        copied_filters.append(doc.GetElement(filter_id).Name)
        
        trans.Commit()

    # Output results
    if copied_filters:
        print("The following filters were successfully copied:")
        for filter_name in set(copied_filters):
            print("- {}".format(filter_name))
    if skipped_filters:
        print("The following filters were skipped due to incompatibility:")
        for filter_name in set(skipped_filters):
            print("- {}".format(filter_name))
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
