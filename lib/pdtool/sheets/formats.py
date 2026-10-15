# -*- coding: utf-8 -*-
"""The eight formats PD Sheets writes, their settings as the window offers them, their defaults, and what each one
can be made from. Plain Python, so the library tests run without Revit.

PDF, DWG, DGN, DWF or DWFx, images and XML are made from sheets and views. IFC and NWC are model formats: Revit makes
them from a view that shows the model (a plan, a ceiling plan, a section, an elevation or a 3D view), never from a
sheet, a legend, a drafting view or a schedule.

Settings are stored under Revit's own names (IFCVersion, ImageFileType and so on), kept as text so a profile reads
without Revit; the second item of each pair is what the window shows.
"""
import copy
import re

# (key in the profile, label in the window). The order is the order of the panels at step 3.
FORMATS = (
    (u"pdf", u"PDF"),
    (u"dwg", u"DWG"),
    (u"dgn", u"DGN"),
    (u"dwf", u"DWF"),
    (u"ifc", u"IFC"),
    (u"nwc", u"NWC"),
    (u"img", u"Image"),
    (u"xml", u"XML"),
)
KEYS = tuple(k for k, _ in FORMATS)
LABELS = dict(FORMATS)

# View types (ViewType names) Revit makes IFC and NWC files from.
MODEL_VIEWS = (u"FloorPlan", u"CeilingPlan", u"EngineeringPlan", u"AreaPlan", u"Section", u"Elevation", u"Detail",
               u"ThreeD")
MODEL_ONLY = (u"ifc", u"nwc")

# The name Revit gives each view type, as the window shows it after a view's name: "Site_01 (3D)", not
# "Site_01 (ThreeD)" (Jarek, 15/10/2026). A type not listed here has its ViewType name split into words.
VIEW_TYPE_NAMES = {
    u"FloorPlan": u"Floor Plan", u"CeilingPlan": u"Ceiling Plan", u"EngineeringPlan": u"Structural Plan",
    u"AreaPlan": u"Area Plan", u"Section": u"Section", u"Elevation": u"Elevation", u"Detail": u"Detail View",
    u"ThreeD": u"3D", u"DraftingView": u"Drafting View", u"Legend": u"Legend", u"Schedule": u"Schedule",
    u"PanelSchedule": u"Panel Schedule", u"ColumnSchedule": u"Graphical Column Schedule",
    u"Rendering": u"Rendering", u"Walkthrough": u"Walkthrough", u"Report": u"Report", u"CostReport": u"Cost Report",
    u"LoadsReport": u"Loads Report", u"PresureLossReport": u"Pressure Loss Report",
    u"SystemsAnalysisReport": u"Systems Analysis Report",
}

DGN_VERSIONS = ((u"DGNVersion8", u"Version 8"), (u"DGNVersion7", u"Version 7"))
# Revit's DWG "Text treatment" (TextTreatment): Approximate keeps each text note as one multiline text, Exact writes
# each line of it as a text of its own. The labels are Revit 2024's, in File, Export, DWG, Text & Fonts. DGN has no
# such setting (DGNExportOptions, read 15/10/2026).
DWG_TEXT_TREATMENTS = ((u"Approximate", u"Preserve editability"), (u"Exact", u"Preserve visual fidelity"))

DWF_FILE_TYPES = ((u"dwf", u"DWF"), (u"dwfx", u"DWFx"))
DWF_IMAGE_FORMATS = ((u"Lossless", u"Lossless"), (u"Lossy", u"Lossy, smaller file"))
DWF_IMAGE_QUALITIES = ((u"Default", u"Revit default"), (u"Low", u"Low"), (u"Medium", u"Medium"), (u"High", u"High"))

IFC_VERSIONS = ((u"IFC2x3CV2", u"IFC 2x3 Coordination View 2.0"), (u"IFC4RV", u"IFC4 Reference View"),
                (u"IFC4DTV", u"IFC4 Design Transfer View"))
SPACE_BOUNDARIES = ((0, u"None"), (1, u"First level"), (2, u"Second level"))

NWC_COORDINATES = ((u"Shared", u"Shared"), (u"Internal", u"Project internal"))
NWC_PARAMETERS = ((u"All", u"All"), (u"Elements", u"Elements only"), (u"None", u"None"))

# (ImageFileType, label, extension)
IMAGE_TYPES = ((u"PNG", u"PNG", u".png"), (u"JPEGLossless", u"JPEG, best quality", u".jpg"),
               (u"JPEGMedium", u"JPEG, medium quality", u".jpg"), (u"JPEGSmallest", u"JPEG, smallest file", u".jpg"),
               (u"TIFF", u"TIFF", u".tif"), (u"BMP", u"BMP", u".bmp"))
IMAGE_RESOLUTIONS = ((u"DPI_72", u"72 dpi"), (u"DPI_150", u"150 dpi"), (u"DPI_300", u"300 dpi"),
                     (u"DPI_600", u"600 dpi"))
IMAGE_DIRECTIONS = ((u"Horizontal", u"wide"), (u"Vertical", u"high"))
# Revit's limits for ImageExportOptions.PixelSize and Zoom (an image wider than this is refused).
IMAGE_PIXELS_MIN, IMAGE_PIXELS_MAX = 32, 15000
IMAGE_ZOOM_MIN, IMAGE_ZOOM_MAX = 1, 100

_RULES = {"rule": u"PD ISO 19650", "view_rule": u"View name"}


def _with_rules(d):
    out = dict(_RULES)
    out.update(d)
    return out


# Defaults. DWF, IFC and NWC start from Revit's own defaults (read from new export options in Revit 2024, 14/10/2026),
# except where noted.
DEFAULTS = {
    u"dgn": _with_rules({"enabled": False, "setup": u"", "version": u"DGNVersion8", "separate": False}),
    # Element properties are on: they are what a DWF is opened for in Design Review (Revit's own default is off).
    u"dwf": _with_rules({"enabled": False, "file_type": u"dwf", "image_format": u"Lossless",
                         "image_quality": u"Default", "crop_box": False, "object_data": True, "areas": False,
                         "textures": True}),
    # Only the elements seen in the view: each view gives its own file. With it off every file holds the whole model.
    u"ifc": _with_rules({"enabled": False, "version": u"IFC2x3CV2", "visible_only": True, "space_boundaries": 0,
                         "split_by_level": False, "base_quantities": False}),
    u"nwc": _with_rules({"enabled": False, "coordinates": u"Shared", "parameters": u"All",
                         "element_properties": False, "links": False, "divide_levels": True, "room_geometry": True,
                         "room_attribute": True, "element_ids": True, "parts": False, "urls": True,
                         "linked_cad": True, "lights": False, "missing_materials": True, "faceting": 1.0}),
    # 2048 pixels wide, as PD's ProSheets profiles export images; Revit's own default is 512.
    u"img": _with_rules({"enabled": False, "file_type": u"PNG", "fit": True, "pixels": 2048,
                         "direction": u"Horizontal", "zoom": 100, "resolution": u"DPI_150"}),
    # The fields written for a sheet and for a view (xmlwriter).
    u"xml": _with_rules({"enabled": False,
                         "sheet_fields": [
                             {"param": u"Sheet Number", "source": u"sheet", "element": u"SheetNumber"},
                             {"param": u"Sheet Name", "source": u"sheet", "element": u"SheetName"},
                             {"param": u"Current Revision", "source": u"sheet", "element": u"CurrentRevision"},
                             {"param": u"Current Revision Date", "source": u"sheet",
                              "element": u"CurrentRevisionDate"},
                             {"param": u"Current Revision Description", "source": u"sheet",
                              "element": u"CurrentRevisionDescription"},
                         ],
                         "view_fields": [
                             {"param": u"View Name", "source": u"sheet", "element": u"ViewName"},
                             {"param": u"Sheet Number", "source": u"sheet", "element": u"SheetNumber"},
                             {"param": u"Sheet Name", "source": u"sheet", "element": u"SheetName"},
                         ]}),
}


def default(key):
    return copy.deepcopy(DEFAULTS[key])


def made_from(key, item):
    """None when the format can be made from this sheet or view, or the reason it cannot, short enough for a cell in
    the file name column."""
    if key not in MODEL_ONLY:
        return None
    if item.get("kind") == u"sheet":
        return u"Views only"
    if (item.get("type") or u"") not in MODEL_VIEWS:
        return u"Model views only"
    return None


def view_type_name(view_type):
    """The view type as the window shows it ("3D", "Floor Plan"), from its ViewType name."""
    if not view_type:
        return u"view"
    if view_type in VIEW_TYPE_NAMES:
        return VIEW_TYPE_NAMES[view_type]
    return re.sub(u"(?<=[a-z])(?=[A-Z])", u" ", view_type)


def extension(key, section):
    """The file extension for this format with the profile's settings for it (section: profile[key])."""
    section = section or {}
    if key == u"dwf":
        return u".dwfx" if section.get("file_type") == u"dwfx" else u".dwf"
    if key == u"img":
        for name, _, ext in IMAGE_TYPES:
            if name == section.get("file_type"):
                return ext
        return u".png"
    return u"." + key


def label(key, section):
    """The format as the export record and the results name it: "DWFx" rather than "DWF" when DWFx is chosen, and
    the image type ("PNG", "JPEG", "TIFF", "BMP") for images."""
    section = section or {}
    if key == u"dwf":
        return u"DWFx" if section.get("file_type") == u"dwfx" else u"DWF"
    if key == u"img":
        ext = extension(key, section)
        return {u".jpg": u"JPEG", u".tif": u"TIFF", u".bmp": u"BMP"}.get(ext, u"PNG")
    return LABELS[key]


def image_numbers(section):
    """The image size settings as numbers within Revit's limits: (pixels, zoom)."""
    def num(value, low, high, fallback):
        # None is tested first: in IronPython 2.7.12 float(None) raises SystemError, not TypeError.
        if value is None:
            return fallback
        try:
            n = int(float(value))
        except (TypeError, ValueError):
            return fallback
        return max(low, min(high, n))
    return (num(section.get("pixels"), IMAGE_PIXELS_MIN, IMAGE_PIXELS_MAX, 2048),
            num(section.get("zoom"), IMAGE_ZOOM_MIN, IMAGE_ZOOM_MAX, 100))
