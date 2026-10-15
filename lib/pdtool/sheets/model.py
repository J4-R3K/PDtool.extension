# -*- coding: utf-8 -*-
"""What PD Sheets reads from the model: sheets and views, their parameters, title block sizes, View/Sheet Sets, and
the views Revit may turn into images (rasterise) in a PDF. Reads only: no transaction, nothing borrowed.

Needs Revit. Names used here are in the Revit API for 2023 to 2026; where a name may be missing in an older release
it is looked up with getattr and the check is reported as not made, never guessed.
"""
import clr

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, DisplayStyle, ElementId, FilteredElementCollector,
                               ImageInstance, ImportInstance, StorageType, View, ViewSheet, ViewSheetSet, ViewType)

from pdtool import id_value
from pdtool.sheets import extra, paper

FEET_TO_MM = 304.8

# Visual styles Revit exports as lines (vector); every other style is rasterised.
_VECTOR_STYLES = (DisplayStyle.Undefined, DisplayStyle.Wireframe, DisplayStyle.HLR)

# Visual styles as Revit names them in the View Control Bar.
_STYLE_NAMES = {u"Shading": u"Shaded", u"ShadingWithEdges": u"Shaded with edges", u"Realistic": u"Realistic",
                u"RealisticWithEdges": u"Realistic with edges", u"FlatColors": u"Consistent colours",
                u"Rendering": u"Rendering", u"Textures": u"Textures"}

# View types that are never exported on their own.
_NOT_EXPORTED = (ViewType.ProjectBrowser, ViewType.SystemBrowser, ViewType.Internal, ViewType.Undefined,
                 ViewType.DrawingSheet)


# StorageType.None, written so: "None" cannot follow a dot in Python 3.
_NO_STORAGE = getattr(StorageType, "None")


def is_button(param):
    """True for a parameter Revit shows as a button in Properties, with no value of its own: "Revisions on Sheet"
    (its Edit button lists the revisions shown on the sheet), "View Range", "Visibility/Graphics Overrides"."""
    return param is not None and param.StorageType == _NO_STORAGE


def _text(param):
    if param is None:
        return None
    if param.StorageType == StorageType.String:
        return param.AsString() or u""
    if param.StorageType == StorageType.ElementId and id_value(param.AsElementId()) == -1:
        # no element chosen: Revit shows "<None>", which is not a value for a file name
        return u""
    if is_button(param):
        return u""
    return param.AsValueString() or u""


def value_getter(doc, no_text=None):
    """value_of(element, part) for names.build: the parameter's text, or None when the parameter does not exist.
    A part's source is "project" (project information), "sheet" (the sheet or view being exported) or "" (the sheet
    or view first, then project information).

    no_text: a set the caller keeps; the name of each parameter found to be a button (is_button) is added to it, so
    the window can say it must come out of the rule (names.missing_text)."""
    info = doc.ProjectInformation

    def read(element, name):
        p = element.LookupParameter(name)
        if no_text is not None and is_button(p):
            no_text.add(name)
        return _text(p)

    def value_of(element, part):
        name, source = part["param"], part.get("source") or u""
        if source in (u"sheet", u""):
            v = read(element, name)
            if v is not None or source == u"sheet":
                return v
        return read(info, name)
    return value_of


def parameter_names(doc, sample_sheet=None, sample_view=None):
    """[(name, source)] for the naming rule editor: every parameter of a sheet (or view) and of project information,
    except the buttons (is_button), which give no value."""
    out = set()
    for element, source in ((sample_sheet, u"sheet"), (sample_view, u"sheet"), (doc.ProjectInformation, u"project")):
        if element is None:
            continue
        for p in element.Parameters:
            try:
                if not is_button(p):
                    out.add((p.Definition.Name, source))
            except Exception:
                pass
    return sorted(out, key=lambda x: (x[1] != u"sheet", x[0].lower()))


def title_block_sizes(doc):
    """{sheet id: (width mm, height mm)} from each sheet's title block. Where a sheet has more than one, the largest."""
    out = {}
    blocks = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType()
    for tb in blocks:
        try:
            w = tb.get_Parameter(BuiltInParameter.SHEET_WIDTH).AsDouble() * FEET_TO_MM
            h = tb.get_Parameter(BuiltInParameter.SHEET_HEIGHT).AsDouble() * FEET_TO_MM
        except Exception:
            continue
        key = id_value(tb.OwnerViewId)
        if key not in out or w * h > out[key][0] * out[key][1]:
            out[key] = (w, h)
    return out


def sheets(doc):
    """One dict per sheet, sorted by number. Placeholder sheets (not drawn in this model) are left out."""
    sizes = title_block_sizes(doc)
    out = []
    for s in FilteredElementCollector(doc).OfClass(ViewSheet):
        if s.IsPlaceholder or s.IsTemplate:
            continue
        w, h = sizes.get(id_value(s.Id), (None, None))
        size, orientation = paper.sheet_size(w, h)
        out.append({
            "key": s.UniqueId, "id": id_value(s.Id), "kind": u"sheet", "element": s,
            "number": s.SheetNumber or u"", "name": s.Name or u"",
            "revision": _text(s.get_Parameter(BuiltInParameter.SHEET_CURRENT_REVISION)) or u"",
            "width_mm": w, "height_mm": h, "size": size or u"No title block", "orientation": orientation or u"",
        })
    out.sort(key=lambda x: x["number"].lower())
    return out


def first_view(doc):
    """One view that can be exported, so the naming rule editor can list the parameters views have and sheets do not."""
    for v in FilteredElementCollector(doc).OfClass(View):
        if not v.IsTemplate and not isinstance(v, ViewSheet) and v.ViewType not in _NOT_EXPORTED:
            return v
    return None


def views(doc):
    """One dict per view that can be printed on its own (not sheets, not view templates), sorted by name."""
    out = []
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate or isinstance(v, ViewSheet) or v.ViewType in _NOT_EXPORTED:
            continue
        try:
            if not v.CanBePrinted:
                continue
        except Exception:
            continue
        out.append({
            "key": v.UniqueId, "id": id_value(v.Id), "kind": u"view", "element": v,
            "number": u"", "name": v.Name or u"", "revision": u"", "type": u"{}".format(v.ViewType),
            "width_mm": None, "height_mm": None, "size": u"", "orientation": u"",
        })
    out.sort(key=lambda x: x["name"].lower())
    return out


def sheet_sets(doc):
    """{set name: set of element ids (int)} for every View/Sheet Set saved in the model."""
    out = {}
    for vs in FilteredElementCollector(doc).OfClass(ViewSheetSet):
        ids = set()
        for v in vs.Views:
            ids.add(id_value(v.Id))
        out[vs.Name] = ids
    return out


def dwg_setups(doc):
    from Autodesk.Revit.DB import BaseExportOptions
    return list(BaseExportOptions.GetPredefinedSetupNames(doc))


def dgn_setups(doc):
    from Autodesk.Revit.DB import DGNExportOptions
    return list(DGNExportOptions.GetPredefinedSetupNames(doc))


# ---- what a DGN or DWG export draws, and views too large to export ---------------------------------------------

def drawn_views(doc, element):
    """The views an export of element draws: a sheet's placed views, or the view itself."""
    if not isinstance(element, ViewSheet):
        return [element]
    out = []
    for vid in element.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if v is not None:
            out.append(v)
    return out


def linked_cad(doc):
    """{type id (int): file name} for each linked CAD file in the model: an ImportInstance that is linked, not
    imported. The type's name is the CAD file's name ("Site plan.dwg", for example)."""
    out = {}
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        try:
            if not inst.IsLinked:
                continue
            key = id_value(inst.GetTypeId())
            if key in out:
                continue
            t = doc.GetElement(inst.GetTypeId())
            name = _text(t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)) if t is not None else None
        except Exception:
            continue
        if name:
            out[key] = name
    return out


def cad_shown(doc, element, cad):
    """The names of the linked CAD files in cad ({type id: name}, from linked_cad) that a DGN export of element
    draws: shown on the sheet itself, in one of its views, or in the view. Needs one collector for each view, so the
    caller passes only the CAD files whose DGN is already in the folder, and nothing is searched for none."""
    if not cad:
        return []
    found = []
    seen = [element] + (drawn_views(doc, element) if isinstance(element, ViewSheet) else [])
    for v in seen:
        try:
            for inst in FilteredElementCollector(doc, v.Id).OfClass(ImportInstance):
                name = cad.get(id_value(inst.GetTypeId()))
                if name and name not in found:
                    found.append(name)
        except Exception:
            continue
    return found


def large_views(doc, element, cache):
    """[(view name, width ft, height ft)] for each view an export of element draws that has no crop region and is
    larger on paper than Revit draws (extra.too_large).

    View.Outline is read only for views with the crop region off: reading it makes Revit build the view's graphics,
    and it took 366 s for the 224 views of a project model (15/10/2026). cache: {view id: (name, width, height) or
    None}, kept by the caller, so a view on several sheets is read once."""
    out = []
    for v in drawn_views(doc, element):
        key = id_value(v.Id)
        if key not in cache:
            cache[key] = None
            try:
                crop = v.CropBoxActive
            except Exception:
                crop = True
            if not crop:
                try:
                    o = v.Outline
                    w, h = o.Max.U - o.Min.U, o.Max.V - o.Min.V
                    if extra.too_large(w, h, False):
                        cache[key] = (v.Name, w, h)
                except Exception:
                    pass
        if cache[key]:
            out.append(cache[key])
    return out


# ---- views that Revit will rasterise ------------------------------------------------------------------------------

class RasterChecker(object):
    """Lists, for a sheet or a view, each view Revit may rasterise in a PDF and why.

    "May": Revit rasterises a view where it draws anything one of these settings applies to, and the check reads the
    settings, not what the view draws. Check 4 (Revit 2024, 14/10/2026) found a view listed that Revit wrote as
    lines: on one sheet the view template sets transparency on Floors and in filter PD-WireIsOFF, and the view draws no
    floor of this model and nothing that passes the filter. Counting this model's elements alone is not enough: a view
    on another sheet draws no element of this model in its seven transparent categories, and Revit rasterised it because
    of the linked models. A collector for a view and a link (in the API for 2023 to 2026) could count those too; that
    is listed for the next build, so for now the setting is listed rather than guessed.

    Causes checked: a visual style other than wireframe or hidden line; transparency set for the view, for a
    category or for a filter (in the view or its view template); sketchy lines; shadows; raster images and imported
    PDFs (Revit places a PDF as an image) in the view or on the sheet itself; rendered images.
    Not checked: transparency set on one element, and settings inside linked models."""

    def __init__(self, doc):
        self.doc = doc
        self._overrides = {}
        self._categories = []
        for c in doc.Settings.Categories:
            try:
                self._categories.append((c.Id, c.Name))
            except Exception:
                pass
        self._shadow_param = getattr(BuiltInParameter, "GRAPHIC_DISPLAY_OPTIONS_SHADOWS", None)
        self._image_counts = None

    def _transparency(self, view):
        """Reasons from transparency set in one view or view template (cached by its id)."""
        key = id_value(view.Id)
        if key in self._overrides:
            return self._overrides[key]
        cats, filters = [], []
        for cid, cname in self._categories:
            try:
                if view.GetCategoryOverrides(cid).Transparency > 0:
                    cats.append(cname)
            except Exception:
                pass
        try:
            for fid in view.GetFilters():
                if not view.GetFilterVisibility(fid):
                    continue
                enabled = getattr(view, "GetIsFilterEnabled", None)
                if enabled is not None and not enabled(fid):
                    continue
                if view.GetFilterOverrides(fid).Transparency > 0:
                    filters.append(self.doc.GetElement(fid).Name)
        except Exception:
            pass
        out = []
        if cats:
            out.append(u"transparency on {} {} ({})".format(
                len(cats), u"category" if len(cats) == 1 else u"categories", u", ".join(sorted(cats)[:5]) +
                (u", ..." if len(cats) > 5 else u"")))
        if filters:
            out.append(u"transparency in filter {}".format(u", ".join(sorted(filters))))
        self._overrides[key] = out
        return out

    def _count_images(self):
        """{view id: [imported PDFs, raster images]} for the whole model in one pass. Images are drawn in one view
        only (OwnerViewId), so no collector per view is needed. With a collector per view, the first check of
        56 sheets took 75 s and later checks under 1 s (14/10/2026); the cause was not isolated, most likely
        Revit preparing each view the first time it is asked."""
        counts = {}
        for img in FilteredElementCollector(self.doc).OfClass(ImageInstance):
            try:
                owner = id_value(img.OwnerViewId)
                t = self.doc.GetElement(img.GetTypeId())
                path = (getattr(t, "Path", u"") or u"").lower()
            except Exception:
                continue
            c = counts.setdefault(owner, [0, 0])
            c[0 if path.endswith(u".pdf") else 1] += 1
        return counts

    def _images(self, view):
        """Reasons from raster images and imported PDFs drawn in the view."""
        if self._image_counts is None:
            self._image_counts = self._count_images()
        out = []
        pdfs, images = self._image_counts.get(id_value(view.Id), (0, 0))
        if pdfs:
            out.append(u"{} imported PDF{} (placed as an image)".format(pdfs, u"" if pdfs == 1 else u"s"))
        if images:
            out.append(u"{} raster image{}".format(images, u"" if images == 1 else u"s"))
        return out

    def view_reasons(self, view):
        out = []
        if view.ViewType == ViewType.Rendering:
            return [u"rendered image"]
        try:
            style = view.DisplayStyle
            if style not in _VECTOR_STYLES:
                name = u"{}".format(style)
                out.append(u"visual style {}".format(_STYLE_NAMES.get(name, name)))
        except Exception:
            pass
        try:
            if view.GetViewDisplayModel().Transparency > 0:
                out.append(u"transparency set in the view's graphic display options")
        except Exception:
            pass
        try:
            if view.GetSketchyLines().EnableSketchyLines:
                out.append(u"sketchy lines")
        except Exception:
            pass
        if self._shadow_param is not None:
            try:
                p = view.get_Parameter(self._shadow_param)
                if p is not None and p.AsInteger() == 1:
                    out.append(u"shadows")
            except Exception:
                pass
        # A view under a view template reports the template's overrides as its own, so a reason the template also
        # gives is listed once, against the template, where it has to be changed.
        from_template = []
        template_id = view.ViewTemplateId
        if template_id is not None and template_id != ElementId.InvalidElementId:
            template = self.doc.GetElement(template_id)
            if template is not None:
                from_template = self._transparency(template)
                name = template.Name
        out.extend(r for r in self._transparency(view) if r not in from_template)
        out.extend(u"{} (view template {})".format(r, name) for r in from_template)
        out.extend(self._images(view))
        return out

    def reasons(self, element):
        """[(view name, [reasons])] for a sheet (its placed views and the sheet itself) or for one view."""
        out = []
        if isinstance(element, ViewSheet):
            for vid in element.GetAllPlacedViews():
                v = self.doc.GetElement(vid)
                if v is None:
                    continue
                r = self.view_reasons(v)
                if r:
                    out.append((v.Name, r))
            on_sheet = self._images(element)
            if on_sheet:
                out.append((u"the sheet itself", on_sheet))
        else:
            r = self.view_reasons(element)
            if r:
                out.append((element.Name, r))
        return out
