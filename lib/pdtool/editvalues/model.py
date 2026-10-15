# -*- coding: utf-8 -*-
"""What Edit Values reads from the model and writes to it. Needs Revit.

The new values and their checks are worked out by pdtool.values, which is tested outside Revit; this module finds the
elements, their parameters and fields, and writes the values in one transaction group, "PD: Edit Values"."""
import System
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, Element, ElementId, ElementMulticategoryFilter,
                               ElementType, FilteredElementCollector, RevitLinkInstance, StorageType)
from System.Collections.Generic import List

from pdtool import id_value, linkrooms, mep, values
from pdtool.transaction import run, transaction_group
from pdtool.worksharing import block_reason

LABEL = u"Edit Values"
SELECTION = u"selection"
VIEW = u"view"
MODEL = u"model"
LINKS = u"RVT Links"


def name_of(element):
    """An element's name (Element.Name cannot be read directly on some element types in IronPython)."""
    if element is None:
        return u""
    try:
        return Element.Name.GetValue(element) or u""
    except Exception:
        try:
            return element.Name or u""
        except Exception:
            return u""


def category_name(category):
    """The BuiltInCategory name of a category ("OST_LightingFixtures"), or u"" where it has none."""
    if category is None:
        return u""
    try:
        bic = category.BuiltInCategory
    except AttributeError:
        bic = System.Enum.ToObject(BuiltInCategory, id_value(category.Id))
    return u"{}".format(bic)


class Item(object):
    """One element in the scope, with what the window shows of it."""

    def __init__(self, doc, element):
        self.element = element
        self.id = id_value(element.Id)
        self.linked = isinstance(element, RevitLinkInstance)
        category = element.Category
        self.category = category_name(category)
        self.category_label = category.Name if category is not None else u"(no category)"
        type_id = element.GetTypeId()
        self.type = doc.GetElement(type_id) if type_id != ElementId.InvalidElementId else None
        self.type_id = id_value(type_id) if self.type is not None else None
        self.type_name = name_of(self.type)
        if self.linked:
            self.family = name_of(element).split(u" : ")[0]
        else:
            try:
                self.family = (self.type.FamilyName or u"") if self.type is not None else u""
            except Exception:
                self.family = u""
        self.in_group = element.GroupId != ElementId.InvalidElementId

    @property
    def type_key(self):
        """Category, family and type: the line in the family and type list."""
        return (self.category_label, self.family, self.type_name)


def collect(doc, scope, view=None, selected=None):
    """The items in a scope. The active view and the whole model give the PD categories only (mep.categories);
    the selection gives every placed element selected, linked models included, so the window can list them."""
    if scope == SELECTION:
        elements = [doc.GetElement(i) for i in (selected or [])]
        elements = [e for e in elements if e is not None and not isinstance(e, ElementType) and
                    (e.Category is not None or isinstance(e, RevitLinkInstance))]
    else:
        cats = [c for c in (mep.resolve(n) for n in mep.categories(mep.EDIT)) if c is not None]
        collector = FilteredElementCollector(doc, view.Id) if scope == VIEW else FilteredElementCollector(doc)
        elements = collector.WhereElementIsNotElementType().WherePasses(
            ElementMulticategoryFilter(List[BuiltInCategory](cats))).ToElements()
    return [Item(doc, e) for e in elements]


# ---- parameters --------------------------------------------------------------------------------------------------

def kind_of(parameter):
    """values.TEXT, WHOLE or YESNO for a parameter Edit Values can change, else None (numbers with units, element
    choices and lists such as Workset are left to Revit)."""
    storage = parameter.StorageType
    if storage == StorageType.String:
        return values.TEXT
    if storage != StorageType.Integer:
        return None
    try:
        spec = parameter.Definition.GetDataType().TypeId or u""
    except Exception:
        try:
            old = u"{}".format(parameter.Definition.ParameterType)
        except Exception:
            return None
        return {u"YesNo": values.YESNO, u"Integer": values.WHOLE, u"NumberOfPoles": values.WHOLE}.get(old)
    if u"spec.bool" in spec:
        return values.YESNO
    if u"spec.int64" in spec or u"numberOfPoles" in spec:
        return values.WHOLE
    return None


class Param(object):
    """A parameter every chosen element has: its name, kind, and whether it is on the type."""

    def __init__(self, name, kind, is_type):
        self.name = name
        self.kind = kind
        self.is_type = is_type

    @property
    def where(self):
        return u"type" if self.is_type else u"instance"

    @property
    def key(self):
        return (self.name, self.is_type)

    def __repr__(self):
        return u"<Param {} {} {}>".format(self.name, self.where, self.kind)


def _parameters_of(host, is_type, found, names):
    """Adds the host's changeable parameters to found {(name, is_type): (kind, read_only)} and every name to names."""
    if host is None:
        return
    for p in host.Parameters:
        name = p.Definition.Name if p.Definition is not None else None
        if not name:
            continue
        names.add(name)
        kind = kind_of(p)
        if kind is None:
            continue
        key = (name, is_type)
        kind_before, read_only_before = found.get(key, (kind, True))
        found[key] = (kind if kind == kind_before else None, read_only_before and p.IsReadOnly)


def parameters(items):
    """(params, names): the parameters every item has that Edit Values can change and that are not read only on all
    of them, sorted by name, instance before type; and every parameter name on any of them, for copy, patterns and the
    value filter. One element of each type is read, since elements of one type have the same parameters."""
    samples = {}
    for item in items:
        if not item.linked:
            samples.setdefault((item.category, item.type_id), item)
    shared = None
    names = set()
    read_only = {}
    for item in samples.values():
        found = {}
        _parameters_of(item.element, False, found, names)
        _parameters_of(item.type, True, found, names)
        here = dict((k, kind) for k, (kind, ro) in found.items() if kind is not None)
        for k, (kind, ro) in found.items():
            read_only[k] = read_only.get(k, True) and ro
        if shared is None:
            shared = here
        else:
            shared = dict((k, kind) for k, kind in shared.items() if here.get(k) == kind)
    params = [Param(name, kind, is_type) for (name, is_type), kind in (shared or {}).items()
              if not read_only.get((name, is_type), True)]
    params.sort(key=lambda p: (p.name.lower(), p.is_type))
    return params, sorted(names, key=lambda n: n.lower())


def find(host, name, kind):
    """(parameter, None), or (None, the reason the element is left out)."""
    if host is None:
        return None, values.NOT_ON_ELEMENT
    found = [p for p in host.GetParameters(name) if kind_of(p) == kind]
    if not found:
        return None, values.NOT_ON_ELEMENT
    if len(found) > 1:
        return None, values.TWO_PARAMETERS
    return found[0], None


def read(parameter, kind):
    """The stored value: text (empty for no value), or an int, or None where a number or yes/no has no value."""
    if kind == values.TEXT:
        return parameter.AsString() or u""
    return parameter.AsInteger() if parameter.HasValue else None


def text_of(parameter):
    """A parameter's value as Revit shows it, for copies, patterns and the value filter."""
    if parameter is None:
        return u""
    if parameter.StorageType == StorageType.String:
        return parameter.AsString() or u""
    if not parameter.HasValue:
        return u""
    text = parameter.AsValueString()
    if text is None and parameter.StorageType == StorageType.Integer:
        text = u"{}".format(parameter.AsInteger())
    return text or u""


# ---- fields ------------------------------------------------------------------------------------------------------

_LEVEL_PARAMETERS = (u"FAMILY_LEVEL_PARAM", u"INSTANCE_REFERENCE_LEVEL_PARAM", u"RBS_START_LEVEL_PARAM",
                     u"SCHEDULE_LEVEL_PARAM", u"INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM")
_TYPE_MARK_PARAMETERS = (u"ALL_MODEL_TYPE_MARK", u"WINDOW_TYPE_ID")


def _builtin(element, names):
    for n in names:
        bip = getattr(BuiltInParameter, n, None)
        if bip is None or element is None:
            continue
        p = element.get_Parameter(bip)
        if p is not None and p.HasValue:
            return p
    return None


def level_name(doc, element):
    level_id = element.LevelId
    if level_id is None or level_id == ElementId.InvalidElementId:
        p = _builtin(element, _LEVEL_PARAMETERS)
        level_id = p.AsElementId() if p is not None and p.StorageType == StorageType.ElementId else None
    level = doc.GetElement(level_id) if level_id is not None and level_id != ElementId.InvalidElementId else None
    return name_of(level)


class Fields(object):
    """Gives the text of a field or parameter for one item: the PD fields of values.FIELDS, then the item's own
    parameters, then its type's. finder is a linkrooms.RoomFinder, or None where no room is needed."""

    def __init__(self, doc, finder=None):
        self.doc = doc
        self.finder = finder

    def text(self, item, name):
        special = values.special_field(name)
        element = item.element
        if special == values.LEVEL:
            return level_name(self.doc, element)
        if special in values.ROOM_FIELDS:
            room = self.finder.room(element) if self.finder is not None else None
            return linkrooms.number(room) if special == values.ROOM_NUMBER else linkrooms.name(room)
        if special == values.PANEL:
            return text_of(_builtin(element, (u"RBS_ELEC_CIRCUIT_PANEL_PARAM",)))
        if special == values.CIRCUIT:
            return text_of(_builtin(element, (u"RBS_ELEC_CIRCUIT_NUMBER",)))
        if special == values.TYPE_MARK:
            return text_of(_builtin(item.type, _TYPE_MARK_PARAMETERS))
        if special == values.FAMILY:
            return item.family
        if special == values.TYPE:
            return item.type_name
        return self.parameter_text(item, name)

    def parameter_text(self, item, name):
        """The text of a parameter of the item, or of its type where the item has none of that name."""
        p = item.element.LookupParameter(name)
        if p is None and item.type is not None:
            p = item.type.LookupParameter(name)
        return text_of(p)

    def getter(self, item):
        """For patterns: the PD fields first, then parameters."""
        return lambda name: self.text(item, name)

    def parameter_getter(self, item):
        """For copies and the value filter: parameters only, so a parameter called Level or Panel is read as it is."""
        return lambda name: self.parameter_text(item, name)


def feeds_board(circuit):
    """True where a circuit feeds electrical equipment (a board): its Load Name is the board's name."""
    try:
        for element in circuit.Elements:
            if category_name(element.Category) == u"OST_ElectricalEquipment":
                return True
    except Exception:
        pass
    return False


def type_counts(doc, items):
    """{type id: instances in the whole model} for the categories of the items."""
    cats = []
    for item in items:
        if item.linked or not item.category or item.category == u"INVALID":
            continue
        bic = mep.resolve(item.category)
        if bic is not None and bic not in cats:
            cats.append(bic)
    counts = {}
    if not cats:
        return counts
    elements = FilteredElementCollector(doc).WhereElementIsNotElementType().WherePasses(
        ElementMulticategoryFilter(List[BuiltInCategory](cats)))
    for e in elements:
        key = id_value(e.GetTypeId())
        counts[key] = counts.get(key, 0) + 1
    return counts


def can_empty(doc, parameter):
    """Revit empties a whole number or yes/no value (ClearValue) only on a shared parameter set to hide when it has no
    value; it refuses every other one."""
    if not parameter.IsShared:
        return False
    shared = doc.GetElement(parameter.Id)
    try:
        return bool(shared.ShouldHideWhenNoValue())
    except Exception:
        return False


def blocked(doc, element):
    """None where the element can be changed now, else the reason (borrowed by another user, changed in the central
    model since the last reload)."""
    return block_reason(doc, element)


# ---- writing -----------------------------------------------------------------------------------------------------

class Target(object):
    """One value to write: key (the check row's key), host (the element or type), the parameter name and kind, and
    the stored value to write (None empties a whole number or yes/no)."""

    def __init__(self, key, host, name, kind, new):
        self.key = key
        self.host = host
        self.name = name
        self.kind = kind
        self.new = new


def _reason(ex):
    text = u"{}".format(getattr(ex, u"Message", None) or ex)
    return text.strip() or type(ex).__name__


def write(target):
    parameter, reason = find(target.host, target.name, target.kind)
    if parameter is None:
        raise ValueError(reason)
    if target.kind == values.TEXT:
        done = parameter.Set(target.new or u"")
    elif target.new is None:
        parameter.ClearValue()
        done = True
    else:
        done = parameter.Set(int(target.new))
    if done is False:
        raise ValueError(u"Revit did not accept the value")


class Applied(object):
    """What happened: results {key: None where written, else Revit's reason}, the warnings Revit gave, and whether
    the change was kept (False for a trial run, or where nothing could be written)."""

    def __init__(self):
        self.results = {}
        self.warnings = []
        self.kept = False
        self.trial = False

    @property
    def written(self):
        return len([k for k, reason in self.results.items() if reason is None])


def apply(doc, targets, dry_run=False):
    """Writes every target in one transaction group, PD: Edit Values, so one Ctrl+Z undoes it all. All the values go
    in one transaction; where Revit refuses that, each is written in its own, so only the ones Revit refuses are left
    out, each with Revit's reason. Every value is read back before the group closes. dry_run undoes it all at the end."""
    out = Applied()
    out.trial = dry_run
    to_write = []
    for t in targets:
        reason = blocked(doc, t.host)
        if reason:
            out.results[t.key] = reason
        else:
            to_write.append(t)
    if not to_write:
        return out
    with transaction_group(doc, LABEL, dry_run) as group:
        failed = {}

        def write_all():
            for t in to_write:
                try:
                    write(t)
                except Exception as ex:
                    failed[t.key] = _reason(ex)

        result = group.add(run(doc, LABEL, write_all))
        if not result.committed:
            failed.clear()
            for t in to_write:
                one = group.add(run(doc, LABEL, write, t))
                if not one.committed:
                    failed[t.key] = u"; ".join(one.errors) or u"Revit did not accept the change"
        for t in to_write:
            if t.key in failed:
                out.results[t.key] = failed[t.key]
                continue
            parameter, reason = find(t.host, t.name, t.kind)
            now = read(parameter, t.kind) if parameter is not None else None
            if parameter is None or not values.same(t.kind, now, t.new):
                out.results[t.key] = reason or u"The value read back after writing is {}".format(
                    values.shown(t.kind, now) or u"empty")
            else:
                out.results[t.key] = None
        for r in group.results:
            for w in r.warnings:
                if w not in out.warnings:
                    out.warnings.append(w)
    out.kept = group.kept
    return out
