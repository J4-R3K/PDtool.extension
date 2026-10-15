# -*- coding: utf-8 -*-
"""PD Schedules (started 15/10/2026).

The PD Schedules button (PD tab, Export panel) exports Revit schedules and panel schedules to Excel workbooks,
replacing DiRoots SheetLink and PanelLink for export. It reads what Revit displays and changes nothing in the model.
The logic that can be proved outside Revit is kept apart from the parts that need Revit, so
`C:/Dev/pyRevit/pdtool-lib-tests/test_schedx.py` runs it under CPython 3 and both IronPython engines pyRevit uses
(2.7.12 in Revit 2023 and 2024, 3.4.2 in Revit 2025 and later): .format(), no f-strings.

Tested outside Revit:
xlsx      - PD's own small xlsx writer (no Excel needed): text, numbers, styles, merged cells, widths, frozen panes,
            print setup, links between sheets. Never writes a formula.
names     - sheet names by Excel's rules, and file names.
grid      - a schedule or a panel schedule laid out as it reads in Revit; which text becomes an Excel number.
dbchart   - a panel schedule laid out as a PD DB chart (pd-db-chart-audit references/rules.md, PD's standard layout).
book      - the workbook: the Contents sheet, then the sheets.

Need Revit (checked in Revit 2024 on a project model, read only):
revitread - lists the schedules and panel schedules, and reads their cells, the board and its circuits.
window    - the PD Schedules window (layout in the button's PDSchedules.xaml).

Plan: C:/Dev/PD-Revit-ScheduleExcel-PLAN-2026-10-15.md (approved by Jarek on 15/10/2026, with choices C1 to C6 as
recommended). Handover: C:/Dev/PD-Revit-ScheduleExcel-HANDOFF.md.
"""
