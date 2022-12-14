from PySide2 import QtCore, QtGui, QtWidgets
import typing as tp
import attr
import pandas as pd
import logging
import os
import sys

logger = logging.getLogger(__name__)

from ExperimentActions import ExperimentAction, Locals, ActionTypes, ControlFlowAction
from VLCControl import VLCControlAction
from LSLControl import LabRecorderAction
from BrainProductsControl import BVRecorderAction
from PsychopyControl import ZMQPicturePresenterAction
from Misc import exceptionToStr

from Configuration import globalConfiguration


@attr.s(auto_attribs=True, cmp=False, init=False)
class Experiment(QtCore.QObject):
    tbl: pd.DataFrame

    _currentRow: int
    _currentCol: int
    _currentAction: tp.Optional[ExperimentAction] = attr.ib(init=False, default=None)
    _previousRow: int
    _previousCol: int

    _isRunning: bool
    _pendingActionLocations: tp.List[tp.Optional[tp.Tuple[int,int]]]

    # given ((ix, iy), (jx, jy), (kx, ky))
    # if at cell [ix, iy]:
    #   if (jx, jy) is not None and \
    #       if got to this cell normally (not by jumping to it):
    #       then jump to [jx, jy]
    #   else:
    #       evaluate condition
    #       if result is True:
    #           proceed normally
    #       else:
    #           go to cell [kx, ky]
    #
    _controlFlowGotos: tp.Dict[tp.Tuple[int, int], tp.List[tp.Optional[tp.Tuple[int, int]]]]

    locals: Locals

    registeredActionTypes: tp.Dict[str, tp.Type]

    _parentWin: tp.Optional[QtWidgets.QWidget] = None

    sigCurrentActionAboutToChange: QtCore.Signal = QtCore.Signal()
    sigCurrentActionChanged: QtCore.Signal = QtCore.Signal()
    sigStartedRunning = QtCore.Signal()
    sigStoppedRunning = QtCore.Signal()
    sigStartingAction = QtCore.Signal()
    sigContentsAboutToChange = QtCore.Signal(list)
    sigContentsChanged = QtCore.Signal(list)

    def __init__(self, tbl: pd.DataFrame, parentWin: tp.Optional[QtWidgets.QWidget] = None):
        QtCore.QObject.__init__(self, parent=None)

        self.tbl = tbl

        self._parseRepeatBlocks()
        self._parseControlFlowBlocks()

        self._parentWin = parentWin

        self._currentCol = -1
        self._currentRow = 0
        self._previousRow = 0
        self._previousCol = 0
        self._isRunning = False
        self.locals = dict()
        self.registeredActionTypes = None
        self._pendingActionLocations = []

        self.locals['conf'] = globalConfiguration

        if self.registeredActionTypes is None:
            self.registeredActionTypes = dict()
            for actionType in ActionTypes + [
                VLCControlAction,
                LabRecorderAction,
                BVRecorderAction,
                ZMQPicturePresenterAction,
            ]:
                self.registeredActionTypes[actionType.key] = actionType

        self._incrementAction()

    def _parseRepeatBlocks(self):
        tbl = self.tbl

        if not any('repeat'==self._columnLabelToKey(column) for column in tbl.columns):
            # no repeats
            return

        repeatColIndices = [iC for iC in range(len(tbl.columns)) if self._columnLabelToKey(tbl.columns[iC])=='repeat']

        assert len(repeatColIndices)==1  # don't support multiple repeat columns for now

        # read all repeat information
        repeatBlocks = dict()
        for iR in range(len(tbl.index)):
            s = tbl.iat[iR, repeatColIndices[0]]
            if len(s) == 0:
                continue
            cmd, key = s.split(' ', maxsplit=1)
            assert len(key) > 0

            # assert that any row with a repeat action is otherwise empty
            for iC in range(len(tbl.columns)):
                if iC == repeatColIndices[0]:
                    continue
                assert len(tbl.iat[iR, iC]) == 0

            if cmd == 'start':
                assert key not in repeatBlocks # should only define each block once
                repeatBlocks[key] = dict(startRow=iR, repeatRows=[])
            elif cmd == 'end':
                assert key in repeatBlocks
                assert 'endRow' not in repeatBlocks[key]
                repeatBlocks[key]['endRow'] = iR
            elif cmd == 'repeat':
                assert key in repeatBlocks
                repeatBlocks[key]['repeatRows'].append(iR)
            else:
                raise NotImplementedError('Unexpected command: %s' % cmd)

        # make sure all repeats were terminated properly
        for repeatBlock in repeatBlocks.values():
            assert 'endRow' in repeatBlock

        # generate new table, expanding repeats
        refTbl = tbl.copy()
        repeatsFound = True
        repeatDepth = 0
        while repeatsFound:
            repeatsFound = False

            if repeatDepth > 100:
                raise RuntimeError('Probable recursive loop in repeat blocks')
            repeatDepth += 1

            iR_orig = -1
            newTbl = []  # start as a list for efficient append
            while iR_orig < len(tbl.index) - 1:
                iR_orig += 1
                s = tbl.iat[iR_orig, repeatColIndices[0]]
                if len(s) == 0:
                    # not a repeat
                    newTbl.append(tbl.iloc[iR_orig])
                    continue

                cmd, key = s.split(' ', maxsplit=1)
                if cmd != 'repeat':
                    # don't include original repeat boundary lines in output table
                    continue

                repeatsFound = True

                repeatBlock = repeatBlocks[key]
                for iR_block in range(repeatBlock['startRow']+1, repeatBlock['endRow']):
                    newTbl.append(refTbl.iloc[iR_block])

            tbl = pd.DataFrame(newTbl)

        # remove repeat column
        tbl.drop(columns='repeat', inplace=True)

        self.tbl = tbl

    def _parseControlFlowBlocks(self):
        self._controlFlowGotos = dict()

        # note: this assumes that table structure (positions of each control flow action in row, col space)
        #  will not change after this point. If later implement dynamic editing of table, will have to
        #  rewrite this to account for any changes

        tbl = self.tbl

        if not any('controlFlow'==self._columnLabelToKey(column) for column in tbl.columns):
            # no control flow statements
            return

        controlFlowColIndices = [iC for iC in range(len(tbl.columns)) if self._columnLabelToKey(tbl.columns[iC])=='controlFlow']

        assert len(controlFlowColIndices) == 1  # don't support multiple controlFlow columns for now

        clausesInProgress: tp.List[tp.Tuple[str, int, int]] = []
        metaclausesInProgress: tp.List[tp.List[tp.Tuple[str, int, int]]] = []

        for iR in range(len(tbl.index)):
            for iC in controlFlowColIndices:
                s = tbl.iat[iR, iC]
                if len(s) == 0:
                    continue

                if ' ' in s:
                    cmd, conditionStr = s.split(' ', maxsplit=1)
                else:
                    cmd = s
                    conditionStr = ''

                self._controlFlowGotos[(iR, iC)] = [None, None]

                if cmd in ('if', 'while'):
                    assert len(conditionStr) > 0
                    clausesInProgress.append((cmd, iR, iC))
                    metaclausesInProgress.append([(cmd, iR, iC)])
                elif cmd == 'elif':
                    assert len(conditionStr) > 0
                    assert clausesInProgress[-1][0] in ('if', 'elif')
                    termStatement = clausesInProgress.pop(-1)
                    self._controlFlowGotos[termStatement[1:3]][1] = (iR, iC)
                    clausesInProgress.append((cmd, iR, iC))
                    metaclausesInProgress[-1].append((cmd, iR, iC))
                elif cmd == 'else':
                    assert len(conditionStr) == 0
                    assert clausesInProgress[-1][0] in ('if', 'elif')
                    termStatement = clausesInProgress.pop(-1)
                    self._controlFlowGotos[termStatement[1:3]][1] = (iR, iC)
                    clausesInProgress.append((cmd, iR, iC))
                    metaclausesInProgress[-1].append((cmd, iR, iC))
                elif cmd == 'end':
                    assert len(conditionStr) == 0
                    assert clausesInProgress[-1][0] in ('if', 'elif', 'else', 'while')
                    termStatement = clausesInProgress.pop(-1)
                    if termStatement[0] in ('else',):
                        # 'else' without a condition would always evaluates to True, so will never jump
                        pass
                    else:
                        # if previous condition evaluated to false, jump to all the way past end
                        self._controlFlowGotos[termStatement[1:3]][1] = (iR, iC+1)

                    if termStatement[0] == 'while':
                        # loop back to beginning of while loop at end
                        self._controlFlowGotos[(iR, iC)][0] = termStatement[1:3]

                    metaclause = metaclausesInProgress.pop(-1)
                    for termStatement in metaclause:
                        if termStatement[0] in ('elif', 'else'):
                            # if arrived at these statements without jumping, then we were in the previous clause
                            #  and should skip all the way past end
                            self._controlFlowGotos[termStatement[1:3]][0] = (iR, iC+1)

                else:
                    raise NotImplementedError()

        # after going through entire table, all control flow statements should be terminated
        if len(clausesInProgress) > 0 or len(metaclausesInProgress) > 0:
            raise RuntimeError('controlFlow statements not terminated (missing "end"?): %s' % (clausesInProgress,))

        logger.debug('Parsed control flow gotos: %s' % (self._controlFlowGotos,))

    def start(self):
        assert not self._isRunning
        if self.currentAction is None:
            self.restart(doStart=True)
            return
        logger.info('Starting/resuming experiment')
        self.sigStartedRunning.emit()
        self._isRunning = True
        self._startCurrentAction(self.currentAction)

    def stop(self):
        if self._isRunning:
            logger.info('Stopping experiment')
            self._isRunning = False
            if self.currentAction is not None:
                self.currentAction.stop()
            self.sigStoppedRunning.emit()

    def next(self):
        if self._isRunning:
            self.stop()
        self._incrementAction()

    def previous(self):
        if self._isRunning:
            self.stop()
        self._incrementAction(decrement=True)

    def restart(self, doStart: bool = False):
        if self._isRunning:
            self.stop()
        self._incrementAction(initialRowCol=(0, -1))
        if doStart:
            self.start()

    def jumpTo(self, location: tp.Tuple[int,int]):
        if self._isRunning:
            self.stop()
        self._incrementAction(initialRowCol=(location[0], location[1]-1), doAllowSkip=False)

    def runActionsThenStop(self, locations: tp.List[tp.Tuple[int,int]]):
        if self._isRunning:
            self.stop()
        self._pendingActionLocations = locations
        self._pendingActionLocations.append(None)  # an indication to stop at end of list
        self._incrementAction()
        self.start()

    def toggleActionsEnabled(self, locations: tp.List[tp.Tuple[int, int]]):
        self.sigContentsAboutToChange.emit(locations)
        for loc in locations:
            val = self.tbl.iat[loc[0], loc[1]]
            if isinstance(val, str) and len(val) == 0:
                pass # do nothing
            elif isinstance(val, str) and len(val) > 1 and val[0] == '#':
                self.tbl.iat[loc[0], loc[1]] = val[1:].lstrip()
            else:
                self.tbl.iat[loc[0], loc[1]] = '# %s' % (val,)
        self.sigContentsChanged.emit(locations)

        if (self.currentRow, self.currentCol) in locations:
            self._incrementAction()

    @property
    def isRunning(self) -> bool:
        return self._isRunning

    @property
    def currentAction(self) -> tp.Optional[ExperimentAction]:
        return self._currentAction

    @property
    def currentRow(self):
        return self._currentRow

    @property
    def currentCol(self):
        return self._currentCol

    @property
    def previousRow(self):
        return self._previousRow

    @property
    def previousCol(self):
        return self._previousCol

    def _startCurrentAction(self, action):
        if action != self.currentAction:
            # current action changed while this was queued, don't actually start
            return
        action = self.currentAction

        action.sigStopping.connect(self._onActionStopped)
        action.onExceptionWhileRunning = self._onActionExceptionWhileRunning
        action.sigPauseRequested.connect(self.stop)
        QtCore.QCoreApplication.processEvents()  # make sure all pending redraws are complete before calling potentially blocking action
        if not self.isRunning:
            # action was already stopped by processing of events above. Don't start.
            pass
        else:
            logger.debug('Starting action %s' % action)
            self.sigStartingAction.emit()
            try:
                action.start(self.locals)

            except Exception as e:
                msgStr = 'Error while starting action %s\n\n' % action
                msgStr += exceptionToStr(e)
                logger.error(msgStr)
                msgBox = QtWidgets.QMessageBox()
                msgBox.setWindowTitle('Error')
                msgBox.setText(msgStr)
                contBtn = msgBox.addButton("Continue", QtWidgets.QMessageBox.AcceptRole)
                stopBtn = msgBox.addButton("Stop", QtWidgets.QMessageBox.RejectRole)
                raiseBtn = msgBox.addButton("Raise", QtWidgets.QMessageBox.DestructiveRole)
                msgBox.setDefaultButton(contBtn)

                msgBox.exec_()

                if msgBox.clickedButton() == stopBtn:
                    logger.info('Stopping experiment due to error')
                    self._isRunning = False
                    self._onActionStopped(action, self.locals)
                    self.sigStoppedRunning.emit()
                elif msgBox.clickedButton() == contBtn:
                    self._onActionStopped(action, self.locals)
                elif msgBox.clickedButton() == raiseBtn:
                    raise e
                else:
                    raise NotImplementedError()

    def _onActionExceptionWhileRunning(self, action: ExperimentAction, e: Exception) -> str:
        msgStr = 'Error while running action %s\n\n' % action
        msgStr += exceptionToStr(e)
        logger.error(msgStr)
        msgBox = QtWidgets.QMessageBox()
        msgBox.setWindowTitle('Error')
        msgBox.setText(msgStr)
        contBtn = msgBox.addButton("Continue", QtWidgets.QMessageBox.AcceptRole)
        stopBtn = msgBox.addButton("Stop", QtWidgets.QMessageBox.RejectRole)
        raiseBtn = msgBox.addButton("Raise", QtWidgets.QMessageBox.DestructiveRole)
        msgBox.setDefaultButton(contBtn)

        msgBox.exec_()

        if msgBox.clickedButton() == stopBtn:
            logger.info('Stopping experiment due to error')
            self._pendingActionLocations = [None, None]   # signal to stop when checking for next action and don't advance
            return 'stop'
        elif msgBox.clickedButton() == contBtn:
            return 'continue'
        elif msgBox.clickedButton() == raiseBtn:
            return 'raise'
        else:
            raise NotImplementedError()

    def _onActionStopped(self, action: ExperimentAction, locals: Locals):
        action.sigStopping.disconnect(self._onActionStopped)
        action.onExceptionWhileRunning = None
        if action != self.currentAction:
            # outdated action
            logger.warning('Outdated action stopped. Not saving locals')
            return

        self.locals = locals
        if self._isRunning:
            didJump = False
            if isinstance(action, ControlFlowAction):
                # check result to determine whether to jump
                if not action.conditionResult:
                    iR, iC = self._currentRow, self._currentCol
                    if (iR, iC) in self._controlFlowGotos and self._controlFlowGotos[(iR, iC)][1] is not None:
                        iR_new, iC_new = self._controlFlowGotos[(iR, iC)][1]
                        logger.debug('Following controlFlow goto (%d, %d)' % (iR_new, iC_new))
                        self._incrementAction(initialRowCol=(iR_new, iC_new-1))
                        didJump = True

            if not didJump:
                self._incrementAction()
            if self.currentAction is not None:
                QtCore.QTimer.singleShot(0, lambda action=self.currentAction:
                    self._startCurrentAction(action))
            else:
                # no more actions to run
                logger.info('Reached end of experiment')
                self._isRunning = False
                self.sigStoppedRunning.emit()

    @staticmethod
    def _columnLabelToKey(columnLabel) -> str:
        key = columnLabel

        # strip out .num mangling of duplicate columns
        if '.' in key:
            raise NotImplementedError()  # TODO

        # strip out any tags
        # TODO: implement more general regex-based tag removal
        key = key.replace('#skip', '').strip()

        return key

    def _createCurrentAction(self):
        key = self._columnLabelToKey(self.tbl.columns[self._currentCol])

        argStr = self.tbl.iat[self._currentRow, self._currentCol]
        if not isinstance(argStr, str):
            argStr = str(argStr)

        if len(argStr) > 0 and argStr[0] == '#':
            # strip '#'
            argStr = argStr[1:].lstrip()

        if key in ('Label', 'Comment'):
            self._currentAction = None
            return

        assert key in self.registeredActionTypes

        self._currentAction = self.registeredActionTypes[key].fromString(argStr, parentWin=self._parentWin)

    def _incrementAction(self, decrement=False, doAllowSkip=True, initialRowCol=None):
        self.sigCurrentActionAboutToChange.emit()
        self._currentAction = None
        self._previousRow = self._currentRow
        self._previousCol = self._currentCol
        if initialRowCol is not None:
            self._currentRow = initialRowCol[0]
            self._currentCol = initialRowCol[1]
            self._pendingActionLocations = []
        while True:
            _doAllowSkip = doAllowSkip
            doAllowSkip = True
            if len(self._pendingActionLocations) > 0:
                loc = self._pendingActionLocations.pop(0)
                if loc is None:
                    # stop here
                    if self.isRunning:
                        self.stop()
                    # if followed by another None, then don't advance to next action
                    if len(self._pendingActionLocations) > 0 and self._pendingActionLocations[0] is None:
                        self._pendingActionLocations.pop(0)
                        self._createCurrentAction()
                        break
                    else:
                        continue
                self._currentRow = loc[0]
                self._currentCol = loc[1]
                assert 0 <= self._currentRow < len(self.tbl.index)
                assert 0 <= self._currentCol < len(self.tbl.columns)
                _doAllowSkip = False
            else:
                if decrement:
                    self._currentCol -= 1
                    if self._currentCol < 0:
                        self._currentRow -= 1
                        self._currentCol = len(self.tbl.columns) - 1
                    if self._currentRow < 0:
                        self._currentRow = 0
                        self._currentCol = 0
                        break
                else:
                    self._currentCol += 1
                    if self._currentCol >= len(self.tbl.columns):
                        self._currentRow += 1
                        self._currentCol = 0
                    if self._currentRow >= len(self.tbl.index):
                        # reached end of table
                        self._currentRow = len(self.tbl.index)
                        self._currentCol = 0
                        break

            columnLabel = self.tbl.columns[self._currentCol]

            if _doAllowSkip and '#skip' in columnLabel:
                # conditionally ignore columns tagged with '#skip'
                # (unless they are manually jumped to)
                continue

            columnKey = self._columnLabelToKey(columnLabel)
            if columnKey in ('Label', 'Comment'):
                # ignore these columns
                continue

            val = self.tbl.iat[self._currentRow, self._currentCol]

            if isinstance(val, str) and len(val)==0:
                continue
            elif isinstance(val, str) and val[0] == '#' and _doAllowSkip:
                # action is disabled
                continue
            elif isinstance(val, float) and pd.isna(val):
                continue

            self._createCurrentAction()

            if initialRowCol is None and isinstance(self._currentAction, ControlFlowAction):
                iR, iC = self._currentRow, self._currentCol
                if (iR, iC) in self._controlFlowGotos and self._controlFlowGotos[(iR, iC)][0] is not None:
                    # don't even evaluate condition, just jump as specified
                    iR_new, iC_new = self._controlFlowGotos[(iR, iC)][0]
                    self._incrementAction(initialRowCol=(iR_new, iC_new - 1))
                    return

            break

        if decrement and self.currentAction is None:
            # assume we decremented past first action
            self._incrementAction()
            return

        logger.debug('Changed current action to %s' % self.currentAction)

        self.sigCurrentActionChanged.emit()

    @classmethod
    def fromFile(cls, filepath: str, **kwargs):
        _, ext = os.path.splitext(filepath)
        if ext == '.xlsx':
            newTbl = pd.read_excel(filepath)
        elif ext == '.csv':
            newTbl = pd.read_csv(filepath)
        else:
            raise NotImplementedError('Unsupported table extension: %s' % ext)
        newTbl.replace('nan', '')
        newTbl.fillna('', inplace=True)
        return cls(tbl=newTbl, **kwargs)


class ExperimentTableModel(QtCore.QAbstractTableModel):
    textLimit: int = 20

    def __init__(self, experiment: Experiment, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent=parent)
        self._exp = experiment
        self._exp.sigCurrentActionAboutToChange.connect(lambda: self.layoutAboutToBeChanged.emit())
        self._exp.sigCurrentActionChanged.connect(lambda: self.layoutChanged.emit())

        self._exp.sigCurrentActionChanged.connect(
            lambda:
            self.dataChanged.emit(self.index(self._exp.currentRow, self._exp.currentCol), self.index(self._exp.currentRow, self._exp.currentCol), QtCore.Qt.BackgroundRole))
        self._exp.sigCurrentActionChanged.connect(
            lambda:
            self.dataChanged.emit(self.index(self._exp.previousRow, self._exp.previousCol), self.index(self._exp.previousRow, self._exp.previousCol), QtCore.Qt.BackgroundRole))
        self._exp.sigStartedRunning.connect(
            lambda:
            self.dataChanged.emit(self.index(self._exp.currentRow, self._exp.currentCol), self.index(self._exp.currentRow, self._exp.currentCol), QtCore.Qt.BackgroundRole))
        self._exp.sigStoppedRunning.connect(
            lambda:
            self.dataChanged.emit(self.index(self._exp.currentRow, self._exp.currentCol), self.index(self._exp.currentRow, self._exp.currentCol), QtCore.Qt.BackgroundRole))

        self._exp.sigContentsAboutToChange.connect(lambda locs: self.layoutAboutToBeChanged.emit())
        self._exp.sigContentsChanged.connect(lambda locs: self.layoutChanged.emit())

    def headerData(self, section:int, orientation:QtCore.Qt.Orientation, role:int=QtCore.Qt.DisplayRole):
        if role not in(QtCore.Qt.DisplayRole, ):
            return None

        if orientation == QtCore.Qt.Horizontal:
            try:
                return self._exp.tbl.columns.tolist()[section]
            except (IndexError, ):
                return None
        elif orientation == QtCore.Qt.Vertical:
            try:
                return self._exp.tbl.index.tolist()[section]
            except (IndexError, ):
                return None

    def data(self, index, role=QtCore.Qt.DisplayRole):

        if not index.isValid():
            return None

        if role == QtCore.Qt.BackgroundRole:
            if index.row() == self._exp.currentRow and index.column() == self._exp.currentCol:
                if self._exp.isRunning:
                    return QtGui.QColor(100, 255, 255)
                else:
                    return QtGui.QColor(255, 100, 100)
            else:
                return QtGui.QColor(255, 255, 255)

        if role not in(QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole):
            return None

        dataStr = str(self._exp.tbl.iat[index.row(), index.column()])

        textLimit = max(self.textLimit, len(self._exp.tbl.columns[index.column()]))

        if role == QtCore.Qt.DisplayRole:
            if len(dataStr) > textLimit:
                dataStr = dataStr[0:textLimit-2] + '...'
            return dataStr
        elif role == QtCore.Qt.ToolTipRole:
            if len(dataStr) > textLimit:
                return dataStr
            else:
                return None


    def setData(self, index: QtCore.QModelIndex, value: tp.Any, role: int = QtCore.Qt.EditRole) -> bool:
        raise NotImplementedError()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._exp.tbl.index)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._exp.tbl.columns)
