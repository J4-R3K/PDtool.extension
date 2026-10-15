# -*- coding: utf-8 -*-
"""The export itself: one Revit export call per sheet (or view) and format, so the file name, paper size,
orientation and raster quality can be set for each sheet and one failed sheet does not stop the rest.

The model is never changed and nothing is left borrowed on a workshared model (checks in Revit 2024 on a project model,
14/10/2026, C:\\Dev\\PD-Revit-Sheets-PLAN-2026-10-14.md, section 5):
- PDF, DWG, DGN, NWC, images and XML need no transaction; IsModified stays False.
- IFC, DWF and DWFx need one: Revit refuses DWF without it ("Exporting to DWF/DWFX requires that document is
  modifiable"), and IFC writes its IFC GUIDs to the elements. The transaction is always rolled back, so nothing is
  changed and nothing is borrowed.
- An NWC made from a 3D view makes Revit borrow that view's own elements (the view, its camera, section box, sun
  settings and work plane grid: 6 elements), although the model is not changed. Run gives them back after the
  export when the user had borrowed nothing before the export started; otherwise the row says so.
Revit shows a message box while it exports a shaded view to DWF ("Revit will use raster printing because this view
uses shading ..."), which stops the export until someone closes it. Run closes that message and the row records it.
Needs Revit.
"""
import os
import shutil
import time

import clr

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (CheckoutStatus, ColorDepthType, DGNExportOptions, DGNFileFormat, Document,
                               DWFExportOptions, DWFImageFormat, DWFImageQuality, DWFXExportOptions, DWGExportOptions,
                               ElementId, ExportPaperFormat, ExportRange, FilteredElementCollector, FitDirectionType,
                               IFCExportOptions, IFCVersion, ImageExportOptions, ImageFileType, ImageResolution,
                               NavisworksCoordinates, NavisworksExportOptions, NavisworksExportScope,
                               NavisworksParameters, OptionalFunctionalityUtils, PageOrientationType,
                               PaperPlacementType, PDFExportOptions, RasterQualityType, RelinquishOptions,
                               TextTreatment, Transaction, TransactWithCentralOptions, ViewSet, WorksharingUtils,
                               ZoomFitType, ZoomType)
from System.Collections.Generic import List

from pdtool.sheets import extra, formats, names, profiles, record, xmlwriter

MM_TO_FEET = 1.0 / 304.8

# The OptionalFunctionalityUtils check for each format that needs a part of Revit that may not be installed.
_AVAILABLE = {u"dwg": "IsDWGExportAvailable", u"dgn": "IsDGNExportAvailable", u"dwf": "IsDWFExportAvailable",
              u"ifc": "IsIFCAvailable", u"nwc": "IsNavisworksExporterAvailable"}

# What the window says when a format cannot be made on this PC. The NWC exporter is a separate Autodesk product,
# installed on Jarek's PC as "Navisworks Exporters 2024" (C:\Program Files\Autodesk, 14/10/2026).
NOT_AVAILABLE = {
    u"nwc": (u"NWC files need Autodesk Navisworks Exporters for this Revit version, which is not installed on this "
             u"PC. NWC is left off."),
    u"ifc": u"The IFC exporter is not available in this Revit. IFC is left off.",
    u"dgn": u"DGN export is not available in this Revit. DGN is left off.",
    u"dwf": u"DWF export is not available in this Revit. DWF is left off.",
    u"dwg": u"DWG export is not available in this Revit. DWG is left off.",
}

# Message boxes Revit shows during an export that PD Sheets answers, by Revit's id for them, with the button pressed
# (TaskDialogResult: Close is 8). Found in Revit's journal, 14/10/2026.
ANSWERS = {u"TaskDialog_Printing_Setting_Changed_For_Shaded_Views": 8}

# Formats that make Revit open a transaction for the export, rolled back afterwards.
_IN_TRANSACTION = (u"ifc", u"dwf")
# Formats after which the borrowing check runs. NWC borrows a 3D view's elements; IFC and DWF are checked as well,
# because their transaction could borrow on a workshared model if Revit changed how it exports.
_BORROW_CHECK = (u"nwc", u"ifc", u"dwf")


def _enum(enum_type, name, default):
    try:
        return getattr(enum_type, name)
    except (AttributeError, TypeError):
        return default


def available(key):
    """True when this Revit can make the format. PDF, images and XML are always available."""
    name = _AVAILABLE.get(key)
    if not name:
        return True
    try:
        return bool(getattr(OptionalFunctionalityUtils, name)())
    except Exception:
        return False


def key_of(fmt):
    """The profile key for a format given as a key ("pdf") or a label ("PDF")."""
    low = (fmt or u"").lower()
    if low in formats.KEYS:
        return low
    for key, label in formats.FORMATS:
        if label.lower() == low:
            return key
    return low


def pdf_options(pdf, file_name, paper_name=None, orientation=None, raster_quality=None):
    """PDFExportOptions from the profile's PDF settings and any setting made for this sheet."""
    o = PDFExportOptions()
    o.Combine = True  # one sheet per call; Combine makes Revit use FileName exactly
    o.FileName = file_name
    o.StopOnError = False
    o.AlwaysUseRaster = not pdf.get("vector", True)
    o.RasterQuality = _enum(RasterQualityType, raster_quality or pdf.get("raster_quality"), RasterQualityType.High)
    o.ColorDepth = _enum(ColorDepthType, pdf.get("colour"), ColorDepthType.Color)
    o.ViewLinksInBlue = bool(pdf.get("view_links_blue"))
    o.HideReferencePlane = bool(pdf.get("hide_ref_planes"))
    o.HideScopeBoxes = bool(pdf.get("hide_scope_boxes"))
    o.HideUnreferencedViewTags = bool(pdf.get("hide_unref_tags"))
    o.HideCropBoundaries = bool(pdf.get("hide_crop"))
    o.ReplaceHalftoneWithThinLines = bool(pdf.get("replace_halftone"))
    o.MaskCoincidentLines = bool(pdf.get("mask_coincident"))
    if pdf.get("zoom") == u"fit":
        o.ZoomType = ZoomType.FitToPage
    else:
        o.ZoomType = ZoomType.Zoom
        o.ZoomPercentage = int(pdf.get("zoom") or 100)
    if pdf.get("centre", True):
        o.PaperPlacement = PaperPlacementType.Center
    else:
        o.PaperPlacement = PaperPlacementType.LowerLeft
        o.OriginOffsetX = float(pdf.get("offset_x_mm") or 0.0) * MM_TO_FEET
        o.OriginOffsetY = float(pdf.get("offset_y_mm") or 0.0) * MM_TO_FEET
    o.PaperFormat = _enum(ExportPaperFormat, paper_name or u"Default", ExportPaperFormat.Default)
    o.PaperOrientation = _enum(PageOrientationType, orientation or u"Auto", PageOrientationType.Auto)
    return o


def dwg_options(doc, dwg):
    """The options for a DWG export from the profile's DWG section: the model's export setup it names, or Revit's
    default settings. Either way the linked models and the views on a sheet go into the one file unless "separate"
    is ticked, and the text treatment is the profile's (profiles.DEFAULT_DWG), whatever the setup says."""
    setup = dwg.get("setup")
    if setup:
        o = DWGExportOptions.GetPredefinedOptions(doc, setup)
        if o is None:
            return None, u"The DWG export setup \"{}\" is not in this model. Choose one of the model's setups.".format(
                setup)
    else:
        o = DWGExportOptions()
    o.MergedViews = not dwg.get("separate")
    o.TextTreatment = _enum(TextTreatment, dwg.get("text"), TextTreatment.Approximate)
    return o, None


def seed_file(version, three_d):
    """Revit's own DGN seed file for the version (V8 or V7), metric, 2D or 3D: <Revit folder>\\ACADInterop\\
    V8-Metric-Seed2D.dgn and so on (the same eight seed files in Revit 2023 to 2026, read 14/10/2026). Revit writes no
    DGN file when no seed is given."""
    folder = os.path.join(os.path.dirname(clr.GetClrType(Document).Assembly.Location), u"ACADInterop")
    return os.path.join(folder, u"{}-Metric-Seed{}.dgn".format(u"V7" if version == u"DGNVersion7" else u"V8",
                                                              u"3D" if three_d else u"2D"))


def dgn_options(doc, dgn, three_d):
    setup = dgn.get("setup")
    if setup:
        o = DGNExportOptions.GetPredefinedOptions(doc, setup)
        if o is None:
            return None, u"The DGN export setup \"{}\" is not in this model. Choose one of the model's setups.".format(
                setup)
        # one file unless "separate" is ticked, as for a DWG (dwg_options)
        o.MergedViews = not dgn.get("separate")
        return o, None
    o = DGNExportOptions()
    o.FileVersion = _enum(DGNFileFormat, dgn.get("version"), DGNFileFormat.DGNVersion8)
    o.SeedName = seed_file(dgn.get("version"), three_d)
    # Revit's own default is a file for each linked model and each view on a sheet (extra.py); PD Sheets makes one
    # file unless "separate" is ticked (formats.DEFAULTS).
    o.MergedViews = not dgn.get("separate")
    if not os.path.isfile(o.SeedName):
        return None, u"Revit's DGN seed file {} is not on this PC.".format(o.SeedName)
    return o, None


def dwf_options(dwf):
    o = DWFXExportOptions() if dwf.get("file_type") == u"dwfx" else DWFExportOptions()
    o.MergedViews = False
    o.StopOnError = False
    o.PaperFormat = ExportPaperFormat.Default
    o.CropBoxVisible = bool(dwf.get("crop_box"))
    o.ImageFormat = _enum(DWFImageFormat, dwf.get("image_format"), DWFImageFormat.Lossless)
    o.ImageQuality = _enum(DWFImageQuality, dwf.get("image_quality"), DWFImageQuality.Default)
    o.ExportObjectData = bool(dwf.get("object_data"))
    o.ExportingAreas = bool(dwf.get("areas"))
    o.ExportTexture = bool(dwf.get("textures"))
    return o


def ifc_options(ifc, view):
    o = IFCExportOptions()
    o.FileVersion = _enum(IFCVersion, ifc.get("version"), IFCVersion.IFC2x3CV2)
    o.SpaceBoundaryLevel = int(ifc.get("space_boundaries") or 0)
    o.WallAndColumnSplitting = bool(ifc.get("split_by_level"))
    o.ExportBaseQuantities = bool(ifc.get("base_quantities"))
    if ifc.get("visible_only", True):
        o.FilterViewId = view.Id
    # The IFC exporter writes each element's IFC GUID back to it unless told not to. The transaction is rolled back
    # in any case; this keeps the export from changing elements at all.
    o.AddOption(u"StoreIFCGUID", u"false")
    return o


def nwc_options(nwc, view):
    o = NavisworksExportOptions()
    o.ExportScope = NavisworksExportScope.View
    o.ViewId = view.Id
    o.Coordinates = _enum(NavisworksCoordinates, nwc.get("coordinates"), NavisworksCoordinates.Shared)
    o.Parameters = _enum(NavisworksParameters, nwc.get("parameters"), NavisworksParameters.All)
    o.ConvertElementProperties = bool(nwc.get("element_properties"))
    o.ExportLinks = bool(nwc.get("links"))
    o.DivideFileIntoLevels = bool(nwc.get("divide_levels"))
    o.ExportRoomGeometry = bool(nwc.get("room_geometry"))
    o.ExportRoomAsAttribute = bool(nwc.get("room_attribute"))
    o.ExportElementIds = bool(nwc.get("element_ids"))
    o.ExportParts = bool(nwc.get("parts"))
    o.ExportUrls = bool(nwc.get("urls"))
    o.ConvertLinkedCADFormats = bool(nwc.get("linked_cad"))
    o.ConvertLights = bool(nwc.get("lights"))
    o.FindMissingMaterials = bool(nwc.get("missing_materials"))
    try:
        o.FacetingFactor = float(nwc.get("faceting") or 1.0)
    except (TypeError, ValueError):
        o.FacetingFactor = 1.0
    return o


def image_options(img, element, file_path):
    pixels, zoom = formats.image_numbers(img)
    o = ImageExportOptions()
    o.ExportRange = ExportRange.SetOfViews
    ids = List[ElementId]()
    ids.Add(element.Id)
    o.SetViewsAndSheets(ids)
    o.FilePath = file_path
    o.ShouldCreateWebSite = False
    file_type = _enum(ImageFileType, img.get("file_type"), ImageFileType.PNG)
    o.HLRandWFViewsFileType = file_type
    o.ShadowViewsFileType = file_type
    if img.get("fit", True):
        o.ZoomType = ZoomFitType.FitToPage
        o.PixelSize = pixels
        o.FitDirection = _enum(FitDirectionType, img.get("direction"), FitDirectionType.Horizontal)
    else:
        o.ZoomType = ZoomFitType.Zoom
        o.Zoom = zoom
        o.ImageResolution = _enum(ImageResolution, img.get("resolution"), ImageResolution.DPI_150)
    return o


def target_path(folder, name, fmt, profile=None):
    """The file this name and format give. fmt is a profile key or a label; profile gives the DWF file type and the
    image type (without it, .dwf and .png)."""
    key = key_of(fmt)
    return os.path.join(folder, name + formats.extension(key, (profile or {}).get(key)))


def in_use(ex):
    """True when Windows refused because another program has the file open (Windows error 32). IronPython 2.7 gives
    it as "[Errno 13] [Errno 32] The process cannot access the file ... because it is being used by another process"
    (Jarek's export record, 14/10/2026, 22:45)."""
    if getattr(ex, "winerror", None) == 32:
        return True
    text = u"{}".format(ex)
    return u"being used by another process" in text or u"[Errno 32]" in text


# ---- one export run ------------------------------------------------------------------------------------------------

def borrowed(doc):
    """How many elements and types the current user has borrowed in a workshared model (0 in one that is not).
    About 0.2 s on a project model (14/10/2026)."""
    if not doc.IsWorkshared:
        return 0
    n = 0
    for collector in (FilteredElementCollector(doc).WhereElementIsNotElementType(),
                      FilteredElementCollector(doc).WhereElementIsElementType()):
        for element_id in collector.ToElementIds():
            if WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByCurrentUser:
                n += 1
    return n


class Run(object):
    """One export run. Used as "with Run(doc, uiapp) as run:" around the exports, so the message box handler is
    always removed afterwards.

    It closes the message boxes in ANSWERS while Revit exports, and lists every message box Revit showed so each
    row can say what happened. On a workshared model it counts what the user had borrowed before the export, so it
    can give back what an export borrowed (only when that was nothing, so it never gives back the user's own
    borrowing)."""

    def __init__(self, doc, uiapp=None):
        self.doc = doc
        self.uiapp = uiapp
        self.messages = []
        self.borrowed_before = borrowed(doc) if doc.IsWorkshared else 0
        # Every file written in this run, in lower case, so a file Revit writes again for a later sheet (the DGN of a
        # linked CAD file shown on several sheets) is not reported as one that was already in the folder.
        self.written = set()
        # {"dwg" or "dgn": the names of every file of that format in this run}, set by the window, so the files of
        # one are not taken for the files of another (extra.companions).
        self.names = {}
        # Linked CAD files in the model (model.linked_cad), read once in a run when a DGN needs them.
        self.cad = None
        self._handler = self._on_dialog  # one object, so the same handler is added and removed

    def __enter__(self):
        if self.uiapp is not None:
            self.uiapp.DialogBoxShowing += self._handler
        return self

    def __exit__(self, *exc):
        if self.uiapp is not None:
            try:
                self.uiapp.DialogBoxShowing -= self._handler
            except Exception:
                pass
        return False

    def _on_dialog(self, sender, args):
        dialog_id = u"{}".format(getattr(args, "DialogId", u"") or u"")
        message = u"{}".format(getattr(args, "Message", u"") or dialog_id)
        button = ANSWERS.get(dialog_id)
        if button is not None:
            args.OverrideResult(button)
        self.messages.append((message, button is not None))

    def notes_since(self, start):
        """The row's note for the message boxes shown since self.messages had start entries."""
        out = []
        for message, answered in self.messages[start:]:
            if answered:
                out.append(u"Revit showed \"{}\" and PD Sheets closed it.".format(message))
            else:
                out.append(u"Revit showed \"{}\".".format(message))
        return out

    def give_back(self):
        """After a model export: the note on anything Revit borrowed for it, or None when nothing is borrowed."""
        if not self.doc.IsWorkshared:
            return None
        now = borrowed(self.doc)
        extra = now - self.borrowed_before
        if extra <= 0:
            return None
        how = u"Give them back with Collaborate, Relinquish All Mine, or by synchronising."
        if self.borrowed_before or self.doc.IsModified:
            return u"Revit borrowed {} elements of the view for this export. {}".format(extra, how)
        try:
            options = RelinquishOptions(False)
            options.CheckedOutElements = True
            WorksharingUtils.RelinquishOwnership(self.doc, options, TransactWithCentralOptions())
        except Exception as ex:
            return u"Revit borrowed {} elements of the view for this export and they could not be given back ({}). {}".format(
                extra, ex, how)
        left = borrowed(self.doc)
        if left:
            return u"Revit borrowed {} elements of the view for this export; {} are still borrowed. {}".format(
                extra, left, how)
        return u"Revit borrowed {} elements of the view for this export; PD Sheets gave them back.".format(extra)


def _rolled_back(doc, call):
    t = Transaction(doc, u"PD Sheets export")
    t.Start()
    try:
        return call()
    finally:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()


def _export_image(doc, folder, element, name, img, path):
    """Revit names an image after the view ("<name> - Sheet - <number> - <sheet name>.png"), so it is written into
    a folder of its own beside the export and moved to the file name from the naming rule."""
    work = os.path.join(folder, u"PD-Sheets-image-{}".format(int(time.time() * 1000)))
    os.makedirs(work)
    try:
        doc.ExportImage(image_options(img, element, os.path.join(work, u"image")))
        made = [f for f in os.listdir(work) if os.path.isfile(os.path.join(work, f))]
        if len(made) != 1:
            return False
        shutil.move(os.path.join(work, made[0]), path)
        return True
    finally:
        shutil.rmtree(work, True)


def _is_3d(item):
    return (item.get("type") or u"") == u"ThreeD"


def _options(doc, key, section, item):
    """(options, problem) for a DWG or DGN export of item."""
    if key == u"dwg":
        return dwg_options(doc, section)
    return dgn_options(doc, section, _is_3d(item))


def extra_existing(doc, folder, item, name, key, section, others=(), listing=None, cad=None):
    """The files already in the folder that a DWG or DGN export of this sheet or view, named name, would write again
    besides the file itself: the files for its linked models and views (extra.companions), the plot settings file of
    a DWG, and for a DGN the file of each linked CAD file shown, which has the CAD file's name. With merged views
    Revit writes none of these (extra.py), so none is listed.

    others: the other names in the same run in this format. cad: model.linked_cad(doc) when the caller has read it."""
    from pdtool.sheets import model
    options, problem = _options(doc, key, section, item)
    merged = bool(problem) or bool(getattr(options, "MergedViews", False))
    if listing is None:
        try:
            listing = os.listdir(folder)
        except OSError:
            return []
    ext = u"." + key
    out = []
    by_low = dict((f.lower(), f) for f in listing)
    if key == u"dwg":
        f = by_low.get((name + extra.SETTINGS_EXTENSION).lower())
        if f:
            out.append(f)
    if merged:
        return out
    view_names = [v.Name for v in model.drawn_views(doc, item["element"])]
    out.extend(extra.companions(name, view_names, listing, [o for o in others if o.lower() != name.lower()], ext))
    if key == u"dgn":
        if cad is None:
            cad = model.linked_cad(doc)
        there = dict((k, n) for k, n in cad.items() if (extra.cad_file(n) or u"").lower() in by_low)
        for n in model.cad_shown(doc, item["element"], there):
            f = by_low[extra.cad_file(n).lower()]
            if f not in out:
                out.append(f)
    return extra.sort_names(out)


def export_one(doc, folder, item, fmt, name, profile, replace, run=None):
    """Export one sheet or view in one format. fmt is the profile key ("pdf") or the label ("PDF"). Returns a row for
    the record (record.COLUMNS keys) with "result" "written", "written under another name: <reason>", "skipped" or
    "failed: <reason>".

    When Replace was chosen and the existing file cannot be removed (it is open in another program), the new file is
    written beside it as "<name> (1)" and so on (names.copy_name); the row then names the file written, and
    "renamed_from" and "in_use" say which name it should have had and why it has not.

    run: the Run this export is part of; without one no message box is answered and borrowing is not checked."""
    key = key_of(fmt)
    section = profile.get(key) or {}
    unique_id = item["key"]
    pdf = profile["pdf"]
    is_pdf = key == u"pdf"
    paper_name = profiles.sheet_setting(profile, unique_id, u"paper") if is_pdf else None
    orientation = profiles.sheet_setting(profile, unique_id, u"orientation") if is_pdf else None
    quality = profiles.sheet_setting(profile, unique_id, u"raster_quality") if is_pdf else None
    path = target_path(folder, name, key, profile)
    row = {
        "file": os.path.basename(path), "format": formats.label(key, section),
        "number": item.get("number"), "name": item.get("name"), "revision": item.get("revision"),
        "paper": (paper_name or u"Use sheet size") if is_pdf else u"",
        "orientation": (orientation or u"Use sheet") if is_pdf else u"",
        "raster_quality": (quality or pdf.get("raster_quality")) if is_pdf else u"",
        "rasterised": item.get("rasterised_count") if is_pdf else u"",
    }
    reason = formats.made_from(key, item)
    if reason:
        row["result"] = u"skipped: {} files are made from model views only".format(formats.label(key, section))
        return row
    if not available(key):
        row["result"] = u"failed: " + NOT_AVAILABLE.get(key, u"This format is not available in this Revit.")
        return row
    started = time.time()
    if os.path.exists(path):
        if not replace:
            row["result"] = u"skipped: the file already exists"
            return row
        try:
            os.remove(path)
        except OSError as ex:
            issued = row["file"]
            name = names.copy_name(name, os.listdir(folder), dwg=key in (u"dwg", u"dgn"),
                                   extension=formats.extension(key, section))
            path = target_path(folder, name, key, profile)
            row["file"] = os.path.basename(path)
            row["renamed_from"] = issued
            row["in_use"] = in_use(ex)
            row["replace_error"] = u"{}".format(ex)
    if key in (u"dwg", u"dgn") and not replace:
        # Skip was chosen for files already in the folder: Revit would replace the files it writes beside the DWG or
        # DGN without asking, so the sheet is skipped when one of them is there from before this run.
        try:
            if run and key == u"dgn" and run.cad is None:
                from pdtool.sheets import model
                run.cad = model.linked_cad(doc)
            there = [f for f in extra_existing(doc, folder, item, name, key, section,
                                               run.names.get(key, ()) if run else (), cad=run.cad if run else None)
                     if f.lower() not in (run.written if run else ())]
        except Exception:
            there = []
        if there:
            row["result"] = u"skipped: Revit would replace {} already in the folder: {}".format(
                u"a file" if len(there) == 1 else u"{} files".format(len(there)), u", ".join(there))
            return row
    # DWG and DGN: the folder is listed before and after, so the files Revit writes beside the main one are known.
    before = extra.snapshot(folder) if key in (u"dwg", u"dgn") else None
    element = item["element"]
    ids = List[ElementId]()
    ids.Add(element.Id)
    first_message = len(run.messages) if run else 0
    notes = []
    try:
        if key == u"pdf":
            ok = doc.Export(folder, ids, pdf_options(pdf, name, paper_name, orientation, quality))
        elif key in (u"dwg", u"dgn"):
            options, problem = _options(doc, key, section, item)
            if problem:
                row["result"] = u"failed: " + problem
                return row
            ok = doc.Export(folder, name, ids, options)
        elif key == u"dwf":
            views = ViewSet()
            views.Insert(element)
            ok = _rolled_back(doc, lambda: doc.Export(folder, name, views, dwf_options(section)))
        elif key == u"ifc":
            ok = _rolled_back(doc, lambda: doc.Export(folder, name, ifc_options(section, element)))
        elif key == u"nwc":
            doc.Export(folder, name, nwc_options(section, element))
            ok = True
        elif key == u"img":
            ok = _export_image(doc, folder, element, name, section, path)
        elif key == u"xml":
            ok = _export_xml(doc, item, section, path)
        else:
            row["result"] = u"failed: PD Sheets does not know the format {}".format(fmt)
            return row
    except Exception as ex:
        row["result"] = u"failed: {}".format(ex)
        ok = None
    finally:
        if run:
            notes.extend(run.notes_since(first_message))
            if key in _BORROW_CHECK:
                try:
                    given = run.give_back()
                except Exception as ex:
                    given = u"PD Sheets could not check what Revit borrowed for this export ({}).".format(ex)
                if given:
                    notes.append(given)
        row["time"] = u"{:.0f} s".format(time.time() - started)
        if notes:
            row["note"] = u" ".join(notes)
    if ok is None:
        return row
    if not ok or not os.path.exists(path):
        row["result"] = u"failed: Revit did not write the file"
        return row
    if row.get("renamed_from"):
        if row["in_use"]:
            row["result"] = (u"written under another name: {} is open in another program, so it could not be "
                             u"replaced").format(row["renamed_from"])
        else:
            row["result"] = u"written under another name: {} could not be replaced ({})".format(
                row["renamed_from"], row["replace_error"])
    else:
        row["result"] = u"written"
    if run:
        run.written.add(os.path.basename(path).lower())
    if before is not None:
        new, again = extra.changes(before, extra.snapshot(folder), leave_out=[os.path.basename(path)])
        mine = run.written if run else set()
        replaced = [f for f in again if f.lower() not in mine]
        row["also_written"] = extra.sort_names(new + again)
        more = extra.note(name, new + [f for f in again if f.lower() in mine], replaced, label=row["format"])
        if more:
            row["note"] = (row.get("note") + u" " + more) if row.get("note") else more
        if run:
            run.written.update(f.lower() for f in new + again)
    size = record.size_mb(path)
    row["size_mb"] = size
    if is_pdf:
        limit = profile.get("size_limit_mb")
        row["over_limit"] = bool(limit and size is not None and size > float(limit))
    return row


def _export_xml(doc, item, xml, path):
    from pdtool.sheets import model
    kind = item.get("kind") or u"sheet"
    fields = xml.get("sheet_fields" if kind == u"sheet" else "view_fields") or []
    value_of = model.value_getter(doc)
    element = item["element"]
    xmlwriter.write(path, kind, xmlwriter.values(fields, lambda f: value_of(element, f)))
    return True
