# -*- coding: utf-8 -*-
"""Create section view for walls or MEP elements like Cable Trays, Fixtures."""
# pylint: disable=import-error,invalid-name,broad-except

__author__ = 'Source: Jeremy Tammik\nAdapted by: pyRevit Script Generator'

from pyrevit import revit, DB, script

output = script.get_output()
doc = revit.doc

VALID_CATEGORIES = [
    DB.BuiltInCategory.OST_CableTray,
    DB.BuiltInCategory.OST_CableTrayFitting,
    DB.BuiltInCategory.OST_ElectricalEquipment,
    DB.BuiltInCategory.OST_ElectricalFixtures,
    DB.BuiltInCategory.OST_LightingFixtures,
    DB.BuiltInCategory.OST_LightingDevices,
    DB.BuiltInCategory.OST_Conduits,
    DB.BuiltInCategory.OST_DuctCurves,
]

def get_section_view_type():
    return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.ViewTypeSection)

def is_valid_mep_element(el):
    try:
        return el.Category and el.Category.Id.IntegerValue in [int(c) for c in VALID_CATEGORIES]
    except:
        return False

def create_section_from_linear(el, section_type_id):
    loc = el.Location
    if not isinstance(loc, DB.LocationCurve):
        return

    curve = loc.Curve
    p = curve.GetEndPoint(0)
    q = curve.GetEndPoint(1)
    v = q - p

    bb = el.get_BoundingBox(None)
    if not bb:
        return

    minZ = bb.Min.Z
    maxZ = bb.Max.Z
    w = v.GetLength()
    offset = 0.1 * w

    bbox_min = DB.XYZ(-w, minZ - offset, -offset)
    bbox_max = DB.XYZ(w, maxZ + offset, offset)

    midpoint = p + 0.5 * v
    x_dir = v.Normalize()
    y_dir = DB.XYZ.BasisZ
    z_dir = x_dir.CrossProduct(y_dir)

    t = DB.Transform.Identity
    t.Origin = midpoint
    t.BasisX = x_dir
    t.BasisY = y_dir
    t.BasisZ = z_dir

    section_box = DB.BoundingBoxXYZ()
    section_box.Transform = t
    section_box.Min = bbox_min
    section_box.Max = bbox_max

    DB.ViewSection.CreateSection(doc, section_type_id, section_box)

def create_section_from_point(el, section_type_id):
    loc = el.Location
    if not isinstance(loc, DB.LocationPoint):
        return

    bb = el.get_BoundingBox(None)
    if not bb:
        return

    minZ = bb.Min.Z
    maxZ = bb.Max.Z
    center = (bb.Min + bb.Max) * 0.5

    dx = (bb.Max.X - bb.Min.X) * 0.75
    dy = (bb.Max.Y - bb.Min.Y) * 0.75
    dz = (maxZ - minZ) * 1.5

    bbox_min = DB.XYZ(-dx, -dy, -dz / 2)
    bbox_max = DB.XYZ(dx, dy, dz / 2)

    t = DB.Transform.Identity
    t.Origin = center
    t.BasisX = DB.XYZ.BasisX
    t.BasisY = DB.XYZ.BasisZ
    t.BasisZ = -DB.XYZ.BasisY

    section_box = DB.BoundingBoxXYZ()
    section_box.Transform = t
    section_box.Min = bbox_min
    section_box.Max = bbox_max

    DB.ViewSection.CreateSection(doc, section_type_id, section_box)

def create_section(el, section_type_id):
    if isinstance(el, DB.Wall):
        create_section_from_linear(el, section_type_id)
    elif is_valid_mep_element(el):
        loc = el.Location
        if isinstance(loc, DB.LocationCurve):
            create_section_from_linear(el, section_type_id)
        elif isinstance(loc, DB.LocationPoint):
            create_section_from_point(el, section_type_id)

def main():
    selection = revit.get_selection()
    if not selection:
        script.exit("No elements selected.")

    section_type = get_section_view_type()
    if section_type == DB.ElementId.InvalidElementId:
        script.exit("No default section view type found.")

    count = 0
    with revit.Transaction("Create Sections from Selection"):
        for el in selection:
            try:
                create_section(el, section_type)
                count += 1
            except Exception as e:
                output.print_md("*Error on `{}` – {}*".format(el.Id, e))

    script.get_output().print_md("✅ Created sections for {} element(s).".format(count))

main()
