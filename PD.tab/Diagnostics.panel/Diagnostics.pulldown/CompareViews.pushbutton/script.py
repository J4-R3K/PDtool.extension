# -*- coding: utf-8 -*-
__title__  = 'Compare Views — Side-by-Side (VG Deep)'
__author__ = 'pyRevit Script Generator'
__doc__    = """Full, side-by-side compare of visibility-affecting settings:
• View globals (template, discipline, detail, display, phase/filter, underlay, view range)
• VG Overrides by group (Model / Annotation / Analytical / Revit Links): Visible/Hidden + OverrideGraphicSettings
• Filters (present/visibility/overrides)
• Worksets visibility
• Revit Links (2024+): By Host View / By Linked View / Custom, Linked View, link-level Phase/Phase Filter
Optionally patch selected differences A → B (template-aware).
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import View as DBView
from pyrevit import revit, forms, script
from System import Enum
from System.Collections.Generic import List

doc = revit.doc
uidoc = revit.uidoc
out = script.get_output()

# ------------------------------------------------------------
# Feature flags (Revit 2024+ deep link API)
try:
    from Autodesk.Revit.DB import RevitLinkGraphicsSettings
    HAS_RLGS = True
except:
    HAS_RLGS = False

# ------------------------------------------------------------
# Utility helpers (IronPython 2 safe)
def try_get_bip(name):
    try:
        return getattr(BuiltInParameter, name)
    except:
        return None

def eid_name(docx, eid):
    try:
        if not eid or eid == ElementId.InvalidElementId:
            return None
        el = docx.GetElement(eid)
        return el.Name if el else None
    except:
        return None

def p_readable(p):
    if not p:
        return None
    try:
        st = p.StorageType
        if st == StorageType.String:
            return p.AsString()
        elif st == StorageType.Integer:
            return str(p.AsInteger())
        elif st == StorageType.Double:
            try:
                return p.AsValueString()
            except:
                return str(p.AsDouble())
        elif st == StorageType.ElementId:
            v = p.AsElementId()
            if v == ElementId.InvalidElementId:
                return "—"
            nm = eid_name(doc, v)
            return nm if nm else "Id({})".format(v.IntegerValue)
    except:
        return None

def get_view_label(v):
    return "{}  [{}]  (Id:{})".format(v.Name, v.ViewType, v.Id.IntegerValue)

def is_plan(v):
    return isinstance(v, ViewPlan)

def view_range_info(v):
    if not is_plan(v):
        return None
    try:
        vr = v.GetViewRange()
        data = {}
        for plane, label in [(PlanViewPlane.TopClipPlane, "Top"),
                             (PlanViewPlane.CutPlane, "Cut"),
                             (PlanViewPlane.BottomClipPlane, "Bottom"),
                             (PlanViewPlane.ViewDepthPlane, "View Depth")]:
            lvl = eid_name(doc, vr.GetLevelId(plane)) or "—"
            off = vr.GetOffset(plane)
            data[label] = "Level={} | Offset(ft)={:.4f}".format(lvl, float(off))
        return data
    except:
        return None

def get_detail_level(v):
    try:
        return str(v.DetailLevel)
    except:
        bip = try_get_bip('VIEW_DETAIL_LEVEL')
        if bip:
            p = v.get_Parameter(bip)
            if p and p.StorageType == StorageType.Integer:
                return str(p.AsInteger())
    return None

def get_display_style(v):
    try:
        return str(v.DisplayStyle)
    except:
        bip = try_get_bip('MODEL_GRAPHICS_STYLE')
        if bip:
            p = v.get_Parameter(bip)
            if p and p.StorageType == StorageType.Integer:
                return str(p.AsInteger())
    return None

def get_phase_filter(v):
    bip = try_get_bip('VIEW_PHASE_FILTER')
    if bip:
        p = v.get_Parameter(bip)
        if p and p.StorageType == StorageType.ElementId:
            return (eid_name(doc, p.AsElementId()), p.AsElementId())
    return (None, None)

def get_phase(v):
    bip = try_get_bip('VIEW_PHASE')
    if bip:
        p = v.get_Parameter(bip)
        if p and p.StorageType == StorageType.ElementId:
            return (eid_name(doc, p.AsElementId()), p.AsElementId())
    return (None, None)

def get_underlay(v):
    d = {}
    for bipname in ['VIEW_UNDERLAY_ORIENTATION', 'VIEW_UNDERLAY_ID']:
        bip = try_get_bip(bipname)
        if not bip:
            continue
        d[bipname] = p_readable(v.get_Parameter(bip))
    return d

def get_template(v):
    try:
        if v.ViewTemplateId and v.ViewTemplateId != ElementId.InvalidElementId:
            vt = doc.GetElement(v.ViewTemplateId)
            return vt
    except:
        pass
    return None

# ------------------------------------------------------------
# OverrideGraphicSettings signature (stable string for compare)
def ogs_signature(ogs):
    if not ogs:
        return "—"
    sig = []
    # Projection
    try:
        lw = ogs.ProjectionLineWeight
        if lw > 0:
            sig.append("ProjLW:{}".format(lw))
    except: pass
    try:
        lp = ogs.ProjectionLinePatternId
        if lp and lp != ElementId.InvalidElementId:
            sig.append("ProjLP:{}".format(eid_name(doc, lp)))
    except: pass
    try:
        c = ogs.ProjectionLineColor
        if c and (c.Red or c.Green or c.Blue):
            sig.append("ProjLC:({},{},{})".format(c.Red, c.Green, c.Blue))
    except: pass
    # Cut
    try:
        clw = ogs.CutLineWeight
        if clw > 0:
            sig.append("CutLW:{}".format(clw))
    except: pass
    try:
        clp = ogs.CutLinePatternId
        if clp and clp != ElementId.InvalidElementId:
            sig.append("CutLP:{}".format(eid_name(doc, clp)))
    except: pass
    try:
        cc = ogs.CutLineColor
        if cc and (cc.Red or cc.Green or cc.Blue):
            sig.append("CutLC:({},{},{})".format(cc.Red, cc.Green, cc.Blue))
    except: pass
    # Surfaces / patterns / material-like overrides (best-effort across versions)
    for att, label in [
        ("SurfaceForegroundPatternId", "SurfPat"),
        ("SurfaceForegroundPatternColor", "SurfCol"),
        ("SurfaceTransparency", "Transp"),
        ("Halftone", "Halftone"),
        ("CutForegroundPatternId", "CutPat"),
        ("CutForegroundPatternColor", "CutCol")
    ]:
        try:
            val = getattr(ogs, att)
            if att.endswith("Id"):
                if val and val != ElementId.InvalidElementId:
                    sig.append("{}:{}".format(label, eid_name(doc, val)))
            elif att.endswith("Color"):
                if val and (val.Red or val.Green or val.Blue):
                    sig.append("{}:({},{},{})".format(label, val.Red, val.Green, val.Blue))
            else:
                # ints/bools/doubles
                if val not in [None, 0, False]:
                    sig.append("{}:{}".format(label, val))
        except:
            # silently skip properties not available in this Revit release
            pass

    return ", ".join(sig) if sig else "—"

# ------------------------------------------------------------
# VG collection (by group) -----------------------------------
def collect_vg(view):
    """Return dict: group -> {category name: (visible_bool, ogs_signature)}"""
    groups = {"Model": {}, "Annotation": {}, "Analytical": {}, "Revit Links": {}}
    cats = doc.Settings.Categories
    enum = CategoryType

    for c in cats:
        try:
            # Skip internal categories and those that can't be hidden
            if not view.CanCategoryBeHidden(c.Id):
                continue
            v = (view.GetCategoryHidden(c.Id) is False)
            ogs = view.GetCategoryOverrides(c.Id)
            sig = ogs_signature(ogs)
            # Group mapping
            g = None
            if c.CategoryType == enum.Model:
                # carve out Revit Links explicitly
                try:
                    if c.Id == ElementId(BuiltInCategory.OST_RvtLinks):
                        g = "Revit Links"
                    else:
                        g = "Model"
                except:
                    g = "Model"
            elif c.CategoryType == enum.Annotation:
                g = "Annotation"
            elif hasattr(enum, "AnalyticalModel") and c.CategoryType == enum.AnalyticalModel:
                g = "Analytical"
            else:
                # leave exotic/other in Model to keep it discoverable
                g = "Model"
            groups[g][c.Name] = (v, sig)
        except:
            continue
    return groups

# ------------------------------------------------------------
# Filters & Worksets -----------------------------------------
def collect_filters(view):
    data = {}
    try:
        ids = list(view.GetFilters())
    except:
        ids = []
    for fid in ids:
        fe = doc.GetElement(fid)
        name = fe.Name if fe else "Id({})".format(fid.IntegerValue)
        rec = {"visible": None, "overrides": "—", "categories": []}
        try:
            rec["visible"] = view.GetFilterVisibility(fid)
        except: pass
        try:
            ogs = view.GetFilterOverrides(fid)
            rec["overrides"] = ogs_signature(ogs)
        except: pass
        try:
            cats = fe.GetCategories()
            if cats:
                rec["categories"] = [eid_name(doc, cid) for cid in cats if cid != ElementId.InvalidElementId]
        except: pass
        data[name] = rec
    return data

def collect_worksets(view):
    vis = {}
    try:
        wsets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
        for ws in wsets:
            try:
                vis[ws.Name] = str(view.GetWorksetVisibility(ws.Id))
            except:
                continue
    except:
        pass
    return vis

# ------------------------------------------------------------
# Links (document-wide map; deep 2024+ when possible) --------
def all_links_map():
    mp = {}
    for lk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            ld = lk.GetLinkDocument()
            key = ld.Title if ld else lk.Name
        except:
            key = lk.Name
        if key not in mp:
            mp[key] = {"instances": [], "typeId": lk.GetTypeId()}
        mp[key]["instances"].append(lk)
    return mp

LINKS_CACHE = all_links_map()

def link_effective(view, link_title):
    """Return dict with effective display for link in 'view' (tolerant to 'no overrides')."""
    info = {"mode": "ByHostView", "linked_view": None, "phase": None, "phase_filter": None, "src": "default"}
    pack = LINKS_CACHE.get(link_title)
    if not pack or not HAS_RLGS:
        return info
    lk = pack["instances"][0]
    rlgs = None; src = None
    # Prefer instance overrides, then type overrides; if none -> default (ByHostView)
    try:
        rlgs = view.GetLinkOverrides(lk.Id)
        src = "instance" if rlgs else None
    except: pass
    if rlgs is None:
        try:
            rlgs = view.GetLinkOverrides(pack["typeId"])
            src = "type" if rlgs else None
        except:
            rlgs = None
    if rlgs is None:
        return info  # default
    info["src"] = src
    try:
        info["mode"] = str(rlgs.LinkVisibilityType)
    except: pass
    try:
        lvid = rlgs.LinkedViewId
        if lvid and lvid != ElementId.InvalidElementId:
            ldoc = lk.GetLinkDocument()
            if ldoc:
                lv = ldoc.GetElement(lvid)
                if isinstance(lv, DBView):
                    info["linked_view"] = lv.Name
    except: pass
    try:
        ph = rlgs.GetPhaseId()
        if ph and ph != ElementId.InvalidElementId:
            info["phase"] = eid_name(lk.GetLinkDocument() or doc, ph)
    except: pass
    try:
        pf = rlgs.GetPhaseFilterId()
        if pf and pf != ElementId.InvalidElementId:
            info["phase_filter"] = eid_name(lk.GetLinkDocument() or doc, pf)
    except: pass
    return info

def collect_links(view):
    """Return {link title: info}"""
    rv = {}
    for title in LINKS_CACHE.keys():
        rv[title] = link_effective(view, title)
    return rv

# ------------------------------------------------------------
# Snapshot + side-by-side diff data --------------------------
def snapshot_view(v):
    ph_name, ph_id = get_phase(v)
    pf_name, pf_id = get_phase_filter(v)
    return {
        "label": get_view_label(v),
        "template": (get_template(v).Name if get_template(v) else None),
        "discipline": p_readable(v.get_Parameter(try_get_bip('VIEW_DISCIPLINE'))),
        "detail": get_detail_level(v),
        "display": get_display_style(v),
        "phase": ph_name, "phase_id": ph_id,
        "phase_filter": pf_name, "phase_filter_id": pf_id,
        "underlay": get_underlay(v),
        "vrange": view_range_info(v),
        "vg": collect_vg(v),
        "filters": collect_filters(v),
        "worksets": collect_worksets(v),
        "links": collect_links(v)
    }

# ------------------------------------------------------------
# Rendering helpers (markdown tables) ------------------------
def print_table(title, rows, show_all=False):
    """rows: list of (name, A, B). If show_all=False keeps only A!=B."""
    diffs = []
    alls  = []
    for (n, a, b) in rows:
        if a != b:
            diffs.append((n, a, b))
        else:
            alls.append((n, a, b))
    data = diffs if not show_all else (diffs + alls)
    if not data and not show_all:
        out.print_md("#### {} — _no differences_".format(title))
        return
    out.print_md("#### {}".format(title))
    out.print_md("| Setting | A | B |")
    out.print_md("|---|---|---|")
    for n, a, b in data:
        # Mark differences in B for visibility
        valA = a if a is not None else "—"
        valB = b if b is not None else "—"
        if a != b:
            valB = "**{}**".format(valB)  # bold when different
        out.print_md("| {} | {} | {} |".format(n, valA, valB))

def print_vg_group(group_name, Amap, Bmap, show_all=False):
    rows = []
    keys = sorted(set(list(Amap.keys()) + list(Bmap.keys())), key=lambda x: x.lower())
    for k in keys:
        av = Amap.get(k); bv = Bmap.get(k)
        avis = av[0] if av else None
        aogs = av[1] if av else "—"
        bvis = bv[0] if bv else None
        bogs = bv[1] if bv else "—"
        rows.append(("{} — Visible".format(k), str(avis), str(bvis)))
        rows.append(("{} — Overrides".format(k), aogs, bogs))
    print_table("VG: {}".format(group_name), rows, show_all)

# ------------------------------------------------------------
# Patch helpers (template-aware where possible) ---------------
def set_bip_on_view_or_template(viewB, bip, raw):
    """Try to set parameter on view; if template-controls block, set on template."""
    if not bip:
        return False, "no-bip"
    # try on view
    try:
        p = viewB.get_Parameter(bip)
        if p:
            st = p.StorageType
            if st == StorageType.Integer:
                ok = p.Set(int(raw))
            elif st == StorageType.Double:
                ok = p.Set(float(raw))
            elif st == StorageType.String:
                ok = p.Set(str(raw))
            elif st == StorageType.ElementId and isinstance(raw, ElementId):
                ok = p.Set(raw)
            else:
                ok = p.Set(raw)
            if ok:
                return True, "view"
    except:
        pass
    # fallback to template
    vt = get_template(viewB)
    if vt:
        try:
            pt = vt.get_Parameter(bip)
            if pt:
                st = pt.StorageType
                if st == StorageType.Integer:
                    ok = pt.Set(int(raw))
                elif st == StorageType.Double:
                    ok = pt.Set(float(raw))
                elif st == StorageType.String:
                    ok = pt.Set(str(raw))
                elif st == StorageType.ElementId and isinstance(raw, ElementId):
                    ok = pt.Set(raw)
                else:
                    ok = pt.Set(raw)
                if ok:
                    return True, "template '{}'".format(vt.Name)
        except:
            pass
    return False, "failed"

def patch_from_choices(viewA, viewB, choices):
    """choices are ('kind', payload...)."""
    if not choices:
        forms.alert("No patchable differences were found.")
        return
    labels = []
    for c in choices:
        k = c[0]
        if k == "discipline": labels.append("Set B.Discipline = A.Discipline")
        elif k == "detail": labels.append("Set B.Detail Level = A.Detail Level")
        elif k == "display": labels.append("Set B.Display Style = A.Display Style")
        elif k == "phase": labels.append("Set B.Phase = A.Phase")
        elif k == "phase_filter": labels.append("Set B.Phase Filter = A.Phase Filter")
        elif k == "underlay": labels.append("Copy Underlay (A → B)")
        elif k == "vrange": labels.append("Copy View Range (A → B)")
        elif k == "vg_vis": labels.append("VG: Set '{}' Visible={} in B".format(c[1], c[2]))
        elif k == "vg_ogs": labels.append("VG: Copy overrides for '{}' (A → B)".format(c[1]))
        elif k == "filter_add": labels.append("Filters: Add '{}' to B (vis+overrides)".format(c[1]))
        elif k == "filter_sync": labels.append("Filters: Sync '{}' vis+overrides".format(c[1]))
        elif k == "workset": labels.append("Workset: '{}' → {}".format(c[1], c[2]))
        elif k == "link_settings": labels.append("Revit Link: Copy display settings for '{}' (A → B)".format(c[1]))
    picked = forms.SelectFromList.show(labels, multiselect=True, title="Select patches to apply (A → B)", button_name="Apply")
    if not picked:
        return
    picked = set(picked)

    with Transaction(doc, "Patch View Differences (A → B)") as t:
        t.Start()
        done = []

        # links helper
        def link_targets(title):
            pack = LINKS_CACHE.get(title)
            if not pack:
                return ([], None)
            return (pack["instances"], pack["typeId"])

        for lab, c in zip(labels, choices):
            if lab not in picked:
                continue
            kind = c[0]

            if kind == "discipline":
                bip = try_get_bip('VIEW_DISCIPLINE')
                pv = viewA.get_Parameter(bip)
                if bip and pv:
                    ok, where = set_bip_on_view_or_template(viewB, bip, pv.AsInteger())
                    if ok: done.append(lab + " ({})".format(where))

            elif kind == "detail":
                try:
                    viewB.DetailLevel = viewA.DetailLevel
                    done.append(lab)
                except: pass

            elif kind == "display":
                try:
                    viewB.DisplayStyle = viewA.DisplayStyle
                    done.append(lab)
                except: pass

            elif kind == "phase":
                bip = try_get_bip('VIEW_PHASE')
                p = viewA.get_Parameter(bip) if bip else None
                if bip and p:
                    ok, where = set_bip_on_view_or_template(viewB, bip, p.AsElementId())
                    if ok: done.append(lab + " ({})".format(where))

            elif kind == "phase_filter":
                bip = try_get_bip('VIEW_PHASE_FILTER')
                p = viewA.get_Parameter(bip) if bip else None
                if bip and p:
                    ok, where = set_bip_on_view_or_template(viewB, bip, p.AsElementId())
                    if ok: done.append(lab + " ({})".format(where))

            elif kind == "underlay":
                for bipname in ['VIEW_UNDERLAY_ORIENTATION', 'VIEW_UNDERLAY_ID']:
                    bip = try_get_bip(bipname)
                    pv = viewA.get_Parameter(bip) if bip else None
                    if pv:
                        raw = pv.AsInteger() if pv.StorageType == StorageType.Integer else pv.AsElementId()
                        ok, where = set_bip_on_view_or_template(viewB, bip, raw)
                        if ok and lab not in done:
                            done.append(lab + " ({})".format(where))

            elif kind == "vrange":
                if is_plan(viewA) and is_plan(viewB):
                    try:
                        src = viewA.GetViewRange()
                        tgt = viewB.GetViewRange()
                        for pl in [PlanViewPlane.TopClipPlane, PlanViewPlane.CutPlane, PlanViewPlane.BottomClipPlane, PlanViewPlane.ViewDepthPlane]:
                            tgt.SetLevelId(pl, src.GetLevelId(pl))
                            tgt.SetOffset(pl, src.GetOffset(pl))
                        viewB.SetViewRange(tgt)
                        done.append(lab)
                    except: pass

            elif kind == "vg_vis":
                cname, avis = c[1], bool(c[2])
                # find category by name
                try:
                    for cat in doc.Settings.Categories:
                        if cat.Name == cname and viewB.CanCategoryBeHidden(cat.Id):
                            viewB.SetCategoryHidden(cat.Id, not avis)
                            done.append(lab)
                            break
                except: pass

            elif kind == "vg_ogs":
                cname = c[1]
                for cat in doc.Settings.Categories:
                    if cat.Name == cname:
                        try:
                            ogs = viewA.GetCategoryOverrides(cat.Id)
                            viewB.SetCategoryOverrides(cat.Id, ogs)
                            done.append(lab)
                        except:
                            pass
                        break

            elif kind in ("filter_add", "filter_sync"):
                fname = c[1]; ai = c[2]
                fid = None
                for f in viewA.GetFilters():
                    fe = doc.GetElement(f)
                    if fe and fe.Name == fname:
                        fid = f
                        break
                if not fid:
                    continue
                # add if missing
                if fid not in list(viewB.GetFilters()):
                    try:
                        viewB.AddFilter(fid)
                    except:
                        pass
                # copy vis + overrides
                try:
                    viewB.SetFilterVisibility(fid, bool(ai["visible"]))
                except: pass
                try:
                    ogs = viewA.GetFilterOverrides(fid)
                    viewB.SetFilterOverrides(fid, ogs)
                except: pass
                done.append(lab)

            elif kind == "workset":
                wsname, state_str = c[1], c[2]
                try:
                    wsets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
                    tgt = [w for w in wsets if w.Name == wsname]
                    if tgt:
                        if "Hidden" in state_str:
                            st = WorksetVisibility.Hidden
                        elif "Visible" in state_str:
                            st = WorksetVisibility.Visible
                        else:
                            st = WorksetVisibility.UseGlobalSettings
                        viewB.SetWorksetVisibility(tgt[0].Id, st)
                        done.append(lab)
                except: pass

            elif kind == "link_settings" and HAS_RLGS:
                title = c[1]
                # settings from A
                pack = LINKS_CACHE.get(title)
                if not pack:
                    continue
                instA = pack["instances"][0]
                rlgsA = None
                try:
                    rlgsA = viewA.GetLinkOverrides(instA.Id) or viewA.GetLinkOverrides(pack["typeId"])
                except:
                    rlgsA = None
                if not rlgsA:
                    # if A has no explicit overrides -> copy "default By Host View" by clearing overrides on B type
                    instB, typeIdB = pack["instances"], pack["typeId"]
                    if typeIdB:
                        try:
                            # Clear overrides by setting a fresh object with ByHostView (defaults)
                            fresh = RevitLinkGraphicsSettings()
                            viewB.SetLinkOverrides(typeIdB, fresh)  # resets to default for type
                            done.append(lab + " (reset to default)")
                        except:
                            pass
                else:
                    # set on type first (even if instances are hidden)
                    instB, typeIdB = pack["instances"], pack["typeId"]
                    ok = False
                    if typeIdB:
                        try:
                            viewB.SetLinkOverrides(typeIdB, rlgsA)
                            ok = True
                        except:
                            ok = False
                    if not ok and instB:
                        try:
                            viewB.SetLinkOverrides(instB[0].Id, rlgsA)
                            ok = True
                        except:
                            ok = False
                    if ok:
                        done.append(lab)

        t.Commit()

    if done:
        out.print_md("### ✅ Applied changes")
        for d in done:
            out.print_md("- {}".format(d))
    else:
        out.print_md("### ⚠️ No changes applied.")

# ------------------------------------------------------------
# Diff builder (builds patchables too) -----------------------
def build_side_by_side(A, B, show_all=False):
    # 1) Global view settings
    rows = []
    rows.append(("Template", A["template"], B["template"]))
    rows.append(("Discipline", A["discipline"], B["discipline"]))
    rows.append(("Detail Level", A["detail"], B["detail"]))
    rows.append(("Display Style", A["display"], B["display"]))
    rows.append(("Phase", A["phase"], B["phase"]))
    rows.append(("Phase Filter", A["phase_filter"], B["phase_filter"]))
    rows.append(("Underlay", str(A["underlay"]), str(B["underlay"])))
    print_table("View — Global", rows, show_all)

    # 2) View Range (plan views)
    if A["vrange"] or B["vrange"]:
        vr_rows = []
        keys = ["Top","Cut","Bottom","View Depth"]
        for k in keys:
            a = A["vrange"].get(k) if A["vrange"] else None
            b = B["vrange"].get(k) if B["vrange"] else None
            vr_rows.append((k, a, b))
        print_table("View Range", vr_rows, show_all)

    # 3) VG per group
    for g in ["Model", "Annotation", "Analytical", "Revit Links"]:
        print_vg_group(g, A["vg"].get(g, {}), B["vg"].get(g, {}), show_all)

    # 4) Filters
    f_rows = []
    fnames = sorted(set(list(A["filters"].keys()) + list(B["filters"].keys())), key=lambda x: x.lower())
    for fn in fnames:
        ai = A["filters"].get(fn)
        bi = B["filters"].get(fn)
        f_rows.append((fn + " — present", str(ai is not None), str(bi is not None)))
        f_rows.append((fn + " — visible", str(ai["visible"] if ai else None), str(bi["visible"] if bi else None)))
        f_rows.append((fn + " — overrides", ai["overrides"] if ai else "—", bi["overrides"] if bi else "—"))
    print_table("Filters", f_rows, show_all)

    # 5) Worksets
    ws_rows = []
    wnames = sorted(set(list(A["worksets"].keys()) + list(B["worksets"].keys())), key=lambda x: x.lower())
    for wn in wnames:
        ws_rows.append((wn, A["worksets"].get(wn), B["worksets"].get(wn)))
    print_table("Worksets", ws_rows, show_all)

    # 6) Revit Links (effective mode)
    lk_rows = []
    for title in sorted(set(list(A["links"].keys()) + list(B["links"].keys())), key=lambda x: x.lower()):
        ai = A["links"].get(title, {})
        bi = B["links"].get(title, {})
        lk_rows.append((title + " — Mode", ai.get("mode"), bi.get("mode")))
        lk_rows.append((title + " — Linked View", ai.get("linked_view"), bi.get("linked_view")))
        lk_rows.append((title + " — Phase", ai.get("phase"), bi.get("phase")))
        lk_rows.append((title + " — Phase Filter", ai.get("phase_filter"), bi.get("phase_filter")))
    if not HAS_RLGS:
        out.print_md("> Note: Per‑link display details require Revit 2024+. Showing **effective defaults** only where possible.")
    print_table("Revit Links (effective)", lk_rows, show_all)

def find_patchables(A, B):
    patch = []
    # Globals
    if A["discipline"] != B["discipline"]:
        patch.append(("discipline", A["discipline"]))
    if A["detail"] != B["detail"]:
        patch.append(("detail", None))
    if A["display"] != B["display"]:
        patch.append(("display", None))
    if A["phase"] != B["phase"]:
        patch.append(("phase", A["phase_id"]))
    if A["phase_filter"] != B["phase_filter"]:
        patch.append(("phase_filter", A["phase_filter_id"]))
    if A["underlay"] != B["underlay"]:
        patch.append(("underlay", None))
    if A["vrange"] != B["vrange"] and (A["vrange"] or B["vrange"]):
        patch.append(("vrange", None))

    # VG vis + overrides
    for g in ["Model", "Annotation", "Analytical", "Revit Links"]:
        ak = A["vg"].get(g, {}); bk = B["vg"].get(g, {})
        for cname in set(list(ak.keys()) + list(bk.keys())):
            a = ak.get(cname); b = bk.get(cname)
            if a and b:
                if a[0] != b[0]:
                    patch.append(("vg_vis", cname, a[0]))
                if a[1] != b[1]:
                    patch.append(("vg_ogs", cname))
            elif a and not b:
                # present in A only — apply vis+ogs
                patch.append(("vg_vis", cname, a[0]))
                patch.append(("vg_ogs", cname))
            # if in B only: nothing to copy from A

    # Filters
    af = A["filters"]; bf = B["filters"]
    for fn in set(list(af.keys()) + list(bf.keys())):
        ai = af.get(fn); bi = bf.get(fn)
        if ai and not bi:
            patch.append(("filter_add", fn, ai))
        elif ai and bi:
            if ai["visible"] != bi["visible"] or ai["overrides"] != bi["overrides"]:
                patch.append(("filter_sync", fn, ai))

    # Worksets
    for wn in set(list(A["worksets"].keys()) + list(B["worksets"].keys())):
        av = A["worksets"].get(wn); bv = B["worksets"].get(wn)
        if av != bv and av is not None:
            patch.append(("workset", wn, av))

    # Revit Links (copy settings from A to B)
    for title in set(list(A["links"].keys()) + list(B["links"].keys())):
        ai = A["links"].get(title); bi = B["links"].get(title)
        if not ai or not bi:
            continue
        # copy when any effective field differs
        if (ai.get("mode") != bi.get("mode") or
            ai.get("linked_view") != bi.get("linked_view") or
            ai.get("phase") != bi.get("phase") or
            ai.get("phase_filter") != bi.get("phase_filter")):
            patch.append(("link_settings", title))
    return patch

# ------------------------------------------------------------
# UI ---------------------------------------------------------
def pick_view(prompt):
    views = [v for v in FilteredElementCollector(doc).OfClass(DBView) if not v.IsTemplate]
    labs  = [get_view_label(v) for v in views]
    chosen = forms.SelectFromList.show(sorted(labs), title=prompt, multiselect=False, button_name="Select")
    if not chosen:
        script.exit()
    for v in views:
        if get_view_label(v) == chosen:
            return v
    script.exit()

def main():
    if doc is None:
        forms.alert("No active document."); return

    viewA = pick_view("Select View A (source)")
    viewB = pick_view("Select View B (target)")

    mode = forms.alert("Output mode?", options=["Differences only (recommended)", "Show everything"])
    show_all = (mode == "Show everything")

    out.print_md("## 🔍 View Compare — Side-by-Side (VG Deep)")
    out.print_md("**A:** {}  \n**B:** {}".format(get_view_label(viewA), get_view_label(viewB)))
    if not HAS_RLGS:
        out.print_md("> Revit 2024+ is required for deep per‑link display details. Using safe defaults.")

    A = snapshot_view(viewA)
    B = snapshot_view(viewB)

    # Side-by-side tables
    build_side_by_side(A, B, show_all)

    # Offer patch
    patchables = find_patchables(A, B)
    if forms.alert("Apply selected differences A → B?", options=["Just Report", "Select & Patch"]) == "Select & Patch":
        # Warning if B uses a template
        vt = get_template(viewB)
        if vt:
            forms.alert("View B uses template '{}'. Selected changes may be written to the TEMPLATE and affect all views using it.".format(vt.Name))
        patch_from_choices(viewA, viewB, patchables)

main()
