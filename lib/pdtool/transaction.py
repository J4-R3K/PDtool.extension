# -*- coding: utf-8 -*-
"""PD failure handling for PDtool changes.

Every change runs in a transaction named "PD: <label>" with a failures preprocessor that
  - clears each warning (so no warning dialog appears) and records its text and element ids;
  - rolls the whole transaction back on any error (so no error dialog appears) and records Revit's reason.
The commit status is always checked, so a change Revit refused is never reported as done.

Do not use pyRevit's revit.Transaction(swallow_errors=True) instead: its FailureSwallower RESOLVES errors, and one of
the resolutions it tries is deleting elements.

Use:

    from pdtool.transaction import run, transaction, transaction_group

    result = run(doc, "Rename sheets", rename_all)        # never raises
    if not result.committed:
        forms.alert(result.summary())

    with transaction(doc, "Rename sheets") as tx:         # raises RolledBack if Revit refuses the change
        rename_all()
    print(tx.result.warnings)

    with transaction_group(doc, "Place fixtures", dry_run=True) as group:   # dry run: everything undone at the end
        for item in items:
            group.add(run(doc, "place " + item.name, lambda: place(item)))
    print(group.summary())                                # dry_run=False: one Ctrl+Z undoes it all

Existing buttons (converted 09/10/2026) use the drop-ins, which keep Revit's error dialog because the user is at the
screen, but clear warnings, check every commit and stop with "Not done" if Revit rolled the change back:

    t = PDTransaction(doc, "Rename sheets")      # was Transaction(doc, ...) or DB.Transaction(doc, ...)
    with PDRevitTransaction("Rename views"):     # was with revit.Transaction("Rename views"):

run(), transaction() and transaction_group() roll errors back without a dialog (for work nobody is watching).
"""
from Autodesk.Revit.DB import (
    FailureProcessingResult,
    FailureSeverity,
    IFailuresPreprocessor,
    SubTransaction,
    Transaction,
    TransactionGroup,
    TransactionStatus,
)

PREFIX = "PD: "


def name_of(label):
    """The transaction name with the PD prefix (added once)."""
    name = (label or "change").strip()
    return name if name.startswith(PREFIX) else PREFIX + name


class FailureCollector(IFailuresPreprocessor):
    """Records every failure Revit raises at commit and clears warnings. Errors roll the transaction back without a
    dialog (roll_back_errors=True), or are left to Revit's own error dialog so the user can pick a fix such as
    "Delete element(s)" or press Cancel (roll_back_errors=False, used by the PDTransaction drop-in for buttons)."""

    def __init__(self, roll_back_errors=True):
        self.warnings = []
        self.errors = []
        self.roll_back_errors = roll_back_errors

    def PreprocessFailures(self, accessor):
        has_error = False
        for message in accessor.GetFailureMessages():
            severity = message.GetSeverity()
            text = _describe(message)
            if severity == FailureSeverity.Warning:
                self.warnings.append(text)
                accessor.DeleteWarning(message)
            elif severity in (FailureSeverity.Error, FailureSeverity.DocumentCorruption):
                # (FailureSeverity.None can't be written in Python 3, so the error kinds are named instead)
                has_error = True
                self.errors.append("{}: {}".format(severity, text))
        if has_error and self.roll_back_errors:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def _describe(message):
    text = message.GetDescriptionText()
    try:
        ids = list(message.GetFailingElementIds())
        if ids:
            # str(ElementId) gives the number in every Revit year
            text += " [elements {}]".format(", ".join(str(i) for i in ids))
    except Exception:
        pass
    return text


def attach(t, roll_back_errors=True):
    """Sets PD failure handling on a transaction that has not been started. Returns the collector."""
    collector = FailureCollector(roll_back_errors)
    options = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(collector)
    options.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(options)
    return collector


class TxResult(object):
    """What happened to one transaction."""

    def __init__(self, name):
        self.name = name
        self.committed = False
        self.status = None
        self.warnings = []
        self.errors = []
        self.value = None

    def summary(self):
        lines = ["{}: {}".format(self.name, "done" if self.committed else "not done, nothing was changed")]
        lines.extend("  Error: " + e for e in self.errors)
        lines.extend("  Warning (cleared): " + w for w in self.warnings)
        return "\n".join(lines)

    def __repr__(self):
        return "<TxResult {} committed={} warnings={} errors={}>".format(
            self.name, self.committed, len(self.warnings), len(self.errors))


def run(doc, label, action, *args):
    """Runs action(*args) in its own transaction with PD failure handling. Never raises: an exception in the action
    rolls the transaction back and is reported in the result. The action's return value is result.value."""
    result = TxResult(name_of(label))
    t = Transaction(doc, result.name)
    collector = attach(t)
    try:
        t.Start()
        result.value = action(*args)
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        result.status = TransactionStatus.RolledBack
        result.errors.append("{}: {}".format(type(ex).__name__, ex))
        result.warnings.extend(collector.warnings)
        t.Dispose()
        return result

    status = t.Commit()
    result.status = status
    result.committed = status == TransactionStatus.Committed
    result.warnings.extend(collector.warnings)
    result.errors.extend(collector.errors)
    if not result.committed and not result.errors:
        result.errors.append("Revit did not commit the change (status {}).".format(status))
    t.Dispose()
    return result


class RolledBack(Exception):
    """Revit refused the change; nothing was changed. .result holds the reasons."""

    def __init__(self, result):
        Exception.__init__(self, result.summary())
        self.result = result


class transaction(object):
    """Context manager form of run(). An exception in the block rolls back and is raised again; a change Revit
    refuses raises RolledBack (set raise_on_rollback=False to read self.result instead)."""

    def __init__(self, doc, label, raise_on_rollback=True):
        self.result = TxResult(name_of(label))
        self._t = Transaction(doc, self.result.name)
        self._collector = attach(self._t)
        self._raise = raise_on_rollback

    def __enter__(self):
        self._t.Start()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                if self._t.HasStarted() and not self._t.HasEnded():
                    self._t.RollBack()
                self.result.status = TransactionStatus.RolledBack
                self.result.errors.append("{}: {}".format(exc_type.__name__, exc))
                self.result.warnings.extend(self._collector.warnings)
                return False  # raise the block's exception again

            status = self._t.Commit()
            self.result.status = status
            self.result.committed = status == TransactionStatus.Committed
            self.result.warnings.extend(self._collector.warnings)
            self.result.errors.extend(self._collector.errors)
            if not self.result.committed:
                if not self.result.errors:
                    self.result.errors.append("Revit did not commit the change (status {}).".format(status))
                if self._raise:
                    raise RolledBack(self.result)
            return False
        finally:
            self._t.Dispose()


def _report(result):
    """Prints cleared warnings and a refused change to the pyRevit output window (silently skipped outside pyRevit)."""
    if not result.warnings and result.committed:
        return
    try:
        from pyrevit import script
        output = script.get_output()
    except Exception:
        return
    if not result.committed:
        output.print_md("**Not done: {}.** Revit rolled the change back, so nothing was changed by it.".format(result.name))
        for e in result.errors:
            output.print_md("- Reason: {}".format(e))
    for w in result.warnings:
        output.print_md("- {}: Revit warning, cleared without a dialog: {}".format(result.name, w))


class PDTransaction(object):
    """Drop-in for Autodesk.Revit.DB.Transaction in existing buttons: same calls (Start, Commit, RollBack, HasStarted,
    `with ... as t`), plus PD failure handling.

    - The name shown in Revit's Undo list gets the "PD: " prefix.
    - Warnings are cleared without a dialog and listed in the output window.
    - Errors still show Revit's own dialog (the user is at the screen and may pick a fix), unless roll_back_errors=True.
    - Commit() checks the result. If Revit rolled the change back (an error, or Cancel pressed in its dialog), it prints
      "Not done" with Revit's reason and raises RolledBack, so the button never reports a refused change as done.
    """

    def __init__(self, doc, name=None, roll_back_errors=False):
        self.result = TxResult(name_of(name))
        self._t = Transaction(doc, self.result.name)
        self._collector = attach(self._t, roll_back_errors)

    def Start(self, *args):
        return self._t.Start(*args)

    def Commit(self):
        status = self._t.Commit()
        self.result.status = status
        self.result.committed = status == TransactionStatus.Committed
        self.result.warnings = list(self._collector.warnings)
        self.result.errors = list(self._collector.errors)
        if not self.result.committed and not self.result.errors:
            self.result.errors.append("Revit did not commit the change (status {}).".format(status))
        _report(self.result)
        if not self.result.committed:
            raise RolledBack(self.result)
        return status

    def RollBack(self):
        # A rollback the button asks for is not a failure; ignore it if the transaction has already ended
        if self._t.HasStarted() and not self._t.HasEnded():
            return self._t.RollBack()
        return TransactionStatus.RolledBack

    def Dispose(self):
        self._t.Dispose()

    def __getattr__(self, attribute):
        # HasStarted, HasEnded, GetStatus, GetName, GetFailureHandlingOptions, ... go to the real transaction
        if attribute.startswith("_"):
            raise AttributeError(attribute)  # never recurse on our own fields
        return getattr(self._t, attribute)

    def __enter__(self):
        return self  # like DB.Transaction: `with` does not start it

    def __exit__(self, exc_type, exc, tb):
        self._t.Dispose()  # rolls back if the block left it started
        return False


class PDRevitTransaction(object):
    """Drop-in for pyRevit's `with revit.Transaction(name, doc=None, nested=False):` with the PDTransaction handling.
    Starts on entry, commits on exit (raising RolledBack if Revit refused), rolls back if the block raised. Like pyRevit's
    own (revit/db/transaction.py), it opens a SubTransaction instead when nested=True or when a transaction is already
    open on the document (Revit refuses a second Transaction then); failures are then handled by the outer transaction."""

    def __init__(self, name=None, doc=None, nested=False, **ignored):
        if doc is None:
            from pyrevit import revit
            doc = revit.doc
        self._doc = doc
        self._name = name
        self._nested = nested
        self._tx = None
        self._sub = None

    def __enter__(self):
        if self._nested or self._doc.IsModifiable:
            self._sub = SubTransaction(self._doc)
            self._sub.Start()
            return self._sub
        self._tx = PDTransaction(self._doc, self._name)
        self._tx.Start()
        return self._tx

    def __exit__(self, exc_type, exc, tb):
        if self._sub is not None:
            try:
                if exc_type is not None:
                    if self._sub.HasStarted() and not self._sub.HasEnded():
                        self._sub.RollBack()
                else:
                    self._sub.Commit()
                return False
            finally:
                self._sub.Dispose()
        try:
            if exc_type is not None:
                self._tx.RollBack()
                return False
            self._tx.Commit()
            return False
        finally:
            self._tx.Dispose()


class transaction_group(object):
    """Groups several transactions. dry_run=True undoes everything at the end (a trial run that reports what would
    happen); dry_run=False merges them into one undo step. An exception in the block undoes everything and is raised
    again. Collect each run() result with add() to get a summary."""

    def __init__(self, doc, label, dry_run=False):
        self.name = name_of(label)
        self.dry_run = dry_run
        self.results = []
        self.kept = False
        self._g = TransactionGroup(doc, self.name)

    def add(self, result):
        self.results.append(result)
        return result

    def __enter__(self):
        self._g.Start()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not (self._g.HasStarted() and not self._g.HasEnded()):
                return False
            if exc_type is not None or self.dry_run:
                self._g.RollBack()
            else:
                self.kept = self._g.Assimilate() == TransactionStatus.Committed
            return False
        finally:
            self._g.Dispose()

    def summary(self):
        done = sum(1 for r in self.results if r.committed)
        lines = ["{}{}: {} of {} changes {}".format(
            self.name, " (trial run, everything undone)" if self.dry_run else "",
            done, len(self.results), "would be made" if self.dry_run else "made")]
        for r in self.results:
            if r.errors or r.warnings:
                lines.append(r.summary())
        return "\n".join(lines)
