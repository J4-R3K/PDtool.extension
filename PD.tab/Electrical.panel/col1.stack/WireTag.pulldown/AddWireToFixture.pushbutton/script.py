# -*- coding: utf-8 -*-
__title__   = "WireTag:: Create Home Run & Tag"
__doc__     = """Version = 1.1
Date    = 20.12.2025
________________________________________________________________
Description:

Pick element with electrical connector -> create short wire stub connected to connector.
Direction is automatic (family-aligned isometric): Facing + Hand (45deg diagonal in plan),
projected to the view plane.

Stub length is automatic: 10mm (with internal fallbacks if Revit rejects too-short wires).

Tag is placed with a Leader and Leader End Condition set to Free, with leader end
snapped to the free end of the wire stub.

Author: Jarek Wityk
"""

# pylint: disable=import-error,invalid-name,broad-except,superfluous-parens
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Electrical import Wire, WireType, WiringType
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
from pyrevit import revit, forms


uidoc = revit.uidoc
doc = revit.doc


# ----------------------------
# Settings (easy to tweak)
# ----------------------------
STUB_LEN_MM = 10.0                   # requested default
FALLBACK_MM = [25.0, 50.0, 100.0, 150.0, 250.0]   # reliability fallbacks
PARAM_NAME = "PD_DATe_WireType"
PARAM_VALUE = "STD-A"

TAG_FAMILY_NAME = "PD_TAG_Wire_2.5mm_CircuitReference"
TAG_TYPE_NAME = "BorderOFF"
TAG_HEAD_OFFSET_MM = 6.0             # small offset from wire so tag head doesn't sit on the line


# ----------------------------
# Helpers
# ----------------------------
def mm_to_ft(mm):
    return float(mm) / 304.8


def is_plan_or_rcp(view):
    try:
        return view.ViewType in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan]
    except:
        return False


def normalize_xyz(v):
    try:
        if v is None:
            return None
        if v.GetLength() < 1e-9:
            return None
        return v.Normalize()
    except:
        return None


def project_to_view_plane(vec, view_dir):
    """Remove component along view direction so direction stays in the view plane."""
    try:
        vd = normalize_xyz(view_dir)
        if not vd:
            return vec
        dot = vec.DotProduct(vd)
        return vec - (vd.Multiply(dot))
    except:
        return vec


def get_electrical_connector(fi):
    """Return first electrical connector found on FamilyInstance."""
    try:
        mep = getattr(fi, "MEPModel", None)
        if not mep:
            return None
        cm = getattr(mep, "ConnectorManager", None)
        if not cm:
            return None
        for c in cm.Connectors:
            try:
                if c.Domain == Domain.DomainElectrical:
                    return c
            except:
                pass
    except:
        pass
    return None


def get_level_id_for(fi):
    """Pick a valid level id for wire creation (element's LevelId -> view GenLevel -> first project level)."""
    try:
        if fi.LevelId and fi.LevelId.IntegerValue > 0:
            return fi.LevelId
    except:
        pass

    v = doc.ActiveView
    try:
        if v and v.GenLevel:
            return v.GenLevel.Id
    except:
        pass

    lvl = FilteredElementCollector(doc).OfClass(Level).FirstElement()
    return lvl.Id if lvl else ElementId.InvalidElementId


def find_first_wire_type():
    wts = list(FilteredElementCollector(doc).OfClass(WireType))
    if not wts:
        return None
    return wts[0]


def set_param_text(el, param_name, value_text):
    try:
        p = el.LookupParameter(param_name)
    except:
        p = None
    if p and (not p.IsReadOnly):
        try:
            p.Set(value_text)
            return True
        except:
            return False
    return False


def find_tag_type(family_name, type_name):
    syms = FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements()
    for s in syms:
        try:
            fam = s.Family
            if fam and fam.Name == family_name and s.Name == type_name:
                return s
        except:
            pass
    return None


def get_family_isometric_direction(fi, conn, view):
    """
    'Isometric to front' but aligned to family:
    direction = normalize(FacingOrientation + HandOrientation)
    projected to view plane.

    Fallbacks:
      - FacingOrientation alone
      - HandOrientation alone
      - Connector CS basis vectors
      - View.RightDirection
    """
    vdir = normalize_xyz(view.ViewDirection)

    # 1) Family-based vectors
    facing = None
    hand = None
    try:
        facing = normalize_xyz(project_to_view_plane(fi.FacingOrientation, vdir))
    except:
        facing = None
    try:
        hand = normalize_xyz(project_to_view_plane(fi.HandOrientation, vdir))
    except:
        hand = None

    # Prefer diagonal (facing + hand) if possible
    if facing and hand:
        diag = normalize_xyz(project_to_view_plane(facing + hand, vdir))
        if diag:
            return diag

    if facing:
        return facing
    if hand:
        return hand

    # 2) Connector coordinate system fallback
    try:
        cs = conn.CoordinateSystem
        # Try BasisX then BasisY then BasisZ, projected to view plane
        for basis in [cs.BasisX, cs.BasisY, cs.BasisZ]:
            cand = normalize_xyz(project_to_view_plane(basis, vdir))
            if cand:
                return cand
    except:
        pass

    # 3) View fallback
    try:
        return normalize_xyz(project_to_view_plane(view.RightDirection, vdir))
    except:
        return None


# ----------------------------
# Preconditions
# ----------------------------
view = doc.ActiveView
if not is_plan_or_rcp(view):
    forms.alert("Active view must be a Floor Plan / RCP (Ceiling Plan) to create wires.",
                exitscript=True)

# ----------------------------
# Pick element
# ----------------------------
try:
    r = uidoc.Selection.PickObject(ObjectType.Element, "Pick an element with an electrical connector")
    el = doc.GetElement(r.ElementId)
except:
    forms.alert("Nothing selected. Cancelled.", exitscript=True)

if not isinstance(el, FamilyInstance):
    forms.alert("Please pick a Family Instance (fixture/device).", exitscript=True)

conn = get_electrical_connector(el)
if conn is None:
    forms.alert("No electrical connector found on this element.", exitscript=True)

try:
    start_pt = conn.Origin
except:
    forms.alert("Could not read connector origin point.", exitscript=True)

wire_type = find_first_wire_type()
if wire_type is None:
    forms.alert("No Wire Types found in this project. Load/define a Wire Type first.", exitscript=True)

level_id = get_level_id_for(el)
if level_id == ElementId.InvalidElementId:
    forms.alert("Could not determine a valid Level for wire creation.", exitscript=True)

# Automatic direction (family-aligned)
direction_vec = get_family_isometric_direction(el, conn, view)
if not direction_vec:
    forms.alert("Could not determine a valid automatic direction.", exitscript=True)

# Lengths: try 10mm first, then fallbacks
try_lengths_ft = [mm_to_ft(STUB_LEN_MM)] + [mm_to_ft(x) for x in FALLBACK_MM]

v_dir = normalize_xyz(view.ViewDirection)


# ----------------------------
# Create wire + set param + tag leader
# ----------------------------
created_wire = None
created_tag = None
param_set_on = None
tag_note = ""
used_len_mm = None
end_pt_used = None

t = Transaction(doc, "WireTag: Add Wire + Tag (Auto)")
t.Start()
try:
    # --- Create wire (try short first, then fallback) ---
    last_err = None
    for idx, L in enumerate(try_lengths_ft):
        end_pt = start_pt + direction_vec.Multiply(L)

        pts = List[XYZ]()
        pts.Add(start_pt)
        pts.Add(end_pt)

        try:
            created_wire = Wire.Create(doc, wire_type.Id, view.Id, WiringType.Arc, pts, conn, None)
            if created_wire:
                # record used length in mm
                if idx == 0:
                    used_len_mm = STUB_LEN_MM
                else:
                    used_len_mm = FALLBACK_MM[idx - 1]
                end_pt_used = end_pt
                break
        except Exception as e:
            last_err = e
            created_wire = None

    if not created_wire:
        raise Exception("Wire creation failed. Last error: {}".format(last_err))

    # --- Set parameter (wire first, then element) ---
    if set_param_text(created_wire, PARAM_NAME, PARAM_VALUE):
        param_set_on = "wire"
    elif set_param_text(el, PARAM_NAME, PARAM_VALUE):
        param_set_on = "element"
    else:
        param_set_on = None

    # --- Tag setup ---
    tag_sym = find_tag_type(TAG_FAMILY_NAME, TAG_TYPE_NAME)
    if tag_sym and (not tag_sym.IsActive):
        tag_sym.Activate()
        doc.Regenerate()

    # Determine tag head point (slightly offset from wire midpoint)
    # Midpoint of the wire curve if available
    mid_pt = None
    try:
        loc_curve = created_wire.Location
        if isinstance(loc_curve, LocationCurve) and loc_curve.Curve:
            mid_pt = loc_curve.Curve.Evaluate(0.5, True)
    except:
        mid_pt = None
    if mid_pt is None:
        mid_pt = start_pt

    # Perpendicular offset in view plane (to avoid tag on top of wire)
    offset_vec = None
    try:
        # perpendicular to direction, in view plane
        # cross product gives a vector perpendicular to direction and view direction
        offset_vec = normalize_xyz(direction_vec.CrossProduct(v_dir))
    except:
        offset_vec = None

    tag_head_pt = mid_pt
    if offset_vec:
        tag_head_pt = mid_pt + offset_vec.Multiply(mm_to_ft(TAG_HEAD_OFFSET_MM))

    # Create the tag. NOTE:
    # IndependentTag.Create(..., addLeader=True, ..., pnt) -> 'pnt' is the LEADER END point for tags with leaders.
    # We'll pass the free end of the stub as initial leader end point, then set LeaderEndCondition to Free and
    # explicitly SetLeaderEnd to ensure it sticks.
    wref = Reference(created_wire)

    try:
        created_tag = IndependentTag.Create(
            doc,
            view.Id,
            wref,
            True,  # addLeader
            TagMode.TM_ADDBY_CATEGORY,
            TagOrientation.Horizontal,
            end_pt_used if end_pt_used else mid_pt  # leader end point
        )

        if created_tag and tag_sym:
            created_tag.ChangeTypeId(tag_sym.Id)

        # Move tag head where we want it
        try:
            created_tag.TagHeadPosition = tag_head_pt
        except:
            pass

        # Force leader to "Free End" (if supported), then set leader end at wire free end
        # This uses the newer API style (LeaderEnd property is obsolete/removed in newer versions).
        try:
            created_tag.LeaderEndCondition = LeaderEndCondition.Free
        except:
            pass

        # Set leader end point (works when leader end condition is Free)
        try:
            if end_pt_used:
                created_tag.SetLeaderEnd(wref, end_pt_used)
        except:
            # If API/version doesn't support this for this tag type, ignore
            pass

    except Exception as ex_tag:
        created_tag = None
        tag_note = "Could not place/configure wire tag leader: {}".format(ex_tag)

    t.Commit()

except Exception as e:
    try:
        t.RollBack()
    except:
        pass
    forms.alert("Failed:\n{}".format(e), exitscript=True)


# ----------------------------
# Report
# ----------------------------
msg = []
msg.append("Wire created: YES")
msg.append("Direction: Auto (Family isometric: Facing + Hand)")
if used_len_mm is not None:
    msg.append("Stub length used: {} mm".format(float(used_len_mm)))
else:
    msg.append("Stub length used: unknown")
msg.append("{} set on: {}".format(PARAM_NAME, param_set_on if param_set_on else "NOT SET"))
if created_tag:
    msg.append("Tag placed: YES (Leader: ON, End: Free*)")
else:
    msg.append("Tag placed: NO ({})".format(tag_note or "unknown"))

msg.append("")
msg.append("*Leader free-end behavior depends on tag/category support in your Revit version.")
forms.alert("\n".join(msg))
