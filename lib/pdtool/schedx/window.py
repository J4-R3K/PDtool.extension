# -*- coding: utf-8 -*-
"""The PD Schedules window (plan section 4.1). Needs Revit and pyRevit.

One page: the list of schedules and panel schedules on the left, the panel schedule layouts, the workbooks and the
output folder on the right, then Export. The results replace the list after the export; Back to the list returns to
it. Modal: Revit waits until the window is closed, and the schedules are read straight from the Export button. The
model is only read (revitread opens no transaction).

The logic it uses is in the other modules of pdtool.schedx, which are tested outside Revit
(pdtool-lib-tests/test_schedx.py). The layout is in the button's PDSchedules.xaml."""
import datetime
import io
import json
import os
import time
import uuid

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System")
from System.Collections.ObjectModel import ObservableCollection
from System.Diagnostics import Process, ProcessStartInfo
from System.Windows import Visibility

from pyrevit import forms

from pdtool.schedx import book, names, revitread, xlsx

LOCAL_FOLDER = os.path.join(os.environ.get("APPDATA") or u"", u"pyRevit", u"PD Schedules")
LAST_USED_FILE = os.path.join(LOCAL_FOLDER, u"last-used.json")
ANY_MODEL = u"(any model)"  # the folder used last in any model, offered for a model exported for the first time
RED = u"#B00020"
GREY = u"#4A5260"
TAB_LIST, TAB_RESULTS = 0, 1


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
        pass  # remembering the last choices is a convenience; the export does not depend on it


def _open_in_windows(path):
    """Open a file or folder as a double click in Windows would (works on .NET Framework and .NET 8)."""
    info = ProcessStartInfo(path)
    info.UseShellExecute = True
    Process.Start(info)


def _plural(n, one, many=None):
    return u"{} {}".format(n, one if n == 1 else (many or one + u"s"))


def _progress_text(name, number, total):
    """The progress bar's line while one schedule is read. Braces are doubled because pyRevit fills {value} and
    {max_value} into the line."""
    text = (u"Reading {} ({} of {}). Revit does not respond to clicks until the schedules are read; press Cancel "
            u"to stop.".format(name, number, total))
    return text.replace(u"{", u"{{").replace(u"}", u"}}")


def _duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return _plural(seconds, u"second")
    return u"{} min {} s".format(seconds // 60, seconds % 60)


def _cannot_write(folder):
    """None when a file can be written in folder, else the reason it cannot."""
    test = os.path.join(folder, u"~pd-schedules-{}.tmp".format(uuid.uuid4().hex[:8]))
    try:
        with io.open(test, "w", encoding="utf-8") as f:
            f.write(u"test")
        os.remove(test)
        return None
    except Exception as ex:
        return u"{}".format(ex)


class ItemRow(forms.Reactive):
    """One schedule or panel schedule in the list."""

    def __init__(self, entry, win):
        self.entry = entry
        self.win = win
        self._ticked = False
        self.search = u"{} {}".format(entry["name"], entry["kind"]).lower()

    @property
    def name(self):
        return self.entry["name"]

    @property
    def kind(self):
        return self.entry["kind"]

    @property
    def is_panel(self):
        return self.entry["kind"] == revitread.KIND_PANEL

    @forms.reactive
    def ticked(self):
        return self._ticked

    @ticked.setter
    def ticked(self, value):
        self._ticked = bool(value)
        self.win.on_ticks_changed()

    def set_ticked_quietly(self, value):
        self._ticked = bool(value)
        self.OnPropertyChanged("ticked")


class ResultRow(object):
    """One sheet written, or one schedule that could not be read or written."""

    def __init__(self, name, sheet=u"", layout=u"", rows=u"", cols=u"", path=None, result=u"", notes=u""):
        self.name = name
        self.sheet = sheet
        self.layout = layout
        self.rows = u"{}".format(rows)
        self.cols = u"{}".format(cols)
        self.path = path
        self.file = os.path.basename(path) if path else u""
        self.result = result
        self.notes = notes


class SchedulesWindow(forms.WPFWindow):

    def __init__(self, xaml_path, doc):
        forms.WPFWindow.__init__(self, xaml_path)
        self.ready = False
        self.doc = doc
        self.model_key = doc.Title
        self.last = _read_json(LAST_USED_FILE, {})
        mine = self.last.get(self.model_key) or {}
        self.rows = [ItemRow(e, self) for e in revitread.list_items(doc)]
        self.shown = list(self.rows)
        self.export_folder = None
        self.PanelRevit.IsChecked = mine.get("panel_revit", True)
        self.PanelChart.IsChecked = mine.get("panel_chart", True)
        if mine.get("one_book", True):
            self.OneBook.IsChecked = True
        else:
            self.BookEach.IsChecked = True
        self.FileNameBox.Text = self._default_stem()
        self._set_folder(mine.get("folder") or (self.last.get(ANY_MODEL) or {}).get("folder"))
        self.ready = True
        self._book_choice()
        self._show_items()

    def _remember(self, **values):
        self.last.setdefault(self.model_key, {}).update(values)
        if values.get("folder"):
            self.last.setdefault(ANY_MODEL, {})["folder"] = values["folder"]
        _write_json(LAST_USED_FILE, self.last)

    def _brush(self, colour):
        from System.Windows.Media import BrushConverter
        return BrushConverter().ConvertFromString(colour)

    # ---- the list -------------------------------------------------------------------------------------------------

    def _show_items(self):
        typed = (self.SearchBox.Text or u"").strip()
        text = typed.lower()
        self.shown = [r for r in self.rows if not text or text in r.search]
        self.ItemGrid.ItemsSource = ObservableCollection[object](self.shown)
        if self.shown:
            self.EmptyNote.Visibility = Visibility.Collapsed
        else:
            if not self.rows:
                note = u"This model has no schedules or panel schedules."
            else:
                note = u"Nothing matches the search \"{}\". Clear the search box to see the whole list.".format(typed)
            self.EmptyNote.Text = note
            self.EmptyNote.Visibility = Visibility.Visible
        self._count()

    def _count(self):
        ticked = [r for r in self.rows if r._ticked]
        panels = len([r for r in ticked if r.is_panel])
        self.TickedCount.Text = u"{} and {} are ticked.".format(
            _plural(len(ticked) - panels, u"schedule"), _plural(panels, u"panel schedule"))

    def OnSearch(self, sender, args):
        if self.ready:
            self._show_items()

    def OnTickAll(self, sender, args):
        for r in self.shown:
            r.set_ticked_quietly(True)
        self.on_ticks_changed()

    def OnTickNone(self, sender, args):
        for r in self.rows:
            r.set_ticked_quietly(False)
        self.on_ticks_changed()

    def on_ticks_changed(self):
        self._count()

    # ---- the workbooks and the folder -----------------------------------------------------------------------------

    def _default_stem(self):
        return names.file_name(u"{}_{}_Schedules".format(self.doc.Title, datetime.date.today().strftime("%Y-%m-%d")))

    def _one_book(self):
        return bool(self.OneBook.IsChecked)

    def _book_choice(self):
        one = self._one_book()
        self.FileNameRow.Visibility = Visibility.Visible if one else Visibility.Collapsed
        if one:
            self.FileNote.Text = u"The first sheet of the workbook is a Contents sheet with a link to every sheet."
        else:
            self.FileNote.Text = (u"Each workbook is named after its schedule. Its first sheet is a Contents sheet "
                                  u"with a link to every sheet.")

    def OnBookChoice(self, sender, args):
        if self.ready:
            self._book_choice()

    def _file_stem(self):
        typed = (self.FileNameBox.Text or u"").strip()
        if typed.lower().endswith(u".xlsx"):
            typed = typed[:-5].rstrip()
        return names.file_name(typed) if typed else u""

    def _set_folder(self, path):
        if not path:
            problem = u"Choose an output folder."
        elif not os.path.isdir(path):
            problem = (u"The folder {} cannot be found. Create it and choose it with Browse, or choose another "
                       u"folder.".format(path))
        else:
            problem = None
        self.folder_path = None if problem else path
        self.folder_problem = problem
        self.FolderBox.Text = path or u""
        self.FolderNote.Text = problem or u"After you export, this folder is offered again for this model."
        self.FolderNote.Foreground = self._brush(RED if problem else GREY)

    def OnBrowse(self, sender, args):
        chosen = forms.pick_folder(title=u"Choose an output folder")
        if not chosen:
            return
        self._remember(folder=chosen)
        self._set_folder(chosen)

    # ---- the export -----------------------------------------------------------------------------------------------

    def OnExport(self, sender, args):
        ticked = [r for r in self.rows if r._ticked]
        if not ticked:
            forms.alert(u"Tick at least one schedule or panel schedule to export.")
            return
        panel_revit = bool(self.PanelRevit.IsChecked)
        panel_chart = bool(self.PanelChart.IsChecked)
        if any(r.is_panel for r in ticked) and not (panel_revit or panel_chart):
            forms.alert(u"Tick \"As in Revit\", \"Distribution board (DB) chart\" or both to export the panel "
                        u"schedules.",
                        sub_msg=u"Panel schedules are ticked in the list, but no layout is ticked for them.")
            return
        folder = self.folder_path
        if not folder:
            forms.alert(self.folder_problem or u"Choose an output folder.")
            return
        problem = _cannot_write(folder)
        if problem:
            forms.alert(u"Files cannot be written to the folder {}. Choose another folder.".format(folder),
                        sub_msg=problem)
            return
        one = self._one_book()
        if one:
            stem = self._file_stem()
            if not stem:
                forms.alert(u"Type a file name for the workbook.")
                return
            stems = [stem]
        else:
            stems = names.unique_files([names.file_name(r.name) for r in ticked])
        there = [s + u".xlsx" for s in stems if os.path.exists(os.path.join(folder, s + u".xlsx"))]
        if there:
            if len(there) == 1:
                text = u"The workbook {} is already in the folder. Replace it?".format(there[0])
            else:
                shown = there[:10] + ([u"and {} more".format(len(there) - 10)] if len(there) > 10 else [])
                text = u"{} of the workbooks are already in the folder:\n\n{}\n\nReplace them?".format(
                    len(there), u"\n".join(shown))
            choice = forms.alert(text, options=[u"Replace", u"Cancel"])
            if choice != u"Replace":
                return
        self._remember(folder=folder, one_book=one, panel_revit=panel_revit, panel_chart=panel_chart)
        made = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        started = time.time()
        results, items = [], []
        stopped = False
        total = len(ticked)
        with forms.ProgressBar(title=u"Reading: {value} of {max_value}", cancellable=True) as pb:
            for i, r in enumerate(ticked):
                if pb.cancelled:
                    stopped = True
                    break
                pb.title = _progress_text(r.name, i + 1, total)
                pb.update_progress(i, total)
                try:
                    item = revitread.read_item(self.doc, r.entry, panel_revit, panel_chart)
                except Exception as ex:
                    results.append(ResultRow(r.name, result=u"Not read: {}".format(ex)))
                    continue
                if one:
                    items.append(item)
                else:
                    results += self._write([item], os.path.join(folder, stems[i] + u".xlsx"), made, panel_revit,
                                           panel_chart)
                pb.update_progress(i + 1, total)
        if one and items and not stopped:
            results += self._write(items, os.path.join(folder, stems[0] + u".xlsx"), made, panel_revit, panel_chart)
        self.export_folder = folder
        self._show_results(results, stopped, one, len(items), time.time() - started)

    def _write(self, items, path, made, panel_revit, panel_chart):
        """Build one workbook of items and save it at path, or as a copy when that file is open in another program.
        Returns a ResultRow for each sheet listed on its Contents sheet."""
        try:
            wb, listed = book.build(items, self.doc.Title, made, panel_revit, panel_chart)
            written = xlsx.save_safely(wb, path, names.copy_name)
        except Exception as ex:
            return [ResultRow(item["name"], path=None, result=u"Not written: {}".format(ex)) for item in items]
        if os.path.normcase(written) == os.path.normcase(path):
            result = u"Written"
        else:
            result = u"Written as {}, because {} was open in another program".format(
                os.path.basename(written), os.path.basename(path))
        out = []
        for sheet, name, layout, rows, cols, notes in listed:
            out.append(ResultRow(name, sheet or u"(not made)", layout, rows if sheet else u"", cols if sheet else u"",
                                 written, result if sheet else u"Not made", notes))
        return out

    def _show_results(self, results, stopped, one, read, seconds):
        self.ResultGrid.ItemsSource = ObservableCollection[object](results)
        files = sorted(set(r.path for r in results if r.path))
        not_read = len([r for r in results if r.result.startswith(u"Not read")])
        not_written = len([r for r in results if r.result.startswith(u"Not written")])
        copies = len(set(r.path for r in results if r.result.startswith(u"Written as")))
        if one and stopped:
            text = u"The export was stopped part way, so no workbook was written."
        elif one and files:
            text = u"{} exported to {} in {}.".format(_plural(read, u"schedule was", u"schedules were"),
                                                     os.path.basename(files[0]), _duration(seconds))
        elif one:
            text = u"No workbook was written."
        else:
            text = u"{} written in {}.".format(_plural(len(files), u"workbook was", u"workbooks were"),
                                               _duration(seconds))
            if stopped:
                text = u"The export was stopped part way. " + text
        if not_read:
            text += u" {} could not be read.".format(_plural(not_read, u"schedule"))
        if not_written:
            text += u" {} could not be written.".format(_plural(not_written, u"sheet"))
        if not_read or not_written:
            text += u" The Result column provides the reason."
        if copies:
            text += (u" {} saved with a number added to the name, because a file of that name was open in another "
                     u"program.").format(
                _plural(copies, u"workbook was", u"workbooks were"))
        self.ResultSummary.Text = text
        self._go(TAB_RESULTS)

    def _go(self, tab):
        self.Tabs.SelectedIndex = tab
        results = tab == TAB_RESULTS
        self.BackButton.Visibility = Visibility.Visible if results else Visibility.Collapsed
        self.ExportButton.Visibility = Visibility.Collapsed if results else Visibility.Visible

    def OnBack(self, sender, args):
        self._go(TAB_LIST)

    def _result_path(self):
        row = self.ResultGrid.SelectedItem
        if isinstance(row, ResultRow) and row.path and os.path.isfile(row.path):
            return row.path
        return None

    def OnOpenLocation(self, sender, args):
        """Open the folder in File Explorer, with the selected file selected."""
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
            forms.alert(u"Select a row whose workbook is in the folder.")

    # ---- closing --------------------------------------------------------------------------------------------------

    def OnClose(self, sender, args):
        self.Close()

    def OnClosing(self, sender, args):
        self._remember(one_book=self._one_book(), panel_revit=bool(self.PanelRevit.IsChecked),
                       panel_chart=bool(self.PanelChart.IsChecked))
