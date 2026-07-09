# -*- coding: utf-8 -*-
__title__   = "Find Linked Panel"
__doc__     = """Version = 1.0
Date    = 2026-01-05
________________________________________________________________
Description:

From a selected board symbol (Detail Item / Generic Annotation) that has been linked
to an Electrical Equipment instance (panel), this tool finds the linked panel and
zooms to it in the model (switching views as needed) and highlights it.

Relative Path:
...\\PD.tab\\Associate.panel\\FindLinkedPanel.pushbutton
________________________________________________________________
How-To:

1. Select the board symbol in the drafting schematic
2. Click "Find Linked Panel"
3. Revit will zoom to the linked Electrical Equipment panel and select it
________________________________________________________________
Author: Jarek Wityk
"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import ElementId, BuiltInCategory
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, Entity, AccessLevel
from System import Guid, String, Int32
from System.Collections.Generic import List

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


# -------------------- Main --------------------
sel_ids = list(uidoc.Selection.GetElementIds())
if not sel_ids or len(sel_ids) != 1:
    forms.alert("Select ONE board symbol first, then run the tool.", exitscript=True)

symbol = doc.GetElement(sel_ids[0])
if not symbol or not symbol.Category:
    forms.alert("Select the board symbol first.", exitscript=True)

# Only allow typical symbol categories (same as your other tools)
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
if not linkdata:
    forms.alert("This symbol is not linked yet.\nUse your Link tool first.", exitscript=True)

panel = resolve_panel(linkdata)
if not panel:
    forms.alert("Linked panel could not be found (deleted/replaced?).\nRe-link the symbol.", exitscript=True)

# Jump/zoom to the element (Revit will choose an appropriate view)
try:
    uidoc.ShowElements(panel.Id)
except Exception as ex:
    forms.alert("Could not zoom to linked panel:\n{}".format(str(ex)), exitscript=True)

# Highlight/select it
try:
    sel_set = List[ElementId]()
    sel_set.Add(panel.Id)
    uidoc.Selection.SetElementIds(sel_set)
except Exception as ex:
    forms.alert("Panel found but could not be selected:\n{}".format(str(ex)))
