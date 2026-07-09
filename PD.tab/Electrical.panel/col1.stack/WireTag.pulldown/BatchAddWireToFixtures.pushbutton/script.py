# -*- coding: utf-8 -*-
__title__   = "WireTag:: Batch Home Run & Tag"
__doc__     = """Version = 1.1
Date    = 20.12.2025
________________________________________________________________
Description:

Batch version:
Select multiple fixtures/devices -> create short wire stub + place a tag for EACH item.

Improvements vs previous batch:
- Explicitly sets TagHeadPosition per element (prevents tags appearing far away)
- Tag head placed directly "in front" of each item (along stub direction)
- Leader ON + LeaderEndCondition Free (best effort) + leader end snapped to stub end

Author: Jarek Wityk
"""

# pylint: disable=import-error,invalid-name,broad-except,superfluous-parens
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Electrical import Wire, WireType, WiringType
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from System.Collections.Generic import List
from pyrevit import revit, forms, script


uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()


# ----------------------------
# Settings (tweak here)
# ----------------------------
STUB_LEN_MM = 10.0
FALLBACK_MM = [25.0, 50.0, 100.0, 150.0, 250.0]

PARAM_NAME = "PD_DATe_WireType"
PARAM_VALUE = "STD-A"

TAG_FAMILY_NAME = "PD_TAG_Wire_2.5mm_CircuitReference"
TAG_TYPE_NAME = "BorderOFF"

# Tag head distance in front of the stub end:
# Computed from view scale but capped so it never goes crazy:
# offset_mm = max(50, min(500, view.Scale * 5))
TAG_PAPER_MM = 5.0
TAG_MIN_MM = 50.0
TAG_MAX_MM = 500.0


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
    Auto direction aligned to family:
      direction = normalize(FacingOrientation + HandOrientation)
    projected to view plane.

    Fallbacks: Facing, Hand, Connector CS, View.RightDirection.
    """
    vdir = normalize_xyz(view.ViewDirection)

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

    if facing and hand:
        diag = normalize_xyz(project_to_view_plane(facing + hand, vdir))
        if diag:
            return diag

    if facing:
        return facing
    if hand:
        return hand

    try:
        cs = conn.CoordinateSystem
        for basis in [cs.BasisX, cs.BasisY, cs.BasisZ]:
            cand = normalize_xyz(project_to_view_plane(basis, vdir))
            if cand:
                return cand
    except:
        pass

    try:
        return normalize_xyz(project_to_view_plane(view.RightDirection, vdir))
    except:
        return None


def compute_tag_head_offset_mm(view):
    """Distance in model mm that corresponds to ~TAG_PAPER_MM on paper."""
    try:
        sc = float(view.Scale)
    except:
        sc = 50.0
    off = sc * float(TAG_PAPER_MM)
    if off < float(TAG_MIN_MM):
        off = float(TAG_MIN_MM)
    if off > float(TAG_MAX_MM):
        off = float(TAG_MAX_MM)
    return off


class ElectricalFixtureSelectionFilter(ISelectionFilter):
    """Allow only FamilyInstances that have an electrical connector."""
    def AllowElement(self, element):
        try:
            if isinstance(element, FamilyInstance):
                return get_electrical_connector(element) is not None
        except:
            pass
        return False

    def AllowReference(self, reference, position):
        return True


# ----------------------------
# Preconditions
# ----------------------------
view = doc.ActiveView
if not is_plan_or_rcp(view):
    forms.alert("Active view must be a Floor Plan / RCP (Ceiling Plan) to create wires.",
                exitscript=True)

wire_type = find_first_wire_type()
if wire_type is None:
    forms.alert("No Wire Types found in this project. Load/define a Wire Type first.",
                exitscript=True)

tag_sym = find_tag_type(TAG_FAMILY_NAME, TAG_TYPE_NAME)

# lengths to try
try_lengths_ft = [mm_to_ft(STUB_LEN_MM)] + [mm_to_ft(x) for x in FALLBACK_MM]

# offset for tag head (per view)
tag_head_off_mm = compute_tag_head_offset_mm(view)
tag_head_off_ft = mm_to_ft(tag_head_off_mm)


# ----------------------------
# Collect targets: preselect OR pick multiple
# ----------------------------
targets = []

try:
    pre_ids = list(uidoc.Selection.GetElementIds())
except:
    pre_ids = []

if pre_ids:
    for eid in pre_ids:
        try:
            e = doc.GetElement(eid)
            targets.append(e)
        except:
            pass
else:
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            ElectricalFixtureSelectionFilter(),
            "Select MULTIPLE fixtures/devices with electrical connectors, then click Finish"
        )
        for r in refs:
            try:
                targets.append(doc.GetElement(r.ElementId))
            except:
                pass
    except:
        forms.alert("Cancelled. Nothing selected.", exitscript=True)

# Filter valid
valid_fis = []
for e in targets:
    try:
        if isinstance(e, FamilyInstance) and get_electrical_connector(e) is not None:
            valid_fis.append(e)
    except:
        pass

if not valid_fis:
    forms.alert("No valid fixtures/devices with electrical connectors were selected.", exitscript=True)

# ----------------------------
# Activate tag type once (if needed)
# ----------------------------
if tag_sym and (not tag_sym.IsActive):
    tx_prep = Transaction(doc, "WireTag: Activate Tag Type")
    tx_prep.Start()
    try:
        tag_sym.Activate()
        tx_prep.Commit()
    except:
        try:
            tx_prep.RollBack()
        except:
            pass


# ----------------------------
# Batch create
# ----------------------------
ok_wires = 0
ok_tags = 0
skipped = 0
failures = []

tg = TransactionGroup(doc, "WireTag: Batch Add Wire + Tag (Auto)")
tg.Start()

for fi in valid_fis:
    fi_id = -1
    try:
        fi_id = fi.Id.IntegerValue
    except:
        pass

    tx = Transaction(doc, "WireTag: {}".format(fi_id))
    tx.Start()

    try:
        conn = get_electrical_connector(fi)
        if conn is None:
            skipped += 1
            tx.RollBack()
            continue

        try:
            start_pt = conn.Origin
        except:
            skipped += 1
            tx.RollBack()
            continue

        direction_vec = get_family_isometric_direction(fi, conn, view)
        if not direction_vec:
            skipped += 1
            tx.RollBack()
            continue

        # --- Create wire stub ---
        created_wire = None
        end_pt_used = None
        last_err = None

        for L in try_lengths_ft:
            end_pt = start_pt + direction_vec.Multiply(L)

            pts = List[XYZ]()
            pts.Add(start_pt)
            pts.Add(end_pt)

            try:
                created_wire = Wire.Create(doc, wire_type.Id, view.Id, WiringType.Arc, pts, conn, None)
                if created_wire:
                    end_pt_used = end_pt
                    break
            except Exception as e:
                last_err = e
                created_wire = None

        if not created_wire:
            raise Exception("Wire creation failed. Last error: {}".format(last_err))

        ok_wires += 1

        # --- Set parameter ---
        if not set_param_text(created_wire, PARAM_NAME, PARAM_VALUE):
            set_param_text(fi, PARAM_NAME, PARAM_VALUE)

        # --- Place tag (one per wire) ---
        created_tag = None

        wref = Reference(created_wire)

        # Tag head = directly in front of the stub end (same direction)
        # This prevents "far away" tags and keeps it per element.
        head_pt = end_pt_used + direction_vec.Multiply(tag_head_off_ft)

        try:
            created_tag = IndependentTag.Create(
                doc,
                view.Id,
                wref,
                True,   # addLeader
                TagMode.TM_ADDBY_CATEGORY,
                TagOrientation.Horizontal,
                head_pt  # initial point (we also force TagHeadPosition below)
            )

            # Set desired type
            if created_tag and tag_sym:
                try:
                    created_tag.ChangeTypeId(tag_sym.Id)
                except:
                    pass

            # Force tag head position (THIS is the key fix)
            try:
                created_tag.TagHeadPosition = head_pt
            except:
                pass

            # Ensure leader behavior
            try:
                created_tag.HasLeader = True
            except:
                pass

            try:
                created_tag.LeaderEndCondition = LeaderEndCondition.Free
            except:
                pass

            # Snap leader end to wire free end
            try:
                if end_pt_used:
                    created_tag.SetLeaderEnd(wref, end_pt_used)
            except:
                pass

            ok_tags += 1

        except Exception as ex_tag:
            failures.append("FI {}: tag failed ({})".format(fi_id, ex_tag))

        tx.Commit()

    except Exception as e:
        try:
            tx.RollBack()
        except:
            pass
        failures.append("FI {}: {}".format(fi_id, str(e)))

tg.Assimilate()

# ----------------------------
# Summary
# ----------------------------
msg = []
msg.append("Selected: {}".format(len(valid_fis)))
msg.append("Wires created: {}".format(ok_wires))
msg.append("Tags placed: {}".format(ok_tags))
msg.append("Skipped: {}".format(skipped))
msg.append("Failures: {}".format(len(failures)))
msg.append("Tag head offset used: {:.0f} mm".format(float(tag_head_off_mm)))

if failures:
    output.print_md("## WireTag Batch — Failures")
    for f in failures:
        output.print_md("- {}".format(f))

forms.alert("\n".join(msg))
