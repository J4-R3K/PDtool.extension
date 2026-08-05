# -*- coding: utf-8 -*-
__title__   = "WireTag:: Create Home Run & Tag"
__doc__     = """Version = 1.2
Date    = 26.07.2026
________________________________________________________________
Description:

Pick element with electrical connector -> create short wire stub connected to connector.
Direction is automatic (family-aligned isometric): Facing + Hand (45deg diagonal in plan),
projected to the view plane.

Stub length is automatic: 10mm (with internal fallbacks if Revit rejects too-short wires).

Tag is placed with a Leader and Leader End Condition set to Free, with leader end
snapped to the free end of the wire stub.

v1.2: Multi-circuit support. If the element has two (or more) electrical connectors
assigned to DIFFERENT circuits, a wire stub + tag is created for EACH circuit.
Each additional stub is rotated 90deg in the view plane so wires/tags do not overlap.

Author: Jarek Wityk
"""

# pylint: disable=import-error,invalid-name,broad-except,superfluous-parens
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import math

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Electrical import Wire, WireType, WiringType, ElectricalSystem
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


def get_electrical_connectors(fi):
    """Return ALL electrical connectors found on FamilyInstance."""
    result = []
    try:
        mep = getattr(fi, "MEPModel", None)
        if not mep:
            return result
        cm = getattr(mep, "ConnectorManager", None)
        if not cm:
            return result
        for c in cm.Connectors:
            try:
                if c.Domain == Domain.DomainElectrical:
                    result.append(c)
            except:
                pass
    except:
        pass
    return result


def get_connector_circuit(conn):
    """Return the ElectricalSystem (circuit) this connector belongs to, or None."""
    try:
        for ref in conn.AllRefs:
            try:
                owner = ref.Owner
                if isinstance(owner, ElectricalSystem):
                    return owner
            except:
                pass
    except:
        pass
    return None


def pick_connectors_for_stubs(fi):
    """
    One connector per DISTINCT circuit.
    - Connectors assigned to different circuits -> one stub+tag each.
    - Two connectors on the SAME circuit -> only the first is used.
    - No circuited connectors at all -> fall back to the first electrical
      connector (previous single-connector behaviour).
    Returns list of (connector, circuit_or_None).
    """
    conns = get_electrical_connectors(fi)
    circuited = []
    seen_ids = set()
    for c in conns:
        sysel = get_connector_circuit(c)
        if sysel is None:
            continue
        try:
            cid = sysel.Id.IntegerValue
        except:
            cid = None
        if cid is not None and cid in seen_ids:
            continue
        if cid is not None:
            seen_ids.add(cid)
        circuited.append((c, sysel))
    if circuited:
        return circuited
    if conns:
        return [(conns[0], None)]
    return []


def circuit_label(sysel):
    """Readable Panel/CircuitNumber label for reporting."""
    if sysel is None:
        return "no circuit"
    pnl = None
    num = None
    try:
        pnl = sysel.PanelName
    except:
        pass
    try:
        num = sysel.CircuitNumber
    except:
        pass
    if pnl or num:
        return "{}/{}".format(pnl or "?", num or "?")
    try:
        return sysel.Name
    except:
        return "circuit"


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


def rotate_in_view_plane(vec, vdir, angle_rad):
    """Rotate vec about the view direction (keeps it in the view plane)."""
    try:
        cosv = math.cos(angle_rad)
        sinv = math.sin(angle_rad)
        rotated = vec.Multiply(cosv) + vdir.CrossProduct(vec).Multiply(sinv)
        return normalize_xyz(rotated)
    except:
        return None


def direction_for_index(base_dir, vdir, idx):
    """First circuit keeps the base direction; each next one is rotated 90deg."""
    if idx == 0 or vdir is None:
        return base_dir
    rot = rotate_in_view_plane(base_dir, vdir, (math.pi / 2.0) * idx)
    return rot if rot else base_dir


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

conn_pairs = pick_connectors_for_stubs(el)
if not conn_pairs:
    forms.alert("No electrical connector found on this element.", exitscript=True)

wire_type = find_first_wire_type()
if wire_type is None:
    forms.alert("No Wire Types found in this project. Load/define a Wire Type first.", exitscript=True)

level_id = get_level_id_for(el)
if level_id == ElementId.InvalidElementId:
    forms.alert("Could not determine a valid Level for wire creation.", exitscript=True)

# Lengths: try 10mm first, then fallbacks
try_lengths_ft = [mm_to_ft(STUB_LEN_MM)] + [mm_to_ft(x) for x in FALLBACK_MM]

v_dir = normalize_xyz(view.ViewDirection)


# ----------------------------
# Create wire + set param + tag leader (one set per circuit)
# ----------------------------
results = []          # per-circuit report lines
param_set_on = None
any_wire = False

t = Transaction(doc, "WireTag: Add Wire + Tag (Auto)")
t.Start()
try:
    # --- Tag setup (once) ---
    tag_sym = find_tag_type(TAG_FAMILY_NAME, TAG_TYPE_NAME)
    if tag_sym and (not tag_sym.IsActive):
        tag_sym.Activate()
        doc.Regenerate()

    for idx, (conn, sysel) in enumerate(conn_pairs):
        label = circuit_label(sysel)

        try:
            start_pt = conn.Origin
        except:
            results.append("{}: SKIPPED (could not read connector origin)".format(label))
            continue

        base_dir = get_family_isometric_direction(el, conn, view)
        if not base_dir:
            results.append("{}: SKIPPED (no valid automatic direction)".format(label))
            continue
        direction_vec = direction_for_index(base_dir, v_dir, idx)

        # --- Create wire (try short first, then fallback) ---
        created_wire = None
        end_pt_used = None
        used_len_mm = None
        last_err = None
        for li, L in enumerate(try_lengths_ft):
            end_pt = start_pt + direction_vec.Multiply(L)

            pts = List[XYZ]()
            pts.Add(start_pt)
            pts.Add(end_pt)

            try:
                created_wire = Wire.Create(doc, wire_type.Id, view.Id, WiringType.Arc, pts, conn, None)
                if created_wire:
                    used_len_mm = STUB_LEN_MM if li == 0 else FALLBACK_MM[li - 1]
                    end_pt_used = end_pt
                    break
            except Exception as e:
                last_err = e
                created_wire = None

        if not created_wire:
            results.append("{}: wire FAILED ({})".format(label, last_err))
            continue

        any_wire = True

        # --- Set parameter (wire first, then element) ---
        if set_param_text(created_wire, PARAM_NAME, PARAM_VALUE):
            param_set_on = "wire"
        elif set_param_text(el, PARAM_NAME, PARAM_VALUE):
            param_set_on = "element"

        # Determine tag head point (slightly offset from wire midpoint)
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
        created_tag = None
        tag_note = ""

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
            try:
                created_tag.LeaderEndCondition = LeaderEndCondition.Free
            except:
                pass

            try:
                if end_pt_used:
                    created_tag.SetLeaderEnd(wref, end_pt_used)
            except:
                pass

        except Exception as ex_tag:
            created_tag = None
            tag_note = "{}".format(ex_tag)

        if created_tag:
            results.append("{}: wire {} mm + tag OK".format(label, float(used_len_mm)))
        else:
            results.append("{}: wire {} mm OK, tag FAILED ({})".format(label, float(used_len_mm), tag_note))

    if not any_wire:
        raise Exception("No wire could be created on any connector:\n" + "\n".join(results))

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
msg.append("Circuits found on element: {}".format(len(conn_pairs)))
msg.append("Direction: Auto (Family isometric: Facing + Hand; +90deg per extra circuit)")
for line in results:
    msg.append("  - {}".format(line))
msg.append("{} set on: {}".format(PARAM_NAME, param_set_on if param_set_on else "NOT SET"))
msg.append("")
msg.append("*Leader free-end behavior depends on tag/category support in your Revit version.")
forms.alert("\n".join(msg))
