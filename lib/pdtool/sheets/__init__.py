# -*- coding: utf-8 -*-
"""PD Sheets (started 14/10/2026).

The PD Sheets button (PD tab, Export panel) exports sheets and views through Revit's own export to PDF, DWG, DGN, DWF or
DWFx, IFC, NWC, images and XML. The logic that can be proved outside Revit is kept apart from the parts that need Revit, so
`C:\\Dev\\pyRevit\\pdtool-lib-tests\\test_sheets.py` can run it under CPython 3 and both IronPython engines pyRevit uses
(2.7.12 in Revit 2023 and 2024, 3.4.2 in Revit 2025 and later): .format(), no f-strings.

Tested outside Revit:
names     - builds a file name from a naming rule, replaces characters Windows refuses, finds blanks and duplicates.
folders   - stores a folder without the user's name in it, and finds it again on any PC (SharePoint libraries synced
            by OneDrive, the user's own folders, or a plain path).
profiles  - reads and writes the JSON profiles, with the PD ISO 19650 rule built in.
prosheets - reads PD's own saved ProSheets profiles (XML) into PD Sheets profiles. No DiRoots program file is read.
paper     - names a title block's size (A1, or 275 x 480 mm) and lists Revit's paper sizes for the PDF.
record    - writes the CSV export record beside the files.
formats   - the eight formats: their settings, defaults, file extensions, and which views each is made from.
xmlwriter - writes PD's own XML file of chosen parameter values for one sheet or view.

Need Revit (checked in Revit 2024 on a project model, 14/10/2026):
model     - reads sheets, views, parameters, title block sizes and View/Sheet Sets, and lists the views Revit may
            rasterise in a PDF, with the reason.
exporter  - one Revit export call per sheet and format; leaves the model unchanged and gives back anything Revit
            borrows for an NWC.
window    - the PD Sheets window (layout in the button's PDSheets.xaml).

Plan and checks: C:\\Dev\\PD-Revit-Sheets-PLAN-2026-10-14.md and C:\\Dev\\PD-Revit-Sheets-v1-BUILD-PLAN-2026-10-14.md.
"""
