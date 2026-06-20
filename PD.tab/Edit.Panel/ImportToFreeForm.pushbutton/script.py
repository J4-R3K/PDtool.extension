# -*- coding: utf-8 -*-
__title__   = "Impt 2\nFreeForm"
__doc__     = """Version = 1.1
Date    = 2026-03-21
________________________________________________________________
Description:

Select an imported SAT/CAD object in the Family Editor
and convert it to a Free Form Element with material control.

Handles both ImportInstance and DirectShape elements
(Revit imports SAT files as DirectShape in newer versions).

________________________________________________________________
How-To:

1. Open a Family document in Revit
2. Select an imported CAD/SAT instance
3. Run this tool
4. The import is converted to FreeFormElement(s)
5. You can then assign materials via Properties

________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    ImportInstance,
    DirectShape,
    Options,
    ViewDetailLevel,
    GeometryInstance,
    Solid,
    FreeFormElement,
    Transaction
)

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

# Check we are in Family Editor
if not doc.IsFamilyDocument:
    forms.alert("This tool only works in the Family Editor.",
                exitscript=True)

# Get current selection
selected = [doc.GetElement(eid)
            for eid in uidoc.Selection.GetElementIds()]

if not selected:
    forms.alert("Please select an imported CAD/SAT instance first.",
                exitscript=True)

# Filter for ImportInstance or DirectShape elements
valid_elements = []
for el in selected:
    if isinstance(el, ImportInstance):
        valid_elements.append(el)
    elif isinstance(el, DirectShape):
        valid_elements.append(el)

if not valid_elements:
    # Show what was actually selected for troubleshooting
    type_names = []
    for el in selected:
        try:
            type_names.append(el.GetType().FullName)
        except:
            type_names.append("unknown")

    forms.alert(
        "Selection does not contain Import Instances or DirectShapes.\n\n"
        "Selected types:\n{}".format("\n".join(type_names)),
        exitscript=True
    )


def extract_solids(element):
    """Extract solid geometry from an element."""
    opt = Options()
    opt.ComputeReferences = True
    opt.DetailLevel = ViewDetailLevel.Fine
    geom_elem = element.get_Geometry(opt)

    solids = []

    if not geom_elem:
        return solids

    for geom_obj in geom_elem:
        # ImportInstance wraps geometry in GeometryInstance
        if isinstance(geom_obj, GeometryInstance):
            inst_geom = geom_obj.GetInstanceGeometry()
            if inst_geom:
                for g in inst_geom:
                    if isinstance(g, Solid) and g.Volume > 0:
                        solids.append(g)
        elif isinstance(geom_obj, Solid) and geom_obj.Volume > 0:
            solids.append(geom_obj)

    return solids


converted_count = 0
failed_count = 0

t = Transaction(doc, "Convert to FreeForm")
t.Start()

try:
    for element in valid_elements:
        el_type = "DirectShape" if isinstance(element, DirectShape) \
            else "ImportInstance"
        out.print_md("### Processing {} (Id {})".format(
            el_type, element.Id.IntegerValue))

        solids = extract_solids(element)

        if not solids:
            out.print_md("* No solids found - skipping")
            failed_count += 1
            continue

        out.print_md("* Found {} solid(s)".format(len(solids)))

        el_converted = 0

        for solid in solids:
            try:
                ff = FreeFormElement.Create(doc, solid)
                if ff:
                    converted_count += 1
                    el_converted += 1
                    out.print_md("* Created FreeForm Id `{}`".format(
                        ff.Id.IntegerValue))
            except Exception as e:
                out.print_md("* Error: `{}`".format(str(e)))
                failed_count += 1

        # Delete the original element after successful conversion
        if el_converted > 0:
            try:
                doc.Delete(element.Id)
                out.print_md("* Deleted original {}".format(el_type))
            except Exception as e:
                out.print_md("* Could not delete original: `{}`".format(
                    str(e)))

    t.Commit()

except Exception as ex:
    try:
        t.RollBack()
    except:
        pass
    forms.alert("Error:\n{}".format(str(ex)), exitscript=True)

if converted_count > 0:
    forms.alert(
        "Done!\n\n"
        "Created: {} Free Form Element(s)\n"
        "Failed: {}\n\n"
        "You can now assign materials via Properties.".format(
            converted_count, failed_count))
else:
    forms.alert("No solids could be converted.\n"
                "Check the imported geometry.")
