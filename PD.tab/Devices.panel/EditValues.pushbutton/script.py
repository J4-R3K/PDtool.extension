# -*- coding: utf-8 -*-
"""Edit Values: change one parameter on many elements at once, checked before it is written. The window is in
lib/pdtool/editvalues; the value changes and checks are in lib/pdtool/values.py."""
from pyrevit import forms, revit, script

from pdtool.editvalues import window

doc = revit.doc
forms.check_modeldoc(doc, exitscript=True)
window.EditValuesWindow(script.get_bundle_file("EditValues.xaml"), doc, revit.uidoc).show_dialog()
