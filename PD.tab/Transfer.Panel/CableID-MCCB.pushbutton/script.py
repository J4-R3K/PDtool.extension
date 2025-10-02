# -*- coding: utf-8 -*-
__title__ = 'Copy Device ➜ Cable'
__author__ = 'pyRevit Script Generator'

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, forms, script

# Revit context
uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()

# Parameter names to copy
PARAMS_TO_COPY = [
    ("PD_DATe_DeviceType1", False),  # Type param
    ("PD_DATe_FrameRating1", True),
    ("PD_DATe_TripRating1", True),
    ("PD_DATe_TripSetting1", True),
    ("PD_DATe_NoOfPolesINT1", True)
]


def get_element_and_family_name(ref):
    el = doc.GetElement(ref.ElementId)
    if el is None:
        return None, None
    symbol = el.Symbol if hasattr(el, "Symbol") else None
    fam_name = symbol.FamilyName if symbol else None
    return el, fam_name


def match_family(name, keyword):
    return keyword in name if name else False


def copy_parameters(source, target):
    symbol = source.Symbol
    copied = []

    for param_name, is_instance in PARAMS_TO_COPY:
        # Pick from instance or type
        src_param = source.LookupParameter(param_name) if is_instance else symbol.LookupParameter(param_name)
        tgt_param = target.LookupParameter(param_name)

        if src_param and tgt_param and src_param.HasValue:
            try:
                tgt_param.Set(
                    src_param.AsValueString() if src_param.StorageType != StorageType.Integer else src_param.AsInteger())
                copied.append(param_name)
            except Exception as e:
                output.print_md("*⚠️ Could not set `{}` – {}*".format(param_name, str(e)))
        else:
            output.print_md("*Skipping `{}` – missing on source or target*".format(param_name))

    return copied


def main_loop():
    output.print_md("## 🔁 Cable Copier Started")
    output.print_md("_Use ESC to cancel at any time_")

    while True:
        try:
            # Pick CableID target
            ref1 = uidoc.Selection.PickObject(ObjectType.Element, "Select CableID element (target)")
            target, name1 = get_element_and_family_name(ref1)

            if not match_family(name1, "PD_DET_SC_CableID"):
                forms.alert("Selected element is not from a CableID family.", exitscript=False)
                continue

            output.print_md("✅ Selected **CableID**: `{}`".format(name1))

            # Pick ProtectiveDevice source
            ref2 = uidoc.Selection.PickObject(ObjectType.Element, "Select ProtectiveDevice element (source)")
            source, name2 = get_element_and_family_name(ref2)

            if not match_family(name2, "PD_DET_SC_ProtectiveDevice"):
                forms.alert("Selected element is not from a ProtectiveDevice family.", exitscript=False)
                continue

            output.print_md("✅ Selected **ProtectiveDevice**: `{}`".format(name2))

            with revit.Transaction("Copy PD Parameters"):
                copied = copy_parameters(source, target)

            if copied:
                output.print_md("✔️ Copied parameters: `{}`".format(", ".join(copied)))
            else:
                output.print_md("⚠️ No parameters copied.")

            # Ask to continue
            cont = forms.alert("Copy complete. Continue?", options=["Yes", "No"])
            if cont == "No":
                output.print_md("✅ Finished copying. Exiting script.")
                break

        except Exception as e:
            output.print_md("🚫 Script cancelled or failed: `{}`".format(str(e)))
            break


main_loop()
