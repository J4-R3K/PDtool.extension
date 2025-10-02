# pyRevit script to copy Legends from a linked model

from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewType,
    Transaction, RevitLinkInstance, ElementId, ElementTransformUtils
)
from pyrevit import revit, forms
from System.Collections.Generic import List  # For ICollection[ElementId] compatibility

# Get current document
doc = revit.doc

# Step 1: Select linked model
def select_linked_model():
    linked_models = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    model_options = {link.GetLinkDocument().Title: link for link in linked_models if link.GetLinkDocument() is not None}

    if not model_options:
        forms.alert("No linked models found in the project.")
        return None

    selected_model_title = forms.SelectFromList.show(
        sorted(model_options.keys()),
        title="Select Linked Model",
        button_name="Select"
    )
    if selected_model_title:
        return model_options[selected_model_title].GetLinkDocument()
    else:
        return None

# Step 2: Get Legend views from linked model
def select_legends(linked_doc):
    legends = FilteredElementCollector(linked_doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    legend_views = [v for v in legends if v.ViewType == ViewType.Legend and not v.IsTemplate]

    if not legend_views:
        forms.alert("No Legends found in the selected linked model.")
        return []

    legend_names = [v.Name for v in legend_views]

    selected_legends = forms.SelectFromList.show(
        sorted(legend_names),
        multiselect=True,
        title="Select Legends to Transfer",
        button_name="Transfer"
    )

    return [v for v in legend_views if v.Name in selected_legends]

# Step 3: Transfer Legends to main model
def transfer_legends():
    linked_doc = select_linked_model()
    if linked_doc is None:
        return

    legends_to_copy = select_legends(linked_doc)
    if not legends_to_copy:
        forms.alert("No legends were selected. Exiting.")
        return

    # Get existing legends in main doc to avoid duplicates
    existing_legends = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    existing_legend_names = [v.Name for v in existing_legends if v.ViewType == ViewType.Legend]

    with Transaction(doc, "Transfer Selected Legends") as trans:
        trans.Start()

        for legend in legends_to_copy:
            if legend.Name in existing_legend_names:
                print("Legend '{}' already exists. Skipping...".format(legend.Name))
                continue

            element_ids_to_copy = List[ElementId]([legend.Id])

            copied_ids = ElementTransformUtils.CopyElements(linked_doc, element_ids_to_copy, doc, None, None)

            if copied_ids.Count > 0:
                print("Successfully copied Legend '{}'.".format(legend.Name))
            else:
                print("Failed to copy Legend '{}'.".format(legend.Name))

        trans.Commit()

    print("Legend transfer complete.")

# Execute
transfer_legends()
