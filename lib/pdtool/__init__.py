# -*- coding: utf-8 -*-
"""PDtool shared library (started 08/10/2026).

pyRevit puts this extension's lib folder on the search path of every PDtool button, so a button imports:

    from pdtool.transaction import run, transaction, transaction_group
    from pdtool.worksharing import keep_editable

Write everything here to run under IronPython 2.7 and CPython 3: .format() not f-strings, `except Exception as ex`.

transaction  - PD failure handling for every change: warnings are cleared and listed, any error rolls the change
               back with Revit's own reason, and no dialog appears (pattern from Gavin Crump's BimGo, RevitEditor).
worksharing  - finds elements another user has borrowed (or that changed in the central model) before a change,
               then asks: go on with the rest, go on and list the others, or stop (pattern from guRoo_Py shareUtils).

Diagnostics > "PDtool Library Test" checks both in the open model and changes nothing.
"""


def id_value(element_id):
    """The number of an ElementId in every Revit year: Value from 2024 (IntegerValue was REMOVED in Revit 2026, checked
    against the installed RevitAPI.dll on 09/10/2026), IntegerValue up to 2023. Returned as a plain Python int, as
    IntegerValue was, so ids still format, compare, hash and JSON-encode exactly as before (Value is a .NET Int64)."""
    try:
        return int(element_id.Value)
    except AttributeError:
        return element_id.IntegerValue
