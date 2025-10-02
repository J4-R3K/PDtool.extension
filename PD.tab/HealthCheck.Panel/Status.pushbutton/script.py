import os
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, DesignOption, View, ImportInstance, Material, Transaction, Family, Workset, FilteredWorksetCollector, ViewSheet, LinePatternElement, FillPatternElement, FamilySymbol, WorksetKind, View3D, ViewSchedule
from pyrevit import revit, forms

# Get the current document from pyRevit's revit module
doc = revit.doc

# Define the list of health metrics we're looking for in the "Metric name" parameter, excluding "FILE SIZE (MB)"
target_metrics = [
    "WARNINGS",
    "WORKSETS",
    "DESIGN OPTIONS",
    "UNPLACED VIEWS",
    "CAD LINKS",
    "CAD IMPORTS",
    "RASTER IMAGES",
    "INVALID ROOMS",
    "IMPORT PATTERNS",
    "INPLACE FAMILIES",
    "MATERIALS",
    "LINE STYLES",
    "FILL PATTERNS",
    "LINE PATTERNS",
    "LOADED FAMILIES"
]

# Define normalization ranges for each metric (excluding "PDF DOCUMENTS")
normalization_ranges = {
    "WARNINGS": (0, 100),
    "WORKSETS": (0, 50),
    "DESIGN OPTIONS": (0, 20),
    "UNPLACED VIEWS": (0, 500),
    "CAD LINKS": (0, 50),
    "CAD IMPORTS": (0, 50),
    "RASTER IMAGES": (0, 50),
    "INVALID ROOMS": (0, 100),
    "IMPORT PATTERNS": (0, 50),
    "INPLACE FAMILIES": (0, 100),
    "MATERIALS": (0, 50000),
    "LINE STYLES": (0, 200),
    "FILL PATTERNS": (0, 200),
    "LINE PATTERNS": (0, 200),
    "LOADED FAMILIES": (0, 1000)
}

# Function to calculate the correct value for each metric
def calculate_metric_value(metric_name):
    if metric_name == "DESIGN OPTIONS":
        design_options = FilteredElementCollector(doc).OfClass(DesignOption).ToElements()
        return len(design_options)
    elif metric_name == "WARNINGS":
        warnings = doc.GetWarnings()
        return len(warnings)
    elif metric_name == "WORKSETS":
        user_worksets = [ws for ws in FilteredWorksetCollector(doc).ToWorksets() if ws.Kind == WorksetKind.UserWorkset]
        return len(user_worksets)
    elif metric_name == "UNPLACED VIEWS":
        views = FilteredElementCollector(doc).OfClass(View).ToElements()
        unplaced_views = [v for v in views if not isinstance(v, (ViewSheet, View3D, ViewSchedule)) and not v.IsTemplate and v.CanBePrinted]
        return len(unplaced_views)
    elif metric_name == "CAD LINKS":
        cad_links = FilteredElementCollector(doc).OfClass(ImportInstance).ToElements()
        return len(cad_links)
    elif metric_name == "RASTER IMAGES":
        raster_images = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RasterImages).ToElements()
        actual_raster_images = [img for img in raster_images if hasattr(img, "Name") and ".png" in img.Name.lower()]
        return len(actual_raster_images)
    elif metric_name == "MATERIALS":
        materials = FilteredElementCollector(doc).OfClass(Material).ToElements()
        return len(materials)
    elif metric_name == "INPLACE FAMILIES":
        all_families = FilteredElementCollector(doc).OfClass(Family).ToElements()
        in_place_families = [f for f in all_families if f.IsInPlace]
        return len(in_place_families)
    elif metric_name == "LINE STYLES":
        line_patterns = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
        return len(line_patterns)
    elif metric_name == "FILL PATTERNS":
        fill_patterns = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
        return len(fill_patterns)
    elif metric_name == "LINE PATTERNS":
        line_patterns = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
        return len(line_patterns)
    elif metric_name == "LOADED FAMILIES":
        loaded_families = FilteredElementCollector(doc).OfClass(Family).ToElements()
        return len(loaded_families)
    else:
        return 0.0

# Function to normalize a value based on min and max range
def normalize_value(value, min_value, max_value):
    if max_value - min_value != 0:
        return (value - min_value) / (max_value - min_value)
    return 0

# Correctly filter family instances based on the category "Generic Annotations"
family_name = "PD_GAN_ModelHealth-Gauge"  # Updated family name

# Filtering only placed FamilyInstance elements (not types)
family_instances = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericAnnotation).WhereElementIsNotElementType().ToElements()
family_instances = [inst for inst in family_instances if inst.Symbol.Family.Name == family_name]

# List to accumulate normalized values
normalized_values = []

# Perform the health check by reading the "Metric name" and updating the "OVERALL" value parameter
with Transaction(doc, "Update Health Check Values") as trans:
    trans.Start()

    overall_instance = None  # To store the instance where "Metric name" is "OVERALL"
    file_size_value = 0.0  # Store the manually entered "FILE SIZE (MB)" value

    for instance in family_instances:
        metric_param = instance.LookupParameter("Metric name")
        value_param = instance.LookupParameter("Value")

        if metric_param and value_param:
            metric_name = metric_param.AsString()

            if metric_name == "FILE SIZE (MB)":
                # Do not update, but read the manually entered value
                file_size_value = value_param.AsDouble()  # Store this value for OVERALL calculation

            elif metric_name in target_metrics:
                # Calculate the correct value for the metric
                calculated_value = calculate_metric_value(metric_name)
                value_param.Set(calculated_value)  # Set the correct calculated value

                # Normalize the value based on the metric's range
                if metric_name in normalization_ranges:
                    min_val, max_val = normalization_ranges[metric_name]
                    normalized_value = normalize_value(calculated_value, min_val, max_val)
                    normalized_values.append(normalized_value)

            elif metric_name == "OVERALL":
                # Store the instance for later to update with the average of normalized values
                overall_instance = instance

    # If "OVERALL" instance was found, calculate the average normalized value and set it
    if overall_instance and normalized_values:
        # Include the file size value if it was entered manually
        if file_size_value > 0:
            min_val, max_val = 0, 500  # Assume a normalization range for file size
            normalized_file_size = normalize_value(file_size_value, min_val, max_val)
            normalized_values.append(normalized_file_size)

        avg_normalized_value = sum(normalized_values) / len(normalized_values)
        overall_value_param = overall_instance.LookupParameter("Value")
        if overall_value_param:
            overall_value_param.Set(avg_normalized_value)

    trans.Commit()

# Final confirmation
forms.alert("Health check values and 'OVERALL' updated successfully for family '{}'.".format(family_name), title="Health Check")
