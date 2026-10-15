# -*- coding: utf-8 -*-
"""Reads schedules and panel schedules from Revit for PD Schedules. Needs Revit.

Read only: no transaction is opened and nothing in the model is set. Every cell is read with TableView.GetCellText,
which gives the text Revit displays, so the sheet reads as the schedule does in Revit.

What the read-only probes of a project model found (Revit 2024.3.60, 15/10/2026), and how this module follows it:
- A section's valid rows are FirstRowNumber to NumberOfRows - 1, and its valid columns FirstColumnNumber to
  NumberOfColumns - 1. A schedule starts at 0. A panel schedule starts at 1 (row 0 and column 0 raise an error), and
  its last counted column raises one too. Every call is guarded, and a row or column that Revit cannot read at all
  is left out.
- GetColumnWidth gives the width on the sheet, in feet.
- The body of a schedule leaves out hidden fields.
- In a panel schedule body, the heading row has slot 0; each slot row gives its slot number and the circuit in it
  (GetSlotNumberByCell, GetCircuitIdByCell). A three-phase circuit gives the same circuit in its three rows.
- A spare is a circuit whose CircuitType is Spare (LoadName "Spare"); a space is a slot marked with IsSpace.
- Built-in parameters that exist: RBS_ELEC_PANEL_NAME, RBS_ELEC_PANEL_SUPPLY_FROM_PARAM,
  RBS_ELEC_PANEL_NUMPHASES_PARAM, RBS_ELEC_CIRCUIT_NUMBER_OF_ELEMENTS_PARAM, RBS_ELEC_CIRCUIT_WIRE_TYPE_PARAM. The
  panel's Location is read by name ("Location"): there is no built-in parameter for it.
"""
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ElementId, FilteredElementCollector, SectionType,
                               SpecTypeId, StorageType, UnitTypeId, UnitUtils, ViewSchedule)
from Autodesk.Revit.DB.Electrical import PanelScheduleView

from pdtool import id_value
from pdtool.schedx import dbchart
from pdtool.schedx.grid import Section, heading_rows

KIND_SCHEDULE = u"schedule"
KIND_PANEL = u"panel schedule"
PANEL_SECTIONS = ((SectionType.Header, u"Header"), (SectionType.Body, u"Body"), (SectionType.Summary, u"Summary"),
                  (SectionType.Footer, u"Footer"))


def _name(element):
    try:
        return element.Name
    except Exception:
        from Autodesk.Revit.DB import Element
        return Element.Name.GetValue(element)


def _kind(view):
    """What kind of schedule a ViewSchedule is, as the list in the window names it."""
    try:
        definition = view.Definition
        if getattr(view, "IsInternalKeynoteSchedule", False):
            return u"keynote legend"
        if getattr(definition, "IsKeySchedule", False):
            return u"key schedule"
        if getattr(definition, "IsMaterialTakeoff", False):
            return u"material takeoff"
        cat = id_value(definition.CategoryId)
        if cat == int(BuiltInCategory.OST_Sheets):
            return u"sheet list"
        if cat == int(BuiltInCategory.OST_Views):
            return u"view list"
    except Exception:
        pass
    return KIND_SCHEDULE


def list_items(doc):
    """The schedules and panel schedules of the model, as the window lists them: [{"id", "name", "kind", "view"}],
    sorted by name. Revision schedules inside title blocks and templates are left out, as Revit's Project Browser
    leaves them out.

    The list does not give the number of rows: GetTableData makes Revit build the whole table, and on a project model
    that took 63 seconds for 115 schedules (15/10/2026). The rows of each sheet are given after the export."""
    out = []
    for v in FilteredElementCollector(doc).OfClass(ViewSchedule):
        try:
            if v.IsTemplate or v.IsTitleblockRevisionSchedule:
                continue
        except Exception:
            continue
        out.append({"id": id_value(v.Id), "name": _name(v), "kind": _kind(v), "view": v})
    for v in FilteredElementCollector(doc).OfClass(PanelScheduleView):
        try:
            if v.IsTemplate or v.IsPanelScheduleTemplate():
                continue
        except Exception:
            continue
        out.append({"id": id_value(v.Id), "name": _name(v), "kind": KIND_PANEL, "view": v})
    out.sort(key=lambda e: e["name"].lower())
    return out


# ---- cells -----------------------------------------------------------------------------------------------------------

def _try(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def read_section(view, stype, name):
    """A Section of what Revit shows in one section of the table, or None when the table has no such section.
    Returns (section, hidden)."""
    data = _try(view.GetTableData().GetSectionData, stype)
    if data is None:
        return None, False
    hidden = bool(_try(lambda: data.HideSection))
    fr, fc = data.FirstRowNumber, data.FirstColumnNumber
    rows_all = list(range(fr, data.NumberOfRows))
    cols_all = list(range(fc, data.NumberOfColumns))
    text = {}
    read_rows, read_cols = set(), set()
    for r in rows_all:
        for c in cols_all:
            t = _try(view.GetCellText, stype, r, c)
            if t is None:
                continue
            text[(r, c)] = t
            read_rows.add(r)
            read_cols.add(c)
    rows = [r for r in rows_all if r in read_rows]
    cols = [c for c in cols_all if c in read_cols]
    widths = {}
    for c in cols:
        w = _try(data.GetColumnWidth, c)
        if w:
            widths[c] = w
    merges = set()
    for r in rows:
        for c in cols:
            m = _try(data.GetMergedCell, r, c)
            if m is not None and (m.Top, m.Left) == (r, c) and (m.Bottom > r or m.Right > c):
                merges.add((m.Top, m.Left, m.Bottom, m.Right))
    return Section(name, rows, cols, text, sorted(merges), widths), hidden


def read_schedule(view):
    """{"header", "body", "heading_rows", "notes"} of a ViewSchedule."""
    notes = []
    header, header_hidden = read_section(view, SectionType.Header, u"Header")
    body, _ = read_section(view, SectionType.Body, u"Body")
    if header is None or header_hidden:
        header = Section(u"Header", [], [], {})
    if body is None:
        body = Section(u"Body", [], [], {})
    definition = view.Definition
    fields = [definition.GetField(i) for i in range(definition.GetFieldCount())]
    shown = [f for f in fields if not f.IsHidden]
    hidden = [f for f in fields if f.IsHidden]
    if hidden:
        notes.append(u"Fields hidden in Revit are left out of this sheet ({}): {}.".format(
            u"1 field" if len(hidden) == 1 else u"{} fields".format(len(hidden)),
            u", ".join(_try(f.GetName) or u"?" for f in hidden)))
    headings = [f.ColumnHeading for f in shown]
    n = heading_rows(body, headings, bool(definition.ShowHeaders))
    return {"header": header, "body": body, "heading_rows": n, "notes": notes}


def read_panel(view):
    """{"sections", "notes"} of a PanelScheduleView: the sections Revit shows, in order. A section hidden in Revit is
    left out and named in the notes."""
    sections, notes = [], []
    for stype, name in PANEL_SECTIONS:
        sec, hidden = read_section(view, stype, name)
        if sec is None or not sec.rows:
            continue
        if hidden:
            notes.append(u"The {} section is hidden in Revit and is left out.".format(name.lower()))
            continue
        if name == u"Body":
            c = sec.cols[0] if sec.cols else 1
            heads = set(r for r in sec.rows if _try(view.GetSlotNumberByCell, r, c) == 0)
            sec.bold_rows = heads
            sec.number_rows = set(sec.rows) - heads
        sections.append(sec)
    return {"sections": sections, "notes": notes}


# ---- the board and its circuits -------------------------------------------------------------------------------------

def _param(element, name=None, bip=None):
    if element is None:
        return None
    try:
        return element.get_Parameter(bip) if bip is not None else element.LookupParameter(name)
    except Exception:
        return None


def _text(element, name=None, bip=None):
    """A parameter's text: AsString for text, AsValueString otherwise. None when there is no such parameter or no
    value."""
    p = _param(element, name, bip)
    if p is None or not p.HasValue:
        return None
    if p.StorageType == StorageType.String:
        return p.AsString()
    return p.AsValueString()


def _int(element, name=None, bip=None):
    p = _param(element, name, bip)
    if p is None or not p.HasValue or p.StorageType != StorageType.Integer:
        return None
    return p.AsInteger()


def _measure(element, name, spec, unit):
    """A number parameter in the unit given: an area in mm2 or a current in amps. A parameter of another kind gives
    its text as Revit shows it, so nothing is converted by guess."""
    p = _param(element, name)
    if p is None or not p.HasValue:
        return None
    if p.StorageType == StorageType.Integer:
        return p.AsInteger()
    if p.StorageType != StorageType.Double:
        return _text(element, name)
    try:
        kind = p.Definition.GetDataType()
    except Exception:
        kind = None
    if kind == spec:
        return UnitUtils.ConvertFromInternalUnits(p.AsDouble(), unit)
    if kind == SpecTypeId.Number:
        return p.AsDouble()
    return p.AsValueString()


def _area(element, name):
    return _measure(element, name, SpecTypeId.Area, UnitTypeId.SquareMillimeters)


def _current(element, name):
    return _measure(element, name, SpecTypeId.Current, UnitTypeId.Amperes)


def _first_filled(*values):
    """The first value that is not blank, or None."""
    for v in values:
        if v is not None and u"{}".format(v).strip():
            return v
    return None


def _circuit(doc, cid):
    es = doc.GetElement(cid)
    if es is None:
        return None
    wire = _text(es, bip=BuiltInParameter.RBS_ELEC_CIRCUIT_WIRE_TYPE_PARAM)
    if wire is None:
        wid = _try(lambda: es.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_WIRE_TYPE_PARAM).AsElementId())
        wire = _name(doc.GetElement(wid)) if wid and wid != ElementId.InvalidElementId else None
    return {
        "id": id_value(cid),
        "number": _try(lambda: es.CircuitNumber),
        "load_name": _try(lambda: es.LoadName),
        "spare": u"{}".format(_try(lambda: es.CircuitType)) == u"Spare",
        "wire_type": wire,
        "size_line": _area(es, u"PD_DATe_CableSizeLine"),
        "size_cpc": _area(es, u"PD_DATe_CableSizeCPC"),
        "device_type": _text(es, u"PD_DATe_ProtectiveDeviceType"),
        "device_rating": _current(es, u"PD_DATe_ProtectiveDeviceRating"),
        "circuit_type": _text(es, u"PD_DATe_CircuitType"),
        "install": _text(es, u"PD_DATe_InstallationMethod"),
        "afdd": _text(es, u"PD_DATe_IsAFDD"),
        "points": _int(es, bip=BuiltInParameter.RBS_ELEC_CIRCUIT_NUMBER_OF_ELEMENTS_PARAM),
        "poles": _try(lambda: es.PolesNumber),
        "start_slot": _try(lambda: es.StartSlot),
    }


def read_chart(doc, view, body=None):
    """({"board", "slots", "notes"}, None), or (None, why the DB chart layout cannot be made for this panel schedule).
    body: the panel's body Section when already read, so its rows are not read again."""
    data = view.GetTableData()
    config = u"{}".format(_try(lambda: data.PanelConfiguration))
    if config != u"OneColumn":
        return None, (u"The DB chart is not made, because the panel schedule is set out as {} in Revit. The DB chart "
                      u"is made only for a panel schedule set out with one column of circuits.".format(config))
    panel = doc.GetElement(view.GetPanel())
    if panel is None:
        return None, u"The DB chart is not made, because the panel schedule is not linked to a board."
    phases = _int(panel, bip=BuiltInParameter.RBS_ELEC_PANEL_NUMPHASES_PARAM) or 1
    board = {
        "project": _try(lambda: doc.ProjectInformation.Name),
        "name": _text(panel, bip=BuiltInParameter.RBS_ELEC_PANEL_NAME) or _name(panel),
        "description": _text(panel, u"PD_DATe_DBtype"),
        "location": _first_filled(_text(panel, u"PD_DATe_DBlocation"), _text(panel, u"Location")),
        "fed_from": _text(panel, bip=BuiltInParameter.RBS_ELEC_PANEL_SUPPLY_FROM_PARAM),
        "phases": phases,
        "slots": data.NumberOfSlots,
        "incoming_type": _text(panel, u"PD_DATe_IncomingDeviceType"),
        "incoming_rating": _current(panel, u"PD_DATe_IncomingDeviceRating"),
    }
    stype = SectionType.Body
    sec = data.GetSectionData(stype)
    first_col = body.cols[0] if body is not None and body.cols else sec.FirstColumnNumber
    rows = body.rows if body is not None else range(sec.FirstRowNumber, sec.NumberOfRows)
    circuits = {}
    slots = []
    shown = {}  # slot -> circuit number Revit shows in the slot's row, for the in-Revit check
    for r in rows:
        slot = _try(view.GetSlotNumberByCell, r, first_col)
        if not slot or slot < 1:
            continue
        cid = _try(view.GetCircuitIdByCell, r, first_col)
        circuit = None
        if cid is not None and cid != ElementId.InvalidElementId:
            key = id_value(cid)
            if key not in circuits:
                circuits[key] = _circuit(doc, cid)
            circuit = circuits[key]
        slots.append({"slot": slot, "circuit": circuit, "space": bool(_try(view.IsSpace, r, first_col))})
        shown[slot] = _try(view.GetCellText, stype, r, first_col)
    notes = []
    if phases not in (1, 3):
        notes.append(u"The board has {} phases. The DB chart is still made, but its layout is for one or three phases. "
                     u"Check the number of phases of the board in the model.".format(phases))
    elif board["slots"] % phases:
        notes.append(u"The number of slots on the board ({}) does not divide equally between {} phases. The DB "
                     u"chart is still made. Check the board size in the model.".format(board["slots"], phases))
    others = sorted(set(c["device_type"] for c in circuits.values()
                        if c and c["device_type"] and c["device_type"] not in dbchart.DEVICE_NAMES))
    if others:
        notes.append(u"These circuit device types are written in the DB chart as Revit holds them: {}. In the "
                     u"circuit rows, a miniature circuit-breaker (MCB) or residual current operated circuit-breaker "
                     u"with integral overcurrent protection (RCBO) is shortened only where its device type in the "
                     u"model reads exactly MCB Type B, MCB Type C, RCBO Type B or RCBO Type C; these are written "
                     u"MCB-B, MCB-C, RCBO-B and RCBO-C.".format(u", ".join(others)))
    return {"board": board, "slots": slots, "shown": shown, "notes": notes}, None


def read_item(doc, entry, panel_revit=True, panel_chart=True):
    """Everything the workbook needs from one entry of list_items (see book.py for the layout)."""
    view = entry["view"]
    item = {"name": entry["name"], "kind": entry["kind"]}
    if entry["kind"] != KIND_PANEL:
        item["schedule"] = read_schedule(view)
        return item
    panel = read_panel(view)
    if panel_revit:
        item["panel"] = panel
    if panel_chart:
        body = [s for s in panel["sections"] if s.name == u"Body"]
        try:
            item["chart"], item["chart_problem"] = read_chart(doc, view, body[0] if body else None)
        except Exception as ex:
            item["chart"], item["chart_problem"] = None, (u"The DB chart is not made, because the board could "
                                                          u"not be read: {}".format(ex))
        if item["chart"] is not None:
            header = [s for s in panel["sections"] if s.name == u"Header"]
            note = dbchart.ways_note(item["chart"]["board"], header[0] if header else None)
            if note:
                item["chart"]["notes"].append(note)
    return item
