from Autodesk.Revit.DB import FilteredElementCollector, View, Transaction, ElementTransformUtils, RevitLinkInstance, ElementId
from pyrevit import revit, forms
from System.Collections.Generic import List  # Import List for ICollection compatibility

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

# Get all view templates in the selected linked model
def select_view_templates(linked_doc):
    view_templates = FilteredElementCollector(linked_doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    view_template_names = [vt.Name for vt in view_templates if vt.IsTemplate]
    
    if not view_template_names:
        forms.alert("No view templates found in the selected model.")
        return []
    
    # Let user select view templates
    selected_templates = forms.SelectFromList.show(sorted(view_template_names), multiselect=True, title="Select View Templates", button_name="Transfer")
    return [vt for vt in view_templates if vt.Name in selected_templates]

# Main function to transfer selected view templates from a selected linked model
def transfer_view_templates():
    # Step 1: Select a linked model
    linked_doc = select_linked_model()
    if linked_doc is None:
        forms.alert("No linked document was selected. Exiting.")
        return  # Exit if no model was selected

    # Step 2: Select specific view templates from the selected linked model
    view_templates_to_copy = select_view_templates(linked_doc)
    if not view_templates_to_copy:
        forms.alert("No view templates were selected. Exiting.")
        return  # Exit if no templates were selected

    # Step 3: Begin transaction to copy the selected view templates
    with Transaction(doc, "Transfer Selected View Templates") as trans:
        trans.Start()

        for view_template in view_templates_to_copy:
            # Check if template with the same name exists in the main document
            existing_template = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
            existing_template = [et for et in existing_template if et.IsTemplate and et.Name == view_template.Name]
            
            if existing_template:
                print("Template '{}' already exists in main document. Skipping...".format(view_template.Name))
                continue
            
            # Convert the list of ElementIds to ICollection[ElementId] for compatibility
            element_ids_to_copy = List[ElementId]([view_template.Id])
            
            # Copy view template to the main document
            copied_ids = ElementTransformUtils.CopyElements(linked_doc, element_ids_to_copy, doc, None, None)
            
            if copied_ids:
                print("Successfully copied template '{}' to main document.".format(view_template.Name))
            else:
                print("Failed to copy template '{}'.".format(view_template.Name))
        
        trans.Commit()
    print("Selected view templates transferred successfully.")

# Execute the function
transfer_view_templates()
