# -*- coding: utf-8 -*-
"""Paper sizes: the title block's size as a reader names it, and Revit's own list of paper sizes for the PDF."""

# ISO 216 A sizes in mm, long side first.
ISO_A = ((u"A0", 1189, 841), (u"A1", 841, 594), (u"A2", 594, 420), (u"A3", 420, 297), (u"A4", 297, 210))
TOLERANCE_MM = 2.0

# Revit's ExportPaperFormat names (Revit 2023 to 2026), in the order the window lists them. "Default" is the size of
# the sheet's title block, shown as "Use sheet size".
REVIT_PAPER = (u"Default", u"ISO_A0", u"ISO_A1", u"ISO_A2", u"ISO_A3", u"ISO_A4", u"ISO_B1", u"ISO_B2", u"ISO_B3",
               u"ISO_B4", u"ANSI_A", u"ANSI_B", u"ANSI_C", u"ANSI_D", u"ANSI_E", u"ARCH_A", u"ARCH_B", u"ARCH_C",
               u"ARCH_D", u"ARCH_E", u"ARCH_E1", u"ARCH_E2", u"ARCH_E3")


def paper_label(name):
    """ "ISO_A1" -> "A1 (ISO)", "Default" -> "Use sheet size"."""
    if name == u"Default":
        return u"Use sheet size"
    if u"_" in name:
        family, size = name.split(u"_", 1)
        return u"{} ({})".format(size, family)
    return name


def sheet_size(width_mm, height_mm):
    """(size, orientation) of a title block: ("A1", "Landscape"), or ("275 x 480 mm", "Portrait") when it is not an
    A size. (None, None) when the size is not known."""
    if not width_mm or not height_mm:
        return None, None
    orientation = u"Landscape" if width_mm >= height_mm else u"Portrait"
    long_side, short_side = max(width_mm, height_mm), min(width_mm, height_mm)
    for name, a, b in ISO_A:
        if abs(long_side - a) <= TOLERANCE_MM and abs(short_side - b) <= TOLERANCE_MM:
            return name, orientation
    return u"{:.0f} x {:.0f} mm".format(width_mm, height_mm), orientation
