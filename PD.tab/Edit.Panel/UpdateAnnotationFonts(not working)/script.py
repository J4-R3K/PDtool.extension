# -*- coding: utf-8 -*-
__title__ = 'Edit Annotation Fonts'
__author__ = 'Jarek Wityk @ PD'

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Drawing")
clr.AddReference("PresentationFramework")

from Autodesk.Revit.DB import *
from System.Drawing import FontFamily
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow
import os

uidoc = revit.uidoc
doc = revit.doc
app = uidoc.Application.Application  # ✅ despite nesting, this works for pushbuttons in pyRevit 5.1
output = script.get_output()


# ----------------------------------------------------
# Function to test if a family can be edited
def is_family_editable(fam):
    try:
        test_doc = app.EditFamily(fam)
        if test_doc:
            test_doc.Close(False)
            return True
    except:
        return False
    return False

# ----------------------------------------------------
# 1️⃣ Collect All Annotation Families (Incl. MEP Tags)

tag_cats = [
    BuiltInCategory.OST_GenericAnnotation,
    BuiltInCategory.OST_RoomTags,
    BuiltInCategory.OST_DoorTags,
    BuiltInCategory.OST_WindowTags,
    BuiltInCategory.OST_SectionHeads,
    BuiltInCategory.OST_ElevationMarks,
    BuiltInCategory.OST_LevelHeads,
    BuiltInCategory.OST_ReferenceViewer,
    BuiltInCategory.OST_SpotElevations,
    BuiltInCategory.OST_SpotSlopes,
    BuiltInCategory.OST_SpotCoordinates,
    BuiltInCategory.OST_MultiCategoryTags,
    BuiltInCategory.OST_MaterialTags,
    BuiltInCategory.OST_KeynoteTags,

    # MEP Tag Categories
    BuiltInCategory.OST_CableTrayTags,
    BuiltInCategory.OST_ConduitTags,
    BuiltInCategory.OST_DuctTags,
    BuiltInCategory.OST_PipeTags,
    BuiltInCategory.OST_ElectricalEquipmentTags,
    BuiltInCategory.OST_ElectricalFixtureTags,
    BuiltInCategory.OST_LightingDeviceTags,
    BuiltInCategory.OST_LightingFixtureTags,
    BuiltInCategory.OST_MechanicalEquipmentTags,
    BuiltInCategory.OST_PlumbingFixtureTags,
    BuiltInCategory.OST_SpecialityEquipmentTags,
    BuiltInCategory.OST_SprinklerTags,
    BuiltInCategory.OST_DataDeviceTags,
    BuiltInCategory.OST_FireAlarmDeviceTags,
    BuiltInCategory.OST_TelephoneDeviceTags,
    BuiltInCategory.OST_SecurityDeviceTags,
]

symbol_ids = set()
for bic in tag_cats:
    collector = FilteredElementCollector(doc).OfCategory(bic).OfClass(FamilySymbol)
    symbol_ids.update([fs.Family.Id for fs in collector if fs and fs.Family])

families = [doc.GetElement(fid) for fid in symbol_ids if doc.GetElement(fid)]
families = sorted(families, key=lambda f: f.Name)

if not families:
    forms.alert("No annotation symbol families found.")
    script.exit()

fam_names = [f.Name for f in families]
output.print_md("## ✏️ Found {} annotation families:".format(len(fam_names)))
for name in fam_names:
    output.print_md("* {}".format(name))

selected = forms.SelectFromList.show(
    fam_names,
    multiselect=True,
    title="Select Annotation Families to Update",
    button_name="Next"
)

if not selected:
    script.exit("Nothing selected.")

selected_fams = [f for f in families if f.Name in selected]

# ----------------------------------------------------
# Filter only editable families
editable_fams = selected_fams
output.print_md("### 🔧 Will attempt to edit:")
for f in editable_fams:
    output.print_md("* {}".format(f.Name))


# ----------------------------------------------------
# 2️⃣ WPF Font Style Editor

class TextStyleEditor(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "TextStyleEditor.xaml")
        WPFWindow.__init__(self, xaml_path)

        # Fonts used in current model
        used_fonts = set()
        all_text_types = FilteredElementCollector(doc).OfClass(TextNoteType).ToElements()
        for s in all_text_types:
            p = s.get_Parameter(BuiltInParameter.TEXT_FONT)
            if p and p.HasValue:
                used_fonts.add(p.AsString())

        # System fonts
        system_fonts = set()
        try:
            system_fonts = set(f.Name for f in FontFamily.Families)
        except:
            pass

        all_fonts = sorted(system_fonts.union(used_fonts))
        if "IBM Plex Mono" not in all_fonts:
            all_fonts.append("IBM Plex Mono")

        self.FontCombo.ItemsSource = sorted(set(all_fonts))
        self.FontCombo.SelectedItem = "Arial"
        self.SizeBox.Text = "2.5"
        self.WidthBox.Text = "1.0"
        self.BoldCheck.IsChecked = False
        self.ItalicCheck.IsChecked = False
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

# Show WPF editor
form = TextStyleEditor()
form.show_dialog()

if not form.Result:
    script.exit("No changes applied.")

# ----------------------------------------------------
# 3️⃣ Apply Style to All Editable Families

pt_to_ft = form.Result["size"] / 304.8
style_str = ""
if form.Result["bold"]:
    style_str += "Bold"
if form.Result["italic"]:
    style_str += " Italic"
style_str = style_str.strip()

output.print_md("### 🔧 Applying to:")
for f in editable_fams:
    output.print_md("* {}".format(f.Name))

updated, skipped = [], []

for fam in editable_fams:
    try:
        fam_doc = app.EditFamily(fam)
        text_types = FilteredElementCollector(fam_doc).OfClass(TextNoteType).ToElements()

        if not text_types:
            skipped.append(fam.Name + " — no TextNoteTypes found")
            fam_doc.Close(False)
            continue

        with Transaction(fam_doc, "Update Text Styles") as t:
            t.Start()
            for tnt in text_types:
                if form.Result["font"]:
                    tnt.get_Parameter(BuiltInParameter.TEXT_FONT).Set(form.Result["font"])
                tnt.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(pt_to_ft)
                tnt.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE).Set(form.Result["width"])
                if style_str:
                    tnt.get_Parameter(BuiltInParameter.TEXT_STYLE).Set(style_str)
            t.Commit()

        fam_doc.LoadFamily(doc, None)
        fam_doc.Close(False)
        updated.append(fam.Name)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        skipped.append(fam.Name + " — Failed to edit. Details:\n" + tb)


# ----------------------------------------------------
# 4️⃣ Summary
if updated:
    output.print_md("### ✅ Updated:")
    for n in updated:
        output.print_md("* {}".format(n))

if skipped:
    output.print_md("### ⚠️ Skipped:")
    for n in skipped:
        output.print_md("* {}".format(n))

forms.alert("Done! Updated {} families.".format(len(updated)))
