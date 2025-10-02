from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
import pyrevit.output as output

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
out = output.get_output()

def log_element_info(element):
    out.print_html("Element ID: <b>{}</b>".format(element.Id))
    category = element.Category.Name if element.Category else "None"
    out.print_html("Category: <b>{}</b>".format(category))

def process_geometry(geometry_element, element_id):
    processed_faces = 0
    for geometry_object in geometry_element:
        if isinstance(geometry_object, Solid):
            for face in geometry_object.Faces:
                processed_faces += 1
                face_id = face.Id
                doc.RemovePaint(element_id, face)
                doc.Regenerate()  # Force a regeneration after removal attempt
                if not doc.IsPainted(element_id, face):  # Check if paint was successfully removed
                    out.print_html("<p>Confirmed paint removal from face of element ID: <b>{0}</b>, Face ID: <b>{1}</b></p>".format(element_id, face_id))
                else:
                    out.print_html("<p>Failed to remove paint from face of element ID: <b>{0}</b>, Face ID: <b>{1}</b></p>".format(element_id, face_id))
    return processed_faces

selected_ids = uidoc.Selection.GetElementIds()
if not selected_ids:
    TaskDialog.Show('Remove Paint', 'No elements selected.')
else:
    with Transaction(doc, 'Remove Paint') as t:
        t.Start()
        for elem_id in selected_ids:
            element = doc.GetElement(elem_id)
            if element is None:
                continue
            log_element_info(element)
            options = Options()
            options.DetailLevel = ViewDetailLevel.Fine
            options.ComputeReferences = True
            options.IncludeNonVisibleObjects = True
            geometry_element = element.get_Geometry(options)
            if geometry_element:
                processed_faces = process_geometry(geometry_element, element.Id)
                if processed_faces > 0:
                    out.print_html("Processed <b>{0}</b> faces on element ID <b>{1}</b>".format(processed_faces, elem_id))
            else:
                out.print_html("No geometry found for element ID: <b>{0}</b>".format(elem_id))
        t.Commit()

    TaskDialog.Show('Remove Paint', 'Operation completed. Check output for details.')
