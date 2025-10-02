from Autodesk.Revit.DB import (
    FilteredElementCollector, BrowserOrganization, Transaction,
    RevitLinkInstance, ElementId, ElementTransformUtils
)
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
    selected_model_title = forms.SelectFromList.show(
        sorted(model_options.keys()), 
        title="Select Linked Model", 
        button_name="Select"
    )
    if selected_model_title:
        return model_options[selected_model_title].GetLinkDocument()
    else:
        return None

# Get all Project Browser settings (BrowserOrganization) in the selected linked model
def select_browser_organizations(linked_doc):
    # Collect BrowserOrganization elements
    browser_orgs = FilteredElementCollector(linked_doc).OfClass(BrowserOrganization).ToElements()
    
    # Collect names using the 'Type Name' parameter
    browser_org_names = []
    browser_org_map = {}
    for bo in browser_orgs:
        try:
            # Access the 'Type Name' parameter
            type_name_param = bo.LookupParameter("Type Name")
            org_name = type_name_param.AsString() if type_name_param and type_name_param.AsString() else "Unnamed (ID: {})".format(bo.Id.IntegerValue)
            browser_org_names.append(org_name)
            browser_org_map[org_name] = bo
        except Exception as e:
            fallback_name = "Error Reading Name (ID: {})".format(bo.Id.IntegerValue)
            browser_org_names.append(fallback_name)
            browser_org_map[fallback_name] = bo
    
    if not browser_org_names:
        forms.alert("No Project Browser settings found in the selected model.")
        return []
    
    # Let user select Project Browser settings
    selected_browser_orgs = forms.SelectFromList.show(
        sorted(browser_org_names),
        multiselect=True,
        title="Select Browser Organizations",
        button_name="Transfer"
    )
    
    # Return the selected BrowserOrganization elements
    return [browser_org_map[name] for name in selected_browser_orgs]

# Main function to transfer selected Project Browser settings from a linked model
def transfer_browser_organizations():
    # Step 1: Select a linked model
    linked_doc = select_linked_model()
    if linked_doc is None:
        forms.alert("No linked document was selected. Exiting.")
        return  # Exit if no model was selected

    # Step 2: Select specific Project Browser settings from the linked model
    browser_orgs_to_copy = select_browser_organizations(linked_doc)
    if not browser_orgs_to_copy:
        forms.alert("No Project Browser settings were selected. Exiting.")
        return  # Exit if no settings were selected

    # Step 3: Begin transaction to copy the selected settings
    with Transaction(doc, "Transfer Selected Project Browser Settings") as trans:
        trans.Start()

        for browser_org in browser_orgs_to_copy:
            # Check if a BrowserOrganization with the same name exists in the main document
            existing_org = FilteredElementCollector(doc).OfClass(BrowserOrganization).ToElements()
            existing_org_names = [
                bo.LookupParameter("Type Name").AsString() if bo.LookupParameter("Type Name") else None
                for bo in existing_org
            ]
            
            type_name_param = browser_org.LookupParameter("Type Name")
            org_name = type_name_param.AsString() if type_name_param else "Unnamed"
            
            if org_name in existing_org_names:
                print("Browser Organization '{}' already exists in the main document. Skipping...".format(org_name))
                continue
            
            # Convert the ElementId to ICollection[ElementId] for compatibility
            element_ids_to_copy = List[ElementId]([browser_org.Id])
            
            # Copy the BrowserOrganization to the main document
            copied_ids = ElementTransformUtils.CopyElements(linked_doc, element_ids_to_copy, doc, None, None)
            
            if copied_ids:
                print("Successfully copied Project Browser setting '{}' to the main document.".format(org_name))
            else:
                print("Failed to copy Project Browser setting '{}'.".format(org_name))
        
        trans.Commit()
    print("Selected Project Browser settings transferred successfully.")

# Execute the function
transfer_browser_organizations()
