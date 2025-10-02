# -*- coding: utf-8 -*-
__title__ = 'Edit Text Style Settings'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
clr.AddReference("System.Drawing")
clr.AddReference("PresentationFramework")

from Autodesk.Revit.DB import *
from System.Drawing import FontFamily
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow
import os

doc = revit.doc

# ---------------------------------------
# 1. Collect all TextNoteTypes
styles = list(FilteredElementCollector(doc).OfClass(TextNoteType).ToElements())
if not styles:
    forms.alert("No Text Styles found.")
    script.exit()

name_map = {}
name_list = []
for s in styles:
    name = s.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if name:
        name_map[name] = s
        name_list.append(name)

selected_name = forms.SelectFromList.show(
    sorted(name_list),
    multiselect=False,
    title="Select Text Style to Edit",
    button_name="Edit"
)

if not selected_name:
    script.exit()

style = name_map[selected_name]

# Get current values
font = style.get_Parameter(BuiltInParameter.TEXT_FONT).AsString()
size_mm = round(style.get_Parameter(BuiltInParameter.TEXT_SIZE).AsDouble() * 304.8, 2)
width_factor = round(style.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE).AsDouble(), 2)
bold = style.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD).AsInteger() == 1
italic = style.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC).AsInteger() == 1

# ---------------------------------------
# 2. Define WPF Window
class TextStyleEditor(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "TextStyleEditor.xaml")
        WPFWindow.__init__(self, xaml_path)

        # Fonts used in current model
        used_fonts = set()
        for s in styles:
            p = s.get_Parameter(BuiltInParameter.TEXT_FONT)
            if p and p.HasValue:
                used_fonts.add(p.AsString())

        # System fonts
        system_fonts = set(f.Name for f in FontFamily.Families)

        # Merge and sort
        all_fonts = sorted(system_fonts.union(used_fonts))

        self.FontCombo.ItemsSource = all_fonts
        self.FontCombo.SelectedItem = font
        self.SizeBox.Text = str(size_mm)
        self.WidthBox.Text = str(width_factor)
        self.BoldCheck.IsChecked = bold
        self.ItalicCheck.IsChecked = italic
        self.Result = None

    def OnApply(self, sender, args):
        try:
            self.Result = {
                "font": self.FontCombo.SelectedItem,
                "size": float(self.SizeBox.Text),
                "width": float(self.WidthBox.Text),
                "bold": self.BoldCheck.IsChecked,
                "italic": self.ItalicCheck.IsChecked
            }
            self.Close()
        except:
            forms.alert("Invalid number in size or width.")
            self.Result = None

    def OnCancel(self, sender, args):
        self.Result = None
        self.Close()

# ---------------------------------------
# 3. Show dialog
form = TextStyleEditor()
form.show_dialog()

if not form.Result:
    script.exit("No changes applied.")

# ---------------------------------------
# 4. Apply values
with Transaction(doc, "Edit Text Style") as tx:
    tx.Start()
    style.get_Parameter(BuiltInParameter.TEXT_FONT).Set(form.Result["font"])
    style.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(form.Result["size"] / 304.8)
    style.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE).Set(form.Result["width"])
    style.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD).Set(1 if form.Result["bold"] else 0)
    style.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC).Set(1 if form.Result["italic"] else 0)
    tx.Commit()

forms.alert("✅ Updated Text Style: {}".format(selected_name))
