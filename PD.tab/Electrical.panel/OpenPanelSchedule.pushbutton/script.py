# -*- coding: utf-8 -*-
__title__   = "Open/Create Panel Schedule"
__doc__     = """Version = 1.0
Date    = 2026-01-05
________________________________________________________________
Description:

Reads the linked panel UniqueId stored on the selected board symbol (Detail Item),
then opens an existing Panel Schedule view for that panel, or creates one if missing.

Relative Path:
...\\PD.tab\\Associate.panel\\OpenPanelSchedule.pushbutton
________________________________________________________________
How-To:

1. Select the board symbol in the drafting schematic
2. Click the button
________________________________________________________________
Author: Jarek Wityk
"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, ElementId, BuiltInCategory
)
from Autodesk.Revit.DB.Electrical import PanelScheduleView
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, Entity, AccessLevel
from System import Guid, String, Int32

from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import revit, forms, script

doc   = revit.doc
uidoc = revit.uidoc


# -------------------- Extensible Storage Schema (MUST match Link tool) --------------------
SCHEMA_GUID = Guid("7E6C8C8B-6A6E-4A3B-8B1C-1B4C34C0D9A1")
SCHEMA_NAME = "PD_BoardSymbolPanelLink"

FIELD_PANEL_UID = "PanelUniqueId"   # string
FIELD_PANEL_EID = "PanelElementId"  # int


def get_or_create_schema():
    s = Schema.Lookup(SCHEMA_GUID)
    if s:
        return s

    sb = SchemaBuilder(SCHEMA_GUID)
    sb.SetSchemaName(SCHEMA_NAME)
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)

    sb.AddSimpleField(FIELD_PANEL_UID, String)
    sb.AddSimpleField(FIELD_PANEL_EID, Int32)

    return sb.Finish()


def read_link(symbol_el):
    """Return {'uid': <uniqueid>, 'eid': <int>} or None"""
    s = get_or_create_schema()
    try:
        ent = symbol_el.GetEntity(s)
    except:
        return None

    if not ent or (hasattr(ent, "IsValid") and (not ent.IsValid())):
        return None

    try:
        f_uid = s.GetField(FIELD_PANEL_UID)
        f_eid = s.GetField(FIELD_PANEL_EID)

        uid = ent.Get[String](f_uid)
        eid = int(ent.Get[Int32](f_eid))

        if uid:
            return {"uid": uid, "eid": eid}
    except:
        pass

    return None


def resolve_panel(linkdata):
    """Try UniqueId first, then ElementId fallback."""
    if not linkdata:
        return None

    uid = linkdata.get("uid")
    if uid:
        try:
            el = doc.GetElement(uid)  # overload: GetElement(string uniqueId)
            if el:
                return el
        except:
            pass

    try:
        eid = int(linkdata.get("eid") or 0)
        if eid > 0:
            return doc.GetElement(ElementId(eid))
    except:
        pass

    return None


def find_schedules_for_panel(panel_el):
    """Return list[PanelScheduleView] that belong to the given panel."""
    res = []
    try:
        pid_int = panel_el.Id.IntegerValue
    except:
        return res

    for v in FilteredElementCollector(doc).OfClass(PanelScheduleView).ToElements():
        try:
            p = v.GetPanel()
            if p and p.IntegerValue == pid_int:
                res.append(v)
        except:
            pass
    return res


# -------------------- Inline linking support (optional) --------------------
def _is_electrical_equipment(el):
    try:
        return el and el.Category and el.Category.Id.IntegerValue == int(BuiltInCategory.OST_ElectricalEquipment)
    except:
        return False


class ElectricalEquipmentFilter(ISelectionFilter):
    def AllowElement(self, element):
        return _is_electrical_equipment(element)

    def AllowReference(self, reference, position):
        return True


def write_link(symbol_el, panel_el):
    """Write link data onto symbol element using same schema."""
    s = get_or_create_schema()
    ent = Entity(s)

    f_uid = s.GetField(FIELD_PANEL_UID)
    f_eid = s.GetField(FIELD_PANEL_EID)

    ent.Set[String](f_uid, panel_el.UniqueId)
    ent.Set[Int32](f_eid, Int32(panel_el.Id.IntegerValue))

    symbol_el.SetEntity(ent)


# -------------------- Main --------------------
sel_ids = list(uidoc.Selection.GetElementIds())
if not sel_ids or len(sel_ids) != 1:
    forms.alert("Select ONE board symbol first, then run the tool.", exitscript=True)

symbol = doc.GetElement(sel_ids[0])
if not symbol or not symbol.Category:
    forms.alert("Select the board symbol first.", exitscript=True)

# Robust category check (avoid Category.Name because it may be localized)
cat_id = symbol.Category.Id.IntegerValue
allowed = [
    int(BuiltInCategory.OST_DetailComponents),
    int(BuiltInCategory.OST_GenericAnnotation),
]
if cat_id not in allowed:
    forms.alert(
        "Selected element is not a supported board symbol.\n\nCategory: {}".format(symbol.Category.Name),
        exitscript=True
    )

linkdata = read_link(symbol)

# If not linked, offer to link now
if not linkdata:
    do_link = forms.alert("This symbol is not linked yet.\n\nLink it now?", yes=True, no=True)
    if not do_link:
        script.exit()

    try:
        pan_ref = uidoc.Selection.PickObject(ObjectType.Element, ElectricalEquipmentFilter(),
                                            "Pick the Electrical Equipment instance (panel) to link")
        panel = doc.GetElement(pan_ref.ElementId)
    except:
        script.exit()

    t = Transaction(doc, "Link Symbol → Panel (inline)")
    t.Start()
    try:
        write_link(symbol, panel)
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except:
            pass
        forms.alert("Failed to link:\n{}".format(str(ex)), exitscript=True)

    linkdata = read_link(symbol)

panel = resolve_panel(linkdata)
if not panel:
    forms.alert("Linked panel could not be found (deleted/replaced?).\nRe-link the symbol.", exitscript=True)

# Find existing schedules and open if found
schedules = find_schedules_for_panel(panel)
if schedules:
    if len(schedules) == 1:
        uidoc.ActiveView = schedules[0]
        script.exit()
    else:
        options = []
        lookup = {}
        for v in schedules:
            key = "[{}] {}".format(v.Id.IntegerValue, v.Name)
            options.append(key)
            lookup[key] = v

        pick = forms.SelectFromList.show(sorted(options),
                                         multiselect=False,
                                         title="Multiple panel schedules found",
                                         button_name="Open")
        if pick:
            uidoc.ActiveView = lookup[pick]
        script.exit()

# Otherwise create schedule, then open it
t = Transaction(doc, "Create Panel Schedule")
t.Start()
try:
    psv = PanelScheduleView.CreateInstanceView(doc, panel.Id)
    t.Commit()
except Exception as ex:
    try:
        t.RollBack()
    except:
        pass
    forms.alert(
        "Could not create a Panel Schedule for this panel.\n\n"
        "Common reasons:\n"
        "- The selected Electrical Equipment is not a valid panelboard\n"
        "- Panel electrical setup is incomplete\n\n"
        "Error:\n{}".format(str(ex)),
        exitscript=True
    )

uidoc.ActiveView = psv
