# -*- coding: utf-8 -*-
"""Parameter value changes and their checks, for Edit Values and later Number Devices (15/10/2026).

No Revit is needed here: the window reads the values from the model, this module works out each new value and its
status, and the window writes the result. Tested outside Revit by pdtool-lib-tests/test_values.py. Plan:
C:\\Dev\\PD-Revit-DeviceTools-PLAN-2026-10-15.md, sections 5 and 8.

    from pdtool import values

    change = values.Change(values.PREFIX, text=u"E-")
    outcome = change.new_text(u"6695")            # Outcome(text=u"E-6695")
    row = values.assess(values.TEXT, change, old=u"6695", outcome=outcome)
    row.state, row.notes                           # (u"Changes", [])

Values are kept as Revit stores them: text as text (empty text for no value), whole numbers and yes/no as int, or None
where the parameter has no value. Text shown to the user is made with shown().
"""
import re

TEXT = u"text"
WHOLE = u"whole number"
YESNO = u"yes/no"
KINDS = (TEXT, WHOLE, YESNO)

# ---- the changes -------------------------------------------------------------------------------------------------

SET = u"set"
PREFIX = u"prefix"
SUFFIX = u"suffix"
REPLACE = u"replace"
CLEAR = u"clear"
CAPITALS = u"capitals"
COPY = u"copy"
PATTERN = u"pattern"

# (change, the name shown in the window, the kinds of parameter it is offered for)
CHANGES = (
    (SET, u"Set the value", (TEXT, WHOLE, YESNO)),
    (PREFIX, u"Add text before", (TEXT, WHOLE)),
    (SUFFIX, u"Add text after", (TEXT, WHOLE)),
    (REPLACE, u"Find and replace", (TEXT, WHOLE)),
    (CLEAR, u"Clear the value", (TEXT, WHOLE, YESNO)),
    (CAPITALS, u"Change to capitals", (TEXT,)),
    (COPY, u"Copy from another parameter", (TEXT, WHOLE, YESNO)),
    (PATTERN, u"Build from fields", (TEXT, WHOLE)),
)
CHANGE_NAMES = dict((c, name) for c, name, _ in CHANGES)
# Changes that put a new value in place of the old one, so a filled value is marked as overwritten.
REPLACES_OLD = (SET, CLEAR, COPY, PATTERN)


def changes_for(kind):
    """The changes offered for a kind of parameter, in the window's order."""
    return [c for c, _, kinds in CHANGES if kind in kinds]


# ---- fields in a pattern -----------------------------------------------------------------------------------------

LEVEL = u"Level"
ROOM_NUMBER = u"Room Number"
ROOM_NAME = u"Room Name"
PANEL = u"Panel"
CIRCUIT = u"Circuit"
TYPE_MARK = u"Type Mark"
FAMILY = u"Family"
TYPE = u"Type"
FIELDS = (LEVEL, ROOM_NUMBER, ROOM_NAME, PANEL, CIRCUIT, TYPE_MARK, FAMILY, TYPE)
ROOM_FIELDS = (ROOM_NUMBER, ROOM_NAME)
_FIELD_BY_LOWER = dict((f.lower(), f) for f in FIELDS)


class PatternError(ValueError):
    pass


def parse_pattern(pattern):
    """A pattern as a list of (is_field, text): ("{Level}-{Mark}" gives [(True, "Level"), (False, "-"),
    (True, "Mark")]). {{ and }} stand for the braces themselves. Raises PatternError with the problem in plain words."""
    parts = []
    literal = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == u"{" and pattern[i + 1:i + 2] == u"{":
            literal.append(u"{")
            i += 2
        elif ch == u"}" and pattern[i + 1:i + 2] == u"}":
            literal.append(u"}")
            i += 2
        elif ch == u"{":
            end = pattern.find(u"}", i + 1)
            if end < 0:
                raise PatternError(u"A { has no } to close it.")
            name = pattern[i + 1:end].strip()
            if not name:
                raise PatternError(u"A field between { and } has no name.")
            if u"{" in name:
                raise PatternError(u"A { has no } to close it.")
            if literal:
                parts.append((False, u"".join(literal)))
                literal = []
            parts.append((True, name))
            i = end + 1
        elif ch == u"}":
            raise PatternError(u"A } has no { before it.")
        else:
            literal.append(ch)
            i += 1
    if literal:
        parts.append((False, u"".join(literal)))
    return parts


def field_names(pattern):
    """The field names in a pattern, in order, each once. Raises PatternError."""
    out = []
    for is_field, text in parse_pattern(pattern):
        if is_field and text not in out:
            out.append(text)
    return out


def special_field(name):
    """The PD field a name stands for ("level" gives "Level"), or None where it is a parameter name."""
    return _FIELD_BY_LOWER.get(name.strip().lower())


def fill_pattern(pattern, get):
    """(text, missing): the pattern with each field replaced by get(name), and the fields that gave no value."""
    out, missing = [], []
    for is_field, text in parse_pattern(pattern):
        if not is_field:
            out.append(text)
            continue
        value = get(text)
        value = u"" if value is None else u"{}".format(value)
        if not value.strip():
            if text not in missing:
                missing.append(text)
        out.append(value)
    return u"".join(out), missing


# ---- the value filter at step 1 ----------------------------------------------------------------------------------

CONTAINS = u"contains"
EQUALS = u"equals"
STARTS = u"starts with"
EMPTY = u"is empty"
FILTERS = (CONTAINS, EQUALS, STARTS, EMPTY)


def matches(value, how, text, match_case=False):
    """True where a value passes the filter. Every value is compared as the text shown in Revit."""
    value = u"" if value is None else u"{}".format(value)
    if how == EMPTY:
        return not value.strip()
    text = u"" if text is None else u"{}".format(text)
    if not match_case:
        value, text = value.lower(), text.lower()
    if how == CONTAINS:
        return text in value
    if how == EQUALS:
        return value == text
    if how == STARTS:
        return value.startswith(text)
    raise ValueError(u"Unknown filter: {}".format(how))


# ---- stored values -----------------------------------------------------------------------------------------------

# Revit keeps a whole-number parameter in 32 bits.
INT_MIN = -2147483648
INT_MAX = 2147483647
_YES = (u"yes", u"y", u"1", u"true")
_NO = (u"no", u"n", u"0", u"false")


def to_stored(kind, text):
    """(value, problem): the value Revit would store for a text, or None and the reason it cannot be stored.
    Empty text means no value: empty text for a text parameter, None for the others."""
    text = u"" if text is None else u"{}".format(text)
    if kind == TEXT:
        return text, None
    plain = text.strip()
    if not plain:
        return None, None
    if kind == WHOLE:
        if re.match(r"^[+-]?[0-9]+$", plain):
            number = int(plain)
            if INT_MIN <= number <= INT_MAX:
                return number, None
            return None, u"{} is outside the range of a whole number in Revit ({} to {})".format(
                _quoted(plain), u"{:,}".format(INT_MIN), u"{:,}".format(INT_MAX))
        return None, u"{} is not a whole number".format(_quoted(plain))
    if kind == YESNO:
        if plain.lower() in _YES:
            return 1, None
        if plain.lower() in _NO:
            return 0, None
        return None, u"{} is not Yes or No".format(_quoted(plain))
    raise ValueError(u"Unknown kind: {}".format(kind))


def shown(kind, stored):
    """The text the window shows for a stored value."""
    if stored is None:
        return u""
    if kind == YESNO:
        return u"Yes" if stored else u"No"
    return u"{}".format(stored)


def is_empty(kind, stored):
    return stored is None or (kind == TEXT and not u"{}".format(stored).strip())


def same(kind, old, new):
    """True where writing new would leave the value as it is (no value and empty text count as the same)."""
    if kind == TEXT:
        return (old or u"") == (new or u"")
    return old == new


def _quoted(text):
    return u"\u201c{}\u201d".format(text)


# ---- one change --------------------------------------------------------------------------------------------------

class Outcome(object):
    """The new value a change gives for one element, as text, or why it gives none.
    left_out: the reason the element is left out, or None. same_note: why the value does not change, when it does not."""

    def __init__(self, text=None, left_out=None, same_note=None):
        self.text = text
        self.left_out = left_out
        self.same_note = same_note

    def __repr__(self):
        return u"Outcome(text={!r}, left_out={!r}, same_note={!r})".format(self.text, self.left_out, self.same_note)


NOTHING_TO_ADD_TO = u"Nothing to add to: the value is empty"
NOT_FOUND = u"The text to find is not in this value"
ALREADY = u"The new value is the same as the value now"


class Change(object):
    """One change chosen at step 2.

    text: the value for SET, the text for PREFIX and SUFFIX, the pattern for PATTERN.
    find, replace_with, match_case: for REPLACE. source: the parameter copied from, for COPY."""

    def __init__(self, kind, text=u"", find=u"", replace_with=u"", match_case=False, source=None):
        if kind not in CHANGE_NAMES:
            raise ValueError(u"Unknown change: {}".format(kind))
        self.kind = kind
        self.text = text or u""
        self.find = find or u""
        self.replace_with = replace_with or u""
        self.match_case = bool(match_case)
        self.source = source

    @property
    def name(self):
        return CHANGE_NAMES[self.kind]

    def problem(self, param_kind, param_name=None):
        """What must be put right at step 2 before the check, or None."""
        if param_kind not in KINDS:
            return u"Only text, whole number and yes/no parameters can be changed with Edit Values."
        if self.kind not in changes_for(param_kind):
            return u"{} cannot be used on a {} parameter.".format(self.name, param_kind)
        if self.kind == SET:
            if not self.text.strip():
                return u"Type the new value. To empty the value, choose Clear the value."
            _, problem = to_stored(param_kind, self.text)
            if problem:
                return problem + u"."
        elif self.kind == PREFIX and not self.text:
            return u"Type the text to add before the value."
        elif self.kind == SUFFIX and not self.text:
            return u"Type the text to add after the value."
        elif self.kind == REPLACE and not self.find:
            return u"Type the text to find."
        elif self.kind == COPY:
            if not self.source:
                return u"Choose the parameter to copy from."
            if param_name is not None and self.source == param_name:
                return u"Choose a parameter other than the one being changed."
        elif self.kind == PATTERN:
            if not self.text.strip():
                return u"Type the pattern, for example {Level}-{Type Mark}."
            try:
                if not field_names(self.text):
                    return u"The pattern has no field in { }. To give every element the same value, choose Set the value."
            except PatternError as ex:
                return u"{}".format(ex)
        return None

    def fields(self):
        """The fields the change reads from each element: the pattern's fields, or the parameter copied from."""
        if self.kind == PATTERN:
            try:
                return field_names(self.text)
            except PatternError:
                return []
        if self.kind == COPY and self.source:
            return [self.source]
        return []

    def new_text(self, old_text, get=None):
        """The Outcome for an element whose value shows as old_text. get(name) gives a field's value as text."""
        old_text = u"" if old_text is None else u"{}".format(old_text)
        k = self.kind
        if k == SET:
            return Outcome(self.text)
        if k == CLEAR:
            return Outcome(u"")
        if k == CAPITALS:
            return Outcome(old_text.upper())
        if k in (PREFIX, SUFFIX):
            if not old_text.strip():
                return Outcome(old_text, same_note=NOTHING_TO_ADD_TO)
            return Outcome(self.text + old_text if k == PREFIX else old_text + self.text)
        if k == REPLACE:
            if self.match_case:
                if self.find not in old_text:
                    return Outcome(old_text, same_note=NOT_FOUND)
                return Outcome(old_text.replace(self.find, self.replace_with))
            pattern = re.compile(re.escape(self.find), re.IGNORECASE | re.UNICODE)
            if not pattern.search(old_text):
                return Outcome(old_text, same_note=NOT_FOUND)
            replace_with = self.replace_with
            return Outcome(pattern.sub(lambda m: replace_with, old_text))
        if k == COPY:
            value = get(self.source) if get else None
            value = u"" if value is None else u"{}".format(value)
            if not value.strip():
                return Outcome(left_out=u"There is no value in {} to copy".format(self.source))
            return Outcome(value)
        if k == PATTERN:
            text, missing = fill_pattern(self.text, get or (lambda name: None))
            if missing:
                return Outcome(left_out=u"No value for {}".format(_join([u"{" + m + u"}" for m in missing])))
            return Outcome(text)
        raise ValueError(k)


def _join(words):
    words = list(words)
    if len(words) < 2:
        return u"".join(words)
    return u"{} and {}".format(u", ".join(words[:-1]), words[-1])


def _plural(n, one, many=None):
    return u"{} {}".format(n, one if n == 1 else (many or one + u"s"))


# ---- PD checks, shown and not enforced ---------------------------------------------------------------------------

LOAD_NAME_FORMAT = u"TYPE - LEVEL ROOM NAME ROOM-CODE_ITEM [TAG]"
_LOAD_NAME = re.compile(r"^(POWER|LIGHTING) - \S+ \S.*_\S.*?( \[[^\[\]]+\])?$", re.UNICODE)


def load_name_problems(text):
    """What differs from the PD Load Name format (memory pd-circuit-naming-convention, 02/10/2026):
    TYPE - LEVEL ROOM NAME ROOM-CODE_ITEM [TAG], in capitals, single spaces. An empty list where it matches."""
    text = u"" if text is None else u"{}".format(text)
    problems = []
    if text != text.upper():
        problems.append(u"not all in capitals")
    if text != text.strip():
        problems.append(u"a space at the start or end")
    if u"  " in text:
        problems.append(u"two spaces together")
    if not (text.startswith(u"POWER - ") or text.startswith(u"LIGHTING - ")):
        problems.append(u"does not start with POWER - or LIGHTING -")
    if u"_" not in text:
        problems.append(u"no _ before the item fed")
    if not problems and not _LOAD_NAME.match(text):
        problems.append(u"does not match the format in full")
    return problems


COMMENTS = u"Comments"
LOAD_NAME = u"Load Name"
CIRCUITS = u"OST_ElectricalCircuit"

# ---- the check at step 3 -----------------------------------------------------------------------------------------

CHANGES_STATE = u"Will change"
NO_CHANGE = u"No change"
LEFT_OUT = u"Left out"
STATES = (CHANGES_STATE, NO_CHANGE, LEFT_OUT)

LINKED = u"This is a linked model: open that model to change its elements"
READ_ONLY = u"Read only: Revit does not let this value be changed"
# Revit empties a whole number or yes/no value only on a shared parameter set to hide when it has no value.
CANNOT_EMPTY = (u"Revit cannot leave this parameter with no value: to give it a different value, choose Set the "
                u"value")
NOT_ON_ELEMENT = u"This element has no parameter of this name"
TWO_PARAMETERS = u"This element has two parameters of this name"
OVERWRITES = u"The value already there will be replaced"
IN_GROUP = u"In a group: Revit may refuse to change it outside group edit mode"
COMMENTS_FILLED = u"Comments already holds text, which may be a record of the element's source or of its source drawing"
# PD circuit naming (memory pd-circuit-naming-convention, 02/10/2026): a submain keeps the name of the board it feeds.
FEEDS_BOARD = (u"Electrical Equipment on this circuit may be a board: under the PD circuit naming rule, a circuit "
               u"feeding a board keeps that board's name")


def type_note(total, chosen):
    """The note on a type parameter: how many instances in the model the change reaches."""
    if total == 1:
        text = u"Type parameter: this is the only element of this type in the model"
    else:
        text = u"Type parameter: the change applies to all {} elements of this type in the model".format(total)
    outside = total - chosen
    if outside > 0:
        text += u", {} of them not chosen".format(outside)
    return text


class Check(object):
    """One row of the check: the old and new value, the state and the notes."""

    def __init__(self, kind, old, new, state, notes):
        self.kind = kind
        self.old = old
        self.new = new
        self.state = state
        self.notes = notes

    @property
    def old_text(self):
        return shown(self.kind, self.old)

    @property
    def new_text(self):
        return shown(self.kind, self.new) if self.state == CHANGES_STATE else u""

    @property
    def writes(self):
        return self.state == CHANGES_STATE

    def __repr__(self):
        return u"Check({}, {!r} -> {!r}, {})".format(self.state, self.old, self.new, self.notes)


def assess(kind, change, old=None, outcome=None, left_out=None, read_only=False, blocked=None, in_group=False,
           type_count=None, param_name=None, category=None, feeds_board=False, cannot_empty=False):
    """The check for one element (or one type, for a type parameter).

    left_out: a reason found before the value was read (linked, no such parameter); the row is left out.
    read_only, blocked (the worksharing reason, such as "Borrowed by ..."): the row is left out if it would change.
    cannot_empty: Revit refuses to empty this whole number or yes/no parameter, so Clear leaves the row out.
    type_count: (instances in the model, instances chosen) for a type parameter. param_name and category drive the PD
    checks on Comments and on circuit Load Names; feeds_board marks a circuit that feeds a board."""
    if left_out:
        return Check(kind, old, None, LEFT_OUT, [left_out])
    if outcome is None:
        outcome = change.new_text(shown(kind, old))
    if outcome.left_out:
        return Check(kind, old, None, LEFT_OUT, [outcome.left_out])
    new, problem = to_stored(kind, outcome.text)
    if problem:
        return Check(kind, old, None, LEFT_OUT, [problem])
    if same(kind, old, new):
        return Check(kind, old, new, NO_CHANGE, [outcome.same_note or ALREADY])
    if read_only:
        return Check(kind, old, new, LEFT_OUT, [READ_ONLY])
    if cannot_empty and new is None and kind != TEXT:
        return Check(kind, old, new, LEFT_OUT, [CANNOT_EMPTY])
    if blocked:
        return Check(kind, old, new, LEFT_OUT, [blocked])
    is_load_name = param_name == LOAD_NAME and category == CIRCUITS and kind == TEXT
    if is_load_name and feeds_board:
        return Check(kind, old, new, LEFT_OUT, [FEEDS_BOARD])

    notes = []
    if type_count is not None:
        notes.append(type_note(type_count[0], type_count[1]))
    if in_group:
        notes.append(IN_GROUP)
    if change.kind in REPLACES_OLD and not is_empty(kind, old):
        notes.append(OVERWRITES)
    if param_name == COMMENTS and not is_empty(kind, old):
        notes.append(COMMENTS_FILLED)
    if is_load_name:
        problems = load_name_problems(new)
        if problems:
            notes.append(u"The new Load Name does not follow the PD circuit naming rule {}: {}".format(
                LOAD_NAME_FORMAT, u"; ".join(problems)))
    return Check(kind, old, new, CHANGES_STATE, notes)


def counts(checks):
    """{state: number of rows} for the summary line."""
    out = dict((s, 0) for s in STATES)
    for c in checks:
        out[c.state] = out.get(c.state, 0) + 1
    return out


def summary(checks):
    """The counts in the summary line: "12 will change, 3 with no change, 1 left out"."""
    n = counts(checks)
    return u"{} will change, {} with no change, {} left out".format(n[CHANGES_STATE], n[NO_CHANGE], n[LEFT_OUT])
