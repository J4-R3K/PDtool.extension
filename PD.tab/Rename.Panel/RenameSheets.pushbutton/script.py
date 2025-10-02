# Import necessary Revit API and pyRevit libraries
from Autodesk.Revit.DB import *
from pyrevit import forms

# Get the current Revit document
doc = __revit__.ActiveUIDocument.Document

# Collect all sheets in the model
sheets = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()

# Ask the user whether to rename Sheet Name or Sheet Number
rename_option = forms.ask_for_one_item(
    ['Sheet Number', 'Sheet Name'],
    default='Sheet Number',
    prompt="What do you want to rename? Choose an option:",
    title="Rename Option"
)

# Validate the user's choice
if rename_option is None:
    forms.alert("Operation cancelled. No changes were made.", exitscript=True)

# Ask if the renaming should be conditional based on Sheet Name
conditional_rename = forms.alert(
    "Do you want the renaming to be conditional based on Sheet Name?",
    options=["Yes", "No"]
)

# Initialize condition_text to None if "No" is selected
condition_text = None

# Handle conditional renaming logic
if conditional_rename == "Yes":
    condition_text = forms.ask_for_string(
        title="Condition Text",
        prompt="Enter the text that must be contained in the Sheet Name for the operation to apply:",
        default=""
    )
    if not condition_text:
        forms.alert("You must provide a condition text for conditional renaming. Operation cancelled.", exitscript=True)

# Now, proceed to ask for the renaming details
# Ask the user for the text to replace or add a prefix
text_to_replace = forms.ask_for_string(
    title="Text to Replace",
    prompt="Enter the text to replace, or leave blank to add a prefix:",
    default=""
)

# Decide prompt for replacement text or prefix
if text_to_replace:
    replacement_text = forms.ask_for_string(
        title="Replacement Text",
        prompt="Enter the replacement text:",
        default=""
    )
else:
    replacement_text = forms.ask_for_string(
        title="Prefix to Add",
        prompt="Enter the prefix to add:",
        default=""
    )

# Validate inputs
if replacement_text is None:
    forms.alert("Operation cancelled. No changes were made.", exitscript=True)

# Start a transaction to rename sheets
t = Transaction(doc, "Rename Sheets")
t.Start()

try:
    for sheet in sheets:
        # Check if the operation should be conditional
        if condition_text and condition_text not in sheet.Name:
            # Skip sheets that do not match the condition
            continue

        if rename_option == 'Sheet Name':
            # Rename Sheet Name
            if text_to_replace:
                # Replace text in the name
                if text_to_replace in sheet.Name:
                    new_name = sheet.Name.replace(text_to_replace, replacement_text)
                    sheet.Name = new_name
            else:
                # Add prefix if no text to replace
                sheet.Name = replacement_text + sheet.Name

        elif rename_option == 'Sheet Number':
            # Rename Sheet Number
            sheet_number_param = sheet.LookupParameter("Sheet Number")
            if sheet_number_param:
                current_value = sheet_number_param.AsString()
                if text_to_replace:
                    # Replace text in the sheet number
                    if text_to_replace in current_value:
                        new_number = current_value.replace(text_to_replace, replacement_text)
                        sheet_number_param.Set(new_number)
                else:
                    # Add prefix if no text to replace
                    new_number = replacement_text + current_value
                    sheet_number_param.Set(new_number)

    # Commit the transaction
    t.Commit()
    forms.alert("Sheet {}s updated successfully!".format(rename_option.lower()), exitscript=False)

except Exception as e:
    # Rollback the transaction in case of an error
    t.RollBack()
    forms.alert("An error occurred: {}".format(str(e)), exitscript=True)
