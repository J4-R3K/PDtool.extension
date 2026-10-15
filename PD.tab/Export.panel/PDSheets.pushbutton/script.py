# -*- coding: utf-8 -*-
"""PD Sheets: export sheets and views with Revit's own export to PDF, DWG, DGN, DWF or DWFx, IFC, NWC, images and XML.
Author: Jarek Wityk @ PD. The window and the export are in lib/pdtool/sheets."""
from pyrevit import forms, revit, script

from pdtool.sheets import window

doc = revit.doc
forms.check_modeldoc(doc, exitscript=True)

window.SheetsWindow(script.get_bundle_file("PDSheets.xaml"), doc).show_dialog()
