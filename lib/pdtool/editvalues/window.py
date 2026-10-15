# -*- coding: utf-8 -*-
"""The Edit Values window, in the pattern of the PD Sheets window. Needs Revit and pyRevit.

Three steps in order, with Back and Next: 1 elements, 2 parameter and change, 3 check; then the results. Apply is
shown only at step 3, and nothing is written before it. Modal: Revit waits until the window is closed, and Apply
writes straight from the window, as one undo step, "PD: Edit Values".

The methods the buttons call (set_scope, chosen, choose_param, make_change, build_checks, apply) work without the
window being shown, so the in-Revit checks can drive them."""
import io
import json
import os

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System")
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Visibility

from Autodesk.Revit.DB import ElementId
from pyrevit import forms

from pdtool import linkrooms, mep, values
from pdtool.editvalues import model

LOCAL_FOLDER = os.path.join(os.environ.get("APPDATA") or u"", u"pyRevit", u"PD Edit Values")
LAST_USED_FILE = os.path.join(LOCAL_FOLDER, u"last-used.json")

RED = u"#B00020"
GREY = u"#4A5260"
NAVY = u"#1F4E79"
GREEN = u"#2E7D32"
STEP_ELEMENTS, STEP_CHANGE, STEP_CHECK, STEP_RESULTS = range(4)
OTHER = u"Other categories in the selection"
SHOW_ALL = u"All"
SHOW_CHOICES = (SHOW_ALL, values.CHANGES_STATE, values.NO_CHANGE, values.LEFT_OUT)
STATE_COLOURS = {values.CHANGES_STATE: NAVY, values.NO_CHANGE: GREY, values.LEFT_OUT: RED}
CHANGED = u"Changed"
FAILED = u"Failed"
WOULD_CHANGE = u"Would change"
VALUE_LABELS = {values.SET: u"New value", values.PREFIX: u"Text to add before the value",
                values.SUFFIX: u"Text to add after the value", values.PATTERN: u"Pattern"}
# The example at step 2 is worked out again at every key pressed, so it looks at about this many elements at most.
EXAMPLE_TRIES = 50
# Elements tried in each model with rooms, to choose the one that finds rooms for most of them.
ROOM_SAMPLE = 60


def _read_json(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    try:
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"{}".format(text))
    except Exception:
        pass


def _plural(n, one, many=None):
    return u"{} {}".format(n, one if n == 1 else (many or one + u"s"))


def _quoted(text):
    return u"“{}”".format(text)


def _groups():
    """The names of the PD groups Edit Values lists, for the notes when the list is empty."""
    return u", ".join(g.name for g in mep.groups())


# ---- rows in the lists -------------------------------------------------------------------------------------------

class CategoryRow(forms.Reactive):
    """A PD group, or a category under it, in the category list at step 1."""

    def __init__(self, win, text, categories, group=None, ticked=False):
        self.win = win
        self.text = text
        self.categories = list(categories)
        self.group = group
        self.children = []
        self._ticked = ticked
        self.weight = u"SemiBold" if group is None else u"Normal"
        self.indent = u"0" if group is None else u"20,0,0,0"

    @forms.reactive
    def ticked(self):
        return self._ticked

    @ticked.setter
    def ticked(self, value):
        self._ticked = bool(value)
        self.win.on_category_ticked(self)


class TypeRow(forms.Reactive):
    """A family and type in the list at step 1."""

    def __init__(self, win, key, count, ticked=True):
        self.win = win
        self.key = key
        self.category, self.family, self.type_name = key
        self.count = count
        self._ticked = ticked

    @forms.reactive
    def ticked(self):
        return self._ticked

    @ticked.setter
    def ticked(self, value):
        self._ticked = bool(value)
        self.win.on_type_ticked()


class ParamRow(object):
    def __init__(self, param):
        self.param = param
        self.name = param.name
        self.where = param.where
        self.kind = param.kind


class CheckRow(object):
    """One row of the check at step 3: an element, or a type where the parameter is a type parameter."""

    def __init__(self, items, host, check, is_type):
        self.items = items
        self.host = host
        self.check = check
        self.is_type = is_type
        first = items[0]
        if is_type:
            self.key = u"t{}".format(first.type_id)
            self.element = u"Type, {} chosen".format(len(items))
        else:
            self.key = u"e{}".format(first.id)
            self.element = u"{}".format(first.id)
        self.category = first.category_label
        self.family = first.family
        self.type_name = first.type_name
        self.result = u""
        self.reason = u""
        # for a type: the elements of the type in the whole model
        self.total = None

    @property
    def old(self):
        return self.check.old_text

    @property
    def new(self):
        return self.check.new_text

    @property
    def state(self):
        return self.check.state

    @property
    def notes(self):
        return u"; ".join(self.check.notes)

    @property
    def colour(self):
        return STATE_COLOURS.get(self.check.state, GREY)

    @property
    def result_colour(self):
        return RED if self.result == FAILED else (GREEN if self.result in (CHANGED, WOULD_CHANGE) else GREY)

    def ids(self):
        return [i.element.Id for i in self.items]


# ---- the window --------------------------------------------------------------------------------------------------

class EditValuesWindow(forms.WPFWindow):

    def __init__(self, xaml_path, doc, uidoc=None):
        self.ready = False
        self.quiet = False
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.uidoc = uidoc
        self.selected = list(uidoc.Selection.GetElementIds()) if uidoc is not None else []
        self.view = doc.ActiveView
        self.cache = {}
        self.scope = None
        self.items = []
        self.cat_rows = []
        self.type_rows = []
        self.params = []
        self.names = []
        self.params_for = None
        self.param = None
        self.checks = []
        self.applied = None
        self.room_sources = None
        self.finders = {}
        self.last = _read_json(LAST_USED_FILE, {})
        self.model_key = doc.Title
        self.step = STEP_ELEMENTS
        self.FilterHow.ItemsSource = list(values.FILTERS)
        self.FilterHow.SelectedIndex = 0
        self.ShowList.ItemsSource = list(SHOW_CHOICES)
        self.ShowList.SelectedIndex = 0
        self.ScopeSelection.Content = u"Elements selected in Revit ({})".format(len(self.selected))
        self.ScopeView.Content = u"Elements in the active view ({})".format(model.name_of(self.view))
        self.ready = True
        if self.selected:
            self.ScopeSelection.IsChecked = True
        else:
            self.ScopeSelection.IsEnabled = False
            self.ScopeView.IsChecked = True
        self._go(STEP_ELEMENTS)

    # ---- the steps ------------------------------------------------------------------------------------------------

    def _go(self, step):
        if step == STEP_CHANGE:
            self._enter_change()
        if step == STEP_CHECK:
            self.build_checks()
            self._show_checks()
        self.step = step
        self.Tabs.SelectedIndex = step
        for i, button in enumerate((self.Step1, self.Step2, self.Step3, self.Step4)):
            current = i == step
            button.Background = self._brush(NAVY if current else u"White")
            button.Foreground = self._brush(u"White" if current else NAVY)
        self.BackButton.IsEnabled = step > STEP_ELEMENTS
        self.NextButton.Visibility = Visibility.Visible if step < STEP_CHECK else Visibility.Collapsed
        self.ApplyButton.Visibility = Visibility.Visible if step == STEP_CHECK else Visibility.Collapsed
        self._say(u"")

    def OnStep(self, sender, args):
        step = int(sender.Tag)
        # Moving forward goes through each step's own checks, as Next does.
        while self.step < step and self.step < STEP_CHECK:
            problem = self._step_problem(self.step)
            if problem:
                self._say(problem, True)
                return
            self._go(self.step + 1)
        if step != self.step:
            self._go(step)

    def OnBack(self, sender, args):
        self._go(max(STEP_ELEMENTS, self.step - 1))

    def OnNext(self, sender, args):
        problem = self._step_problem(self.step)
        if problem:
            self._say(problem, True)
            return
        self._go(self.step + 1)

    def _step_problem(self, step):
        """What must be done before leaving a step with Next, or None."""
        if step == STEP_ELEMENTS:
            if not self.items:
                return u"No elements are listed for the option chosen. Choose another of the three options at the top."
            chosen = self.chosen()
            if not chosen:
                return (u"No element is chosen. Tick at least one category and one family and type, and check the "
                        u"filter under the lists.")
            if all(i.linked for i in chosen):
                return (u"Only linked models are chosen. A linked model and its elements cannot be changed with Edit "
                        u"Values: choose elements of this model, or open that model to change its elements.")
        if step == STEP_CHANGE:
            if self.param is None:
                return u"Choose the parameter to change."
            change = self.make_change()
            problem = change.problem(self.param.kind, self.param.name)
            if problem:
                return problem
            if self._uses_rooms(change) and not self._sources():
                return (u"Take {Room Number} and {Room Name} out of the pattern: this model and its loaded links "
                        u"have no placed rooms.")
        return None

    def _say(self, text, problem=False):
        self.Status.Text = text
        self.Status.Foreground = self._brush(RED if problem else GREY)

    def _brush(self, colour):
        from System.Windows.Media import BrushConverter
        return BrushConverter().ConvertFromString(colour)

    # ---- step 1: elements -----------------------------------------------------------------------------------------

    def OnScope(self, sender, args):
        if not self.ready:
            return
        if self.ScopeSelection.IsChecked:
            self.set_scope(model.SELECTION)
        elif self.ScopeView.IsChecked:
            self.set_scope(model.VIEW)
        else:
            self.set_scope(model.MODEL)

    def set_scope(self, scope):
        """Reads the elements of a scope (once each) and fills the category list. The selection starts with every
        category ticked; the active view and the whole model start with none."""
        self.scope = scope
        if scope not in self.cache:
            self.cache[scope] = model.collect(self.doc, scope, self.view, self.selected)
        self.items = self.cache[scope]
        self._fill_categories(scope == model.SELECTION)
        self._show_types()

    def _fill_categories(self, ticked):
        counts, labels = {}, {}
        for item in self.items:
            counts[item.category] = counts.get(item.category, 0) + 1
            labels[item.category] = item.category_label
        rows = []
        offered = mep.categories(mep.EDIT)
        groups = [(g.name, [c for c in g.categories if counts.get(c)]) for g in mep.groups(mep.EDIT)]
        others = sorted((c for c in counts if c not in offered), key=lambda c: labels[c].lower())
        if others:
            groups.append((OTHER, others))
        for name, cats in groups:
            if not cats:
                continue
            group = CategoryRow(self, u"{} ({})".format(name, sum(counts[c] for c in cats)), cats, None, ticked)
            rows.append(group)
            for c in cats:
                label = mep.label(c) if c in offered else labels[c]
                row = CategoryRow(self, u"{} ({})".format(label, counts[c]), [c], group, ticked)
                group.children.append(row)
                rows.append(row)
        self.cat_rows = rows
        self.CategoryList.ItemsSource = ObservableCollection[object](rows)
        self.EmptyNote.Visibility = Visibility.Collapsed if rows else Visibility.Visible
        if not rows:
            self.EmptyNote.Text = {
                model.SELECTION: u"Nothing that can be changed with Edit Values is selected in Revit.",
                model.VIEW: u"The active view shows no elements in the categories of the PD groups ({}). Choose Whole "
                            u"model, or close this window, open a plan or a 3D view that shows them and start Edit "
                            u"Values again.".format(_groups()),
                model.MODEL: u"This model has no elements in the categories of the PD groups ({}).".format(
                    _groups())}[self.scope]

    def on_category_ticked(self, row):
        if self.quiet:
            return
        self.quiet = True
        try:
            if row.group is None:
                for child in row.children:
                    child.ticked = row._ticked
            else:
                row.group.ticked = all(c._ticked for c in row.group.children)
        finally:
            self.quiet = False
        self._show_types()

    def on_type_ticked(self):
        if not self.quiet:
            self._count()

    def _ticked_categories(self):
        return set(r.categories[0] for r in self.cat_rows if r.group is not None and r._ticked)

    def _show_types(self):
        cats = self._ticked_categories()
        before = dict((r.key, r._ticked) for r in self.type_rows)
        counts = {}
        for item in self.items:
            if item.category in cats:
                counts[item.type_key] = counts.get(item.type_key, 0) + 1
        keys = sorted(counts, key=lambda k: (k[0].lower(), k[1].lower(), k[2].lower()))
        self.type_rows = [TypeRow(self, k, counts[k], before.get(k, True)) for k in keys]
        self.TypeGrid.ItemsSource = ObservableCollection[object](self.type_rows)
        self._count()

    def OnTickAllTypes(self, sender, args):
        self._tick_types(True)

    def OnTickNoTypes(self, sender, args):
        self._tick_types(False)

    def _tick_types(self, value):
        self.quiet = True
        try:
            for r in self.type_rows:
                r.ticked = value
        finally:
            self.quiet = False
        self._count()

    def OnFilterChanged(self, sender, args):
        if self.ready:
            self._count()

    def OnFilterListOpened(self, sender, args):
        """The parameter names of the elements in the ticked categories, read when the list is opened."""
        cats = self._ticked_categories()
        _, names = model.parameters([i for i in self.items if i.category in cats])
        chosen = self.FilterParam.SelectedItem
        self.FilterParam.ItemsSource = names
        if chosen in names:
            self.FilterParam.SelectedItem = chosen

    def chosen(self):
        """The items ticked at step 1 that pass the value filter."""
        cats = self._ticked_categories()
        types = set(r.key for r in self.type_rows if r._ticked)
        out = [i for i in self.items if i.category in cats and i.type_key in types]
        name = self.FilterParam.SelectedItem if self.FilterOn.IsChecked else None
        if name:
            how = self.FilterHow.SelectedItem or values.CONTAINS
            text = self.FilterText.Text or u""
            case = bool(self.FilterCase.IsChecked)
            fields = model.Fields(self.doc)
            out = [i for i in out if not i.linked and
                   values.matches(fields.parameter_text(i, name), how, text, case)]
        return out

    def _count(self):
        self.ChosenCount.Text = u"{} chosen".format(_plural(len(self.chosen()), u"element"))

    # ---- step 2: parameter and change -----------------------------------------------------------------------------

    def _enter_change(self):
        chosen = [i for i in self.chosen() if not i.linked]
        ids = tuple(i.id for i in chosen)
        if ids != self.params_for:
            self.params_for = ids
            self.params, self.names = model.parameters(chosen)
            if self.param is not None and self.param.key not in [p.key for p in self.params]:
                self.param = None
            self.SourceList.ItemsSource = self.names
            self.FieldList.ItemsSource = list(values.FIELDS) + self.names
        self._show_params()
        if not self.params:
            self.ParamNote.Text = (u"The chosen elements of this model have no text, whole number or yes/no parameter "
                                   u"in common that can be changed. Go back to step 1 and choose different or fewer "
                                   u"categories, families or types.")
        elif len(chosen) == 1:
            self.ParamNote.Text = (u"These are the text, whole number and yes/no parameters that the chosen element "
                                   u"of this model has, except those that are read only.")
        else:
            self.ParamNote.Text = (u"These are the text, whole number and yes/no parameters that all {} chosen elements "
                                   u"of this model have, except those that are read only on all of them."
                                   .format(len(chosen)))
        self._show_example()

    def _show_params(self):
        text = (self.ParamSearch.Text or u"").strip().lower()
        rows = [ParamRow(p) for p in self.params if not text or text in p.name.lower()]
        self.ParamGrid.ItemsSource = ObservableCollection[object](rows)
        for r in rows:
            if self.param is not None and r.param.key == self.param.key:
                self.ParamGrid.SelectedItem = r

    def OnParamSearch(self, sender, args):
        if self.ready:
            self._show_params()

    def OnParamChosen(self, sender, args):
        row = self.ParamGrid.SelectedItem
        if row is not None:
            self.choose_param(row.param)

    def choose_param(self, param):
        """Sets the parameter to change and offers the changes that suit its kind."""
        before = self._change_kind()
        self.param = param
        kinds = values.changes_for(param.kind)
        self.ready = False
        self.ChangeList.ItemsSource = [values.CHANGE_NAMES[k] for k in kinds]
        self.ChangeList.SelectedIndex = kinds.index(before) if before in kinds else 0
        self.ready = True
        self.ChosenParam.Text = u"{} ({} parameter, {})".format(param.name, param.where, param.kind)
        self._show_change_boxes()

    def _change_kind(self):
        name = self.ChangeList.SelectedItem
        for k, n, _ in values.CHANGES:
            if n == name:
                return k
        return None

    def choose_change(self, kind):
        """Picks a change by its kind (values.SET and so on)."""
        self.ChangeList.SelectedItem = values.CHANGE_NAMES[kind]
        self._show_change_boxes()

    def OnChangeChosen(self, sender, args):
        if self.ready:
            self._show_change_boxes()

    def _show_change_boxes(self):
        kind = self._change_kind()
        shown = lambda yes: Visibility.Visible if yes else Visibility.Collapsed
        self.ValuePanel.Visibility = shown(kind in VALUE_LABELS)
        self.ValueLabel.Text = VALUE_LABELS.get(kind, u"")
        self.ValueHint.Text = (u"Type Yes or No." if kind == values.SET and self.param is not None and
                               self.param.kind == values.YESNO else u"")
        self.FindPanel.Visibility = shown(kind == values.REPLACE)
        self.SourcePanel.Visibility = shown(kind == values.COPY)
        self.FieldPanel.Visibility = shown(kind == values.PATTERN)
        self._show_rooms()
        self._show_example()

    def OnChangeTyped(self, sender, args):
        if self.ready:
            self._show_rooms()
            self._show_example()

    def OnInsertField(self, sender, args):
        name = self.FieldList.SelectedItem
        if not name:
            self._say(u"Choose a field, then press Insert field.", True)
            return
        token = u"{" + name + u"}"
        at = self.ValueBox.CaretIndex
        text = self.ValueBox.Text or u""
        self.ValueBox.Text = text[:at] + token + text[at:]
        self.ValueBox.CaretIndex = at + len(token)
        self.ValueBox.Focus()

    def make_change(self):
        """The values.Change the boxes at step 2 describe."""
        kind = self._change_kind() or values.SET
        return values.Change(kind, text=self.ValueBox.Text or u"", find=self.FindBox.Text or u"",
                             replace_with=self.ReplaceBox.Text or u"", match_case=bool(self.MatchCase.IsChecked),
                             source=self.SourceList.SelectedItem)

    @staticmethod
    def _uses_rooms(change):
        return change.kind == values.PATTERN and any(
            values.special_field(f) in values.ROOM_FIELDS for f in change.fields())

    def _sources(self):
        """The models with placed rooms, listed once. The one used last on this model is chosen first; otherwise the
        one that finds a room for most of the chosen elements (on one PD project model the link with fewer rooms found
        rooms for 317 of 376 fixtures, the one with more rooms for 199)."""
        if self.room_sources is None:
            self.room_sources = linkrooms.sources(self.doc)
            labels = [u"{} ({})".format(s.label, _plural(s.count, u"room")) for s in self.room_sources]
            self.RoomList.ItemsSource = labels
            remembered = (self.last.get(self.model_key) or {}).get("rooms")
            names = [s.label for s in self.room_sources]
            index = names.index(remembered) if remembered in names else None
            if index is None and self.room_sources:
                own = [i for i in self.chosen() if not i.linked]
                sample = own[::max(1, len(own) // ROOM_SAMPLE)]
                found = []
                for s in self.room_sources:
                    finder = self.finders.setdefault(s.label, linkrooms.RoomFinder(s))
                    found.append(sum(1 for i in sample if finder.room(i.element) is not None))
                index = max(range(len(self.room_sources)), key=lambda i: (found[i], self.room_sources[i].count))
            if index is not None:
                self.RoomList.SelectedIndex = index
        return self.room_sources

    def _source(self):
        sources = self._sources()
        i = self.RoomList.SelectedIndex
        return sources[i] if sources and 0 <= i < len(sources) else None

    def _finder(self):
        source = self._source()
        if source is None:
            return None
        if source.label not in self.finders:
            self.finders[source.label] = linkrooms.RoomFinder(source)
        return self.finders[source.label]

    def _show_rooms(self):
        uses = self._uses_rooms(self.make_change())
        self.RoomPanel.Visibility = Visibility.Visible if uses else Visibility.Collapsed
        if uses:
            sources = self._sources()
            self.RoomNote.Text = (u"" if sources else
                                  u"This model and its loaded links have no placed rooms.")

    def OnRoomChosen(self, sender, args):
        if self.ready:
            self._show_example()

    def _fields(self, change):
        return model.Fields(self.doc, self._finder() if self._uses_rooms(change) else None)

    def _getter(self, fields, change, item):
        return fields.parameter_getter(item) if change.kind == values.COPY else fields.getter(item)

    def _show_example(self):
        """One chosen element and what the change would make of its value, under the boxes at step 2: the first of
        about EXAMPLE_TRIES elements, spread through the chosen ones, that the change would alter; or the first one
        tried, where none of them would change."""
        self.Example.Text = u""
        if self.param is None:
            return
        change = self.make_change()
        if change.problem(self.param.kind, self.param.name):
            return
        fields = self._fields(change)
        first = None
        own = [i for i in self.chosen() if not i.linked]
        # spread through the list: elements next to each other in it are often alike
        for item in own[::max(1, len(own) // EXAMPLE_TRIES)]:
            host = item.type if self.param.is_type else item.element
            parameter, _ = model.find(host, self.param.name, self.param.kind)
            if parameter is None:
                continue
            old = model.read(parameter, self.param.kind)
            outcome = change.new_text(values.shown(self.param.kind, old), self._getter(fields, change, item))
            check = values.assess(self.param.kind, change, old, outcome)
            before = values.shown(self.param.kind, old)
            what = u"element {}".format(item.id) if not self.param.is_type else u"type {}".format(item.type_name)
            if check.writes:
                self.Example.Text = u"For example, on {}: {} becomes {}.".format(
                    what, _quoted(before) if before else u"no value",
                    _quoted(check.new_text) if check.new_text else u"no value")
                return
            if first is None:
                first = u"For example, on {}: {}. {}.".format(what, check.state.lower(), u"; ".join(check.notes))
        if first is not None:
            self.Example.Text = first

    # ---- step 3: check --------------------------------------------------------------------------------------------

    def build_checks(self):
        """The check rows for the chosen elements, the parameter and the change. Nothing is written."""
        change = self.make_change()
        param = self.param
        fields = self._fields(change)
        items = self.chosen()
        rows = []
        if not param.is_type:
            for item in items:
                rows.append(self._check_item(item, change, fields))
        else:
            by_type = {}
            order = []
            for item in items:
                if item.linked or item.type is None:
                    rows.append(self._check_item(item, change, fields))
                    continue
                if item.type_id not in by_type:
                    by_type[item.type_id] = []
                    order.append(item.type_id)
                by_type[item.type_id].append(item)
            counts = model.type_counts(self.doc, items)
            for type_id in order:
                rows.append(self._check_type(by_type[type_id], change, fields, counts.get(type_id, 0)))
        self.checks = rows
        # the Results step shows the last Apply; a new check replaces its rows, so Results waits for the next Apply
        self.Step4.IsEnabled = False
        return rows

    def _assess(self, change, host, **kw):
        """values.assess, then the worksharing check for a row that would change (it is slower, so only then)."""
        check = values.assess(self.param.kind, change, **kw)
        if check.writes:
            reason = model.blocked(self.doc, host)
            if reason:
                check = values.assess(self.param.kind, change, blocked=reason, **kw)
        return check

    def _cannot_empty(self, change, parameter):
        """Clear on a whole number or yes/no parameter that Revit will not empty."""
        return (change.kind == values.CLEAR and self.param.kind != values.TEXT and
                not model.can_empty(self.doc, parameter))

    def _check_item(self, item, change, fields):
        param = self.param
        if item.linked:
            return CheckRow([item], None, values.assess(param.kind, change, left_out=values.LINKED), False)
        host = item.type if param.is_type else item.element
        parameter, reason = model.find(host, param.name, param.kind)
        if parameter is None:
            return CheckRow([item], host, values.assess(param.kind, change, left_out=reason), param.is_type)
        old = model.read(parameter, param.kind)
        outcome = change.new_text(values.shown(param.kind, old), self._getter(fields, change, item))
        feeds = (param.name == values.LOAD_NAME and item.category == values.CIRCUITS and
                 model.feeds_board(item.element))
        check = self._assess(change, host, old=old, outcome=outcome, read_only=parameter.IsReadOnly,
                             in_group=item.in_group, param_name=param.name, category=item.category,
                             feeds_board=feeds, cannot_empty=self._cannot_empty(change, parameter))
        return CheckRow([item], host, check, param.is_type)

    def _check_type(self, items, change, fields, total):
        param = self.param
        first = items[0]
        host = first.type
        parameter, reason = model.find(host, param.name, param.kind)
        if parameter is None:
            return CheckRow(items, host, values.assess(param.kind, change, left_out=reason), True)
        old = model.read(parameter, param.kind)
        old_text = values.shown(param.kind, old)
        outcomes = [change.new_text(old_text, self._getter(fields, change, i)) for i in items]
        distinct = []
        for o in outcomes:
            if (o.text, o.left_out) not in distinct:
                distinct.append((o.text, o.left_out))
        if len(distinct) > 1:
            shown = [_quoted(t) if lo is None else lo for t, lo in distinct[:3]]
            why = (u"A type parameter has one value for every element of the type, but the chosen elements of this "
                   u"type would not all have the same new value: {}".format(u", ".join(shown)))
            if len(distinct) > 3:
                why += u" and {} more".format(len(distinct) - 3)
            return CheckRow(items, host, values.assess(param.kind, change, left_out=why), True)
        total = max(total, len(items))
        check = self._assess(change, host, old=old, outcome=outcomes[0], read_only=parameter.IsReadOnly,
                             type_count=(total, len(items)), param_name=param.name, category=first.category,
                             cannot_empty=self._cannot_empty(change, parameter))
        row = CheckRow(items, host, check, True)
        row.total = total
        return row

    def _show_checks(self):
        self.CheckSummary.Text = u"{}: {}.".format(self._what(), values.summary(self.checks))
        self.CheckSummary.Foreground = self._brush(NAVY)
        reach = self._outside()
        if reach == 1:
            self.TypeWarning.Text = (u"This is a type parameter. The change also applies to 1 element that you did not "
                                     u"choose, because it is of the same type as elements you chose.")
        elif reach:
            self.TypeWarning.Text = (u"This is a type parameter. The change also applies to {} elements that you did not "
                                     u"choose, because they are of the same type as elements you chose.".format(reach))
        else:
            self.TypeWarning.Text = u""
        self.TypeWarning.Visibility = Visibility.Visible if reach else Visibility.Collapsed
        self._fill_check_grid()

    def _what(self):
        change = self.make_change()
        return u"{} ({})".format(self.param.name, change.name)

    def _outside(self):
        """Elements a type parameter change reaches that were not chosen."""
        return sum(max(0, row.total - len(row.items)) for row in self.checks
                   if row.is_type and row.check.writes and row.total)

    def OnShowChosen(self, sender, args):
        if self.ready:
            self._fill_check_grid()

    def _fill_check_grid(self):
        state = self.ShowList.SelectedItem or SHOW_ALL
        rows = [r for r in self.checks if state == SHOW_ALL or r.state == state]
        self.CheckGrid.ItemsSource = ObservableCollection[object](rows)

    def OnApply(self, sender, args):
        writes = [r for r in self.checks if r.check.writes]
        if not writes:
            self._say(u"Nothing will change. The reasons are in the Notes column; press Back to change the choices.",
                      True)
            return
        reach = self._outside()
        if reach and not forms.alert(
                u"The change to this type parameter also applies to {} that you did not choose. Apply it?".format(
                    _plural(reach, u"element")), title=u"Edit Values", yes=True, no=True):
            return
        self.apply()
        self._go(STEP_RESULTS)

    def apply(self, dry_run=False):
        """Writes the rows that change, as one undo step. dry_run undoes everything at the end (used by the in-Revit
        checks). Returns model.Applied."""
        param = self.param
        targets = [model.Target(r.key, r.host, param.name, param.kind, r.check.new)
                   for r in self.checks if r.check.writes]
        self.applied = model.apply(self.doc, targets, dry_run)
        for r in self.checks:
            if r.check.writes:
                reason = self.applied.results.get(r.key)
                if reason is None:
                    r.result = WOULD_CHANGE if dry_run else CHANGED
                    r.reason = u""
                else:
                    r.result = FAILED
                    r.reason = reason
            else:
                r.result = r.state
                r.reason = r.notes
        self._show_results()
        self._remember()
        return self.applied

    # ---- results --------------------------------------------------------------------------------------------------

    def _show_results(self):
        applied = self.applied
        done = applied.written
        if applied.trial:
            # every row not written, as the button "Select elements not changed and close" selects them
            refused = len([r for r in self.checks if r.result not in (CHANGED, WOULD_CHANGE)])
            text = u"Trial run, everything undone: {} would change, {} would not.".format(done, refused)
        elif done:
            failed = len([r for r in self.checks if r.result == FAILED])
            text = (u"{} changed, {} failed. To undo all the changes in one step, press Ctrl+Z in Revit "
                    u"(PD: Edit Values in the Undo list).".format(_plural(done, u"value"), failed))
        else:
            text = u"Nothing was changed. The reasons are in the Reason column."
        self.ResultSummary.Text = text
        self.ResultGrid.ItemsSource = ObservableCollection[object](self.checks)
        self.Warnings.Text = u"\n".join(applied.warnings)
        self.WarningsPanel.Visibility = Visibility.Visible if applied.warnings else Visibility.Collapsed
        self.Step4.IsEnabled = True

    def _select(self, rows):
        ids = []
        for r in rows:
            ids.extend(r.ids())
        if not ids or self.uidoc is None:
            self._say(u"There are no elements to select.", True)
            return
        self.uidoc.Selection.SetElementIds(List[ElementId](ids))
        self.Close()

    def OnSelectChanged(self, sender, args):
        self._select([r for r in self.checks if r.result in (CHANGED, WOULD_CHANGE)])

    def OnSelectNotChanged(self, sender, args):
        self._select([r for r in self.checks if r.result not in (CHANGED, WOULD_CHANGE)])

    def _remember(self):
        source = self._source() if self.room_sources else None
        if source is not None:
            entry = self.last.get(self.model_key) or {}
            entry["rooms"] = source.label
            self.last[self.model_key] = entry
            _write_json(LAST_USED_FILE, self.last)

    def OnClose(self, sender, args):
        self.Close()
