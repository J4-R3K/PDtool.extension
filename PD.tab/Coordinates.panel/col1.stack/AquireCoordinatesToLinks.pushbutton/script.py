# script.py  (IronPython 2 / pyRevit)
# Acquire shared coordinates from selected Revit links into the ACTIVE (host) model.
# Cloud worksharing note: ACC/BIM 360 supports Acquire, but not Publish.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance,
    TransactWithCentralOptions, SynchronizeWithCentralOptions,
    RelinquishOptions, SaveOptions, LinkElementId,
    ModelPathUtils
)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

if doc is None:
    forms.alert("No active Revit document.", exitscript=True)

# --------------------------
# Helpers
# --------------------------
def is_cloud_workshared(rvt_doc):
    try:
        if not rvt_doc.IsWorkshared:
            return False
        mp = rvt_doc.GetWorksharingCentralModelPath()
        if mp is None:
            return False
        # Heuristic: cloud paths convert to a user-visible string starting with "Autodesk Docs://"
        vis = ModelPathUtils.ConvertModelPathToUserVisiblePath(mp)
        return vis.startswith("Autodesk Docs://")
    except:
        return False

def get_loaded_link_pairs():
    """Return list of tuples: (label, RevitLinkInstance, link_doc). Loaded only."""
    pairs = []
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            ldoc = inst.GetLinkDocument()
            if ldoc:
                label = "{} -> {}".format(inst.Name or "<Unnamed Instance>", ldoc.Title)
                pairs.append((label, inst, ldoc))
        except:
            pass
    return pairs

def select_links():
    pairs = get_loaded_link_pairs()
    if not pairs:
        forms.alert("No loaded link documents were found.\n(Ensure links are loaded and you have read access.)")
        return []
    name_map = dict((label, (inst, ldoc)) for (label, inst, ldoc) in pairs)
    picked_labels = forms.SelectFromList.show(
        sorted(name_map.keys()),
        multiselect=True,
        title="Select link(s) to ACQUIRE coordinates from",
        button_name="Acquire"
    )
    if not picked_labels:
        return []
    confirm_text = "Active host:\n  {}\n\nAcquire coordinates FROM:\n- {}\n\nThis updates the ACTIVE file's shared coordinates.".format(
        doc.Title, "\n- ".join(picked_labels)
    )
    if not forms.alert(confirm_text, yes=True, no=True, warn_icon=False):
        return []
    return [name_map[n] for n in picked_labels]

def sync_or_save_host():
    """Persist changes to the ACTIVE document."""
    try:
        if doc.IsWorkshared:
            twc = TransactWithCentralOptions()
            swc = SynchronizeWithCentralOptions()
            rel = RelinquishOptions(True)
            rel.CheckoutElements = True
            rel.FamilyWorksets   = True
            rel.StandardWorksets = True
            rel.UserWorksets     = True
            rel.ViewWorksets     = True
            swc.SetRelinquishOptions(rel)
            swc.SaveLocalAfter = False
            swc.Comment = "pyRevit: Acquire Coordinates"
            doc.SynchronizeWithCentral(twc, swc)
            return "Synchronized with Central"
        else:
            so = SaveOptions()
            so.OverwriteExistingFile = True
            doc.Save(so)
            return "Saved"
    except Exception as e:
        return "Could not persist changes: {0}".format(e)

def acquire_from_link(host_doc, link_inst, link_doc):
    """Acquire using LinkElementId (Revit 2024 signature)."""
    host_doc.AcquireCoordinates(LinkElementId(link_inst.Id))
    return "acquired via LinkElementId"

# --------------------------
# Main
# --------------------------
pairs = select_links()
if not pairs:
    script.exit()

# Heads-up: show why Publish is blocked if both models are ACC cloud-workshared
if is_cloud_workshared(doc) and any(is_cloud_workshared(ldoc) for (_, ldoc) in [p[1:] for p in pairs]):
    output.print_md("**Note:** On ACC cloud worksharing, Revit disables 'Publish Coordinates'. This tool uses **Acquire** instead (cloud-supported).")

success, failed = [], []

for (inst, link_doc) in pairs:
    try:
        how = acquire_from_link(doc, inst, link_doc)
        result = sync_or_save_host()
        success.append("{} (instance: {}) - {} - {}".format(link_doc.Title, inst.Name, how, result))
    except Exception as e:
        failed.append("{} (instance: {}) - {}".format(
            getattr(link_doc, "Title", "Unknown Link"),
            getattr(inst, "Name", "Unknown Instance"),
            e
        ))

if success:
    output.print_md("### Coordinates acquired from:")
    for msg in success:
        output.print_md("* " + msg)
if failed:
    output.print_md("\n### Skipped / Failed:")
    for msg in failed:
        output.print_md("* " + msg)

TaskDialog.Show("Acquire Coordinates", "Done.\n\nSuccess: {0}\nFailed: {1}".format(len(success), len(failed)))
