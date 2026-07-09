# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB.Electrical import PanelScheduleView
import re


doc = revit.doc
output = script.get_output()


class CircuitItem(forms.TemplateListItem):
    def __init__(self, item):
        forms.TemplateListItem.__init__(self, item)

    @property
    def name(self):
        data = self.item
        circuit = data['circuit']
        return u"Way {0} | Cct {1} | {2}".format(data['way'], safe_attr(circuit, 'CircuitNumber', ''), get_load_name(circuit))


class PanelItem(forms.TemplateListItem):
    def __init__(self, item):
        forms.TemplateListItem.__init__(self, item)

    @property
    def name(self):
        p = self.item
        mark = get_param_str(p, 'Mark')
        return '{}{}'.format(safe_attr(p, 'Name', 'Unnamed Panel'), ' | Mark: {}'.format(mark) if mark else '')


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
    result = []
    fec = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_ElectricalEquipment).WhereElementIsNotElementType()
    for e in fec:
        try:
            if exclude_id and e.Id.IntegerValue == exclude_id.IntegerValue:
                continue
            if e.MEPModel is not None:
                result.append(e)
        except Exception:
            pass
    result.sort(key=lambda x: safe_attr(x, 'Name', ''))
    return result


def get_body_section(psv):
    return psv.GetTableData().GetSectionData(DB.SectionType.Body)


def get_circuit_id_at_row(psv, row):
    for col in range(0, 8):
        try:
            eid = psv.GetCircuitIdByCell(row, col)
            if eid and eid != DB.ElementId.InvalidElementId:
                return eid
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


def get_source_circuits(psv):
    body = get_body_section(psv)
    seen = set()
    items = []
    for row in range(body.FirstRowNumber, body.LastRowNumber + 1):
        if is_spare_row(psv, row):
            continue
        eid = get_circuit_id_at_row(psv, row)
        if not eid:
            continue
        if eid.IntegerValue in seen:
            continue
        seen.add(eid.IntegerValue)
        circuit = doc.GetElement(eid)
        items.append({'row': row, 'way': get_way_label(psv, row, circuit), 'circuit': circuit})
    return items


def reassign_circuit_to_panel(circuit, dest_panel):
    try:
        circuit.SelectPanel(dest_panel)
        return True, None
    except Exception as ex:
        return False, str(ex)


def unwrap_selected_items(selected):
    result = []
    for x in selected:
        result.append(x.item if hasattr(x, 'item') else x)
    return result


def sort_key_for_item(item):
    c = item['circuit']
    cnum = safe_attr(c, 'CircuitNumber', '') or ''
    m = re.match(r'(\d+)L(\d+)', str(cnum))
    if m:
        return (int(m.group(1)), int(m.group(2)), str(cnum))
    m2 = re.match(r'(\d+)', str(cnum))
    if m2:
        return (int(m2.group(1)), 99, str(cnum))
    try:
        return (int(item['way']), 99, str(cnum))
    except Exception:
        return (999999, 99, str(cnum))


def main():
    source_psv = get_active_panel_schedule()
    source_panel = get_source_panel_from_psv(source_psv)
    if not source_panel:
        forms.alert('Could not resolve source panel.', exitscript=True)

    source_items = get_source_circuits(source_psv)
    if not source_items:
        forms.alert('No non-spare circuits found in active panel schedule.', exitscript=True)

    selected = forms.SelectFromList.show([CircuitItem(x) for x in source_items], title='Select circuits to transfer', multiselect=True, width=700, button_name='Transfer')
    if not selected:
        script.exit()

    selected_items = unwrap_selected_items(selected)
    selected_items = sorted(selected_items, key=sort_key_for_item)
    panel = forms.SelectFromList.show([PanelItem(p) for p in get_all_panels(exclude_id=source_panel.Id)], title='Select destination panel', multiselect=False, width=600, button_name='Transfer')
    if not panel:
        script.exit()

    dest_panel = panel.item if hasattr(panel, 'item') else panel

    report = []
    t = DB.Transaction(doc, 'Bulk reassign circuits to different panel')
    t.Start()
    for item in selected_items:
        circuit = item['circuit']
        source_way = item['way']
        ok, err = reassign_circuit_to_panel(circuit, dest_panel)
        if ok:
            report.append('OK   | Way {} | {} | reassigned in ordered sequence'.format(source_way, safe_attr(circuit, 'CircuitNumber', '')))
        else:
            report.append('FAIL | Way {} | {} | {}'.format(source_way, safe_attr(circuit, 'CircuitNumber', ''), err))
    t.Commit()

    if report:
        output.print_md('## Bulk Transfer Circuits')
        for line in report:
            output.print_md('- {}'.format(line))


if __name__ == '__main__':
    main()
