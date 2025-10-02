import clr
clr.AddReference('RevitServices')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, ViewSheet, RevitLinkInstance
from pyrevit import forms
from RevitServices.Persistence import DocumentManager
from pyrevit import revit

# Use pyRevit's way of getting the active document
doc = revit.doc

if doc is None:
    forms.alert("Error: Could not retrieve the current Revit document.")
    raise Exception("Current document is None")

# Function to get sheets from a document
def get_sheets(doc, model_reference):
    if doc is None:
        forms.alert("Error: Document is None for model: {}".format(model_reference))
        return []  # Return empty list if the document is None
    
    try:
        sheets = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()
        sheet_list = []
        
        for sheet in sheets:
            sheet_number = sheet.SheetNumber
            sheet_name = sheet.Name
            sheet_list.append([model_reference, sheet_number, sheet_name])
        
        return sheet_list
    except Exception as e:
        forms.alert("Error: Failed to collect sheets from '{}': {}".format(model_reference, e))
        return []

output_data = []

# Get sheets from the current model
current_model_reference = "Current Model"
output_data.extend(get_sheets(doc, current_model_reference))

# Get linked documents
link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()

for link in link_instances:
    try:
        link_doc = link.GetLinkDocument()
        if link_doc is not None:
            linked_model_reference = link.Name
            output_data.extend(get_sheets(link_doc, linked_model_reference))
        else:
            forms.alert("Warning: Linked model document for '{}' could not be found or accessed.".format(link.Name))
    except Exception as e:
        forms.alert("Error: Error processing linked model '{}': {}".format(link.Name, e))

# Prepare output text
output_text = "Model Reference\tSheet Number\tSheet Name\n"
for entry in output_data:
    output_text += "{}\t{}\t{}\n".format(entry[0], entry[1], entry[2])

# Display output in a pyRevit window
forms.alert(output_text, title="Sheet Export")
