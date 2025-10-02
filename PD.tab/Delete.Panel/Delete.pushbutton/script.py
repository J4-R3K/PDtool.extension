# pylint: disable=import-error,invalid-name,broad-except,superfluous-parens
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import revit, DB

# Get the current UIDocument and Document from the revit module
uidoc = revit.uidoc
doc = revit.doc

def delete_selected_element():
    """Delete the selected element in Revit."""
    # Start a transaction to delete the element
    with DB.Transaction(doc, "Delete Selected Element") as trans:
        try:
            # Prompt user to select an element
            selection = uidoc.Selection
            pickedRef = selection.PickObject(ObjectType.Element, "Please select an element to delete")
            selected_element_id = pickedRef.ElementId
            
            if selected_element_id:
                trans.Start()
                doc.Delete(selected_element_id)
                trans.Commit()
                TaskDialog.Show("Success", "Element deleted successfully.")
        except Exception as e:
            # If an error occurs, cancel the transaction and show an error dialog
            if trans.GetStatus() == DB.TransactionStatus.Started:
                trans.RollBack()
            TaskDialog.Show("Error", "Failed to delete element. Error: {0}".format(str(e)))

if __name__ == "__main__":
    delete_selected_element()
