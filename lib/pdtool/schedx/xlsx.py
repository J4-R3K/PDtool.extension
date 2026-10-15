# -*- coding: utf-8 -*-
"""PD's own small xlsx writer: plain Python, no Excel needed on the PC, runs under IronPython 2.7 and 3.4 and CPython 3.

A workbook is a zip of XML parts (ECMA-376, Office Open XML SpreadsheetML). This writer makes only what PD Schedules
needs: text and numbers, bold, borders, wrapped text, a fill colour, merged cells, column widths and hidden columns,
row heights, frozen panes, repeat rows and print area, landscape A4 fitted to one page wide, and links from one sheet
to another.

Text is always written as text and never as a formula: no cell ever holds a formula part (<f>), so a value such as
"=SUM(A1)" from the model reads in Excel exactly as it does in Revit. A number is written as a number only when the
caller passes a number or a Num.
"""
import os
import re
import uuid
import zipfile

MAX_ROWS = 1048576
MAX_COLS = 16384
MAX_TEXT = 32767  # characters Excel allows in one cell
MAX_WIDTH = 255.0
MAX_HEIGHT = 409.0  # points

NS_MAIN = u"http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = u"http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = u"http://schemas.openxmlformats.org/package/2006/relationships"

# Characters XML 1.0 does not allow: control characters other than tab, line feed and carriage return, and U+FFFE,
# U+FFFF. A value holding one would make the file unreadable, so they are left out.
_NOT_ALLOWED = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
# Excel reads "_x0041_" in a cell as the character it codes ("A"). Such text from the model is kept as it reads by
# coding its "_" as "_x005F_".
_CODED = re.compile(u"_(x[0-9A-Fa-f]{4}_)")


class Num(object):
    """A number written exactly as its text, which must be a plain number ("12", "-0.5"). Used so the number in the
    file is the text Revit showed, with no rounding by the conversion to a float and back."""
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return u"Num({})".format(self.text)

    def __eq__(self, other):
        return isinstance(other, Num) and other.text == self.text

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.text)


def col_letter(index):
    """0 gives "A", 25 "Z", 26 "AA"."""
    out = u""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = u"ABCDEFGHIJKLMNOPQRSTUVWXYZ"[rem] + out
    return out


def ref(row, col):
    """The cell reference of a 0-based row and column: (0, 0) gives "A1"."""
    return u"{}{}".format(col_letter(col), row + 1)


def area(r1, c1, r2, c2):
    return u"{}:{}".format(ref(r1, c1), ref(r2, c2))


def clean_text(value):
    """Text as it is written in the file: characters XML does not allow left out, line ends made "\\n" (the line end
    Excel uses inside a cell), "_xHHHH_" kept as it reads, and cut at Excel's limit. Returns (text, cut)."""
    text = _NOT_ALLOWED.sub(u"", u"{}".format(value))
    text = text.replace(u"\r\n", u"\n").replace(u"\r", u"\n")
    cut = len(text) > MAX_TEXT
    if cut:
        text = text[:MAX_TEXT]
    return _CODED.sub(u"_x005F_\\1", text), cut


def esc(text):
    return text.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;")


def esc_attr(text):
    return esc(text).replace(u'"', u"&quot;").replace(u"\n", u"&#10;").replace(u"\t", u"&#9;")


def quote_sheet(name):
    """A sheet name as a formula or defined name refers to it: 'Sheet name', with any ' doubled."""
    return u"'{}'".format(name.replace(u"'", u"''"))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _num_text(value):
    if isinstance(value, Num):
        return value.text
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(u"A cell cannot hold {}.".format(value))
        # 15 significant figures, as Excel keeps; repr() differs between IronPython 2.7, 3.4 and CPython
        return u"{0:.15g}".format(value + 0.0 if value else 0.0)
    return u"{}".format(int(value))


def _dec(value):
    """A width or height to two places, written the same way by every Python engine ("34", "18.1")."""
    text = u"{0:.2f}".format(float(value))  # IronPython 2.7 refuses .2f on an int
    return text.rstrip(u"0").rstrip(u".")


# ---- styles ----------------------------------------------------------------------------------------------------------

class Style(object):
    """How a cell looks. Two styles with the same settings are the same style in the file."""
    __slots__ = ("bold", "border", "wrap", "fill", "align", "valign", "colour", "underline")

    def __init__(self, bold=False, border=False, wrap=False, fill=None, align=None, valign=u"top", colour=None,
                 underline=False):
        self.bold = bold
        self.border = border
        self.wrap = wrap
        self.fill = fill  # "RRGGBB" or None
        self.align = align  # "left", "center", "right" or None
        self.valign = valign  # "top", "center", "bottom"
        self.colour = colour  # font colour "RRGGBB" or None
        self.underline = underline

    def key(self):
        return (self.bold, self.border, self.wrap, self.fill, self.align, self.valign, self.colour, self.underline)

    def but(self, **changes):
        """A copy of this style with some settings changed."""
        out = Style(*self.key())
        for k, v in changes.items():
            setattr(out, k, v)
        return out


PLAIN = Style()


class _Styles(object):
    """The style table of the workbook (xl/styles.xml). Index 0 is the plain style."""

    def __init__(self):
        self.fonts = [(False, None, False)]
        self.fills = [None, u"gray125"]  # the first two fills are required by Excel
        self.xfs = [(0, 0, 0, False, None, u"bottom")]
        self.index = {}

    def of(self, style):
        if style is None:
            return 0
        key = style.key()
        if key in self.index:
            return self.index[key]
        font = (style.bold, style.colour, style.underline)
        if font not in self.fonts:
            self.fonts.append(font)
        if style.fill and style.fill not in self.fills:
            self.fills.append(style.fill)
        xf = (self.fonts.index(font), self.fills.index(style.fill) if style.fill else 0, 1 if style.border else 0,
              style.wrap, style.align, style.valign)
        self.xfs.append(xf)
        self.index[key] = len(self.xfs) - 1
        return self.index[key]

    def xml(self):
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<styleSheet xmlns="{}">'.format(NS_MAIN)]
        out.append(u'<fonts count="{}">'.format(len(self.fonts)))
        for bold, colour, underline in self.fonts:
            out.append(u"<font>{}{}<sz val=\"11\"/>{}<name val=\"Calibri\"/><family val=\"2\"/></font>".format(
                u"<b/>" if bold else u"", u"<u/>" if underline else u"",
                u'<color rgb="FF{}"/>'.format(colour) if colour else u'<color theme="1"/>'))
        out.append(u"</fonts>")
        out.append(u'<fills count="{}">'.format(len(self.fills)))
        out.append(u'<fill><patternFill patternType="none"/></fill>')
        out.append(u'<fill><patternFill patternType="gray125"/></fill>')
        for colour in self.fills[2:]:
            out.append(u'<fill><patternFill patternType="solid"><fgColor rgb="FF{}"/><bgColor indexed="64"/>'
                       u'</patternFill></fill>'.format(colour))
        out.append(u"</fills>")
        thin = u'<{0} style="thin"><color auto="1"/></{0}>'
        out.append(u'<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
                   u"<border>{}{}{}{}<diagonal/></border></borders>".format(
                       thin.format(u"left"), thin.format(u"right"), thin.format(u"top"), thin.format(u"bottom")))
        out.append(u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>')
        out.append(u'<cellXfs count="{}">'.format(len(self.xfs)))
        for font, fill, border, wrap, align, valign in self.xfs:
            attrs = u'numFmtId="0" fontId="{}" fillId="{}" borderId="{}" xfId="0"'.format(font, fill, border)
            if font:
                attrs += u' applyFont="1"'
            if fill:
                attrs += u' applyFill="1"'
            if border:
                attrs += u' applyBorder="1"'
            alignment = u""
            if wrap or align or valign != u"bottom":
                attrs += u' applyAlignment="1"'
                parts = []
                if align:
                    parts.append(u'horizontal="{}"'.format(align))
                if valign != u"bottom":
                    parts.append(u'vertical="{}"'.format(valign))
                if wrap:
                    parts.append(u'wrapText="1"')
                alignment = u"<alignment {}/>".format(u" ".join(parts))
            out.append(u"<xf {}>{}</xf>".format(attrs, alignment) if alignment else u"<xf {}/>".format(attrs))
        out.append(u"</cellXfs>")
        out.append(u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>')
        out.append(u'<dxfs count="0"/><tableStyles count="0"/></styleSheet>')
        return u"".join(out)


# ---- sheets ----------------------------------------------------------------------------------------------------------

class Sheet(object):
    """One worksheet. Rows and columns are counted from 0."""

    def __init__(self, name):
        self.name = name
        self.cells = {}  # (row, col) -> (value, Style)
        self.merges = []  # (r1, c1, r2, c2)
        self.widths = {}  # col -> width in characters
        self.heights = {}  # row -> height in points
        self.hidden_cols = set()
        self.freeze_rows = 0
        self.freeze_cols = 0
        self.print_titles = None  # (first row, last row)
        self.print_area = None  # (r1, c1, r2, c2)
        self.landscape = True
        self.fit_width = True
        self.links = []  # (row, col, sheet name): a link to cell A1 of another sheet
        self.cut = 0  # cells cut at Excel's limit

    def set(self, row, col, value, style=None):
        if row < 0 or col < 0 or row >= MAX_ROWS or col >= MAX_COLS:
            raise ValueError(u"Cell {},{} is outside the sheet.".format(row, col))
        self.cells[(row, col)] = (value, style)

    def get(self, row, col):
        return self.cells.get((row, col), (None, None))[0]

    def merge(self, r1, c1, r2, c2):
        if r2 < r1 or c2 < c1:
            raise ValueError(u"A merged area must run down and to the right.")
        if (r1, c1) != (r2, c2):
            self.merges.append((r1, c1, r2, c2))

    def size(self):
        """(rows, columns) used, counting merged areas and set widths."""
        rows = cols = 0
        for r, c in self.cells:
            rows, cols = max(rows, r + 1), max(cols, c + 1)
        for r1, c1, r2, c2 in self.merges:
            rows, cols = max(rows, r2 + 1), max(cols, c2 + 1)
        return rows, cols

    def problems(self):
        """What would make Excel repair the file: merged areas that overlap."""
        out = []
        taken = {}
        for m in self.merges:
            r1, c1, r2, c2 = m
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (r, c) in taken:
                        out.append(u"Merged areas {} and {} overlap.".format(area(*taken[(r, c)]), area(*m)))
                        return out
                    taken[(r, c)] = m
        return out

    def xml(self, strings, styles, selected=False):
        rows, cols = self.size()
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<worksheet xmlns="{}" xmlns:r="{}">'.format(NS_MAIN, NS_REL)]
        if self.fit_width:
            out.append(u'<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
        out.append(u'<dimension ref="{}"/>'.format(area(0, 0, max(rows, 1) - 1, max(cols, 1) - 1)))
        view = u'<sheetView workbookViewId="0"{}>'.format(u' tabSelected="1"' if selected else u"")
        fr, fc = self.freeze_rows, self.freeze_cols
        if fr or fc:
            pane = u"bottomRight" if fr and fc else (u"bottomLeft" if fr else u"topRight")
            view += u'<pane{}{} topLeftCell="{}" activePane="{}" state="frozen"/><selection pane="{}"/>'.format(
                u' xSplit="{}"'.format(fc) if fc else u"", u' ySplit="{}"'.format(fr) if fr else u"", ref(fr, fc),
                pane, pane)
        out.append(u"<sheetViews>{}</sheetView></sheetViews>".format(view))
        out.append(u'<sheetFormatPr defaultRowHeight="15"/>')
        if self.widths or self.hidden_cols:
            out.append(u"<cols>")
            for c in sorted(set(self.widths) | self.hidden_cols):
                w = min(max(self.widths.get(c, 8.43), 0.5), MAX_WIDTH)
                out.append(u'<col min="{0}" max="{0}" width="{1}" customWidth="1"{2}/>'.format(
                    c + 1, _dec(w), u' hidden="1"' if c in self.hidden_cols else u""))
            out.append(u"</cols>")
        out.append(u"<sheetData>")
        by_row = {}
        for (r, c) in self.cells:
            by_row.setdefault(r, []).append(c)
        for r in sorted(set(by_row) | set(self.heights)):
            attrs = u' r="{}"'.format(r + 1)
            if r in self.heights:
                attrs += u' ht="{}" customHeight="1"'.format(_dec(min(self.heights[r], MAX_HEIGHT)))
            cells = []
            for c in sorted(by_row.get(r, [])):
                value, style = self.cells[(r, c)]
                s = styles.of(style)
                sa = u' s="{}"'.format(s) if s else u""
                if value is None or value == u"":
                    cells.append(u'<c r="{}"{}/>'.format(ref(r, c), sa))
                elif isinstance(value, Num) or _is_number(value):
                    cells.append(u'<c r="{}"{}><v>{}</v></c>'.format(ref(r, c), sa, _num_text(value)))
                else:
                    text, cut = clean_text(value)
                    self.cut += 1 if cut else 0
                    cells.append(u'<c r="{}"{} t="s"><v>{}</v></c>'.format(ref(r, c), sa, strings.of(text)))
            out.append(u"<row{}>{}</row>".format(attrs, u"".join(cells)))
        out.append(u"</sheetData>")
        if self.merges:
            out.append(u'<mergeCells count="{}">'.format(len(self.merges)))
            out.extend(u'<mergeCell ref="{}"/>'.format(area(*m)) for m in self.merges)
            out.append(u"</mergeCells>")
        if self.links:
            out.append(u"<hyperlinks>")
            for r, c, target in self.links:
                out.append(u'<hyperlink ref="{}" location="{}!A1" display="{}"/>'.format(
                    ref(r, c), esc_attr(quote_sheet(target)), esc_attr(clean_text(target)[0])))
            out.append(u"</hyperlinks>")
        out.append(u'<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>')
        out.append(u'<pageSetup paperSize="9" orientation="{}"{}/>'.format(
            u"landscape" if self.landscape else u"portrait",
            u' fitToWidth="1" fitToHeight="0"' if self.fit_width else u""))
        out.append(u"</worksheet>")
        return u"".join(out)


class _Strings(object):
    """The shared strings table (xl/sharedStrings.xml): each different text is stored once."""

    def __init__(self):
        self.items = []
        self.index = {}
        self.uses = 0

    def of(self, text):
        self.uses += 1
        if text not in self.index:
            self.index[text] = len(self.items)
            self.items.append(text)
        return self.index[text]

    def xml(self):
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<sst xmlns="{}" count="{}" uniqueCount="{}">'.format(NS_MAIN, self.uses, len(self.items))]
        for text in self.items:
            out.append(u'<si><t xml:space="preserve">{}</t></si>'.format(esc(text)))
        out.append(u"</sst>")
        return u"".join(out)


# ---- the workbook ----------------------------------------------------------------------------------------------------

class Workbook(object):

    def __init__(self):
        self.sheets = []

    def add_sheet(self, name):
        """A new sheet. The name must already follow Excel's rules (schedx.names.sheet_name)."""
        if any(s.name.lower() == name.lower() for s in self.sheets):
            raise ValueError(u"There is already a sheet called {}.".format(name))
        sheet = Sheet(name)
        self.sheets.append(sheet)
        return sheet

    def problems(self):
        out = []
        if not self.sheets:
            out.append(u"The workbook has no sheets.")
        for s in self.sheets:
            out.extend(u"{}: {}".format(s.name, p) for p in s.problems())
        return out

    def parts(self):
        """[(part name, text)] in the order they are written to the zip."""
        problems = self.problems()
        if problems:
            raise ValueError(u" ".join(problems))
        strings, styles = _Strings(), _Styles()
        sheet_parts = [(u"xl/worksheets/sheet{}.xml".format(i + 1), s.xml(strings, styles, selected=(i == 0)))
                       for i, s in enumerate(self.sheets)]
        n = len(self.sheets)
        types = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                 u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                 u'<Default Extension="xml" ContentType="application/xml"/>',
                 u'<Override PartName="/xl/workbook.xml" '
                 u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
        for i in range(n):
            types.append(u'<Override PartName="/xl/worksheets/sheet{}.xml" '
                         u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                         .format(i + 1))
        types.append(u'<Override PartName="/xl/styles.xml" '
                     u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
        types.append(u'<Override PartName="/xl/sharedStrings.xml" '
                     u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>')
        types.append(u"</Types>")
        root_rels = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     u'<Relationships xmlns="{}"><Relationship Id="rId1" '
                     u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                     u'Target="xl/workbook.xml"/></Relationships>').format(NS_PKG_REL)
        wb = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              u'<workbook xmlns="{}" xmlns:r="{}">'.format(NS_MAIN, NS_REL),
              u'<bookViews><workbookView activeTab="0"/></bookViews><sheets>']
        for i, s in enumerate(self.sheets):
            wb.append(u'<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(esc_attr(s.name), i + 1, i + 1))
        wb.append(u"</sheets>")
        names = []
        for i, s in enumerate(self.sheets):
            q = esc(quote_sheet(s.name))
            if s.print_area:
                r1, c1, r2, c2 = s.print_area
                names.append(u'<definedName name="_xlnm.Print_Area" localSheetId="{}">{}!${}${}:${}${}</definedName>'
                             .format(i, q, col_letter(c1), r1 + 1, col_letter(c2), r2 + 1))
            if s.print_titles:
                r1, r2 = s.print_titles
                names.append(u'<definedName name="_xlnm.Print_Titles" localSheetId="{}">{}!${}:${}</definedName>'
                             .format(i, q, r1 + 1, r2 + 1))
        if names:
            wb.append(u"<definedNames>{}</definedNames>".format(u"".join(names)))
        wb.append(u"</workbook>")
        wb_rels = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                   u'<Relationships xmlns="{}">'.format(NS_PKG_REL)]
        for i in range(n):
            wb_rels.append(u'<Relationship Id="rId{0}" '
                           u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                           u'Target="worksheets/sheet{0}.xml"/>'.format(i + 1))
        wb_rels.append(u'<Relationship Id="rId{}" '
                       u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                       u'Target="styles.xml"/>'.format(n + 1))
        wb_rels.append(u'<Relationship Id="rId{}" '
                       u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
                       u'Target="sharedStrings.xml"/>'.format(n + 2))
        wb_rels.append(u"</Relationships>")
        return ([(u"[Content_Types].xml", u"".join(types)), (u"_rels/.rels", root_rels),
                 (u"xl/workbook.xml", u"".join(wb)), (u"xl/_rels/workbook.xml.rels", u"".join(wb_rels))]
                + sheet_parts + [(u"xl/styles.xml", styles.xml()), (u"xl/sharedStrings.xml", strings.xml())])

    def cut_cells(self):
        return sum(s.cut for s in self.sheets)

    def save(self, path):
        """Write the workbook to path (any file already there is replaced). Use save_safely to keep a file that is
        open in Excel."""
        parts = self.parts()
        try:
            z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
        except RuntimeError:  # no zlib in this Python: store the parts without compression
            z = zipfile.ZipFile(path, "w", zipfile.ZIP_STORED)
        try:
            for name, text in parts:
                z.writestr(str(name), text.encode("utf-8"))
        finally:
            z.close()
        return path


def save_safely(workbook, path, copy_name):
    """Write the workbook to a temporary file beside path, then put it in place. When a file of that name is open in
    another program (Excel locks the file it has open), the workbook is kept as the name copy_name gives instead.
    Returns the path written. copy_name(name without extension, file names in the folder) gives "<name> (1)"."""
    folder, file_name = os.path.split(path)
    stem, ext = os.path.splitext(file_name)
    tmp = os.path.join(folder, u"~pd-{}-{}.tmp".format(stem[:40], uuid.uuid4().hex[:8]))
    workbook.save(tmp)
    try:
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return path
    except OSError:
        pass
    try:
        other = os.path.join(folder, copy_name(stem, os.listdir(folder)) + ext)
        os.rename(tmp, other)
        return other
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_back(path):
    """{part name: text} of a workbook written here, for the tests."""
    z = zipfile.ZipFile(path)
    try:
        return dict((n, z.read(n).decode("utf-8")) for n in z.namelist())
    finally:
        z.close()

