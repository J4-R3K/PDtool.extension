# -*- coding: utf-8 -*-
__title__   = "Select Tags\nby Text"
__doc__     = """Version = 1.0
Date    = 2026-03-07
________________________________________________________________
Description:

Select all tags in the current view or entire project that
contain a specific text string (case-insensitive).

Works with any tag type: Room Tags, Door Tags, Space Tags,
Area Tags, Independent Tags, Multi-Category Tags, etc.

________________________________________________________________
How-To:

1. Run the tool
2. Choose scope: Active View or Entire Project
3. Type the text string to search for
4. Matching tags are selected in Revit

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
clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    ElementId,
    IndependentTag,
    SpatialElementTag
)
from System.Collections.Generic import List

from pyrevit import revit, forms


doc   = revit.doc
uidoc = revit.uidoc


# All tag built-in category names (resolved via getattr so
# missing ones in older/newer Revit builds are silently skipped)
_TAG_CAT_NAMES = [
    "OST_CableTrayFittingTags",
    "OST_CableTrayTags",
    "OST_CalloutHeads",
    "OST_CaseworkTags",
    "OST_CeilingTags",
    "OST_ConduitFittingTags",
    "OST_ConduitTags",
    "OST_CurtainWallPanelTags",
    "OST_DoorTags",
    "OST_DuctAccessoryTags",
    "OST_DuctFittingTags",
    "OST_DuctInsulationsTags",
    "OST_DuctLiningsTags",
    "OST_DuctTags",
    "OST_ElectricalCircuitTags",
    "OST_ElectricalEquipmentTags",
    "OST_ElectricalFixtureTags",
    "OST_FloorTags",
    "OST_FurnitureTags",
    "OST_GenericModelTags",
    "OST_LightingDeviceTags",
    "OST_LightingFixtureTags",
    "OST_MechanicalEquipmentTags",
    "OST_MultiCategoryTags",
    "OST_NurseCallDeviceTags",
    "OST_PipeAccessoryTags",
    "OST_PipeFittingTags",
    "OST_PipeInsulationsTags",
    "OST_PipeTags",
    "OST_PlumbingFixtureTags",
    "OST_RoofTags",
    "OST_RoomTags",
    "OST_SecurityDeviceTags",
    "OST_SpecialityEquipmentTags",
    "OST_SpaceTags",
    "OST_SprinklerTags",
    "OST_StructuralColumnTags",
    "OST_StructuralConnectionHandlerTags",
    "OST_StructuralFoundationTags",
    "OST_StructuralFramingTags",
    "OST_TelephoneDeviceTags",
    "OST_WallTags",
    "OST_WindowTags",
    "OST_AreaTags",
    "OST_FireAlarmDeviceTags",
    "OST_CommunicationDeviceTags",
    "OST_DataDeviceTags",
]

TAG_CATEGORIES = []
for _name in _TAG_CAT_NAMES:
    _bic = getattr(BuiltInCategory, _name, None)
    if _bic is not None:
        TAG_CATEGORIES.append(_bic)


def get_tag_text(tag):
    """Extract displayed text from any tag element.
    Tries multiple approaches for maximum compatibility."""

    # 1) IndependentTag.TagText (Revit 2022+)
    if isinstance(tag, IndependentTag):
        try:
            txt = tag.TagText
            if txt:
                return txt
        except:
            pass

    # 2) SpatialElementTag.TagText (Room/Space/Area tags)
    if isinstance(tag, SpatialElementTag):
        try:
            txt = tag.TagText
            if txt:
                return txt
        except:
            pass

    # 3) Fallback: read all string parameters on the tag
    try:
        for p in tag.Parameters:
            try:
                if p.HasValue and p.StorageType.ToString() == "String":
                    val = p.AsString()
                    if val:
                        return val
            except:
                pass
    except:
        pass

    # 4) Fallback: read the tagged element's parameter values
    #    (useful when the tag simply displays the host's param)
    try:
        host_id = None
        if isinstance(tag, IndependentTag):
            try:
                # Revit 2022+ multi-ref tags
                ref_ids = tag.GetTaggedLocalElementIds()
                if ref_ids and ref_ids.Count > 0:
                    for rid in ref_ids:
                        host_id = rid
                        break
            except:
                pass
            if host_id is None:
                try:
                    host_id = tag.TaggedLocalElementId
                except:
                    pass

        if host_id is not None and host_id != ElementId.InvalidElementId:
            host = doc.GetElement(host_id)
            if host:
                parts = []
                for p in host.Parameters:
                    try:
                        if p.HasValue and p.StorageType.ToString() == "String":
                            val = p.AsString()
                            if val:
                                parts.append(val)
                    except:
                        pass
                if parts:
                    return " | ".join(parts)
    except:
        pass

    return ""


def collect_tags(scope_view_id):
    """Collect all tag elements from the given scope.
    scope_view_id: ElementId of active view, or None for project-wide."""

    all_tags = []

    for bic in TAG_CATEGORIES:
        try:
            if scope_view_id:
                collector = FilteredElementCollector(doc, scope_view_id)
            else:
                collector = FilteredElementCollector(doc)

            elements = collector.OfCategory(bic) \
                               .WhereElementIsNotElementType() \
                               .ToElements()

            for el in elements:
                all_tags.append(el)
        except:
            # Some categories may not exist in every project
            pass

    return all_tags


def main():

    # --- Scope selection ---
    scope = forms.CommandSwitchWindow.show(
        ["Active View", "Entire Project"],
        message="Search scope:"
    )

    if not scope:
        return

    # --- Search string ---
    search = forms.ask_for_string(
        prompt="Enter text to search for (case-insensitive):",
        title="Select Tags by Text"
    )

    if not search:
        return

    search_lower = search.lower()

    # --- Collect tags ---
    if scope == "Active View":
        active_view = doc.ActiveView
        if active_view is None:
            forms.alert("No active view.", exitscript=True)
        tags = collect_tags(active_view.Id)
    else:
        tags = collect_tags(None)

    if not tags:
        forms.alert("No tags found in {}.".format(
            "active view" if scope == "Active View" else "project"))
        return

    # --- Filter by text ---
    matching_ids = List[ElementId]()

    for tag in tags:
        txt = get_tag_text(tag)
        if txt and search_lower in txt.lower():
            matching_ids.Add(tag.Id)

    # --- Select ---
    if matching_ids.Count > 0:
        uidoc.Selection.SetElementIds(matching_ids)
        forms.alert("{} tag(s) selected containing '{}'.".format(
            matching_ids.Count, search))
    else:
        forms.alert("No tags found containing '{}'.".format(search))


if __name__ == "__main__":
    main()
