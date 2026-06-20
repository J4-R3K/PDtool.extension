# script.py  (IronPython 2 / pyRevit)
# Reset Link Residual Transform (Report + Optional Fix) - ASCII only

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance, Transaction,
    ElementTransformUtils, XYZ, Line
)
from Autodesk.Revit.UI import TaskDialog
from math import atan2
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

if doc is None:
    forms.alert("No active Revit document.", exitscript=True)

# --------------------------
# Helpers
# --------------------------
def get_links(rdoc):
    links = []
    for inst in FilteredElementCollector(rdoc).OfClass(RevitLinkInstance):
        try:
            ldoc = inst.GetLinkDocument()
            if ldoc:
                links.append((inst, ldoc))
        except:
            pass
    return links

def select_links():
    pairs = get_links(doc)
    if not pairs:
        forms.alert("No loaded Revit links found.", exitscript=True)
    label_map = {}
    labels = []
    for inst, ldoc in pairs:
        label = "{} -> {}".format(inst.Name or "<Instance>", ldoc.Title)
        label_map[label] = (inst, ldoc)
        labels.append(label)
    picked = forms.SelectFromList.show(sorted(labels), multiselect=True, title="Select link instance(s)")
    if not picked:
        script.exit()
    return [label_map[x] for x in picked]

def z_rotation_from_basisX(bx):
    # angle of basisX in XY plane relative to +X (radians)
    return atan2(bx.Y, bx.X)

def report_instance(inst, ldoc):
    tf = inst.GetTotalTransform()  # Transform from link to host
    angle_rad = z_rotation_from_basisX(tf.BasisX)
    angle_deg = angle_rad * 180.0 / 3.141592653589793
    tx, ty, tz = tf.Origin.X, tf.Origin.Y, tf.Origin.Z
    info = {
        "title": ldoc.Title,
        "inst": inst,
        "angle_deg": angle_deg,
        "tx": tx, "ty": ty, "tz": tz
    }
    return info

def pretty_list(infos):
    lines = []
    ft_to_mm = 304.8
    for i in infos:
        lines.append(
            "* {} (instance: {})\n  - rotation about Z: {:.6f} deg\n  - E/W (X): {:.3f} mm\n  - N/S (Y): {:.3f} mm\n  - Elev (Z): {:.3f} mm".format(
                i["title"], i["inst"].Name,
                i["angle_deg"],
                i["tx"]*ft_to_mm, i["ty"]*ft_to_mm, i["tz"]*ft_to_mm
            )
        )
    return "\n".join(lines)

def inverse_transform(inst):
    """
    Build and apply the inverse of the instance's current transform.
    WARNING: This zeros the instance relative to host origin, not necessarily to shared coordinates.
    """
    tf = inst.GetTotalTransform()
    inv = tf.Inverse

    # Derive rotation about Z from inv.BasisX
    angle_rad = z_rotation_from_basisX(inv.BasisX)

    # Rotation axis: global Z through host origin (0,0,0)
    axis = Line.CreateBound(XYZ(0,0,0), XYZ(0,0,1))

    # Apply inside a transaction: rotate then move
    with Transaction(doc, "Reset Link Instance Transform (Inverse)") as t:
        t.Start()
        try:
            if abs(angle_rad) > 1e-10:
                ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle_rad)
            # Move by inverse translation
            move_vec = inv.Origin
            if move_vec.GetLength() > 1e-10:
                ElementTransformUtils.MoveElement(doc, inst.Id, move_vec)
            t.Commit()
            return True, "Applied inverse rotation/translation"
        except Exception as e:
            t.RollBack()
            return False, str(e)

# --------------------------
# Main
# --------------------------
pairs = select_links()
infos = [report_instance(inst, ldoc) for (inst, ldoc) in pairs]

# 1) Report
output.print_md("### Current residual transforms (before reset)")
output.print_md(pretty_list(infos))

# 2) Ask if we should zero the residual transform
do_fix = forms.alert(
    "Apply inverse rotation/translation to zero the instance transform?\n\n"
    "Only do this if the link is intended to be placed By Shared Coordinates.\n"
    "Otherwise, cancel and use the UI Reset Position button.",
    yes=True, no=True, warn_icon=True
)

if not do_fix:
    TaskDialog.Show("Reset Transform", "No changes made.")
    script.exit()

# 3) Apply inverse per selection
success, failed = [], []
for (inst, ldoc) in pairs:
    ok, msg = inverse_transform(inst)
    if ok:
        success.append("{} (instance: {}) - {}".format(ldoc.Title, inst.Name, msg))
    else:
        failed.append("{} (instance: {}) - {}".format(ldoc.Title, inst.Name, msg))

# 4) Report after
if success:
    output.print_md("### Reset applied:")
    for s in success:
        output.print_md("* " + s)
if failed:
    output.print_md("\n### Skipped / Failed:")
    for f in failed:
        output.print_md("* " + f)

TaskDialog.Show("Reset Transform", "Done.\n\nSuccess: {0}\nFailed: {1}".format(len(success), len(failed)))
