# -*- coding: utf-8 -*-
__title__  = 'Colour Source Diagnostic'
__author__ = 'PD'
__doc__    = """Dump the ACTIVE view's space/room colour source + overrides.
Identifies whether the on-screen colour comes from a Color Fill Scheme,
view Filters, or a linked model, and lists every relevant override so a
'shows on screen but will not plot' issue can be diagnosed.

Open the RCP view (not the sheet), then run.
Writes C:\\Dev\\revit_view_diag.txt and prints to the pyRevit output window.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import codecs
import System
from Autodesk.Revit.DB import *
from pyrevit import revit, script

try:
    from Autodesk.Revit.DB import LabelUtils
except:
    LabelUtils = None

doc  = revit.doc
view = revit.active_view
out  = script.get_output()

OUT = r"C:\Dev\revit_view_diag.txt"
lines = []

def w(s):
    try:
        lines.append(s if isinstance(s, unicode) else unicode(str(s)))
    except:
        lines.append(u"<unprintable>")

def hdr(t):
    w(u"")
    w(u"===== " + t + u" =====")

def patname(pid):
    try:
        if pid and pid.IntegerValue != -1:
            el = doc.GetElement(pid)
            if el is not None:
                return el.Name
    except:
        pass
    return "<none>"

def param_name(pid):
    try:
        iv = pid.IntegerValue
        if iv < 0:
            bip = None
            try:
                bip = System.Enum.ToObject(BuiltInParameter, iv)
            except:
                bip = None
            if bip is not None and LabelUtils is not None:
                try:
                    return LabelUtils.GetLabelFor(bip)
                except:
                    pass
            return "BIP({0})".format(iv)
        el = doc.GetElement(pid)
        if el is not None:
            try:
                return el.Name
            except:
                try:
                    return el.GetDefinition().Name
                except:
                    return "param({0})".format(iv)
    except:
        pass
    return "?"

def rule_value(r):
    for attr in ("RuleString", "RuleValue"):
        try:
            v = getattr(r, attr)
            if v is not None:
                return v
        except:
            pass
    return "?"

def rule_param(r):
    try:
        return param_name(r.GetRuleParameter())
    except Exception as e:
        return "err:{0}".format(e)

cat_map = [("Rooms", BuiltInCategory.OST_Rooms),
           ("MEP Spaces", BuiltInCategory.OST_MEPSpaces),
           ("Areas", BuiltInCategory.OST_Areas)]

# --- View basics ---
hdr("VIEW")
w("Name: {0}".format(view.Name))
w("Type: {0}".format(view.ViewType))
w("Id: {0}".format(view.Id.IntegerValue))
w("IsSheet: {0}".format(isinstance(view, ViewSheet)))
try:
    w("IsTemplate: {0}".format(view.IsTemplate))
except: pass
try:
    vtid = view.ViewTemplateId
    if vtid and vtid.IntegerValue != -1:
        vt = doc.GetElement(vtid)
        w("ViewTemplate: {0} (id {1})".format(vt.Name if vt else "?", vtid.IntegerValue))
    else:
        w("ViewTemplate: <none>")
except Exception as e:
    w("ViewTemplate: err {0}".format(e))
try:
    w("Discipline: {0}".format(view.Discipline))
except: pass
try:
    w("DetailLevel: {0}".format(view.DetailLevel))
except: pass

# --- Color fill schemes assigned to this view ---
hdr("COLOR FILL SCHEMES (view-assigned)")
for label, bic in cat_map:
    try:
        catId = ElementId(bic)
        sid = view.GetColorFillSchemeId(catId)
        if sid and sid.IntegerValue != -1:
            sch = doc.GetElement(sid)
            nm = sch.Name if sch else "?"
            w("{0}: SCHEME APPLIED -> '{1}' (id {2})".format(label, nm, sid.IntegerValue))
            try:
                ents = sch.GetEntries()
                cnt = ents.Size if hasattr(ents, "Size") else len(list(ents))
                w("   entries: {0}".format(cnt))
            except Exception as e:
                w("   entries err: {0}".format(e))
        else:
            w("{0}: <no scheme>".format(label))
    except Exception as e:
        w("{0}: err {1}".format(label, e))

# --- View filters + overrides ---
hdr("FILTERS ON VIEW")
try:
    fids = view.GetFilters()
    w("count: {0}".format(len(list(fids))))
    for fid in fids:
        fel = doc.GetElement(fid)
        fname = fel.Name if fel else "?"
        try:
            vis = view.GetFilterVisibility(fid)
        except:
            vis = "?"
        w("")
        w("- {0} | visible={1}".format(fname, vis))
        try:
            ogs = view.GetFilterOverrides(fid)
            try:
                fgvis = ogs.IsSurfaceForegroundPatternVisible
            except:
                fgvis = "?"
            fpid = ogs.SurfaceForegroundPatternId
            col = ogs.SurfaceForegroundPatternColor
            colstr = "invalid"
            if col and col.IsValid:
                colstr = "{0},{1},{2}".format(col.Red, col.Green, col.Blue)
            w("   surf-fg: visible={0} pattern='{1}' color={2}".format(fgvis, patname(fpid), colstr))
            try:
                bgvis = ogs.IsSurfaceBackgroundPatternVisible
            except:
                bgvis = "?"
            bpid = ogs.SurfaceBackgroundPatternId
            bcol = ogs.SurfaceBackgroundPatternColor
            bcolstr = "invalid"
            if bcol and bcol.IsValid:
                bcolstr = "{0},{1},{2}".format(bcol.Red, bcol.Green, bcol.Blue)
            w("   surf-bg: visible={0} pattern='{1}' color={2}".format(bgvis, patname(bpid), bcolstr))
            w("   transparency: {0}".format(ogs.Transparency))
            w("   halftone: {0}".format(ogs.Halftone))
        except Exception as e:
            w("   overrides err: {0}".format(e))
        # rules (only for the space/litecom filters, to identify the driving parameter)
        if "IsSpace" in fname or "Litecom" in fname:
            try:
                if hasattr(fel, "GetRules"):
                    for r in fel.GetRules():
                        w("   rule: param='{0}' value='{1}'".format(rule_param(r), rule_value(r)))
                else:
                    w("   rule: <no GetRules on this filter>")
            except Exception as e:
                w("   rules err: {0}".format(e))
except Exception as e:
    w("filters err: {0}".format(e))

# --- Category-level overrides + visibility ---
hdr("CATEGORY OVERRIDES / VISIBILITY")
for label, bic in cat_map:
    try:
        catId = ElementId(bic)
        try:
            hidden = view.GetCategoryHidden(catId)
        except:
            hidden = "?"
        w("{0}: hidden={1}".format(label, hidden))
        try:
            ogs = view.GetCategoryOverrides(catId)
            w("   transparency={0} halftone={1} surf-fg-pattern='{2}'".format(
                ogs.Transparency, ogs.Halftone, patname(ogs.SurfaceForegroundPatternId)))
        except Exception as e:
            w("   catov err: {0}".format(e))
    except Exception as e:
        w("{0}: err {1}".format(label, e))

# --- Elements visible in this view (host) ---
hdr("ELEMENTS IN VIEW (host)")
for label, bic in cat_map:
    try:
        col = FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        w("{0}: {1} visible".format(label, len(col)))
    except Exception as e:
        w("{0}: err {1}".format(label, e))

# --- Linked models ---
hdr("LINKED MODELS")
try:
    links = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    w("count: {0}".format(len(links)))
    for lk in links:
        try:
            nm = lk.Name
        except:
            nm = "?"
        w("- {0}".format(nm))
except Exception as e:
    w("links err: {0}".format(e))

hdr("END")
try:
    f = codecs.open(OUT, "w", "utf-8")
    f.write(u"\n".join(lines))
    f.close()
    out.print_md("**Diagnostic written to:** `{0}`".format(OUT))
except Exception as e:
    out.print_md("**WRITE FAILED:** {0}".format(e))

for l in lines:
    try:
        print(l)
    except:
        print("<line>")
