# -*- coding: utf-8 -*-
"""PD Schedules: export schedules and panel schedules to Excel workbooks, laid out as Revit shows them, and panel
schedules also as PD distribution board (DB) charts. Author: Jarek Wityk @ PD. The window and the export are in
lib/pdtool/schedx."""
from pyrevit import forms, revit, script

from pdtool.schedx import window

doc = revit.doc
forms.check_modeldoc(doc, exitscript=True)

window.SchedulesWindow(script.get_bundle_file("PDSchedules.xaml"), doc).show_dialog()
