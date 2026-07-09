# -*- coding: utf-8 -*-
__title__   = "Link: Symbol → Panel"
__doc__     = """Version = 1.0
Date    = 2026-01-05
________________________________________________________________
Description:

Pick a board symbol (Detail Item / Detail Component / Generic Annotation) on a Drafting schematic
and link it to a specific Electrical Equipment instance (panel) by storing the panel UniqueId
on the symbol using Extensible Storage.

Relative Path:
...\\PD.tab\\Schematic.panel\\Link Board Symbol.pushbutton
________________________________________________________________
How-To:

1. Run tool
2. Pick the board symbol (detail item) in drafting schematic
3. Pick the Electrical Equipment panel instance
________________________________________________________________
Author: Jarek Wityk
"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import Transaction, BuiltInCategory, FamilyInstance
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, Entity, AccessLevel
from System import Guid, String, Int32

from pyrevit import revit, forms, script

doc   = revit.doc
uidoc = revit.uidoc


# -------------------- Schema (MUST match your existing link tool) --------------------
SCHEMA_GUID = Guid("7E6C8C8B-6A6E-4A3B-8B1C-1B4C34C0D9A1")
SCHEMA_NAME = "PD_BoardSymbolPanelLink"

FIELD_PANEL_UID = "PanelUniqueId"
FIELD_PANEL_EID = "PanelElementId"


def _bic(name):
    try:
        return getattr(BuiltInCategory, name)
    except:
        return None

BIC_DETAIL_1 = _bic("OST_DetailComponents")
BIC_DETAIL_2 = _bic("OST_GenericAnnotation")
BIC_ELEC_EQ  = _bic("OST_ElectricalEquipment")


def _cat_is(el, bic):
    try:
        if el and el.Category and bic is not None:
            return el.Category.Id.IntegerValue == int(bic)
    except:
        pass
    return False

def _is_symbol(el):
    try:
        if not isinstance(el, FamilyInstance):
            return False
        return _cat_is(el, BIC_DETAIL_1) or _cat_is(el, BIC_DETAIL_2)
    except:
        return False

def _is_panel(el):
    try:
        return isinstance(el, FamilyInstance) and _cat_is(el, BIC_ELEC_EQ)
    except:
        return False


class SymbolFilter(ISelectionFilter):
    def AllowElement(self, element):
        return _is_symbol(element)
    def AllowReference(self, reference, position):
        return True


class PanelFilter(ISelectionFilter):
    def AllowElement(self, element):
        return _is_panel(element)
    def AllowReference(self, reference, position):
        return True


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


def write_link(symbol_el, panel_el):
    s = get_or_create_schema()
    ent = Entity(s)

    uid = panel_el.UniqueId
    eid_int = panel_el.Id.IntegerValue

    f_uid = s.GetField(FIELD_PANEL_UID)
    f_eid = s.GetField(FIELD_PANEL_EID)

    ent.Set[String](f_uid, uid)
    ent.Set[Int32](f_eid, Int32(eid_int))

    symbol_el.SetEntity(ent)


# -------------------- Main --------------------
try:
    sym_ref = uidoc.Selection.PickObject(ObjectType.Element, SymbolFilter(),
                                        "Pick the board symbol (Detail Item) on the drafting schematic")
    symbol = doc.GetElement(sym_ref.ElementId)
except:
    script.exit()

try:
    pan_ref = uidoc.Selection.PickObject(ObjectType.Element, PanelFilter(),
                                        "Pick the Electrical Equipment instance (panel) to link")
    panel = doc.GetElement(pan_ref.ElementId)
except:
    script.exit()

t = Transaction(doc, "Link Board Symbol → Panel")
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

forms.alert("✅ Linked symbol to panel:\n{}".format(panel.Name))
