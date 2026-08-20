import ast
import logging
import typing as tp

from qtpy import QtCore, QtGui, QtWidgets

from ExperimentAutomator.Experiment import Experiment

logger = logging.getLogger(__name__)


# membership checked with `type(v) in ...` rather than isinstance: bool is a subclass of int,
# and subclasses like np.float64 should not be edited as if they were their parent type
_EDITABLE_TYPES = (bool, int, float, str, type(None))

_valueDisplayLimit = 100
_valueTooltipLimit = 2000


class _RowSnapshot(tp.NamedTuple):
    key: tp.Any  # raw dict key, kept for lookups back into locals
    nameText: str
    typeName: str
    displayText: str
    tooltipText: str
    editable: bool


def _safeRepr(value: tp.Any) -> str:
    # arbitrary objects in locals can raise anything from __repr__
    # (e.g. Configuration raises KeyError, not AttributeError, from __getattr__)
    try:
        return repr(value)
    except Exception as e:
        return '<repr() failed: %s>' % (type(e).__name__,)


def _truncate(s: str, limit: int) -> str:
    if len(s) > limit:
        return s[:limit - 3] + '...'
    return s


def _buildRowSnapshot(key: tp.Any, value: tp.Any) -> _RowSnapshot:
    try:
        nameText = str(key)
    except Exception as e:
        nameText = '<str() failed: %s>' % (type(e).__name__,)
    fullRepr = _safeRepr(value)
    return _RowSnapshot(
        key=key,
        nameText=nameText,
        typeName=type(value).__name__,
        displayText=_truncate(fullRepr, _valueDisplayLimit),
        tooltipText=_truncate(fullRepr, _valueTooltipLimit),
        editable=type(value) in _EDITABLE_TYPES,
    )


def _parseEditText(text: str, targetType: type) -> tp.Any:
    """
    Parse editor text as a Python literal, preserving the target type.

    Any target type may be set to None, either explicitly or (for non-str targets) with empty
    input. A NoneType target accepts any primitive literal, since None has no type to preserve.

    Raises ValueError if the text cannot be parsed or does not match the target type.
    """
    stripped = text.strip()
    if len(stripped) == 0:
        if targetType is str:
            raise ValueError("ambiguous empty input for a str variable: use '' for an empty string, or None")
        return None
    try:
        val = ast.literal_eval(stripped)
    except Exception:
        # literal_eval can raise ValueError, SyntaxError, TypeError, MemoryError, or RecursionError
        if targetType is str:
            raise ValueError("not a valid Python literal (string values must be quoted, e.g. 'text')")
        else:
            raise ValueError('not a valid Python literal')
    if val is None:
        return None
    if targetType is type(None):
        if type(val) in (bool, int, float, str):
            return val
        raise ValueError('unsupported literal type %s' % (type(val).__name__,))
    if type(val) is targetType:
        return val
    if targetType is float and type(val) is int:
        return float(val)
    raise ValueError('expected %s literal, got %s' % (targetType.__name__, type(val).__name__))


class LocalsTableModel(QtCore.QAbstractTableModel):
    _columnLabels: tp.ClassVar[tp.Tuple[str, ...]] = ('Name', 'Type', 'Value')

    def __init__(self, experiment: Experiment, parent: tp.Optional[QtCore.QObject] = None):
        QtCore.QAbstractTableModel.__init__(self, parent=parent)
        self._exp = experiment
        self._rows: tp.List[_RowSnapshot] = []
        self.refreshFromLocals()

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._columnLabels)

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            try:
                return self._columnLabels[section]
            except IndexError:
                return None
        return None

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        try:
            row = self._rows[index.row()]
        except IndexError:
            return None
        col = index.column()

        if role == QtCore.Qt.DisplayRole:
            return (row.nameText, row.typeName, row.displayText)[col]
        elif role == QtCore.Qt.ToolTipRole:
            if col == 2:
                return row.tooltipText
        elif role == QtCore.Qt.EditRole:
            if col != 2:
                return None
            # look up the live value rather than the snapshot so the editor pre-fills the
            # current value; repr() form round-trips through _parseEditText unchanged
            if row.key not in self._exp.locals:
                return None
            val = self._exp.locals[row.key]
            if type(val) not in _EDITABLE_TYPES:
                return None
            # returning a str also ensures the default delegate uses a QLineEdit rather than
            # typed editors (QSpinBox caps at int32; QDoubleSpinBox rounds to 2 decimals)
            return _safeRepr(val)
        return None

    def flags(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        # editability comes from the snapshot, not a live lookup: flags() is called
        # constantly during painting; setData re-validates against the live value anyway
        if index.column() == 2 and self._rows[index.row()].editable:
            flags |= QtCore.Qt.ItemIsEditable
        return flags

    def setData(self, index: QtCore.QModelIndex, value: tp.Any, role: int = QtCore.Qt.EditRole) -> bool:
        if role != QtCore.Qt.EditRole or not index.isValid() or index.column() != 2:
            return False

        key = self._rows[index.row()].key
        if key not in self._exp.locals:
            logger.warning('Cannot edit variable %s: no longer defined' % (self._rows[index.row()].nameText,))
            return False

        # re-derive the target type from the live value at commit time, in case it
        # changed (e.g. by a running experiment) while the editor was open
        oldVal = self._exp.locals[key]
        targetType = type(oldVal)
        if targetType not in _EDITABLE_TYPES:
            logger.warning('Cannot edit variable %s: type %s is not editable' % (key, targetType.__name__))
            return False

        text = str(value)
        try:
            newVal = _parseEditText(text, targetType)
        except ValueError as e:
            logger.warning('Rejected edit of variable %s: could not convert %r to %s (%s)' % (
                key, text, targetType.__name__, e))
            return False

        if type(newVal) is targetType and newVal == oldVal:
            # no-op commit (e.g. opened editor and immediately pressed enter)
            return True

        # mutate in place; the locals dict object itself must never be rebound
        self._exp.locals[key] = newVal
        logger.info('Variable %s changed from %s to %s via Variables panel' % (
            key, _safeRepr(oldVal), _safeRepr(newVal)))
        self._rows[index.row()] = _buildRowSnapshot(key, newVal)
        self.dataChanged.emit(self.index(index.row(), 1), self.index(index.row(), 2))
        return True

    def refreshFromLocals(self):
        newRows = [_buildRowSnapshot(key, val) for key, val in self._exp.locals.items()]
        if [row.key for row in self._rows] == [row.key for row in newRows]:
            # same variables: update changed rows only, preserving view selection
            for iRow, (oldRow, newRow) in enumerate(zip(self._rows, newRows)):
                if oldRow != newRow:
                    self._rows[iRow] = newRow
                    self.dataChanged.emit(self.index(iRow, 1), self.index(iRow, 2))
        else:
            self.beginResetModel()
            self._rows = newRows
            self.endResetModel()


class VariablesTableView(QtWidgets.QTableView):
    def __init__(self, parent: tp.Optional[QtWidgets.QWidget] = None):
        QtWidgets.QTableView.__init__(self, parent=parent)
        self.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setWordWrap(False)

    def isEditing(self) -> bool:
        # state() is protected in C++; calling it from within a subclass works in both PyQt and PySide
        return self.state() == QtWidgets.QAbstractItemView.EditingState


class VariablesDockWidget(QtWidgets.QDockWidget):
    _refreshIntervalMs: int = 1000

    def __init__(self, experiment: Experiment, parent: tp.Optional[QtWidgets.QWidget] = None):
        QtWidgets.QDockWidget.__init__(self, 'Variables', parent=parent)
        self.setObjectName('VariablesDock')  # required for saveState/restoreState persistence

        self._exp = experiment

        self._model = LocalsTableModel(experiment=experiment, parent=self)
        self._view = VariablesTableView(parent=self)
        self._view.setModel(self._model)
        self._view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.setWidget(self._view)

        # a periodic refresh (only while visible) is the only way to catch in-place mutation
        # of held objects (e.g. conf.addConfiguration(...)), which changes no keys and emits
        # no signal; timer events are still delivered inside nested modal event loops
        self._refreshTimer = QtCore.QTimer(self)
        self._refreshTimer.setInterval(self._refreshIntervalMs)
        self._refreshTimer.timeout.connect(self.refresh)

        self.visibilityChanged.connect(self._onVisibilityChanged)

        self._exp.sigCurrentActionChanged.connect(self.refresh)

    def _onVisibilityChanged(self, visible: bool):
        if visible:
            self.refresh()
            self._refreshTimer.start()
        else:
            self._refreshTimer.stop()

    def refresh(self):
        if not self.isVisible():
            return
        if self._view.isEditing():
            # don't pull the rug out from under an in-progress edit
            return
        self._model.refreshFromLocals()
