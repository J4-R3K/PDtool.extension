from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, Transaction, ElementTransformUtils, RevitLinkInstance, ElementId
from pyrevit import revit, forms
from System.Collections.Generic import List  # Import List for ICollection compatibility

# Get the current document
doc = revit.doc

# Function to select a linked model
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

# Function to select scope boxes from the selected linked model
def select_scope_boxes(linked_doc):
    scope_boxes = FilteredElementCollector(linked_doc).OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType().ToElements()
    scope_box_names = [sb.Name for sb in scope_boxes]
    
    if not scope_box_names:
        forms.alert("No scope boxes found in the selected model.")
        return []
    
    # Let user select scope boxes
    selected_scope_boxes = forms.SelectFromList.show(sorted(scope_box_names), multiselect=True, title="Select Scope Boxes", button_name="Transfer")
    return [sb for sb in scope_boxes if sb.Name in selected_scope_boxes]

# Main function to transfer selected scope boxes from a linked model
def transfer_scope_boxes():
    # Step 1: Select a linked model
    linked_doc = select_linked_model()
    if linked_doc is None:
        forms.alert("No linked document was selected. Exiting.")
        return  # Exit if no model was selected

    # Step 2: Select specific scope boxes from the selected linked model
    scope_boxes_to_copy = select_scope_boxes(linked_doc)
    if not scope_boxes_to_copy:
        forms.alert("No scope boxes were selected. Exiting.")
        return  # Exit if no scope boxes were selected

    # Step 3: Begin transaction to copy the selected scope boxes
    with Transaction(doc, "Transfer Selected Scope Boxes") as trans:
        trans.Start()

        for scope_box in scope_boxes_to_copy:
            # Check if a scope box with the same name exists in the main document
            existing_scope_box = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType().ToElements()
            existing_scope_box = [esb for esb in existing_scope_box if esb.Name == scope_box.Name]
            
            if existing_scope_box:
                print("Scope Box '{}' already exists in main document. Skipping...".format(scope_box.Name))
                continue
            
            # Convert the list of ElementIds to ICollection[ElementId] for compatibility
            element_ids_to_copy = List[ElementId]([scope_box.Id])
            
            # Copy scope box to the main document
            copied_ids = ElementTransformUtils.CopyElements(linked_doc, element_ids_to_copy, doc, None, None)
            
            if copied_ids:
                print("Successfully copied scope box '{}' to main document.".format(scope_box.Name))
            else:
                print("Failed to copy scope box '{}'.".format(scope_box.Name))
        
        trans.Commit()
    print("Selected scope boxes transferred successfully.")

# Execute the function
transfer_scope_boxes()
