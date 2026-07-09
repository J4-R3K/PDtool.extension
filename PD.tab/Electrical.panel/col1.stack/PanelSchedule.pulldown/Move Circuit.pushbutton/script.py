# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB.Electrical import PanelScheduleView
import re


doc = revit.doc


class CircuitOption(forms.TemplateListItem):
    def __init__(self, item, way_label, source_row):
        forms.TemplateListItem.__init__(self, item)
        self.way_label = way_label
        self.source_row = source_row

    @property
    def name(self):
        c = self.item
        cnum = safe_attr(c, 'CircuitNumber', '')
        load_name = get_load_name(c)
        return u"Way {0} | Cct {1} | {2}".format(self.way_label or '?', cnum, load_name)


class PanelOption(forms.TemplateListItem):
    def __init__(self, item):
        forms.TemplateListItem.__init__(self, item)

    @property
    def name(self):
        p = self.item
        pname = safe_attr(p, 'Name', 'Unnamed Panel')
        mark = get_param_str(p, 'Mark')
        bits = [pname]
        if mark:
            bits.append('Mark: {}'.format(mark))
        return ' | '.join(bits)


def safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def get_param_str(elem, pname):
    try:
        p = elem.LookupParameter(pname)
        if p and p.HasValue:
            if p.StorageType == DB.StorageType.String:
                return p.AsString()
            v = p.AsValueString()
            if v:
                return v
    except Exception:
        pass
    return ''


def get_active_panel_schedule():
    view = doc.ActiveView
    if not isinstance(view, PanelScheduleView):
        forms.alert('Open a panel schedule view first.', exitscript=True)
    return view


def get_source_panel_from_psv(psv):
    try:
        return doc.GetElement(psv.GetPanel())
    except Exception:
        return None


def get_all_panels(exclude_id=None):
    panels = []
    fec = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_ElectricalEquipment).WhereElementIsNotElementType()
    for e in fec:
        try:
            if exclude_id and e.Id.IntegerValue == exclude_id.IntegerValue:
                continue
            if e.MEPModel is not None:
                panels.append(e)
        except Exception:
            continue
    panels.sort(key=lambda x: safe_attr(x, 'Name', ''))
    return panels


def get_body_section(psv):
    td = psv.GetTableData()
    return td.GetSectionData(DB.SectionType.Body)


def iter_slot_rows(psv):
    body = get_body_section(psv)
    for row in range(body.FirstRowNumber, body.LastRowNumber + 1):
        yield row


def get_circuit_for_row(psv, row):
    for col in range(0, 8):
        try:
            eid = psv.GetCircuitIdByCell(row, col)
            if eid and eid != DB.ElementId.InvalidElementId:
                return doc.GetElement(eid)
        except Exception:
            pass
    return None


def is_spare_row(psv, row):
    for col in range(0, 8):
        try:
            if psv.IsSpare(row, col):
                return True
        except Exception:
            pass
    return False


def get_way_label(psv, row, circuit=None):
    if circuit is not None:
        cnum = safe_attr(circuit, 'CircuitNumber', '')
        if cnum:
            m = re.match(r'(\d+)', str(cnum))
            if m:
                return m.group(1)
    return str(row)


def get_load_name(circuit):
    for pname in ['Load Name', 'Description']:
        val = get_param_str(circuit, pname)
        if val and val.strip() and val.strip().lower() != 'spare':
            return val.strip()
    try:
        names = []
        for eid in circuit.Elements:
            e = doc.GetElement(eid)
            if e:
                n = get_param_str(e, 'Load Name') or safe_attr(e, 'Name', None)
                if n and str(n).strip().lower() != 'spare':
                    names.append(str(n).strip())
        if names:
            return ', '.join(names[:3])
    except Exception:
        pass
    return 'Unnamed load'


def get_circuit_rows(psv):
    results = []
    seen = set()
    for row in iter_slot_rows(psv):
        if is_spare_row(psv, row):
            continue
        circuit = get_circuit_for_row(psv, row)
        if not circuit:
            continue
        cid = circuit.Id.IntegerValue
        if cid in seen:
            continue
        seen.add(cid)
        way = get_way_label(psv, row, circuit)
        results.append((row, circuit, way))
    return results


def reassign_circuit_to_panel(circuit, dest_panel):
    try:
        circuit.SelectPanel(dest_panel)
        return True, None
    except Exception as ex:
        return False, str(ex)


def main():
    source_psv = get_active_panel_schedule()
    source_panel = get_source_panel_from_psv(source_psv)
    if not source_panel:
        forms.alert('Could not resolve the source panel from the active panel schedule.', exitscript=True)

    circuit_rows = get_circuit_rows(source_psv)
    if not circuit_rows:
        forms.alert('No non-spare circuits found in the active panel schedule.', exitscript=True)

    circuit_options = [CircuitOption(c, w, row) for row, c, w in circuit_rows]
    selected = forms.SelectFromList.show(circuit_options, title='Select circuit to move', multiselect=False, width=700, button_name='Next')
    if not selected:
        script.exit()

    source_circuit = selected.item if hasattr(selected, 'item') else selected
    panels = get_all_panels(exclude_id=source_panel.Id)
    panel_options = [PanelOption(p) for p in panels]
    dest_panel_opt = forms.SelectFromList.show(panel_options, title='Select destination panel', multiselect=False, width=700, button_name='Move Circuit')
    if not dest_panel_opt:
        script.exit()

    dest_panel = dest_panel_opt.item if hasattr(dest_panel_opt, 'item') else dest_panel_opt
    t = DB.Transaction(doc, 'Reassign circuit to different panel')
    t.Start()
    ok, err = reassign_circuit_to_panel(source_circuit, dest_panel)
    if not ok:
        t.RollBack()
        forms.alert("Could not assign circuit to destination panel:\n{}".format(err), exitscript=True)
    t.Commit()


if __name__ == '__main__':
    main()
