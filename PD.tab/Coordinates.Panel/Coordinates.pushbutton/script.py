from Autodesk.Revit.DB import FilteredElementCollector, BasePoint, BuiltInParameter, RevitLinkInstance
from pyrevit import revit, forms
import tempfile
import os
import math

# Get the current document
doc = revit.doc

# Function to get base points from a given document
def get_base_points_from_doc(doc, model_name="Current Model"):
    base_points = FilteredElementCollector(doc).OfClass(BasePoint).ToElements()

    if not base_points:
        return "Model: {}\nNo base points found.\n\n".format(model_name)
    
    output = "Model: {}\n".format(model_name)
    for i, bp in enumerate(base_points, start=1):
        try:
            # Retrieve X, Y, Z coordinates and convert from feet to millimeters
            bp_x_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
            bp_y_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
            bp_z_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)

            if bp_x_param and bp_y_param and bp_z_param:
                bp_x = bp_x_param.AsDouble() * 304.8  # convert feet to mm
                bp_y = bp_y_param.AsDouble() * 304.8
                bp_z = bp_z_param.AsDouble() * 304.8
            else:
                output += "Base Point (ID: {}) has missing coordinates.\n".format(bp.Id.IntegerValue)
                continue
            
            # Try to retrieve the Angle to True North parameter, and convert radians to degrees
            angle_to_north_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
            if angle_to_north_param and angle_to_north_param.HasValue:
                angle_to_north_radians = angle_to_north_param.AsDouble()  # Angle in radians
                angle_to_north_degrees = math.degrees(angle_to_north_radians)  # Convert to degrees
                label = "Project Base Point"
                output += "{} (ID: {}):\n".format(label, bp.Id.IntegerValue)
                output += "N/S (Y): {:.2f} mm\n".format(bp_y)
                output += "E/W (X): {:.2f} mm\n".format(bp_x)
                output += "Elevation (Z): {:.2f} mm\n".format(bp_z)
                output += "Angle to True North: {:.2f} deg\n\n".format(angle_to_north_degrees)
            else:
                label = "Survey Point"
                output += "{} (ID: {}):\n".format(label, bp.Id.IntegerValue)
                output += "N/S (Y): {:.2f} mm\n".format(bp_y)
                output += "E/W (X): {:.2f} mm\n".format(bp_x)
                output += "Elevation (Z): {:.2f} mm\n\n".format(bp_z)
        except Exception as e:
            output += "{} (ID: {}) coordinates could not be retrieved.\nError: {}\n\n".format(label, bp.Id.IntegerValue, e)
    
    return output

# Function to save coordinates to a temporary file and open it
def save_to_temp_file(content):
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, "base_point_coordinates.txt")
    
    # Write the content to the file
    with open(file_path, 'w') as f:
        f.write(content)
    
    # Notify the user and open the file
    forms.alert("The base point coordinates have been saved to a temporary text file:\n{}".format(file_path))
    os.startfile(file_path)  # This will open the file in the default text editor

# Function to get base points from all linked models
def get_base_points_from_all_linked_models(doc):
    output = ""
    
    # First, get the base points from the current model
    output += get_base_points_from_doc(doc, "Current Model")

    # Then, get the linked models
    link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()

    for link in link_instances:
        link_doc = link.GetLinkDocument()  # Get the linked document
        if link_doc:
            model_name = link.Name  # Use the link's name as the model name
            output += get_base_points_from_doc(link_doc, model_name)
        else:
            output += "Model: {}\nLinked model document could not be accessed.\n\n".format(link.Name)

    return output

# Main function to display the coordinates in a temporary file
def main():
    base_point_info = get_base_points_from_all_linked_models(doc)
    if base_point_info:
        save_to_temp_file(base_point_info)

# Execute the main function
main()
