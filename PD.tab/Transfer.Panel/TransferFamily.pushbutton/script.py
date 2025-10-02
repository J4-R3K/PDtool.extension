from Autodesk.Revit.DB import FilteredElementCollector, Family, FamilySymbol, Transaction, ElementTransformUtils, RevitLinkInstance, ElementId
from pyrevit import revit, forms
from System.Collections.Generic import List  # Import for ICollection compatibility

# Get the current document
doc = revit.doc

# Get all linked models and let the user select one
def select_linked_model():
    linked_models = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    model_options = {link.GetLinkDocument().Title: link for link in linked_models if link.GetLinkDocument() is not None}
    
    if not model_options:
        forms.alert("No linked models found in the project.")
        return None

    # Let user select the model
    selected_model_title = forms.SelectFromList.show(sorted(model_options.keys()), title="Select Linked Model", button_name="Select")
    if selected_model_title:
        return model_options[selected_model_title].GetLinkDocument()
    else:
        return None

# Get all families in the selected linked model
def select_families(linked_doc):
    families = FilteredElementCollector(linked_doc).OfClass(Family).ToElements()
    family_names = [fam.Name for fam in families]
    
    if not family_names:
        forms.alert("No families found in the selected model.")
        return []
    
    # Let user select families
    selected_families = forms.SelectFromList.show(sorted(family_names), multiselect=True, title="Select Families", button_name="Transfer")
    return [fam for fam in families if fam.Name in selected_families]

# Main function to transfer selected families and their types from a linked model
def transfer_families():
    # Step 1: Select a linked model
    linked_doc = select_linked_model()
    if linked_doc is None:
        forms.alert("No linked document was selected. Exiting.")
        return  # Exit if no model was selected

    # Step 2: Select specific families from the selected linked model
    families_to_copy = select_families(linked_doc)
    if not families_to_copy:
        forms.alert("No families were selected. Exiting.")
        return  # Exit if no families were selected

    # Step 3: Begin transaction to copy the selected families
    with Transaction(doc, "Transfer Selected Families and Types") as trans:
        trans.Start()

        for family in families_to_copy:
            # Check if family with the same name exists in the main document
            existing_families = FilteredElementCollector(doc).OfClass(Family).ToElements()
            existing_family_names = [ef.Name for ef in existing_families]

            if family.Name in existing_family_names:
                print("Family '{}' already exists in the main document. Skipping...".format(family.Name))
                continue

            # Collect all FamilySymbols (types) associated with the family
            family_symbols = FilteredElementCollector(linked_doc).OfClass(FamilySymbol).ToElements()
            family_symbols_to_copy = [fs for fs in family_symbols if fs.Family.Id == family.Id]

            # Ensure FamilySymbols are activated (loaded types)
            for symbol in family_symbols_to_copy:
                if not symbol.IsActive:
                    symbol.Activate()
                    linked_doc.Regenerate()  # Regenerate the document to reflect the activation

            # Combine family and its symbols to copy
            element_ids_to_copy = List[ElementId]()
            element_ids_to_copy.Add(family.Id)
            for symbol in family_symbols_to_copy:
                element_ids_to_copy.Add(symbol.Id)

            # Copy family and its types to the main document
            copied_ids = ElementTransformUtils.CopyElements(linked_doc, element_ids_to_copy, doc, None, None)

            if copied_ids.Count > 0:
                print("Successfully copied family '{}' and its types to the main document.".format(family.Name))
            else:
                print("Failed to copy family '{}'.".format(family.Name))

        trans.Commit()

    print("Selected families and their types transferred successfully.")

# Execute the function
transfer_families()
