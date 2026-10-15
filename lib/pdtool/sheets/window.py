# -*- coding: utf-8 -*-
"""The PD Sheets window: PD's own design (v1 build plan, "The window"). Needs Revit and pyRevit.

Four steps in order, with Back and Next (Jarek, 14/10/2026, after his first use: "the 'next' natural progression is
missing"): 1 sheets and views, 2 file names, 3 formats and folder, 4 check and export; then the results. The Export
button is shown only at step 4.

Modal: Revit waits until the window is closed, and the export runs straight from the Export button. The logic it uses
is in the other modules of pdtool.sheets, which are tested outside Revit (pdtool-lib-tests/test_sheets.py)."""
import copy
import datetime
import io
import json
import os

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System")
from System import Action
from System.Collections.ObjectModel import ObservableCollection
from System.Diagnostics import Process, ProcessStartInfo
from System.Windows import Visibility
from System.Windows.Threading import DispatcherPriority

from pyrevit import forms

from pdtool.sheets import exporter, extra, folders, formats, model, names, paper, profiles, prosheets, record, xmlwriter

LOCAL_FOLDER = os.path.join(os.environ.get("APPDATA") or u"", u"pyRevit", u"PD Sheets")
LAST_USED_FILE = os.path.join(LOCAL_FOLDER, u"last-used.json")
DIROOTS_BELOW = u"AppSettings\\DiRoots"

ALL_ITEMS = u"(all)"
USE_SHEET_SIZE = paper.paper_label(u"Default")
USE_SHEET = u"Use sheet"
USE_PROFILE = u"Use profile"
PAPER_CHOICES = [paper.paper_label(n) for n in paper.REVIT_PAPER]
PAPER_BY_LABEL = dict((paper.paper_label(n), n) for n in paper.REVIT_PAPER)
ORIENTATION_CHOICES = [USE_SHEET, u"Portrait", u"Landscape"]
QUALITY_CHOICES = [USE_PROFILE] + list(profiles.RASTER_QUALITIES)
COLOUR_LABELS = ((u"Color", u"Colour"), (u"GrayScale", u"Grey scale"), (u"BlackLine", u"Black lines"))
SOURCE_LABELS = ((u"sheet", u"Sheet or view"), (u"project", u"Project information"),
                 (u"", u"Sheet or view, then project information"))
SOURCE_CHOICES = [label for _, label in SOURCE_LABELS]
DWG_DEFAULT = u"(Revit's default settings)"
DGN_DEFAULT = u"(Revit's own settings)"
# (label, profile key) in the order of the panels at step 3. The label is how the window names the format.
FORMATS = tuple((label, key) for key, label in formats.FORMATS)
KEY_OF = dict(FORMATS)
# How a rule's use is named at step 2 ("Used for PDF of sheets, images of views").
USE_NAMES = {u"img": u"images"}


def _rule_uses():
    """Every rule box at step 3: (what it names, key, "rule" for sheets or "view_rule" for views). IFC and NWC are
    made from views only, so they have no rule for sheets."""
    out = []
    for label, key in FORMATS:
        what = USE_NAMES.get(key, label)
        if key not in formats.MODEL_ONLY:
            out.append((u"{} of sheets".format(what), key, "rule"))
        out.append((u"{} of views".format(what), key, "view_rule"))
    return tuple(out)


RULE_USES = _rule_uses()
IMAGE_TYPES = tuple((name, label) for name, label, _ in formats.IMAGE_TYPES)
RED = u"#B00020"
GREY = u"#4A5260"
NAVY = u"#1F4E79"
STEP_SHEETS, STEP_NAMES, STEP_FORMATS, STEP_CHECK, STEP_RESULTS = range(5)


def _read_json(path, default):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        return default


def _write_json(path, data):
    try:
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"{}".format(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)))
    except Exception:
        pass  # remembering the last profile is a convenience; the export does not depend on it


def _uiapp():
    """Revit's UIApplication, which the export needs to answer Revit's message boxes; None outside pyRevit."""
    try:
        from pyrevit import HOST_APP
        return HOST_APP.uiapp
    except Exception:
        return None


def _open_in_windows(path):
    """Open a file or folder as a double click in Windows would (works on .NET Framework and .NET 8)."""
    info = ProcessStartInfo(path)
    info.UseShellExecute = True
    Process.Start(info)


def _plural(n, one, many=None):
    return u"{} {}".format(n, one if n == 1 else (many or one + u"s"))


def _join(words):
    """"PDF", "PDF and DWG", "PDF, DWG and IFC"."""
    words = list(words)
    if len(words) < 2:
        return u"".join(words)
    return u"{} and {}".format(u", ".join(words[:-1]), words[-1])


def _labels(pairs):
    return [label for _, label in pairs]


def _label_for(pairs, value):
    """The label shown for a stored value; the first label when the value is not in the list."""
    return dict(pairs).get(value, pairs[0][1])


def _value_for(pairs, label):
    """The stored value for a label chosen; the first value when nothing is chosen."""
    return dict((l, v) for v, l in pairs).get(label, pairs[0][0])


def _progress_text(label, fmt, number, total):
    """The progress bar's line while one file is written. Braces are doubled because pyRevit fills {value} and
    {max_value} into the line."""
    text = u"Writing the {} of {} ({} of {}). Revit does not respond until the file is written.".format(
        fmt, label, number, total)
    return text.replace(u"{", u"{{").replace(u"}", u"}}")


class ItemRow(forms.Reactive):
    """One sheet or view in the list. Paper, orientation and raster quality are kept in the profile for this sheet."""

    def __init__(self, item, win):
        self.item = item
        self.win = win
        self.key = item["key"]
        self.kind = item["kind"]
        if self.kind == u"sheet":
            self.label = item["number"]
        else:
            self.label = u"{} ({})".format(item["name"], formats.view_type_name(item.get("type")))
        self.search = u"{} {}".format(item["number"], item["name"]).lower()
        self._ticked = False
        self._check = u""
        self.typed = {}
        self.built = {}
        self.reasons = None
        # [(view name, width ft, height ft)] of the views with no crop region that are too large to export
        # (model.large_views), or None until checked.
        self.large = None

    # shown, not edited
    @property
    def number(self):
        return self.item["number"]

    @property
    def name(self):
        return self.item["name"]

    @property
    def revision(self):
        return self.item["revision"]

    @property
    def size_text(self):
        if self.kind != u"sheet":
            return u""
        o = self.item.get("orientation") or u""
        return u"{} {}".format(self.item["size"], o.lower()).strip()

    @property
    def raster_text(self):
        if self.reasons is None:
            return u"not checked"
        return _plural(len(self.reasons), u"view") if self.reasons else u"none"

    @property
    def check(self):
        return self._check

    @property
    def name_colour(self):
        return RED if self._check else u"Black"

    @property
    def paper_choices(self):
        return PAPER_CHOICES

    @property
    def orientation_choices(self):
        return ORIENTATION_CHOICES

    @property
    def quality_choices(self):
        return QUALITY_CHOICES

    # edited in the list
    @forms.reactive
    def ticked(self):
        return self._ticked

    @ticked.setter
    def ticked(self, value):
        self._ticked = bool(value)
        self.win.on_ticks_changed()

    @forms.reactive
    def paper(self):
        name = profiles.sheet_setting(self.win.profile, self.key, u"paper")
        return paper.paper_label(name) if name else USE_SHEET_SIZE

    @paper.setter
    def paper(self, label):
        name = PAPER_BY_LABEL.get(label)
        profiles.set_sheet_setting(self.win.profile, self.key, u"paper", None if name in (None, u"Default") else name)

    @forms.reactive
    def orientation(self):
        return profiles.sheet_setting(self.win.profile, self.key, u"orientation") or USE_SHEET

    @orientation.setter
    def orientation(self, label):
        profiles.set_sheet_setting(self.win.profile, self.key, u"orientation", None if label == USE_SHEET else label)

    @forms.reactive
    def quality(self):
        return profiles.sheet_setting(self.win.profile, self.key, u"raster_quality") or USE_PROFILE

    @quality.setter
    def quality(self, label):
        profiles.set_sheet_setting(self.win.profile, self.key, u"raster_quality",
                                   None if label == USE_PROFILE else label)

    @forms.reactive
    def pdf_name(self):
        return self.name_for(u"PDF")

    @pdf_name.setter
    def pdf_name(self, value):
        self._type(u"PDF", value)

    @forms.reactive
    def dwg_name(self):
        return self.name_for(u"DWG")

    @dwg_name.setter
    def dwg_name(self, value):
        self._type(u"DWG", value)

    @forms.reactive
    def dgn_name(self):
        return self.shown_name(u"DGN")

    @dgn_name.setter
    def dgn_name(self, value):
        self._type(u"DGN", value)

    @forms.reactive
    def dwf_name(self):
        return self.shown_name(u"DWF")

    @dwf_name.setter
    def dwf_name(self, value):
        self._type(u"DWF", value)

    @forms.reactive
    def ifc_name(self):
        return self.shown_name(u"IFC")

    @ifc_name.setter
    def ifc_name(self, value):
        self._type(u"IFC", value)

    @forms.reactive
    def nwc_name(self):
        return self.shown_name(u"NWC")

    @nwc_name.setter
    def nwc_name(self, value):
        self._type(u"NWC", value)

    @forms.reactive
    def img_name(self):
        return self.shown_name(u"Image")

    @img_name.setter
    def img_name(self, value):
        self._type(u"Image", value)

    @forms.reactive
    def xml_name(self):
        return self.shown_name(u"XML")

    @xml_name.setter
    def xml_name(self, value):
        self._type(u"XML", value)

    # used by the window
    def not_made(self, fmt):
        """Why this sheet or view cannot be exported in this format ("Views only" for a sheet as IFC), or None."""
        return formats.made_from(KEY_OF[fmt], self.item)

    def shown_name(self, fmt):
        reason = self.not_made(fmt)
        return u"({})".format(reason.lower()) if reason else self.name_for(fmt)

    def name_for(self, fmt):
        return self.typed.get(fmt) or self.built.get(fmt, (u"", []))[0]

    def missing(self, fmt):
        if fmt in self.typed:
            return []
        return self.built.get(fmt, (u"", []))[1]

    def _type(self, fmt, value):
        """A name typed over for this sheet (kept until the window closes). Clearing the cell goes back to the rule."""
        if self.not_made(fmt):
            # nothing is exported in this format, so the cell goes back to saying why
            prop = u"{}_name".format(KEY_OF[fmt])
            self.win._later(lambda: self.OnPropertyChanged(prop))
            return
        value = names.clean(value or u"")
        if not value or value == self.built.get(fmt, (u"", []))[0]:
            self.typed.pop(fmt, None)
        else:
            self.typed[fmt] = value
        self.win.refresh_checks()

    def rebuild(self):
        prof = self.win.profile
        element = self.item["element"]
        value_of = self.win.value_of
        for fmt, key in FORMATS:
            if self.not_made(fmt):
                self.built[fmt] = (u"", [])
                continue
            rule_name = prof[key]["rule" if self.kind == u"sheet" else "view_rule"]
            r = profiles.rule(prof, rule_name)
            if r is None:
                self.built[fmt] = (u"", [u"the rule {} (not in this profile)".format(rule_name)])
            else:
                self.built[fmt] = names.build(r["parts"], lambda part: value_of(element, part))
        for _, key in FORMATS:
            self.OnPropertyChanged(u"{}_name".format(key))

    def set_ticked_quietly(self, value):
        self._ticked = bool(value)
        self.OnPropertyChanged("ticked")

    def set_check(self, message):
        if message != self._check:
            self._check = message
            self.OnPropertyChanged("check")
            self.OnPropertyChanged("name_colour")

    def set_reasons(self, reasons):
        self.reasons = reasons
        self.OnPropertyChanged("raster_text")

    def refresh_settings(self):
        for prop in ("paper", "orientation", "quality"):
            self.OnPropertyChanged(prop)


class PartRow(forms.Reactive):
    """One part of a naming rule. Every change goes through the window, which first makes a copy when the rule is the
    built-in PD ISO 19650 rule (SheetsWindow.edit_part)."""

    def __init__(self, part, win, index):
        self.part = part
        self.win = win
        self.index = index

    @property
    def param(self):
        return self.part["param"]

    @property
    def source_choices(self):
        return SOURCE_CHOICES

    @forms.reactive
    def source(self):
        found = dict(SOURCE_LABELS)
        return found.get(self.part.get("source") or u"", SOURCE_CHOICES[-1])

    @source.setter
    def source(self, label):
        value = dict((v, k) for k, v in SOURCE_LABELS).get(label, u"")
        if value != (self.part.get("source") or u""):
            self.win.edit_part(self.index, "source", value)

    @forms.reactive
    def prefix(self):
        return self.part.get("prefix") or u""

    @prefix.setter
    def prefix(self, value):
        self._edit("prefix", value)

    @forms.reactive
    def suffix(self):
        return self.part.get("suffix") or u""

    @suffix.setter
    def suffix(self, value):
        self._edit("suffix", value)

    @forms.reactive
    def sep(self):
        return self.part.get("sep") or u""

    @sep.setter
    def sep(self, value):
        self._edit("sep", value)

    def _edit(self, key, value):
        value = value or u""
        if value != (self.part.get(key) or u""):
            self.win.edit_part(self.index, key, value)


class ParamRow(object):
    """One parameter in the list on the left of step 2, with its value on the sheet the preview uses."""

    def __init__(self, name, source, value):
        self.param = name
        self.source = source
        self._value = value

    @property
    def name(self):
        return self.param

    @property
    def where(self):
        return {u"sheet": u"Sheet or view", u"project": u"Project information"}.get(self.source, self.source)

    @property
    def value(self):
        return u"(empty)" if self._value in (None, u"") else self._value


class XmlRow(forms.Reactive):
    """One value in the XML files: a parameter, or a fixed text written the same in every file (xmlwriter). Changes
    are made in the profile's field itself."""

    def __init__(self, field, win):
        self.field = field
        self.win = win

    @property
    def is_fixed(self):
        return not self.field.get("param")

    @property
    def param(self):
        return self.field.get("param") or u""

    @property
    def where(self):
        if self.is_fixed:
            return u"Fixed text"
        return dict(SOURCE_LABELS).get(self.field.get("source") or u"", SOURCE_CHOICES[-1])

    @forms.reactive
    def element(self):
        return self.field.get("element") or u""

    @element.setter
    def element(self, value):
        self.field["element"] = (value or u"").strip()
        self.win.on_xml_edited()

    @forms.reactive
    def value(self):
        return (self.field.get("value") or u"") if self.is_fixed else u""

    @value.setter
    def value(self, text):
        if self.is_fixed:
            self.field["value"] = text or u""
            self.win.on_xml_edited()


class ResultRow(object):
    def __init__(self, row, folder):
        self.row = row
        self.path = os.path.join(folder, row.get("file") or u"") if folder and row.get("file") else None

    @property
    def file(self):
        return self.row.get("file") or u""

    @property
    def result(self):
        return self.row.get("result") or u""

    @property
    def size(self):
        s = self.row.get("size_mb")
        return u"{:.2f}".format(s) if isinstance(s, float) else u""

    @property
    def over(self):
        return u"yes" if self.row.get("over_limit") else u""

    @property
    def rasterised(self):
        r = self.row.get("rasterised")
        return u"" if r is None else u"{}".format(r)

    @property
    def time(self):
        return self.row.get("time") or u""

    @property
    def note(self):
        return self.row.get("note") or u""


class SheetsWindow(forms.WPFWindow):

    def __init__(self, xaml_path, doc):
        self.ready = False
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.home = os.environ.get("USERPROFILE") or os.path.expanduser(u"~")
        self.mounts = folders.read_mounts()
        self.profiles_dir, self.shared = folders.profiles_folder(self.mounts, self.home,
                                                                 os.path.join(LOCAL_FOLDER, u"profiles"))
        # names of the parameters in the rules that Revit gives no value for (model.is_button), found as names are built
        self.no_text = set()
        self.value_of = model.value_getter(doc, self.no_text)
        self.checker = model.RasterChecker(doc)
        self.large_cache = {}
        self.sheet_rows = [ItemRow(i, self) for i in model.sheets(doc)]
        self.view_rows = None
        self.sets = model.sheet_sets(doc)
        self.setups = model.dwg_setups(doc)
        try:
            self.dgn_setups = model.dgn_setups(doc)
        except Exception:
            self.dgn_setups = []
        # What this Revit can make: NWC needs Autodesk Navisworks Exporters, which is installed separately.
        self.available = dict((key, exporter.available(key)) for key in formats.KEYS)
        self.xml_kind = u"sheet"
        self.xml_rows = []
        self.left_out = 0
        sample_sheet = self.sheet_rows[0].item["element"] if self.sheet_rows else None
        self.params = model.parameter_names(doc, sample_sheet, model.first_view(doc))
        self.last = _read_json(LAST_USED_FILE, {})
        self.model_key = doc.Title
        self.profile = None
        self.profile_path = None
        self.saved_text = None
        self.folder_stored = {}
        self.folder_path = None
        self.folder_problem = None
        self.part_rows = []
        self.record_path = None
        self.export_folder = None
        self.step = STEP_SHEETS
        self.search_text = {u"sheet": u"", u"view": u""}
        self.rule_message = None  # (rule name, note) after the built-in rule is copied for an edit
        self.copied_to = None
        self._fill_fixed_lists()
        self.ready = True
        self._load_profile_list((self.last.get(self.model_key) or {}).get("profile"))
        self.ShowSheets.IsChecked = True
        self._go(STEP_SHEETS)

    # ---- set-up ---------------------------------------------------------------------------------------------------

    def _fill_fixed_lists(self):
        self.PdfQuality.ItemsSource = list(profiles.RASTER_QUALITIES)
        self.PdfColour.ItemsSource = [label for _, label in COLOUR_LABELS]
        self.DwgSetup.ItemsSource = [DWG_DEFAULT] + list(self.setups)
        self.DgnSetup.ItemsSource = [DGN_DEFAULT] + list(self.dgn_setups)
        for box, pairs in ((self.DwgText, formats.DWG_TEXT_TREATMENTS), (self.DgnVersion, formats.DGN_VERSIONS),
                           (self.DwfType, formats.DWF_FILE_TYPES),
                           (self.DwfImageFormat, formats.DWF_IMAGE_FORMATS),
                           (self.DwfImageQuality, formats.DWF_IMAGE_QUALITIES), (self.IfcVersion, formats.IFC_VERSIONS),
                           (self.IfcSpaces, formats.SPACE_BOUNDARIES), (self.NwcCoordinates, formats.NWC_COORDINATES),
                           (self.NwcParameters, formats.NWC_PARAMETERS), (self.ImgType, IMAGE_TYPES),
                           (self.ImgDirection, formats.IMAGE_DIRECTIONS),
                           (self.ImgResolution, formats.IMAGE_RESOLUTIONS)):
            box.ItemsSource = _labels(pairs)
        for _, key in FORMATS:
            if key in (u"pdf", u"dwg") or self.available[key]:
                continue
            self._tick_box(key).IsEnabled = False
            note = getattr(self, self._prefix(key) + u"Missing")
            note.Text = exporter.NOT_AVAILABLE.get(key, u"This format is not available in this Revit.")
            note.Visibility = Visibility.Visible
        self.XmlParam.ItemsSource = [self._param_label(n, s) for n, s in self.params]
        set_names = sorted(self.sets.keys(), key=lambda s: s.lower())
        self.SetFilter.ItemsSource = [ALL_ITEMS] + set_names
        self.SetFilter.SelectedIndex = 0
        self._fill_params()
        if self.shared:
            self.ProfileWhere.Text = (u"Profiles are kept in the shared folder PD - 00_Templates\\AppSettings\\PD Sheets, "
                                      u"so everyone who syncs that library sees the same profiles.")
        else:
            self.ProfileWhere.Text = (u"The PD - 00_Templates library is not synced on this PC, so profiles are kept on "
                                      u"this PC only, in {}.".format(self.profiles_dir))

    def _later(self, fn):
        """Run fn once WPF has finished the edit in hand (a list cannot be replaced while one of its cells commits)."""
        self.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(fn))

    @staticmethod
    def _prefix(key):
        """The start of the names of a format's boxes at step 3: "Pdf", "Dgn", "Img"."""
        return key[:1].upper() + key[1:]

    def _tick_box(self, key):
        return getattr(self, u"Do" + self._prefix(key))

    def _expander(self, key):
        return getattr(self, self._prefix(key) + u"Expander")

    @staticmethod
    def _param_label(name, source):
        return u"{} ({})".format(name, dict(SOURCE_LABELS).get(source, source))

    # ---- the steps ------------------------------------------------------------------------------------------------

    def _go(self, step):
        """Show one step. Entering step 4 checks the ticked sheets for rasterised views first."""
        if step == STEP_CHECK and not self._enter_check():
            return
        if step == STEP_NAMES:
            self._fill_params()
            self._preview()
        self.step = step
        self.Tabs.SelectedIndex = step
        for i, button in enumerate((self.Step1, self.Step2, self.Step3, self.Step4, self.Step5)):
            current = i == step
            button.Background = self._brush(NAVY if current else u"White")
            button.Foreground = self._brush(u"White" if current else NAVY)
        self.BackButton.IsEnabled = step > STEP_SHEETS
        self.NextButton.Visibility = Visibility.Visible if step < STEP_CHECK else Visibility.Collapsed
        self.ExportButton.Visibility = Visibility.Visible if step == STEP_CHECK else Visibility.Collapsed
        self.refresh_checks()

    def OnStep(self, sender, args):
        self._go(int(sender.Tag))

    def OnBack(self, sender, args):
        self._go(max(STEP_SHEETS, self.step - 1))

    def OnNext(self, sender, args):
        problem = self._step_problem(self.step)
        if problem:
            self._say(problem, True)
            return
        self._go(self.step + 1)

    def _step_problem(self, step):
        """What must be done before leaving a step with Next, or None."""
        if step == STEP_SHEETS and not self._ticked():
            return u"Tick at least one sheet or view first."
        if step == STEP_FORMATS:
            problem = self._controls_to_profile()
            if problem:
                return problem
            if not self._formats():
                return u"Tick at least one format first."
            if self.folder_problem:
                return self.folder_problem
        return None

    def _say(self, text, problem=False):
        self.Status.Text = text
        self.Status.Foreground = self._brush(RED if problem else GREY)

    def _rows(self):
        return self.sheet_rows + (self.view_rows or [])

    def _views(self):
        if self.view_rows is None:
            self.view_rows = [ItemRow(i, self) for i in model.views(self.doc)]
            for r in self.view_rows:
                r.rebuild()
        return self.view_rows

    # ---- profiles -------------------------------------------------------------------------------------------------

    def _load_profile_list(self, select=None):
        listed = profiles.list_profiles(self.profiles_dir)
        self.profile_files = dict((n, p) for n, p in listed if n)
        damaged = [os.path.basename(p) for n, p in listed if not n]
        names_ = sorted(self.profile_files.keys(), key=lambda s: s.lower())
        if not names_:
            starter = profiles.new(u"PD standard")
            path = profiles.save(starter, self.profiles_dir)
            self.profile_files[starter["name"]] = path
            names_ = [starter["name"]]
        if select not in names_:
            select = names_[0]
        self.ready = False
        self.ProfileList.ItemsSource = names_
        self.ProfileList.SelectedItem = select
        self.ready = True
        if damaged:
            self.ProfileWhere.Text += u" {} could not be read: {}.".format(
                _plural(len(damaged), u"profile file"), u", ".join(damaged))
        self._open_profile(select)

    def _open_profile(self, name):
        path = self.profile_files.get(name)
        try:
            self.profile = profiles.load(path)
        except Exception as ex:
            forms.alert(u"The profile {} could not be read, so a new profile is shown instead.".format(name),
                        sub_msg=u"{}".format(ex))
            self.profile = profiles.new(name)
        self.profile_path = path
        self.rule_message = None
        for r in self._rows():
            r.typed = {}
        self._profile_to_controls()
        # Read the boxes back before the snapshot, so a number stored as 5 and read back as 5.0 is not a change.
        self._controls_to_profile()
        self.saved_text = self._snapshot()
        remembered = (self.last.get(self.model_key) or {}).get("folder")
        # A remembered folder was chosen by this user on this PC (Browse, Use this folder or an export), so a folder
        # on another computer in it is not asked about again; one from the profile is (_set_folder).
        self._set_folder(remembered if remembered else self.profile.get("folder") or {}, confirmed=bool(remembered))
        self._rebuild_names()
        for r in self._rows():
            r.refresh_settings()

    def _snapshot(self):
        return json.dumps(self.profile, sort_keys=True)

    def _changed(self):
        problem = self._controls_to_profile()
        return problem is None and self._snapshot() != self.saved_text

    def _ask_to_save(self):
        """True to go on (saved, or the changes are not wanted), False to stay."""
        if not self._changed():
            return True
        choice = forms.alert(u"The profile {} has changes that are not saved. Save them?".format(self.profile["name"]),
                             options=[u"Save", u"Do not save", u"Cancel"])
        if choice == u"Save":
            return self._save()
        return choice == u"Do not save"

    def _save(self):
        problem = self._controls_to_profile()
        if problem:
            forms.alert(problem)
            return False
        path = profiles.save(self.profile, self.profiles_dir)
        if self.profile_path and os.path.normcase(self.profile_path) != os.path.normcase(path):
            profiles.delete(self.profile_path)
        self.profile_path = path
        self.saved_text = self._snapshot()
        return True

    def _ask_name(self, default, prompt, taken):
        name = forms.ask_for_string(default=default, prompt=prompt, title=u"PD Sheets")
        if not name:
            return None
        name = name.strip()
        low = profiles.file_name_for(name).lower()
        if any(profiles.file_name_for(n).lower() == low for n in taken):
            forms.alert(u"There is already a profile called {}. Choose another name.".format(name))
            return None
        return name

    def OnProfileChosen(self, sender, args):
        if not self.ready or self.profile is None:
            return
        chosen = self.ProfileList.SelectedItem
        if not chosen or chosen == self.profile["name"]:
            return
        if not self._ask_to_save():
            self.ready = False
            self.ProfileList.SelectedItem = self.profile["name"]
            self.ready = True
            return
        self._open_profile(chosen)

    def OnNew(self, sender, args):
        if not self._ask_to_save():
            return
        name = self._ask_name(u"New profile", u"Name of the new profile", self.profile_files.keys())
        if not name:
            return
        profiles.save(profiles.new(name), self.profiles_dir)
        self._load_profile_list(name)

    def OnSave(self, sender, args):
        if self._save():
            self.Status.Text = u"The profile {} is saved.".format(self.profile["name"])

    def OnSaveAs(self, sender, args):
        problem = self._controls_to_profile()
        if problem:
            forms.alert(problem)
            return
        name = self._ask_name(self.profile["name"] + u" copy", u"Name of the copy", self.profile_files.keys())
        if not name:
            return
        copied = copy.deepcopy(self.profile)
        copied["name"] = name
        profiles.save(copied, self.profiles_dir)
        self.saved_text = self._snapshot()  # the changes are now in the copy, not in this profile
        self._load_profile_list(name)

    def OnRename(self, sender, args):
        others = [n for n in self.profile_files.keys() if n != self.profile["name"]]
        name = self._ask_name(self.profile["name"], u"New name of the profile", others)
        if not name or name == self.profile["name"]:
            return
        self.profile["name"] = name
        if self._save():
            self._load_profile_list(name)

    def OnDelete(self, sender, args):
        if not forms.alert(u"Delete the profile {}? Everyone who uses the shared folder loses it too.".format(
                self.profile["name"]), yes=True, no=True, ok=False):
            return
        if self.profile_path:
            profiles.delete(self.profile_path)
        self.profile = None
        self._load_profile_list()

    def OnImport(self, sender, args):
        start, problem = folders.to_local({"library": folders.PD_TEMPLATES_LIBRARY, "below": DIROOTS_BELOW},
                                          self.mounts, self.home)
        paths = forms.pick_file(file_ext=u"xml", init_dir=start if not problem else u"", multi_file=True,
                                title=u"Choose the ProSheets profiles to import")
        if not paths:
            return
        paths = list(paths)  # pick_file with multi_file gives a .NET string array
        taken = set(profiles.file_name_for(n).lower() for n in self.profile_files.keys())
        made, notes = [], []
        for path in paths:
            label = os.path.splitext(os.path.basename(path))[0]
            try:
                found = prosheets.read_file(path, self.mounts, self.home, label)
            except Exception as ex:
                notes.append(u"{} could not be read ({}).".format(os.path.basename(path), ex))
                continue
            for prof, prof_notes in found:
                base, n = prof["name"], 2
                while profiles.file_name_for(prof["name"]).lower() in taken:
                    prof["name"] = u"{} ({})".format(base, n)
                    n += 1
                profiles.save(prof, self.profiles_dir)
                taken.add(profiles.file_name_for(prof["name"]).lower())
                made.append(prof["name"])
                notes.extend(u"{}: {}".format(prof["name"], t) for t in prof_notes)
        if made and not self._ask_to_save():
            return
        if made:
            self._load_profile_list(made[0])
        text = u"{} made from ProSheets: {}.".format(_plural(len(made), u"profile"), u", ".join(made) or u"none")
        if made:
            text += (u" Each one is now a PD Sheets profile with the same file names, output folder and PDF settings. "
                     u"Choose it from the Profile list.")
        forms.alert(text, expanded=u"\n".join(notes) if notes else None)

    # ---- profile to the window and back ---------------------------------------------------------------------------

    def _profile_to_controls(self):
        self.ready = False
        pdf, dwg = self.profile["pdf"], self.profile["dwg"]
        self.PdfVector.IsChecked = bool(pdf.get("vector", True))
        self.PdfRaster.IsChecked = not pdf.get("vector", True)
        self.PdfQuality.SelectedItem = pdf.get("raster_quality")
        self.PdfColour.SelectedItem = dict(COLOUR_LABELS).get(pdf.get("colour"), u"Colour")
        self.PdfCentre.IsChecked = bool(pdf.get("centre", True))
        self.PdfOffset.IsChecked = not pdf.get("centre", True)
        self.PdfOffsetX.Text = u"{:g}".format(float(pdf.get("offset_x_mm") or 0))
        self.PdfOffsetY.Text = u"{:g}".format(float(pdf.get("offset_y_mm") or 0))
        fit = pdf.get("zoom") == u"fit"
        self.PdfFit.IsChecked = fit
        self.PdfZoom.IsChecked = not fit
        self.PdfZoomValue.Text = u"100" if fit else u"{}".format(pdf.get("zoom") or 100)
        self.PdfLinksBlue.IsChecked = bool(pdf.get("view_links_blue"))
        self.PdfHideRef.IsChecked = bool(pdf.get("hide_ref_planes"))
        self.PdfHideScope.IsChecked = bool(pdf.get("hide_scope_boxes"))
        self.PdfHideTags.IsChecked = bool(pdf.get("hide_unref_tags"))
        self.PdfHideCrop.IsChecked = bool(pdf.get("hide_crop"))
        self.PdfHalftone.IsChecked = bool(pdf.get("replace_halftone"))
        self.PdfMask.IsChecked = bool(pdf.get("mask_coincident"))
        self.SizeLimit.Text = u"{:g}".format(float(self.profile.get("size_limit_mb") or 0))
        for _, key in FORMATS:
            # a format this Revit cannot make stays off, but the profile keeps its own setting for another PC
            on = bool(self.profile[key].get("enabled")) and self.available.get(key, True)
            self._tick_box(key).IsChecked = on
            self._expander(key).IsExpanded = on
        setup = dwg.get("setup") or u""
        listed = [DWG_DEFAULT] + list(self.setups)
        if setup and setup not in listed:
            listed.append(setup)
        self.DwgSetup.ItemsSource = listed
        self.DwgSetup.SelectedItem = setup or DWG_DEFAULT
        self.DwgSeparate.IsChecked = bool(dwg.get("separate"))
        self.DwgText.SelectedItem = _label_for(formats.DWG_TEXT_TREATMENTS, dwg.get("text"))
        self._other_formats_to_controls()
        self._fill_rules()
        self._name_columns()
        self.ready = True

    def _controls_to_profile(self):
        """Read the settings boxes into the profile. Returns a message when a number cannot be read, else None."""
        if self.profile is None:
            return None
        pdf, dwg = self.profile["pdf"], self.profile["dwg"]
        try:
            limit = float((self.SizeLimit.Text or u"0").strip())
            off_x = float((self.PdfOffsetX.Text or u"0").strip())
            off_y = float((self.PdfOffsetY.Text or u"0").strip())
            zoom = int((self.PdfZoomValue.Text or u"100").strip())
        except ValueError:
            return (u"A number in the PDF settings cannot be read. Type the file size limit, the offsets and the zoom "
                    u"as numbers only.")
        if not 10 <= zoom <= 1000 or limit < 0:
            return u"The zoom must be between 10 and 1000 %, and the file size limit 0 or more."
        pdf["vector"] = bool(self.PdfVector.IsChecked)
        pdf["raster_quality"] = self.PdfQuality.SelectedItem or profiles.DEFAULT_PDF["raster_quality"]
        pdf["colour"] = dict((v, k) for k, v in COLOUR_LABELS).get(self.PdfColour.SelectedItem, u"Color")
        pdf["centre"] = bool(self.PdfCentre.IsChecked)
        pdf["offset_x_mm"] = off_x
        pdf["offset_y_mm"] = off_y
        pdf["zoom"] = u"fit" if self.PdfFit.IsChecked else zoom
        pdf["view_links_blue"] = bool(self.PdfLinksBlue.IsChecked)
        pdf["hide_ref_planes"] = bool(self.PdfHideRef.IsChecked)
        pdf["hide_scope_boxes"] = bool(self.PdfHideScope.IsChecked)
        pdf["hide_unref_tags"] = bool(self.PdfHideTags.IsChecked)
        pdf["hide_crop"] = bool(self.PdfHideCrop.IsChecked)
        pdf["replace_halftone"] = bool(self.PdfHalftone.IsChecked)
        pdf["mask_coincident"] = bool(self.PdfMask.IsChecked)
        problem = self._other_formats_to_profile()
        if problem:
            return problem
        for _, key in FORMATS:
            if self.available.get(key, True):
                self.profile[key]["enabled"] = bool(self._tick_box(key).IsChecked)
        setup = self.DwgSetup.SelectedItem
        dwg["setup"] = u"" if setup in (None, DWG_DEFAULT) else setup
        dwg["separate"] = bool(self.DwgSeparate.IsChecked)
        dwg["text"] = _value_for(formats.DWG_TEXT_TREATMENTS, self.DwgText.SelectedItem)
        self.profile["size_limit_mb"] = limit
        return None

    def _other_formats_to_controls(self):
        """The DGN, DWF, IFC, NWC, image and XML settings into their boxes."""
        p = self.profile
        dgn, dwf, ifc, nwc, img = p["dgn"], p["dwf"], p["ifc"], p["nwc"], p["img"]
        setup = dgn.get("setup") or u""
        listed = [DGN_DEFAULT] + list(self.dgn_setups)
        if setup and setup not in listed:
            listed.append(setup)
        self.DgnSetup.ItemsSource = listed
        self.DgnSetup.SelectedItem = setup or DGN_DEFAULT
        self.DgnVersion.SelectedItem = _label_for(formats.DGN_VERSIONS, dgn.get("version"))
        self.DgnVersion.IsEnabled = not setup
        self.DgnSeparate.IsChecked = bool(dgn.get("separate"))
        self.DwfType.SelectedItem = _label_for(formats.DWF_FILE_TYPES, dwf.get("file_type"))
        self.DwfImageFormat.SelectedItem = _label_for(formats.DWF_IMAGE_FORMATS, dwf.get("image_format"))
        self.DwfImageQuality.SelectedItem = _label_for(formats.DWF_IMAGE_QUALITIES, dwf.get("image_quality"))
        self.DwfObjectData.IsChecked = bool(dwf.get("object_data"))
        self.DwfAreas.IsChecked = bool(dwf.get("areas"))
        self.DwfCropBox.IsChecked = bool(dwf.get("crop_box"))
        self.DwfTextures.IsChecked = bool(dwf.get("textures"))
        self.IfcVersion.SelectedItem = _label_for(formats.IFC_VERSIONS, ifc.get("version"))
        try:
            spaces = int(ifc.get("space_boundaries") or 0)
        except (TypeError, ValueError):
            spaces = 0
        self.IfcSpaces.SelectedItem = _label_for(formats.SPACE_BOUNDARIES, spaces)
        self.IfcVisibleOnly.IsChecked = bool(ifc.get("visible_only", True))
        self.IfcSplit.IsChecked = bool(ifc.get("split_by_level"))
        self.IfcQuantities.IsChecked = bool(ifc.get("base_quantities"))
        self.NwcCoordinates.SelectedItem = _label_for(formats.NWC_COORDINATES, nwc.get("coordinates"))
        self.NwcParameters.SelectedItem = _label_for(formats.NWC_PARAMETERS, nwc.get("parameters"))
        try:
            self.NwcFaceting.Text = u"{:g}".format(float(nwc.get("faceting") or 1.0))
        except (TypeError, ValueError):
            self.NwcFaceting.Text = u"1"
        for box, name in self._nwc_ticks():
            box.IsChecked = bool(nwc.get(name))
        self.ImgType.SelectedItem = _label_for(IMAGE_TYPES, img.get("file_type"))
        pixels, zoom = formats.image_numbers(img)
        self.ImgFit.IsChecked = bool(img.get("fit", True))
        self.ImgZoom.IsChecked = not img.get("fit", True)
        self.ImgPixels.Text = u"{}".format(pixels)
        self.ImgDirection.SelectedItem = _label_for(formats.IMAGE_DIRECTIONS, img.get("direction"))
        self.ImgZoomValue.Text = u"{}".format(zoom)
        self.ImgResolution.SelectedItem = _label_for(formats.IMAGE_RESOLUTIONS, img.get("resolution"))
        self.XmlSheets.IsChecked = self.xml_kind == u"sheet"
        self.XmlViews.IsChecked = self.xml_kind == u"view"
        self._show_xml()

    def _nwc_ticks(self):
        return ((self.NwcElementIds, "element_ids"), (self.NwcElementProperties, "element_properties"),
                (self.NwcUrls, "urls"), (self.NwcDivideLevels, "divide_levels"),
                (self.NwcRoomGeometry, "room_geometry"), (self.NwcRoomAttribute, "room_attribute"),
                (self.NwcParts, "parts"), (self.NwcLinks, "links"), (self.NwcLinkedCad, "linked_cad"),
                (self.NwcLights, "lights"), (self.NwcMissingMaterials, "missing_materials"))

    def _other_formats_to_profile(self):
        """Read the DGN, DWF, IFC, NWC and image boxes into the profile (the XML values are changed in the profile as
        they are edited). Returns a message when a number cannot be used, else None."""
        p = self.profile
        dgn, dwf, ifc, nwc, img = p["dgn"], p["dwf"], p["ifc"], p["nwc"], p["img"]
        try:
            faceting = float((self.NwcFaceting.Text or u"1").strip())
        except ValueError:
            return u"The NWC faceting factor cannot be read. Type it as a number only, such as 1."
        if faceting <= 0:
            return u"The NWC faceting factor must be more than 0. Revit's default is 1."
        try:
            pixels = int((self.ImgPixels.Text or u"").strip())
            zoom = int((self.ImgZoomValue.Text or u"").strip())
        except ValueError:
            return u"A number in the image settings cannot be read. Type the pixels and the zoom as whole numbers only."
        if not formats.IMAGE_PIXELS_MIN <= pixels <= formats.IMAGE_PIXELS_MAX:
            return u"The image size must be between {} and {} pixels.".format(formats.IMAGE_PIXELS_MIN,
                                                                             formats.IMAGE_PIXELS_MAX)
        if not formats.IMAGE_ZOOM_MIN <= zoom <= formats.IMAGE_ZOOM_MAX:
            return u"The image zoom must be between {} and {} %.".format(formats.IMAGE_ZOOM_MIN, formats.IMAGE_ZOOM_MAX)
        setup = self.DgnSetup.SelectedItem
        dgn["setup"] = u"" if setup in (None, DGN_DEFAULT) else setup
        dgn["version"] = _value_for(formats.DGN_VERSIONS, self.DgnVersion.SelectedItem)
        dgn["separate"] = bool(self.DgnSeparate.IsChecked)
        dwf["file_type"] = _value_for(formats.DWF_FILE_TYPES, self.DwfType.SelectedItem)
        dwf["image_format"] = _value_for(formats.DWF_IMAGE_FORMATS, self.DwfImageFormat.SelectedItem)
        dwf["image_quality"] = _value_for(formats.DWF_IMAGE_QUALITIES, self.DwfImageQuality.SelectedItem)
        dwf["object_data"] = bool(self.DwfObjectData.IsChecked)
        dwf["areas"] = bool(self.DwfAreas.IsChecked)
        dwf["crop_box"] = bool(self.DwfCropBox.IsChecked)
        dwf["textures"] = bool(self.DwfTextures.IsChecked)
        ifc["version"] = _value_for(formats.IFC_VERSIONS, self.IfcVersion.SelectedItem)
        ifc["space_boundaries"] = _value_for(formats.SPACE_BOUNDARIES, self.IfcSpaces.SelectedItem)
        ifc["visible_only"] = bool(self.IfcVisibleOnly.IsChecked)
        ifc["split_by_level"] = bool(self.IfcSplit.IsChecked)
        ifc["base_quantities"] = bool(self.IfcQuantities.IsChecked)
        nwc["coordinates"] = _value_for(formats.NWC_COORDINATES, self.NwcCoordinates.SelectedItem)
        nwc["parameters"] = _value_for(formats.NWC_PARAMETERS, self.NwcParameters.SelectedItem)
        nwc["faceting"] = faceting
        for box, name in self._nwc_ticks():
            nwc[name] = bool(box.IsChecked)
        img["file_type"] = _value_for(IMAGE_TYPES, self.ImgType.SelectedItem)
        img["fit"] = bool(self.ImgFit.IsChecked)
        img["pixels"] = pixels
        img["direction"] = _value_for(formats.IMAGE_DIRECTIONS, self.ImgDirection.SelectedItem)
        img["zoom"] = zoom
        img["resolution"] = _value_for(formats.IMAGE_RESOLUTIONS, self.ImgResolution.SelectedItem)
        return None

    # ---- output folder and formats --------------------------------------------------------------------------------

    def _set_folder(self, stored, confirmed=False):
        """Show the output folder. A folder on another computer (folders.is_network) is not looked at until the user
        has chosen it or pressed Use this folder: Windows contacts that computer as soon as the folder is looked at,
        and a profile may come from the shared folder or a ProSheets import (security review of commit 352edb9,
        15/10/2026)."""
        self.folder_stored = stored or {}
        if not self.folder_stored:
            path, problem = None, u"Choose an output folder."
        else:
            path, problem = folders.to_local(self.folder_stored, self.mounts, self.home)
        ask = not problem and not confirmed and folders.is_network(path)
        if ask:
            problem = (u"The output folder {} is on another computer on the network. Press Use this folder to export "
                       u"there, or Browse to choose another folder.").format(path)
        elif not problem and not os.path.isdir(path):
            problem = u"The folder {} is not on this PC. Choose another folder, or create it first.".format(path)
        self.UseFolderButton.Visibility = Visibility.Visible if ask else Visibility.Collapsed
        self.folder_path = None if problem else path
        self.folder_problem = problem
        self.FolderBox.Text = path or u""
        self.FolderNote.Text = problem or self._folder_note()
        self.FolderNote.Foreground = self._brush(RED if problem else u"#4A5260")
        self.refresh_checks()

    def _folder_note(self):
        """How the folder is kept in the profile, which says whether it will open for a colleague."""
        stored = self.folder_stored
        if "library" in stored:
            return (u"Kept in the profile as {}, so it opens on any PC that syncs that SharePoint library."
                    .format(folders.describe(stored)))
        if "home" in stored:
            return (u"Kept in the profile as {} inside the user folder of whoever exports, so it opens for a colleague "
                    u"only if they have the same folder.".format(stored["home"]))
        return u"Kept in the profile exactly as shown, so it opens only on a PC that has this path."

    def _brush(self, colour):
        from System.Windows.Media import BrushConverter
        return BrushConverter().ConvertFromString(colour)

    def OnBrowse(self, sender, args):
        chosen = forms.pick_folder(title=u"Choose the output folder")
        if not chosen:
            return
        stored = folders.to_stored(chosen, self.mounts, self.home)
        self.profile["folder"] = stored
        self._remember(folder=stored)
        self._set_folder(stored, confirmed=True)

    def OnUseFolder(self, sender, args):
        """The user confirms the profile's folder on another computer (_set_folder), which is then remembered as a
        folder chosen with Browse is."""
        self._remember(folder=self.folder_stored)
        self._set_folder(self.folder_stored, confirmed=True)

    def _formats(self):
        """The labels of the formats ticked, in the order of the panels. A format this Revit cannot make is never
        among them."""
        return [label for label, key in FORMATS
                if self.available.get(key, True) and self._tick_box(key).IsChecked]

    def _name_formats(self):
        """The formats whose file names are shown and checked: those ticked, or PDF until a format is ticked."""
        return self._formats() or [u"PDF"]

    def _made(self, rows, formats_):
        """[(row, format)] for every ticked item and format that gives a file: IFC and NWC are not made from sheets,
        legends, drafting views or schedules."""
        return [(r, fmt) for r in rows for fmt in formats_ if not r.not_made(fmt)]

    def _left_out_text(self, rows, formats_):
        """A sentence on the items left out of a format, or "" when nothing is left out."""
        left = [(r, fmt) for r in rows for fmt in formats_ if r.not_made(fmt)]
        if not left:
            return u""
        which = _join(sorted(set(fmt for _, fmt in left), key=lambda f: KEY_OF[f]))
        return (u" {} not made, because {} files are made only from views of the model: plans, ceiling plans, "
                u"sections, elevations and 3D views.").format(_plural(len(left), u"file is", u"files are"), which)

    @staticmethod
    def _column(grid, header):
        for column in grid.Columns:
            if u"{}".format(column.Header) == header:
                return column
        return None

    def _name_columns(self):
        """File name columns for the formats in use, in both lists; paper, orientation, raster quality and rasterised
        views only when PDF is ticked, because they apply only to PDF. Columns are found by their heading."""
        shown = self._name_formats()
        pdf = bool(self.DoPdf.IsChecked)

        def vis(on):
            return Visibility.Visible if on else Visibility.Collapsed
        for label, _ in FORMATS:
            for grid in (self.ItemGrid, self.CheckGrid):
                column = self._column(grid, u"{} file name".format(label))
                if column is not None:
                    column.Visibility = vis(label in shown)
        for header in (u"Paper", u"Orientation", u"Raster quality", u"May be rasterised"):
            column = self._column(self.CheckGrid, header)
            if column is not None:
                column.Visibility = vis(pdf)

    def OnFormats(self, sender, args):
        for _, key in FORMATS:
            if self._tick_box(key).IsChecked:
                self._expander(key).IsExpanded = True
        self._name_columns()
        self.refresh_checks()

    def OnDwgSetup(self, sender, args):
        if self.ready:
            self.refresh_checks()

    def OnDgnSetup(self, sender, args):
        if self.ready:
            self.DgnVersion.IsEnabled = self.DgnSetup.SelectedItem in (None, DGN_DEFAULT)
            self.refresh_checks()

    def OnDwfType(self, sender, args):
        """DWF or DWFx changes the file extension, so the file names are checked again."""
        if self.ready:
            self.profile["dwf"]["file_type"] = _value_for(formats.DWF_FILE_TYPES, self.DwfType.SelectedItem)
            self.refresh_checks()

    def _remember(self, **values):
        one = self.last.setdefault(self.model_key, {})
        one.update(values)
        _write_json(LAST_USED_FILE, self.last)

    # ---- the list of sheets and views -----------------------------------------------------------------------------

    def _kind(self):
        return u"sheet" if self.ShowSheets.IsChecked else u"view"

    def _show_items(self):
        sheets = self._kind() == u"sheet"
        rows = self.sheet_rows if sheets else self._views()
        typed = (self.SearchBox.Text or u"").strip()
        text = typed.lower()
        chosen_set = self.SetFilter.SelectedItem
        ids = self.sets.get(chosen_set) if chosen_set and chosen_set != ALL_ITEMS else None
        self.shown = [r for r in rows if (not text or text in r.search) and (ids is None or r.item["id"] in ids)]
        self.ItemGrid.ItemsSource = ObservableCollection[object](self.shown)
        for i in (1, 3, 4):  # number, revision and sheet size are for sheets only
            self.ItemGrid.Columns[i].Visibility = Visibility.Visible if sheets else Visibility.Collapsed
        # An empty list says why (Jarek, 14/10/2026: "views does not show any views", with the sheets' search
        # "9933" still in the box).
        what = u"sheets" if sheets else u"views"
        if self.shown:
            self.EmptyNote.Visibility = Visibility.Collapsed
        else:
            if not rows:
                note = u"This model has no {} that can be exported.".format(what)
            elif text and ids is not None:
                note = u"No {} in the set {} match the search \"{}\". Clear the search box or choose (all).".format(
                    what, chosen_set, typed)
            elif text:
                note = u"No {} match the search \"{}\". Clear the search box to see them all.".format(what, typed)
            else:
                note = u"The set {} has no {}. Choose (all) to see them all.".format(chosen_set, what)
            self.EmptyNote.Text = note
            self.EmptyNote.Visibility = Visibility.Visible
        self._count()

    def _count(self):
        sheets = len([r for r in self.sheet_rows if r._ticked])
        views = len([r for r in (self.view_rows or []) if r._ticked])
        self.TickedCount.Text = u"{} and {} ticked".format(_plural(sheets, u"sheet"), _plural(views, u"view"))

    def OnListKind(self, sender, args):
        """Sheets and views each keep their own search, so a sheet number typed for sheets does not empty the views."""
        if not self.ready:
            return
        self.ready = False
        self.SearchBox.Text = self.search_text.get(self._kind(), u"")
        self.ready = True
        self._show_items()

    def OnSearch(self, sender, args):
        if self.ready:
            self.search_text[self._kind()] = self.SearchBox.Text or u""
            self._show_items()

    def OnSetFilter(self, sender, args):
        if self.ready:
            self._show_items()

    def OnTickAll(self, sender, args):
        for r in self.shown:
            r.set_ticked_quietly(True)
        self.on_ticks_changed()

    def OnTickNone(self, sender, args):
        for r in self._rows():
            r.set_ticked_quietly(False)
        self.on_ticks_changed()

    def on_ticks_changed(self):
        self._count()
        self.refresh_checks()

    def _ticked(self):
        return [r for r in self._rows() if r._ticked]

    def _selected(self):
        row = self.ItemGrid.SelectedItem
        if isinstance(row, ItemRow):
            return row
        ticked = self._ticked()
        if ticked:
            return ticked[0]
        return self.sheet_rows[0] if self.sheet_rows else None

    def OnItemSelected(self, sender, args):
        """The selected sheet is the one step 2 previews (_selected); nothing else changes here."""
        pass

    def OnCheckSelected(self, sender, args):
        row = self.CheckGrid.SelectedItem
        if not isinstance(row, ItemRow):
            return
        if row.reasons is None:
            row.set_reasons(self.checker.reasons(row.item["element"]))
        self._show_reasons(row)

    def _show_reasons(self, row):
        what = u"sheet {}".format(row.label) if row.kind == u"sheet" else u"view {}".format(row.label)
        if not row.reasons:
            self.RasterHead.Text = u"No view in the PDF of {} has a setting that makes Revit rasterise it.".format(what)
            self.RasterList.Text = u""
            return
        # "May": the check reads the settings, not what the view draws (model.RasterChecker; check 4, 14/10/2026).
        self.RasterHead.Text = (u"{} in the PDF of {} may be rasterised. Revit rasterises a view where it draws "
                                u"anything these settings apply to, from this model or a linked model:").format(
            _plural(len(row.reasons), u"view"), what)
        self.RasterList.Text = u"\n".join(u"{}: {}.".format(v, u"; ".join(rs)) for v, rs in row.reasons)

    def _enter_check(self):
        """Fill step 4 with the ticked items. With PDF ticked, each is checked for rasterised views first (a progress
        bar that can be cancelled; False when it is). Returns True to show the step."""
        ticked = self._ticked()
        chosen = self._formats()
        if u"PDF" in chosen and not self._check_raster(ticked):
            return False
        if any(KEY_OF[f] in extra.SIZE_CHECKED for f in chosen) and not self._check_large(ticked):
            return False
        self.CheckGrid.ItemsSource = ObservableCollection[object](ticked)
        self._name_columns()
        self.RasterHead.Text = u"Select a sheet to see the views that may be rasterised in its PDF, and why."
        self.RasterList.Text = u""
        sheets = len([r for r in ticked if r.kind == u"sheet"])
        views = len(ticked) - sheets
        what = u" and ".join(x for x in (_plural(sheets, u"sheet") if sheets else u"",
                                         _plural(views, u"view") if views else u"") if x) or u"Nothing"
        text = u"{} ticked, as {}: {} to {}.".format(
            what, _join(chosen) or u"no format yet", _plural(len(self._made(ticked, chosen)), u"file"),
            self.folder_path or u"no folder yet")
        text += self._left_out_text(ticked, chosen)
        if u"PDF" in chosen:
            heavy = len([r for r in ticked if r.reasons])
            if heavy:
                text += u" {} of them {} views that may be rasterised: select one to see which and why.".format(
                    heavy, u"has" if heavy == 1 else u"have")
            elif ticked:
                text += u" No view has a setting that makes Revit rasterise it."
        large = extra.large_note(self._large_found(ticked, chosen))
        if large:
            text += u" " + large
        self.CheckSummary.Text = text
        return True

    def _check_large(self, rows):
        """Finds, for each ticked sheet or view, the views with no crop region that are too large to export
        (model.large_views). A progress bar that can be cancelled; False when it is."""
        todo = [r for r in rows if r.large is None]
        if not todo:
            return True
        with forms.ProgressBar(title=u"Checking view sizes: {value} of {max_value}", cancellable=True) as pb:
            for i, r in enumerate(todo):
                if pb.cancelled:
                    return False
                r.large = model.large_views(self.doc, r.item["element"], self.large_cache)
                pb.update_progress(i + 1, len(todo))
        return True

    def _large_found(self, rows, chosen):
        """[(view name, width ft, height ft, sheet or None)] for extra.large_note: the views too large to export in
        the formats chosen that the size check applies to (extra.SIZE_CHECKED)."""
        keys = [f for f in chosen if KEY_OF[f] in extra.SIZE_CHECKED]
        found, seen = [], set()
        for r in rows:
            if not r.large or all(r.not_made(f) for f in keys):
                continue
            sheet = r.label if r.kind == u"sheet" else None
            for view, w, h in r.large:
                if (view, sheet) not in seen:
                    seen.add((view, sheet))
                    found.append((view, w, h, sheet))
        return found

    def _check_raster(self, rows):
        todo = [r for r in rows if r.reasons is None]
        if not todo:
            return True
        with forms.ProgressBar(title=u"Checking views: {value} of {max_value}", cancellable=True) as pb:
            for i, r in enumerate(todo):
                if pb.cancelled:
                    return False
                r.set_reasons(self.checker.reasons(r.item["element"]))
                pb.update_progress(i + 1, len(todo))
        return True

    # ---- naming rules ---------------------------------------------------------------------------------------------

    def _rule_names(self):
        return [r["name"] for r in self.profile["rules"]]

    def _fill_rules(self, select=None):
        was = self.ready
        self.ready = False
        rule_names = self._rule_names()
        self.RuleList.ItemsSource = rule_names
        self.RuleList.SelectedItem = select if select in rule_names else rule_names[0]
        for box, key, which in self._rule_boxes():
            box.ItemsSource = rule_names
            box.SelectedItem = self.profile[key][which]
        self.ready = was
        self._show_parts()

    def _rule_boxes(self):
        """[(box, key, "rule" or "view_rule")] for every rule box at step 3 (PdfRule, PdfViewRule, ..., XmlViewRule)."""
        return [(getattr(self, self._prefix(key) + (u"Rule" if which == "rule" else u"ViewRule")), key, which)
                for _, key, which in RULE_USES]

    def _current_rule(self):
        return profiles.rule(self.profile, self.RuleList.SelectedItem)

    def _show_parts(self):
        rule = self._current_rule()
        self.part_rows = [PartRow(p, self, i) for i, p in enumerate((rule or {}).get("parts", []))]
        self.PartGrid.ItemsSource = ObservableCollection[object](self.part_rows)
        if self.rule_message and rule is not None and self.rule_message[0] == rule["name"]:
            self.RuleNote.Text = self.rule_message[1]
        elif rule is not None and rule["name"] == profiles.PD_ISO_RULE_NAME:
            self.RuleNote.Text = (u"This is PD's standard ISO 19650 rule. If you change it, PD Sheets makes a copy for "
                                  u"this profile and leaves the standard rule as it is.")
        else:
            self.RuleNote.Text = u"The separator after the last part is not used."
        used = [label for label, key, which in RULE_USES if rule is not None and self.profile[key][which] == rule["name"]]
        self.RuleUse.Text = (u"Used for {}.".format(u", ".join(used)) if used else
                             u"Not used yet: choose it for a format at step 3.")
        self._preview()

    def _rule_to_edit(self):
        """The rule to change. The built-in PD ISO 19650 rule is never changed: the first edit makes a copy, every
        format that used the built-in rule now uses the copy, and the edit goes into the copy (Jarek, 14/10/2026:
        "everything is greyed out", when the built-in rule could only be copied by hand first)."""
        rule = self._current_rule()
        if rule is None or rule["name"] != profiles.PD_ISO_RULE_NAME:
            return rule
        taken = [n.lower() for n in self._rule_names()]
        name, n = u"PD ISO 19650 changed", 2
        while name.lower() in taken:
            name = u"PD ISO 19650 changed ({})".format(n)
            n += 1
        copied = copy.deepcopy(rule)
        copied["name"] = name
        self.profile["rules"].append(copied)
        moved = []
        for label, key, which in RULE_USES:
            if self.profile[key][which] == rule["name"]:
                self.profile[key][which] = name
                moved.append(label)
        self.rule_message = (name, u"The built-in PD ISO 19650 rule stays as it is. Your change is in the copy {}{}."
                             .format(name, u", now used for " + u", ".join(moved) if moved else u""))
        self.copied_to = name
        return copied

    def _after_part_edit(self, select=None):
        """Show the parts again once WPF has finished the edit in hand, keeping the selected part."""
        def done():
            if self.copied_to:
                name, self.copied_to = self.copied_to, None
                self._fill_rules(name)
            else:
                self._show_parts()
            if select is not None and 0 <= select < len(self.part_rows):
                self.PartGrid.SelectedIndex = select
            self.on_rule_edited()
        self._later(done)

    def edit_part(self, index, key, value):
        """A change typed or chosen in the parts list (PartRow)."""
        rule = self._rule_to_edit()
        if rule is None or not 0 <= index < len(rule["parts"]):
            return
        rule["parts"][index][key] = value
        if self.copied_to:
            self._after_part_edit(index)
        else:
            self.on_rule_edited()

    def _preview(self):
        rule = self._current_rule()
        row = self._selected()
        if rule is None or row is None:
            self.RulePreview.Text = u""
            return
        name, missing = names.build(rule["parts"], lambda part: self.value_of(row.item["element"], part))
        text = u"{}  ({})".format(name or u"(empty)", row.label)
        if missing:
            text += u"  " + names.missing_text(missing, self.no_text)
        self.RulePreview.Text = text

    def on_rule_edited(self):
        self._rebuild_names()
        self._preview()

    def _rebuild_names(self):
        for r in self._rows():
            r.rebuild()
        self.refresh_checks()

    def OnRuleChosen(self, sender, args):
        if self.ready:
            self._show_parts()

    def OnFormatRule(self, sender, args):
        if not self.ready:
            return
        for box, key, which in self._rule_boxes():
            if box.SelectedItem:
                self.profile[key][which] = box.SelectedItem
        self._rebuild_names()

    def _ask_rule_name(self, default):
        name = forms.ask_for_string(default=default, prompt=u"Name of the rule", title=u"PD Sheets")
        if not name:
            return None
        name = name.strip()
        if name.lower() in [n.lower() for n in self._rule_names()]:
            forms.alert(u"There is already a rule called {}. Choose another name.".format(name))
            return None
        return name

    def OnRuleNew(self, sender, args):
        name = self._ask_rule_name(u"New rule")
        if name:
            self.profile["rules"].append({"name": name, "parts": []})
            self._fill_rules(name)

    def OnRuleCopy(self, sender, args):
        rule = self._current_rule()
        if rule is None:
            return
        name = self._ask_rule_name(rule["name"] + u" copy")
        if name:
            copied = copy.deepcopy(rule)
            copied["name"] = name
            self.profile["rules"].append(copied)
            self._fill_rules(name)

    def OnRuleRename(self, sender, args):
        rule = self._current_rule()
        if rule is None or rule["name"] == profiles.PD_ISO_RULE_NAME:
            forms.alert(u"The PD ISO 19650 rule is built in and keeps its name.")
            return
        name = self._ask_rule_name(rule["name"])
        if not name:
            return
        old = rule["name"]
        rule["name"] = name
        for _, key in FORMATS:
            for which in ("rule", "view_rule"):
                if self.profile[key].get(which) == old:
                    self.profile[key][which] = name
        self._fill_rules(name)

    def OnRuleDelete(self, sender, args):
        rule = self._current_rule()
        if rule is None or rule["name"] == profiles.PD_ISO_RULE_NAME:
            forms.alert(u"The PD ISO 19650 rule is built in and cannot be deleted.")
            return
        used = [label for label, key, which in RULE_USES if self.profile[key][which] == rule["name"]]
        if used:
            forms.alert(u"The rule {} is used for {}. Choose another rule for {} first.".format(
                rule["name"], u", ".join(used), u"them" if len(used) > 1 else u"it"))
            return
        self.profile["rules"].remove(rule)
        self._fill_rules()

    def _move_part(self, step):
        """Move the selected part up (-1) or down (1), or remove it (0)."""
        try:
            self.PartGrid.CommitEdit()
        except Exception:
            pass
        i = self.PartGrid.SelectedIndex
        current = self._current_rule()
        if current is None or i < 0:
            self._say(u"Select a part in the list on the right first.", True)
            return
        j = i + step
        if step and not 0 <= j < len(current["parts"]):
            return
        parts = self._rule_to_edit()["parts"]
        if step:
            parts[i], parts[j] = parts[j], parts[i]
        else:
            parts.pop(i)
            j = min(i, len(parts) - 1)
        self._after_part_edit(j)

    def OnPartUp(self, sender, args):
        self._move_part(-1)

    def OnPartDown(self, sender, args):
        self._move_part(1)

    def OnPartRemove(self, sender, args):
        self._move_part(0)

    def _fill_params(self):
        """Every sheet, view and project information parameter in the model, with its value on the sheet the preview
        uses (Jarek, 14/10/2026: "the parameters should be on left hand side allowing user to add them")."""
        text = (self.ParamSearch.Text or u"").strip().lower()
        row = self._selected()
        element = row.item["element"] if row is not None else None
        shown = []
        for n, s in self.params:
            if text and text not in n.lower():
                continue
            value = None
            if element is not None:
                try:
                    value = self.value_of(element, {"param": n, "source": s})
                except Exception:
                    value = None
            shown.append(ParamRow(n, s, value))
        self.ParamGrid.ItemsSource = ObservableCollection[object](shown)
        self.ParamGrid.Columns[2].Header = u"Value on {}".format(row.label) if row is not None else u"Value"

    def OnParamSearch(self, sender, args):
        if self.ready:
            self._fill_params()

    def OnParamAdd(self, sender, args):
        chosen = self.ParamGrid.SelectedItem
        if not isinstance(chosen, ParamRow):
            self._say(u"Select a parameter in the list on the left first.", True)
            return
        if self._current_rule() is None:
            return
        try:
            self.PartGrid.CommitEdit()
        except Exception:
            pass
        parts = self._rule_to_edit()["parts"]
        at = self.PartGrid.SelectedIndex
        at = at + 1 if 0 <= at < len(parts) else len(parts)
        parts.insert(at, names.part(chosen.param, sep=u"-", source=chosen.source))
        self._after_part_edit(at)

    # ---- the values in the XML files ------------------------------------------------------------------------------

    def _xml_fields(self, kind=None):
        """The profile's list of values for sheets or for views (the list itself, so changes go into the profile)."""
        xml = self.profile["xml"]
        name = "sheet_fields" if (kind or self.xml_kind) == u"sheet" else "view_fields"
        if not isinstance(xml.get(name), list):
            xml[name] = []
        return xml[name]

    def _show_xml(self, select=None):
        if self.profile is None:
            return
        self.xml_rows = [XmlRow(f, self) for f in self._xml_fields()]
        self.XmlGrid.ItemsSource = ObservableCollection[object](self.xml_rows)
        if select is not None and 0 <= select < len(self.xml_rows):
            self.XmlGrid.SelectedIndex = select
        self._xml_notes()

    def _xml_sample_row(self):
        """The sheet or view the sample uses: the first one ticked of the kind shown, else the first in the list."""
        rows = self.sheet_rows if self.xml_kind == u"sheet" else (self.view_rows or [])
        ticked = [r for r in rows if r._ticked]
        return ticked[0] if ticked else (rows[0] if rows else None)

    def _xml_notes(self):
        fields = self._xml_fields()
        found = xmlwriter.problems(fields)
        if not fields:
            found.insert(0, u"No values are listed, so the XML files would be empty. Add a parameter or a fixed text.")
        self.XmlProblems.Text = u" ".join(found)
        row = self._xml_sample_row()
        if row is None:
            self.XmlSampleHead.Text = u"Tick a view at step 1 to see what its XML file would hold."
            self.XmlSample.Text = u""
            return
        element = row.item["element"]
        try:
            pairs = xmlwriter.values(fields, lambda f: self.value_of(element, f))
            self.XmlSampleHead.Text = u"The XML file of {} would read:".format(row.label)
            self.XmlSample.Text = u"\r\n".join(xmlwriter.lines(self.xml_kind, pairs))
        except Exception as ex:
            self.XmlSampleHead.Text = u"The values of {} could not be read ({}).".format(row.label, ex)
            self.XmlSample.Text = u""

    def on_xml_edited(self):
        """An element name or a fixed text typed in the list (XmlRow)."""
        self._xml_notes()
        self.refresh_checks()

    def OnXmlKind(self, sender, args):
        if not self.ready or self.profile is None:
            return
        self.xml_kind = u"sheet" if self.XmlSheets.IsChecked else u"view"
        self._show_xml()

    def _xml_commit(self):
        try:
            self.XmlGrid.CommitEdit()
        except Exception:
            pass

    def _xml_insert(self, field):
        """Add a value after the one selected, or at the end, with an element name not used yet."""
        self._xml_commit()
        fields = self._xml_fields()
        taken = set(f.get("element") for f in fields)
        base, n = field["element"], 2
        while field["element"] in taken:
            field["element"] = u"{}{}".format(base, n)
            n += 1
        at = self.XmlGrid.SelectedIndex
        at = at + 1 if 0 <= at < len(fields) else len(fields)
        fields.insert(at, field)
        self._later(lambda: self._show_xml(at))
        self.refresh_checks()

    def OnXmlAdd(self, sender, args):
        chosen = self.XmlParam.SelectedItem or self.XmlParam.Text
        found = [(n, s) for n, s in self.params if self._param_label(n, s) == chosen]
        if not found:
            self._say(u"Choose a parameter in the box to the left of Add the parameter first.", True)
            return
        name, source = found[0]
        self._xml_insert(xmlwriter.field(name, source))

    def OnXmlAddFixed(self, sender, args):
        self._xml_insert(xmlwriter.fixed(u"FixedText", u""))

    def _move_xml(self, step):
        """Move the selected value up (-1) or down (1), or remove it (0)."""
        self._xml_commit()
        fields = self._xml_fields()
        i = self.XmlGrid.SelectedIndex
        if not 0 <= i < len(fields):
            self._say(u"Select a value in the XML list first.", True)
            return
        j = i + step
        if step and not 0 <= j < len(fields):
            return
        if step:
            fields[i], fields[j] = fields[j], fields[i]
        else:
            fields.pop(i)
            j = min(i, len(fields) - 1)
        self._later(lambda: self._show_xml(j))
        self.refresh_checks()

    def OnXmlUp(self, sender, args):
        self._move_xml(-1)

    def OnXmlDown(self, sender, args):
        self._move_xml(1)

    def OnXmlRemove(self, sender, args):
        self._move_xml(0)

    # ---- checks before export -------------------------------------------------------------------------------------

    def refresh_checks(self):
        if not self.ready or self.profile is None:
            return
        ticked = self._ticked()
        chosen = self._formats()
        named = self._name_formats()
        messages = {}
        for fmt in named:
            key = KEY_OF[fmt]
            ext = formats.extension(key, self.profile.get(key))
            made = [r for r in ticked if not r.not_made(fmt)]
            found = names.problems([(r.label, r.name_for(fmt), r.missing(fmt)) for r in made],
                                   self.folder_path or u"", ext, self.no_text)
            for r in made:
                if r.label in found:
                    prefix = u"{}: ".format(fmt) if len(named) > 1 else u""
                    messages.setdefault(r.label, []).append(prefix + found[r.label])
        for r in self._rows():
            r.set_check(u" ".join(messages.get(r.label, [])) if r._ticked else u"")
        files = len(self._made(ticked, chosen))
        blockers = []
        if not ticked:
            blockers.append(u"Tick the sheets or views to export.")
        if not chosen:
            blockers.append(u"Tick at least one format.")
        elif ticked and not files:
            blockers.append(u"Nothing ticked can be exported as {}: these files are made only from views of the model "
                            u"(plans, ceiling plans, sections, elevations and 3D views). Tick one of those views at "
                            u"step 1.".format(_join(chosen)))
        if self.folder_problem:
            blockers.append(self.folder_problem)
        if messages:
            blockers.append(u"{} ticked {} a problem with the file name. The Problems column says what to change.".format(
                len(messages), u"item has" if len(messages) == 1 else u"items have"))
        setup = self.DwgSetup.SelectedItem
        if u"DWG" in chosen and setup not in ([DWG_DEFAULT] + list(self.setups)):
            blockers.append(u"The DWG export setup {} is not in this model. Choose one of the model's setups at "
                            u"step 3.".format(setup))
        setup = self.DgnSetup.SelectedItem
        if u"DGN" in chosen and setup not in ([DGN_DEFAULT] + list(self.dgn_setups)):
            blockers.append(u"The DGN export setup {} is not in this model. Choose one of the model's setups at "
                            u"step 3.".format(setup))
        if u"XML" in chosen:
            for kind, what in ((u"sheet", u"sheets"), (u"view", u"views")):
                if not any(r.kind == kind for r in ticked):
                    continue
                fields = self._xml_fields(kind)
                if not fields:
                    blockers.append(u"No values are listed for the XML files of {}. Add them at step 3.".format(what))
                elif xmlwriter.problems(fields):
                    blockers.append(u"The XML values for {} have a problem: {} Change it at step 3.".format(
                        what, xmlwriter.problems(fields)[0]))
        self.ExportButton.IsEnabled = not blockers
        # The status line says what to do next at the step on show.
        step = getattr(self, "step", STEP_SHEETS)
        if step == STEP_SHEETS:
            if ticked:
                self._say(u"{} ticked. Press Next to set the file names.".format(_plural(len(ticked), u"item")))
            else:
                self._say(u"Tick the sheets or views to export.")
        elif step == STEP_NAMES:
            if messages:
                self._say(u"{} ticked {} a problem with the file name. The Problems column at step 1 says what to "
                          u"change.".format(len(messages), u"item has" if len(messages) == 1 else u"items have"), True)
            else:
                self._say(u"Press Next to choose the formats and the output folder.")
        elif step == STEP_FORMATS:
            if not chosen:
                self._say(u"Tick at least one format.")
            elif self.folder_problem:
                self._say(self.folder_problem, True)
            else:
                self._say(u"Press Next to check each item before export.")
        elif step == STEP_CHECK:
            if blockers:
                self._say(blockers[0], True)
            else:
                self._say(u"Ready to export {} to {}. Press Export.".format(_plural(files, u"file"), self.folder_path))
        else:
            self._say(getattr(self, "results_text", u""))

    # ---- export ---------------------------------------------------------------------------------------------------

    def OnExport(self, sender, args):
        problem = self._controls_to_profile()
        if problem:
            forms.alert(problem)
            return
        self.refresh_checks()
        if not self.ExportButton.IsEnabled:
            return
        folder = self.folder_path
        test = os.path.join(folder, u"PD-Sheets-write-test.tmp")
        try:
            with io.open(test, "w", encoding="utf-8") as f:
                f.write(u"test")
            os.remove(test)
        except Exception as ex:
            forms.alert(u"PD Sheets cannot write to the folder {}. Choose another folder.".format(folder),
                        sub_msg=u"{}".format(ex))
            return
        ticked = self._ticked()
        chosen = self._formats()
        todo = self._made(ticked, chosen)
        self.left_out_text = self._left_out_text(ticked, chosen)
        names_by_key = {}
        for r, fmt in todo:
            names_by_key.setdefault(KEY_OF[fmt], []).append(r.name_for(fmt))
        existing, beside = self._already_there(folder, todo, names_by_key)
        replace = False
        if existing or beside:
            choice = forms.alert(extra.already_text(len(existing), len(beside),
                                                    [fmt for _, fmt in beside.values()]),
                                 options=[u"Replace them", u"Skip them", u"Cancel"])
            if choice not in (u"Replace them", u"Skip them"):
                return
            replace = choice == u"Replace them"
        if u"PDF" in chosen and not self._check_raster(ticked):
            return
        app = self.doc.Application
        rows = []
        total = len(todo)
        stopped = False
        # Run clears the selection for the export so nothing prints in Revit's selection colours, answers the message
        # box Revit shows while it exports a shaded view to DWF, and gives back what Revit borrows on a workshared
        # model for an NWC (exporter.Run).
        with exporter.Run(self.doc, _uiapp()) as run:
            run.names = names_by_key
            with forms.ProgressBar(title=u"Exporting: {value} of {max_value}", cancellable=True) as pb:
                for r, fmt in todo:
                    if pb.cancelled:
                        stopped = True
                        break
                    key = KEY_OF[fmt]
                    r.item["rasterised_count"] = len(r.reasons) if r.reasons is not None else None
                    # Revit does not respond during doc.Export, for over a minute on a large sheet, so the bar names
                    # the file in hand and says so (Jarek, 14/10/2026: "the whole panel seems to be stuck")
                    what = u"image" if key == u"img" else formats.label(key, self.profile.get(key))
                    pb.title = _progress_text(r.label, what, len(rows) + 1, total)
                    pb.update_progress(len(rows), total)
                    row = exporter.export_one(self.doc, folder, r.item, fmt, r.name_for(fmt), self.profile, replace,
                                              run)
                    row.update({"revit": app.VersionNumber, "user": app.Username, "profile": self.profile["name"]})
                    rows.append(row)
                    pb.update_progress(len(rows), total)
        try:
            self.record_path = record.write(folder, datetime.datetime.now(), rows)
        except Exception as ex:
            self.record_path = None
            forms.alert(u"The files are written, but the export record could not be saved.", sub_msg=u"{}".format(ex))
        self.export_folder = folder
        self._remember(profile=self.profile["name"], folder=self.folder_stored)
        self._show_results(rows, stopped)
        self.Step5.IsEnabled = True
        self._go(STEP_RESULTS)

    def _already_there(self, folder, todo, names_by_key):
        """({lower name: name} of the files to export that are already in the folder, {lower name: (name, format
        label)} of the other files already there that Revit would write again beside a DWG or DGN: for linked
        models, views on a sheet, linked CAD files and the plot settings (exporter.extra_existing))."""
        existing, beside = {}, {}
        for r, fmt in todo:
            path = exporter.target_path(folder, r.name_for(fmt), fmt, self.profile)
            if os.path.exists(path):
                existing[os.path.basename(path).lower()] = os.path.basename(path)
        if not any(KEY_OF[fmt] in (u"dwg", u"dgn") for _, fmt in todo):
            return existing, beside
        try:
            listing = os.listdir(folder)
        except OSError:
            return existing, beside
        cad = None
        for r, fmt in todo:
            key = KEY_OF[fmt]
            if key not in (u"dwg", u"dgn"):
                continue
            try:
                if key == u"dgn" and cad is None:
                    cad = model.linked_cad(self.doc)
                found = exporter.extra_existing(self.doc, folder, r.item, r.name_for(fmt), key, self.profile[key],
                                                names_by_key.get(key, ()), listing, cad)
            except Exception:
                found = []
            for f in found:
                if f.lower() not in existing:
                    beside[f.lower()] = (f, fmt)
        return existing, beside

    def _show_results(self, rows, stopped):
        folder = self.export_folder or self.folder_path
        self.ResultGrid.ItemsSource = ObservableCollection[object]([ResultRow(r, folder) for r in rows])
        written = len([r for r in rows if (r.get("result") or u"").startswith(u"written")])
        skipped = len([r for r in rows if (r.get("result") or u"").startswith(u"skipped")])
        failed = len(rows) - written - skipped
        over = len([r for r in rows if r.get("over_limit")])
        text = u"{} written, {} skipped and {} failed.".format(written, skipped, failed)
        if stopped:
            text = u"The export was stopped part way. " + text
        renamed = record.renamed_summary(rows)
        if renamed:
            text += u" " + renamed
        if failed:
            text += u" The Result column gives the reason for each failure."
        noted = len([r for r in rows if r.get("note")])
        if noted:
            text += u" The Note column says what Revit did during the export of {}.".format(
                _plural(noted, u"file"))
        text += getattr(self, "left_out_text", u"")
        if over:
            text += u" {} larger than the limit of {:g} MB.".format(
                _plural(over, u"PDF is", u"PDFs are"), float(self.profile.get("size_limit_mb") or 0))
        if self.record_path:
            text += u" The export record is saved as {}.".format(os.path.basename(self.record_path))
        self.ResultSummary.Text = text
        self.results_text = text

    def _result_path(self):
        row = self.ResultGrid.SelectedItem
        if isinstance(row, ResultRow) and row.path and os.path.isfile(row.path):
            return row.path
        return None

    def OnOpenLocation(self, sender, args):
        """Open the folder in File Explorer, with the selected file selected (Jarek, 14/10/2026: the results were
        "missing 'Open File Location'")."""
        path = self._result_path()
        if path:
            Process.Start(u"explorer.exe", u'/select,"{}"'.format(path))
            return
        folder = self.export_folder or self.folder_path
        if folder and os.path.isdir(folder):
            _open_in_windows(folder)

    def OnOpenFile(self, sender, args):
        path = self._result_path()
        if path:
            _open_in_windows(path)
        else:
            forms.alert(u"Select a file that was written in the list first.")

    def OnOpenRecord(self, sender, args):
        if self.record_path and os.path.isfile(self.record_path):
            _open_in_windows(self.record_path)
        else:
            forms.alert(u"There is no export record yet. It is saved beside the files after an export.")

    # ---- closing --------------------------------------------------------------------------------------------------

    def OnClose(self, sender, args):
        self.Close()

    def OnClosing(self, sender, args):
        if self.profile is not None and not self._ask_to_save():
            args.Cancel = True
            return
        if self.profile is not None:
            self._remember(profile=self.profile["name"])
