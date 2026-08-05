# -*- coding: utf-8 -*-
__title__   = "Hide: Linked\nSelection"
__doc__     = """Version = 1.0
Date    = 2026-07-18
________________________________________________________________
Description:

Hide the SELECTED linked elements in the current view (or its
view template) - as close to per-element as Revit allows.

Revit cannot hide individual linked elements by id (no per-element
hide, no id-based filter rules, selection filters do not evaluate
against links). This tool gets as close as possible:

1) Select linked elements (TAB into links), run the tool
   (host elements in the selection are hidden directly).
2) Elements are grouped by link + category + type.
3) For each group the tool builds the TIGHTEST rule-based filter
   that matches the selection: Family Name + Type Name, then
   narrowed further by Mark / Comments / Length / Elevation /
   Volume where those distinguish the selected elements from
   identical-type siblings (per-element signatures OR-ed together).
4) The filter is verified by actually running it against the host
   and every loaded link: the report states exactly how many
   elements it matches and lists any UNSELECTED elements that get
   caught (parameter-identical siblings cannot be separated -
   that is a Revit limit, and the report tells you when it happens).
5) Filter is applied with visibility OFF to the view template if
   one is assigned, otherwise to the active view.

Filter naming: PD_pY_HideLnk_<CategoryShort>_<TypeName>
Unhide: V/G > Filters > tick the PD_pY_HideLnk_* filter visibility
back on (or remove the filter from the view/template).
________________________________________________________________
Get Free:
BIM & Electrical Knowledge:  https://projectdesign.io/knowledgehub/
Design Tools: https://projectdesign.io/tools/
Documents, files, Revit families: https://projectdesign.io/downloads/
________________________________________________________________
Author: Jarek Wityk"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ParameterFilterElement,
    ElementParameterFilter,
    ParameterFilterRuleFactory,
    LogicalOrFilter,
    ElementFilter,
    ElementId,
    BuiltInParameter,
    StorageType,
    Transaction,
    RevitLinkInstance,
    Element,
    View
)
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

from pyrevit import revit, forms, script


doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

FILTER_PREFIX = "PD_pY_HideLnk"
DOUBLE_TOL = 1.0e-6

# Candidate narrowing parameters, tried in order.
# (BuiltInParameter name, storage kind 's'tring / 'd'ouble)
CANDIDATE_BIPS = [
    ("ALL_MODEL_MARK", "s"),
    ("ALL_MODEL_INSTANCE_COMMENTS", "s"),
    ("INSTANCE_LENGTH_PARAM", "d"),
    ("CURVE_ELEM_LENGTH", "d"),
    ("STRUCTURAL_FRAME_CUT_LENGTH", "d"),
    ("STRUCTURAL_ELEVATION_AT_TOP", "d"),
    ("STRUCTURAL_ELEVATION_AT_BOTTOM", "d"),
    ("INSTANCE_ELEVATION_PARAM", "d"),
    ("INSTANCE_FREE_HOST_OFFSET_PARAM", "d"),
    ("RBS_OFFSET_PARAM", "d"),
    ("HOST_VOLUME_COMPUTED", "d"),
]


# -----------------------------------------------------------
# Version-safe rule creation (Revit 2023+ dropped caseSensitive)
# -----------------------------------------------------------

def make_equals_rule(param_id, value, kind):
    if kind == "s":
        try:
            return ParameterFilterRuleFactory.CreateEqualsRule(
                param_id, value)
        except Exception:
            return ParameterFilterRuleFactory.CreateEqualsRule(
                param_id, value, False)
    else:
        return ParameterFilterRuleFactory.CreateEqualsRule(
            param_id, value, DOUBLE_TOL)


def rule_applicable(param_id, cat_id, kind):
    """Can this parameter be used in a filter for this category?"""
    cat_ids = List[ElementId]()
    cat_ids.Add(cat_id)
    try:
        test_val = "x" if kind == "s" else 1.0
        rule = make_equals_rule(param_id, test_val, kind)
        epf = ElementParameterFilter(rule)
        return ParameterFilterElement.AllRuleParametersApplicable(
            doc, cat_ids, epf)
    except Exception:
        return False


# -----------------------------------------------------------
# Value reading
# -----------------------------------------------------------

def read_value(el, bip, kind):
    """Read a comparable value or None."""
    try:
        p = el.get_Parameter(bip)
        if p is None or not p.HasValue:
            return None
        if kind == "s":
            v = p.AsString()
            if v is None or len(v.strip()) == 0:
                return None
            return v
        else:
            if p.StorageType != StorageType.Double:
                return None
            return p.AsDouble()
    except Exception:
        return None


def values_equal(a, b, kind):
    if a is None or b is None:
        return False
    if kind == "s":
        return a == b
    return abs(a - b) <= DOUBLE_TOL


def get_name_safe(el):
    try:
        return Element.Name.GetValue(el)
    except Exception:
        try:
            p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            return p.AsString() if p else "?"
        except Exception:
            return "?"


def get_type_names(el):
    """(family_name, type_name) read from the element's type."""
    fname = ""
    tname = ""
    try:
        et = el.Document.GetElement(el.GetTypeId())
        if et is not None:
            try:
                fp = et.get_Parameter(
                    BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if fp and fp.HasValue:
                    fname = fp.AsString() or ""
            except Exception:
                pass
            tname = get_name_safe(et) or ""
    except Exception:
        pass
    return fname, tname


# -----------------------------------------------------------
# Selection
# -----------------------------------------------------------

def gather_selection():
    """Returns (host_ids, linked_items).
    linked_items = list of (link_doc, linked_element)."""
    host_ids = []
    linked_items = []

    refs = []
    try:
        refs = list(uidoc.Selection.GetReferences())
    except Exception:
        refs = []

    # Also include plain element selection (host elements)
    try:
        for eid in uidoc.Selection.GetElementIds():
            el = doc.GetElement(eid)
            if el is not None and not isinstance(el, RevitLinkInstance):
                host_ids.append(eid)
    except Exception:
        pass

    if not refs and not host_ids:
        # Nothing pre-selected: multi-pick with TAB into links
        try:
            refs = list(uidoc.Selection.PickObjects(
                ObjectType.LinkedElement,
                "Select linked elements to hide (TAB into links). "
                "Finish to run. ESC cancels."))
        except Exception:
            refs = []

    for r in refs:
        try:
            lid = r.LinkedElementId
            host_el = doc.GetElement(r.ElementId)
            if lid and lid != ElementId.InvalidElementId and \
                    isinstance(host_el, RevitLinkInstance):
                ldoc = host_el.GetLinkDocument()
                if ldoc is not None:
                    lel = ldoc.GetElement(lid)
                    if lel is not None:
                        linked_items.append((ldoc, lel))
                continue
            if host_el is not None and \
                    not isinstance(host_el, RevitLinkInstance):
                host_ids.append(r.ElementId)
        except Exception:
            pass

    return host_ids, linked_items


# -----------------------------------------------------------
# All documents the filter will act on (host + loaded links)
# -----------------------------------------------------------

def all_visible_docs():
    docs = [doc]
    seen = set()
    try:
        for li in FilteredElementCollector(doc) \
                .OfClass(RevitLinkInstance):
            ld = li.GetLinkDocument()
            if ld is None:
                continue
            key = ld.Title
            if key not in seen:
                seen.add(key)
                docs.append(ld)
    except Exception:
        pass
    return docs


def collect_matches(elem_filter, cat_id, docs):
    """Run the candidate filter in every doc.
    Returns list of (doc, element)."""
    hits = []
    for d in docs:
        try:
            for e in FilteredElementCollector(d) \
                    .OfCategoryId(cat_id) \
                    .WhereElementIsNotElementType() \
                    .WherePasses(elem_filter):
                hits.append((d, e))
        except Exception:
            pass
    return hits


# -----------------------------------------------------------
# Filter building
# -----------------------------------------------------------

def base_rules(cat_id, fam_name, type_name):
    rules = []
    fam_id = ElementId(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
    typ_id = ElementId(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    if fam_name and rule_applicable(fam_id, cat_id, "s"):
        rules.append(make_equals_rule(fam_id, fam_name, "s"))
    if type_name and rule_applicable(typ_id, cat_id, "s"):
        rules.append(make_equals_rule(typ_id, type_name, "s"))
    return rules


def build_group_filter(cat_id, fam_name, type_name,
                       selected, others):
    """Build the tightest ElementFilter for this group.
    selected/others = lists of elements (same category+type).
    Returns (elem_filter, isolated_bool)."""

    base = base_rules(cat_id, fam_name, type_name)
    if not base:
        return None, False

    base_filter = ElementParameterFilter(_to_rule_list(base))

    if not others:
        return base_filter, True

    # Try one shared narrowing rule first: a param where every
    # selected element has the same value and no other does.
    usable = []
    for bip_name, kind in CANDIDATE_BIPS:
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        pid = ElementId(bip)
        if rule_applicable(pid, cat_id, kind):
            usable.append((bip, pid, kind))

    for bip, pid, kind in usable:
        vals = [read_value(e, bip, kind) for e in selected]
        if any(v is None for v in vals):
            continue
        first = vals[0]
        if not all(values_equal(v, first, kind) for v in vals):
            continue
        if any(values_equal(read_value(o, bip, kind), first, kind)
               for o in others):
            continue
        rules = list(base)
        rules.append(make_equals_rule(pid, first, kind))
        return ElementParameterFilter(_to_rule_list(rules)), True

    # Per-element signatures OR-ed together
    per_el_filters = []
    all_isolated = True
    for e in selected:
        found = None
        for bip, pid, kind in usable:
            v = read_value(e, bip, kind)
            if v is None:
                continue
            if any(values_equal(read_value(o, bip, kind), v, kind)
                   for o in others):
                continue
            found = (pid, v, kind)
            break
        if found is None:
            all_isolated = False
            continue
        rules = list(base)
        rules.append(make_equals_rule(found[0], found[1], found[2]))
        per_el_filters.append(ElementParameterFilter(
            _to_rule_list(rules)))

    if per_el_filters and all_isolated:
        if len(per_el_filters) == 1:
            return per_el_filters[0], True
        fl = List[ElementFilter]()
        for f in per_el_filters:
            fl.Add(f)
        return LogicalOrFilter(fl), True

    # Cannot isolate: fall back to base (catches siblings too)
    return base_filter, False


def _to_rule_list(rules):
    from Autodesk.Revit.DB import FilterRule
    rl = List[FilterRule]()
    for r in rules:
        rl.Add(r)
    return rl


# -----------------------------------------------------------
# Naming / applying
# -----------------------------------------------------------

def sanitize(s, maxlen=40):
    keep = []
    for c in s.replace(" ", "_"):
        if c.isalnum() or c in ("_", "-"):
            keep.append(c)
    return "".join(keep)[:maxlen]


def shorten_category(cat_name):
    if not cat_name:
        return "El"
    parts = cat_name.replace("-", " ").split()
    if len(parts) == 1:
        return cat_name[:8]
    return "".join([w[0].upper() for w in parts if w])[:8]


def unique_filter_name(base_name, existing_names):
    if base_name not in existing_names:
        return base_name
    n = 2
    while True:
        cand = "{}_{}".format(base_name, n)
        if cand not in existing_names:
            return cand
        n += 1


def get_hide_target(view):
    """View template if assigned, else the view itself."""
    try:
        vt_id = view.ViewTemplateId
        if vt_id and vt_id != ElementId.InvalidElementId:
            vt = doc.GetElement(vt_id)
            if isinstance(vt, View):
                return vt, True
    except Exception:
        pass
    return view, False


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------

def main():
    host_ids, linked_items = gather_selection()
    if not host_ids and not linked_items:
        forms.alert("Nothing selected.", exitscript=True)

    active_view = doc.ActiveView
    target, is_template = get_hide_target(active_view)

    docs = all_visible_docs()

    # Group linked elements: (doc_title, cat_int, type_int) -> data
    groups = {}
    for ldoc, lel in linked_items:
        try:
            cat = lel.Category
            if cat is None:
                continue
            key = (ldoc.Title, cat.Id.IntegerValue,
                   lel.GetTypeId().IntegerValue)
            if key not in groups:
                groups[key] = {"doc": ldoc, "cat_id": cat.Id,
                               "cat_name": cat.Name, "els": []}
            groups[key]["els"].append(lel)
        except Exception:
            pass

    existing_names = set()
    for pf in FilteredElementCollector(doc) \
            .OfClass(ParameterFilterElement):
        try:
            existing_names.add(pf.Name)
        except Exception:
            pass

    report = []
    warn_lines = []

    t = Transaction(doc, "PD_pY Hide Linked Selection")
    t.Start()
    try:
        # 1) host elements: plain per-element hide
        if host_ids:
            hideable = List[ElementId]()
            for eid in host_ids:
                try:
                    el = doc.GetElement(eid)
                    if el is not None and \
                            el.CanBeHidden(active_view):
                        hideable.Add(eid)
                except Exception:
                    pass
            if hideable.Count > 0:
                active_view.HideElements(hideable)
                report.append("Host elements hidden directly: {}"
                              .format(hideable.Count))

        # 2) linked groups: tightest possible rule filter
        for key in groups:
            g = groups[key]
            ldoc = g["doc"]
            cat_id = g["cat_id"]
            sel = g["els"]
            sel_ids = set([e.Id.IntegerValue for e in sel])
            fam_name, type_name = get_type_names(sel[0])

            # all same-type instances across host + every link
            type_pool = []
            for d in docs:
                try:
                    for e in FilteredElementCollector(d) \
                            .OfCategoryId(cat_id) \
                            .WhereElementIsNotElementType():
                        f2, t2 = get_type_names(e)
                        if f2 == fam_name and t2 == type_name:
                            type_pool.append((d, e))
                except Exception:
                    pass
            others = [e for (d, e) in type_pool
                      if not (d.Title == ldoc.Title and
                              e.Id.IntegerValue in sel_ids)]

            elem_filter, isolated = build_group_filter(
                cat_id, fam_name, type_name, sel, others)
            if elem_filter is None:
                warn_lines.append(
                    "SKIPPED {} : {} - family/type name not "
                    "filterable for this category.".format(
                        fam_name, type_name))
                continue

            # verify what the filter really matches
            hits = collect_matches(elem_filter, cat_id, docs)
            extras = [(d, e) for (d, e) in hits
                      if not (d.Title == ldoc.Title and
                              e.Id.IntegerValue in sel_ids)]

            fname = unique_filter_name(
                "{}_{}_{}".format(FILTER_PREFIX,
                                  shorten_category(g["cat_name"]),
                                  sanitize(type_name)),
                existing_names)
            existing_names.add(fname)

            cat_ids = List[ElementId]()
            cat_ids.Add(cat_id)
            pfe = ParameterFilterElement.Create(
                doc, fname, cat_ids, elem_filter)

            if not target.IsFilterApplied(pfe.Id):
                target.AddFilter(pfe.Id)
            target.SetFilterVisibility(pfe.Id, False)

            line = "`{}` -> hides {} matched ({} selected)".format(
                fname, len(hits), len(sel))
            report.append(line)
            if extras:
                ex_desc = ", ".join(
                    ["{} id {}".format(d.Title, e.Id.IntegerValue)
                     for (d, e) in extras[:10]])
                warn_lines.append(
                    "`{}` ALSO hides {} unselected identical "
                    "element(s): {}{}".format(
                        fname, len(extras), ex_desc,
                        "..." if len(extras) > 10 else ""))

        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        forms.alert("Error:\n{}".format(ex), exitscript=True)

    # ---- report ----
    out.print_md("## Hide Linked Selection")
    out.print_md("* Applied to: `{}` ({})".format(
        target.Name, "view template" if is_template else "view"))
    for line in report:
        out.print_md("* " + line)
    if warn_lines:
        out.print_md("### Warnings")
        for w in warn_lines:
            out.print_md("* " + w)
        out.print_md(
            "*Parameter-identical linked elements cannot be "
            "separated by any Revit filter - the extras above are "
            "hidden too. If they must stay visible, the only fix "
            "is a distinguishing value (e.g. Mark) added in the "
            "link source model.*")

    if not report and not warn_lines:
        forms.alert("Nothing was hidden.")


if __name__ == "__main__":
    main()
