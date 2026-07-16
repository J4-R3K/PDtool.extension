# -*- coding: utf-8 -*-
__title__   = "Copy: Cable Trays"
__doc__     = """Version = 1.0
Date    = 20.12.2025
________________________________________________________________
Description:

Copy Cable Trays and Cable Tray Fittings from a selected Revit Link into this model,
  preserving coordinates via the link transform. Optionally remap each source type to a
  host type after copy.

Relative Path:
...\
________________________________________________________________
How-To:

1. Click on

________________________________________________________________
Get Free:
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('System')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, RevitLinkInstance, ElementId,
    Transaction, ElementTransformUtils, CopyPasteOptions,
    IDuplicateTypeNamesHandler, BuiltInParameter, StorageType, Category
)
from System.Collections.Generic import List
from pyrevit import revit, forms, script

# ------------------------------------------------------------------------------
# Context
# ------------------------------------------------------------------------------
doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

if doc is None:
    forms.alert("No active Revit document.", exitscript=True)

# ------------------------------------------------------------------------------
# Constants & utils
# ------------------------------------------------------------------------------
MM_PER_FT = 304.8

def _bic(*names):
    for n in names:
        try: return getattr(BuiltInCategory, n)
        except Exception: pass
    return None

CAT_TRAY     = _bic('OST_CableTray', 'OST_CableTrays')
CAT_TRAY_FIT = _bic('OST_CableTrayFitting', 'OST_CableTrayFittings')
if CAT_TRAY is None or CAT_TRAY_FIT is None:
    forms.alert("Could not resolve Cable Tray categories.", exitscript=True)

CATID_TRAY = Category.GetCategory(doc, CAT_TRAY).Id

# Duplicate type name handler (IronPython-safe)
class _DupTypeRename(IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        from Autodesk.Revit.DB import DuplicateTypeAction
        try:
            return DuplicateTypeAction.Rename
        except:
            return DuplicateTypeAction.UseDestinationTypes

def to_idlist(py_ids):
    idlist = List[ElementId]()
    for i in py_ids: idlist.Add(i)
    return idlist

# ------------------------------------------------------------------------------
# Name/parameter helpers (IronPython-safe)
# ------------------------------------------------------------------------------
def safe_type_name(eltype):
    try:
        p = eltype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            s = p.AsString()
            if s: return s
    except: pass
    try:
        p = eltype.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p:
            s = p.AsString()
            if s: return s
    except: pass
    try:
        n = eltype.Name
        if n: return n
    except: pass
    try:    return u"<Type {}>".format(eltype.Id.IntegerValue)
    except: return u"<Type>"

def safe_family_name(eltype):
    try:
        fn = getattr(eltype, "FamilyName", None)
        if fn: return fn
    except: pass
    try:
        p = eltype.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        if p:
            s = p.AsString()
            if s: return s
    except: pass
    try:
        fam = getattr(eltype, "Family", None)
        if fam and getattr(fam, "Name", None):
            return fam.Name
    except: pass
    try:
        cat = eltype.Category
        if cat and cat.Name: return cat.Name
    except: pass
    return "System"

def _first_param(el, name_candidates=None, bip_candidates=None):
    name_candidates = name_candidates or []
    bip_candidates  = bip_candidates or []
    for n in name_candidates:
        try:
            p = el.LookupParameter(n)
            if p: return p
        except: pass
    for bn in bip_candidates:
        try:
            bip = getattr(BuiltInParameter, bn)
            p = el.get_Parameter(bip)
            if p: return p
        except: pass
    return None

def param_as_str(el, name_candidates=None, bip_candidates=None):
    p = _first_param(el, name_candidates, bip_candidates)
    if not p: return None
    try:
        s = p.AsValueString()
        if s: return s
    except: pass
    try:
        s = p.AsString()
        if s: return s
    except: pass
    try: return str(p.AsInteger())
    except: pass
    try: return str(p.AsDouble())
    except: pass
    return None

def param_as_double(el, name_candidates=None, bip_candidates=None):
    p = _first_param(el, name_candidates, bip_candidates)
    if not p: return None
    try:
        if p.StorageType == StorageType.Double:
            return p.AsDouble()
    except: pass
    return None

def fmt_dim_mm(val_ft):
    if val_ft is None: return None
    return round(val_ft * MM_PER_FT, 1)

def get_w_h_ft(from_obj):
    w = param_as_double(from_obj, ["Width"],  ["RBS_CABLETRAY_WIDTH_PARAM",  "WIDTH_PARAM"])
    h = param_as_double(from_obj, ["Height"], ["RBS_CABLETRAY_HEIGHT_PARAM", "HEIGHT_PARAM"])
    return (w, h)

def get_wxh_mm(from_obj):
    w, h = get_w_h_ft(from_obj)
    return (fmt_dim_mm(w), fmt_dim_mm(h))

def get_part_type_str(el_or_type):
    # Try label first, then several common BIPs used across versions/content
    return param_as_str(
        el_or_type, ["Part Type"],
        ["RBS_PART_TYPE", "RBS_FAMILY_CONTENT_PART_TYPE", "FAMILY_CONTENT_PART_TYPE",
         "RBS_FITTING_PARTTYPE", "RBS_CABLETRAY_FITTING_TYPE", "RBS_CABLETRAY_SHAPE"]
    )

# Canonical keys for part types
def norm_part_key(s):
    if not s: return None
    s2 = s.strip().lower()
    if "horiz" in s2 or "elbow" in s2 and "vertical" not in s2:                return "Horizontal Bend"
    if "vertical" in s2 and ("inside" in s2 or "internal" in s2):              return "Vertical Inside Bend"
    if "vertical" in s2 and ("outside" in s2 or "external" in s2):             return "Vertical Outside Bend"
    if "tee" in s2:                                                             return "Tee"
    if "cross" in s2:                                                           return "Cross"
    if "reducer" in s2 or "transition" in s2:                                   return "Transition"
    if "union" in s2 or "coupling" in s2:                                       return "Union"
    # Fallback
    if "vert" in s2:                                                            return "Vertical Inside Bend"
    return None

# Build a readable label
def build_type_label(eltype, is_fitting, sample_elem=None):
    fam = safe_family_name(eltype)
    typ = safe_type_name(eltype)
    part = get_part_type_str(eltype)
    if not part and sample_elem is not None:
        part = get_part_type_str(sample_elem)
    if not part:
        part = "Fitting" if is_fitting else "Tray"
    w, h = get_wxh_mm(eltype)
    if (w is None or h is None) and sample_elem is not None:
        w2, h2 = get_wxh_mm(sample_elem); w = w or w2; h = h or h2
    try:    idv = eltype.Id.IntegerValue
    except: idv = -1
    label = u"{} | Family: {} | Type: {} | Part: {} | Size: {}×{} mm | Id: {}".format(
        "Fitting" if is_fitting else "Tray", fam, typ, part,
        "-" if w is None else w, "-" if h is None else h, idv)
    return label, part

# ------------------------------------------------------------------------------
# Selection + grouping
# ------------------------------------------------------------------------------
def pick_link_instance():
    links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
    if not links:
        forms.alert("No Revit Links found.", exitscript=True)
    items, imap = [], {}
    for li in links:
        ldoc = li.GetLinkDocument()
        title = ldoc.Title if ldoc else "(unloaded)"
        label = "{}  —  {}".format(li.Name, title)
        items.append(label); imap[label] = li
    sel = forms.SelectFromList.show(sorted(items), multiselect=False,
                                    title="Select Revit Link to copy FROM", button_name="Use Link")
    if not sel: script.exit()
    return imap[sel]

def collect_link_elems(linkdoc):
    trays = list(FilteredElementCollector(linkdoc).OfCategory(CAT_TRAY).WhereElementIsNotElementType())
    fits  = list(FilteredElementCollector(linkdoc).OfCategory(CAT_TRAY_FIT).WhereElementIsNotElementType())
    return trays, fits

def group_used_types(elems, srcdoc):
    # { srcTypeUid : { 'type': ElementType, 'typeName': str, 'typeId': ElementId,
    #                  'elemIds': [ElementId], 'sampleElemId': ElementId } }
    groups = {}
    for e in elems:
        tid = e.GetTypeId()
        if tid == ElementId.InvalidElementId: continue
        t = srcdoc.GetElement(tid)
        if t is None: continue
        key = t.UniqueId
        if key not in groups:
            groups[key] = {'type': t, 'typeName': safe_type_name(t),
                           'typeId': tid, 'elemIds': [], 'sampleElemId': e.Id}
        groups[key]['elemIds'].append(e.Id)
    return groups

def collect_host_types(cat, is_fitting):
    types   = list(FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType())
    by_disp = {}
    for t in types:
        label, _ = build_type_label(t, is_fitting)
        by_disp[label] = t
    return by_disp

# ------------------------------------------------------------------------------
# Tray mapping UI (simple list per source type)
# ------------------------------------------------------------------------------
def ask_tray_mapping(linkdoc, tray_groups, host_tray_disp):
    KEEP   = u"<< Keep Source Type (copy as-is) >>"
    SOURCE = u"<< SOURCE — read-only >>"

    tray_map = {}  # srcTypeUid -> hostTypeId or None
    if not tray_groups:
        return tray_map

    forms.alert(
        "Map CABLE TRAY TYPES.\nPick a host Tray Type for each source type, or choose:\n{}".format(KEEP),
        title="Tray Type Mapping", warn_icon=False
    )

    for uid in sorted(tray_groups.keys(), key=lambda k: tray_groups[k]['typeName']):
        info   = tray_groups[uid]
        sample = linkdoc.GetElement(info.get('sampleElemId')) if info.get('sampleElemId') else None

        # Build a rich label for the SOURCE (Family + Type + Part + Size + Id)
        src_label, _ = build_type_label(info['type'], is_fitting=False, sample_elem=sample)

        # Title is single-line to avoid trimming in some pyRevit builds
        title  = u"Map Tray Type: {}".format(src_label)
        header = u"{}  {}".format(SOURCE, src_label)

        options = [KEEP, header] + sorted(host_tray_disp.keys())

        while True:
            sel = forms.SelectFromList.show(
                options, multiselect=False, title=title, button_name="Use Selection"
            )
            if not sel or sel == KEEP:
                tray_map[uid] = None
                break
            if sel == header:
                continue
            tray_map[uid] = host_tray_disp[sel].Id
            break

    return tray_map

# ------------------------------------------------------------------------------
# Copy helpers
# ------------------------------------------------------------------------------
def copy_trays_with_mapping(srcdoc, dst_doc, transform, tray_groups, tray_map):
    copied = 0; retyped = 0; failed = []
    cpo = CopyPasteOptions()
    try: cpo.SetDuplicateTypeNamesHandler(_DupTypeRename())
    except: pass

    for uid, info in tray_groups.items():
        elem_ids = info['elemIds']
        src_name = info['typeName']
        try:
            with Transaction(dst_doc, "Copy Tray Group: {}".format(src_name)) as t:
                t.Start()
                new_ids = ElementTransformUtils.CopyElements(srcdoc, to_idlist(elem_ids), dst_doc, transform, cpo)
                new_list = [nid for nid in new_ids]
                copied += len(new_list)

                host_type_id = tray_map.get(uid)
                if host_type_id and host_type_id != ElementId.InvalidElementId:
                    for nid in new_list:
                        try:
                            e = dst_doc.GetElement(nid)
                            if e: e.ChangeTypeId(host_type_id); retyped += 1
                        except Exception as rex:
                            failed.append(("Retype Tray '{}'".format(src_name), str(rex)))
                t.Commit()
        except Exception as ex:
            failed.append(("Copy Tray '{}'".format(src_name), str(ex)))
    return copied, retyped, failed

def copy_fittings_as_is(srcdoc, dst_doc, transform, fit_groups):
    """Copy ALL fitting elements as-is in a single pass (keeps connections best)."""
    all_ids = []
    for info in fit_groups.values():
        all_ids.extend(info['elemIds'])

    # --- FIX: always return THREE values ---
    if not all_ids:
        return 0, [], []   # (count, issues, new_ids)

    cpo = CopyPasteOptions()
    try: cpo.SetDuplicateTypeNamesHandler(_DupTypeRename())
    except: pass

    copied_ids = []
    failed = []
    try:
        with Transaction(dst_doc, "Copy Cable Tray Fittings (as-is)") as t:
            t.Start()
            new_ids = ElementTransformUtils.CopyElements(srcdoc, to_idlist(all_ids), dst_doc, transform, cpo)
            copied_ids = [nid for nid in new_ids]
            t.Commit()
    except Exception as ex:
        failed.append(("Copy Fittings", str(ex)))
    return len(copied_ids), failed, copied_ids

# ------------------------------------------------------------------------------
# AUTO fittings: use host tray type default fitting types
# ------------------------------------------------------------------------------
DEFAULT_FIT_PARAM_NAMES = {
    "Horizontal Bend":     ["Horizontal Bend"],
    "Vertical Inside Bend":["Vertical Inside Bend", "Vertical Bend - Inside"],
    "Vertical Outside Bend":["Vertical Outside Bend", "Vertical Bend - Outside"],
    "Tee":                 ["Tee"],
    "Cross":               ["Cross"],
    "Transition":          ["Transition", "Reducer"],
    "Union":               ["Union", "Coupling"]
}

def get_default_fitting_typeid(tray_type, part_key):
    labels = DEFAULT_FIT_PARAM_NAMES.get(part_key, []) or []
    for name in labels:
        try:
            p = tray_type.LookupParameter(name)
            if p and p.StorageType == StorageType.ElementId:
                eid = p.AsElementId()
                if eid and eid != ElementId.InvalidElementId:
                    return eid
        except: pass
    return None

def get_connectors(element):
    conns = []
    try:
        mm = getattr(element, "MEPModel", None)
        if mm:
            cm = getattr(mm, "ConnectorManager", None)
            if cm:
                for c in cm.Connectors: conns.append(c)
    except: pass
    try:
        cm = getattr(element, "ConnectorManager", None)
        if cm:
            for c in cm.Connectors: conns.append(c)
    except: pass
    return conns

def first_connected_tray_typeid(element):
    for c in get_connectors(element):
        try:
            for r in c.AllRefs:
                owner = r.Owner
                if owner and owner.Category and owner.Category.Id.IntegerValue == CATID_TRAY.IntegerValue:
                    return owner.GetTypeId()
        except: pass
    return None

def get_w_h_ft_type(eltype):
    w = param_as_double(eltype, ["Width"],  ["RBS_CABLETRAY_WIDTH_PARAM",  "WIDTH_PARAM"])
    h = param_as_double(eltype, ["Height"], ["RBS_CABLETRAY_HEIGHT_PARAM", "HEIGHT_PARAM"])
    return (w, h)

def sizes_match(type_a, type_b, tol_ft=1e-6):
    wa, ha = get_w_h_ft_type(type_a)
    wb, hb = get_w_h_ft_type(type_b)
    if wa is None or ha is None or wb is None or hb is None:
        return True  # if we can't read sizes, don't block the swap
    return abs((wa or 0) - (wb or 0)) < tol_ft and abs((ha or 0) - (hb or 0)) < tol_ft

def norm_part_from_element_or_type(doc, el):
    ftype = doc.GetElement(el.GetTypeId())
    p = get_part_type_str(ftype) or get_part_type_str(el)
    return norm_part_key(p)

def auto_retype_fittings_by_tray_defaults(dst_doc, new_fit_ids):
    """Retype copied fittings to host tray type defaults where safe."""
    if not new_fit_ids:
        return 0, []

    retyped = 0
    failed  = []

    tray_default_fit = {}  # trayTypeId -> { part_key : fittingTypeId }

    with Transaction(dst_doc, "Retype Fittings to Tray Defaults") as t:
        t.Start()
        for nid in new_fit_ids:
            try:
                fit = dst_doc.GetElement(nid)
                if not fit: continue
                fit_type = dst_doc.GetElement(fit.GetTypeId())

                part_key = norm_part_from_element_or_type(dst_doc, fit)
                if not part_key:
                    continue

                tray_tid = first_connected_tray_typeid(fit)
                if not tray_tid:
                    continue

                if tray_tid not in tray_default_fit:
                    tray_default_fit[tray_tid] = {}

                dest_tid = tray_default_fit[tray_tid].get(part_key)
                if dest_tid is None:
                    tray_type = dst_doc.GetElement(tray_tid)
                    dest_tid = get_default_fitting_typeid(tray_type, part_key)
                    tray_default_fit[tray_tid][part_key] = dest_tid

                if dest_tid and dest_tid != ElementId.InvalidElementId:
                    host_ftype = dst_doc.GetElement(dest_tid)
                    if sizes_match(host_ftype, fit_type):
                        fit.ChangeTypeId(dest_tid)
                        retyped += 1
            except Exception as ex:
                failed.append(("Retype Fitting", str(ex)))
        t.Commit()
    return retyped, failed

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
link_inst = pick_link_instance()
link_doc  = link_inst.GetLinkDocument()
if link_doc is None:
    forms.alert("The selected link is unloaded or inaccessible.", exitscript=True)

# Gather source elements
trays, fits = collect_link_elems(link_doc)
if not trays and not fits:
    forms.alert("No Cable Trays or Cable Tray Fittings found in the selected link.", exitscript=True)

# Group by used types
tray_groups = group_used_types(trays, link_doc)
fit_groups  = group_used_types(fits,  link_doc)

# Host type choices (trays)
host_tray_disp = collect_host_types(CAT_TRAY, is_fitting=False)

# Tray mapping
tray_map = ask_tray_mapping(link_doc, tray_groups, host_tray_disp)

# Fitting handling mode
mode = forms.SelectFromList.show(
    ["AUTO: Use defaults from mapped host Tray Type",
     "AS-IS: Copy fittings as they are (no retyping)"],
    multiselect=False, title="How should fittings be handled?", button_name="Continue"
)
if not mode: script.exit()
mode_auto = mode.startswith("AUTO")

# Copy trays (per type group) with retype to mapped host types
xform = link_inst.GetTransform()
copied_trays, retyped_trays, tray_errors = copy_trays_with_mapping(link_doc, doc, xform, tray_groups, tray_map)

# Copy fittings as-is (keeps connections/sizes from source)
copied_fits, fit_copy_errors, new_fit_ids = copy_fittings_as_is(link_doc, doc, xform, fit_groups)

# Optional: AUTO retype fittings to host tray type defaults
retyped_fits = 0
auto_fit_errors = []
if mode_auto and new_fit_ids:
    try: doc.Regenerate()
    except: pass
    retyped_fits, auto_fit_errors = auto_retype_fittings_by_tray_defaults(doc, new_fit_ids)

# ------------------------------------------------------------------------------
# Report
# ------------------------------------------------------------------------------
out.print_md("### ✅ Copy complete")
out.print_md("* Copied **Trays**: **{}**  (Retyped to host types: **{}**)".format(copied_trays, retyped_trays))
out.print_md("* Copied **Fittings**: **{}**  ({} mode; Retyped after copy: **{}**)".format(
    copied_fits, "AUTO" if mode_auto else "AS‑IS", retyped_fits))

issues = tray_errors + fit_copy_errors + auto_fit_errors
if issues:
    out.print_md("\n### ⚠️ Notes / Skips")
    for what, reason in issues:
        out.print_md("* {} — {}".format(what, reason))

out.print_md("\n---")
out.print_md("**How it works**")
out.print_md("* Trays are copied per type group and retyped immediately to the mapped host types. (Pattern mirrors your working transfer tools.)")  # :contentReference[oaicite:1]{index=1}
out.print_md("* Fittings are copied *as-is* to keep connections. If **AUTO**, the script then retypes each fitting to the default fitting type on the connected tray’s host type, only when sizes match, keeping connections intact.")
