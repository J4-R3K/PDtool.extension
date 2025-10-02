from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkInstance,
    Category,
    CategorySet,
    InstanceBinding,
    ElementId,
    BuiltInCategory,
    BuiltInParameterGroup,
    StorageType,
    Transaction
)
from pyrevit import revit, forms
import System

doc = revit.doc
app = doc.Application

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

def get_project_info_parameters(linked_doc):
    """
    Get all writable parameters from ProjectInfo in the linked doc,
    and store their parameter groups as well.
    Returns:
        param_list: List of parameter names
        param_groups: Dict mapping param_name -> BuiltInParameterGroup
    """
    pi = linked_doc.ProjectInformation
    param_list = []
    param_groups = {}
    for p in pi.Parameters:
        if not p.IsReadOnly:
            param_list.append(p.Definition.Name)
            param_groups[p.Definition.Name] = p.Definition.ParameterGroup
    return list(set(param_list)), param_groups

def parameter_exists_in_main_doc(param_name):
    """Check if a parameter with this name exists in main doc's ProjectInfo."""
    main_pi = doc.ProjectInformation
    p = main_pi.LookupParameter(param_name)
    return p is not None

def create_project_parameter(param_name, param_group):
    """
    Attempt to create a project parameter with given param_name from the shared parameter file,
    assigning it to the provided param_group (BuiltInParameterGroup).
    """
    sp_file = app.OpenSharedParameterFile()
    if sp_file is None:
        forms.alert("No shared parameter file is set. Cannot create parameter '{}'.".format(param_name))
        return False

    param_def = None
    for group in sp_file.Groups:
        for ext_def in group.Definitions:
            if ext_def.Name == param_name:
                param_def = ext_def
                break
        if param_def:
            break

    if not param_def:
        forms.alert("Parameter '{}' not found in shared parameter file. Cannot create it.".format(param_name))
        return False

    cat = Category.GetCategory(doc, BuiltInCategory.OST_ProjectInformation)
    cat_set = app.Create.NewCategorySet()
    cat_set.Insert(cat)

    binding = app.Create.NewInstanceBinding(cat_set)
    binding_map = doc.ParameterBindings

    # Insert with the parameter group retrieved from the linked doc
    if not binding_map.Insert(param_def, binding, param_group):
        # If insert fails, try ReInsert
        if not binding_map.ReInsert(param_def, binding, param_group):
            forms.alert("Failed to bind parameter '{}' to ProjectInformation.".format(param_name))
            return False

    print("Parameter '{}' created and bound to ProjectInformation under group '{}'.".format(param_name, param_group))
    return True

def transfer_parameter_values(linked_doc, param_names):
    linked_pi = linked_doc.ProjectInformation
    main_pi = doc.ProjectInformation

    for name in param_names:
        source_param = linked_pi.LookupParameter(name)
        if source_param is None:
            print("Parameter '{}' not found in linked ProjectInformation.".format(name))
            continue
        target_param = main_pi.LookupParameter(name)
        if target_param is None:
            print("Parameter '{}' not found in main ProjectInformation after creation. Skipping.".format(name))
            continue
        if target_param.IsReadOnly:
            print("Parameter '{}' is read-only in main doc. Skipping.".format(name))
            continue

        st = target_param.StorageType
        try:
            if st == StorageType.String:
                val = source_param.AsString() or ""
                target_param.Set(val)
                print("Project parameter '{}' set to '{}'.".format(name, val))
            elif st == StorageType.Integer:
                val = source_param.AsInteger()
                target_param.Set(val)
                print("Project parameter '{}' set to integer '{}'.".format(name, val))
            elif st == StorageType.Double:
                val = source_param.AsDouble()
                target_param.Set(val)
                print("Project parameter '{}' set to double '{}'.".format(name, val))
            elif st == StorageType.ElementId:
                val = source_param.AsElementId()
                target_param.Set(val)
                print("Project parameter '{}' set to ElementId '{}'.".format(name, val))
            else:
                print("Unsupported storage type for parameter '{}'. Skipping.".format(name))
        except Exception as e:
            print("Failed to set parameter '{}': {}".format(name, e))

def main():
    linked_doc = select_linked_model()
    if linked_doc is None:
        return

    linked_params, param_groups = get_project_info_parameters(linked_doc)
    if not linked_params:
        forms.alert("No parameters found in linked ProjectInformation.")
        return

    selected_params = forms.SelectFromList.show(
        sorted(linked_params),
        multiselect=True,
        title="Select Parameters to Transfer",
        button_name="Transfer"
    )
    if not selected_params:
        forms.alert("No parameters selected. Exiting.")
        return

    response = forms.alert(
        "Create missing parameters in main doc if they don't exist?",
        options=["Yes", "No"]
    )
    create_missing = response == "Yes"

    with Transaction(doc, "Transfer Project Parameters and Values") as t:
        t.Start()

        # Check and create missing parameters if requested
        for p_name in selected_params[:]:
            if not parameter_exists_in_main_doc(p_name):
                if create_missing:
                    param_group = param_groups.get(p_name, BuiltInParameterGroup.PG_TEXT)
                    success = create_project_parameter(p_name, param_group)
                    if not success:
                        print("Skipping parameter '{}' because it couldn't be created.".format(p_name))
                        selected_params.remove(p_name)
                else:
                    print("Parameter '{}' does not exist in main doc. Skipping.".format(p_name))
                    selected_params.remove(p_name)

        # Transfer values for the remaining selected parameters
        transfer_parameter_values(linked_doc, selected_params)

        t.Commit()

    print("Selected project parameters transferred successfully.")

if __name__ == "__main__":
    main()
