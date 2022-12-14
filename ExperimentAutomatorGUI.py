import sys
import os
from PySide2 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import typing as tp
import attr
import pandas as pd
import logging
import time
import argparse
import psutil
import subprocess
import shelve
import traceback

from Experiment import Experiment, ExperimentTableModel
from LogConsole import LogConsole
from Configuration import globalConfiguration

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, tablePath: str):
        super().__init__()

        self.exp = Experiment.fromFile(tablePath, parentWin=self)
        self.exp.sigStartedRunning.connect(self._onStartedRunning)
        self.exp.sigStoppedRunning.connect(self._onStoppedRunning)
        self.exp.sigCurrentActionChanged.connect(self._scrollToCurrentAction)
        self.exp.sigStartingAction.connect(self._onStartingAction)

        self.expModel = ExperimentTableModel(experiment=self.exp)

        self.mainToolbar = QtWidgets.QToolBar()
        self.mainToolbar.setObjectName('MainToolBar')
        self.mainToolbar.setIconSize(QtCore.QSize(72, 72))
        self.mainToolbar.setFixedHeight(80)

        thisDir, _ = os.path.split(os.path.realpath(__file__))

        self.restartExpAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir,'Resources','baseline-skip_previous-24px.svg')),
            'Restart')
        self.restartExpAction.triggered.connect(self.exp.restart)
        self.mainToolbar.addAction(self.restartExpAction)

        self.prevAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir,'Resources','baseline-fast_rewind-24px.svg')),
            'Previous')
        self.prevAction.triggered.connect(self.exp.previous)
        self.mainToolbar.addAction(self.prevAction)

        self.playAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir, 'Resources', 'baseline-play_arrow-24px.svg')),
            '&Play')
        self.playAction.triggered.connect(self._onPlayPause)
        self.playAction.setShortcut(QtGui.QKeySequence(" "))
        self.mainToolbar.addAction(self.playAction)

        self.nextAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir,'Resources','baseline-fast_forward-24px.svg')),
            'Next')
        self.nextAction.triggered.connect(self.exp.next)
        self.mainToolbar.addAction(self.nextAction)

        elapsedContainerWidget = QtWidgets.QWidget()
        elapsedContainerWidget.setLayout(QtWidgets.QVBoxLayout())
        self.elapsedTimeLabel = QtWidgets.QLabel('Elapsed time\n in action:')
        elapsedContainerWidget.layout().addWidget(self.elapsedTimeLabel, stretch=2)
        self.elapsedTimeField = QtWidgets.QLabel('')
        elapsedContainerWidget.layout().addWidget(self.elapsedTimeField, stretch=1)
        self.elapsedTimeLabel.setVisible(False)
        self.elapsedTimeField.setVisible(False)
        self.mainToolbar.addWidget(elapsedContainerWidget)
        self.timeLastStarted = None
        self.elapsedTimeUpdateTimer = QtCore.QTimer()
        self.elapsedTimeUpdateTimer.timeout.connect(self._updateElapsedTime)
        self.elapsedTimeUpdateTimer.setInterval(100)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.mainToolbar.addWidget(spacer)

        self.evalAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir, 'Resources', 'console.svg')),
            'Evaluate code')
        self.evalAction.triggered.connect(self.evalStr)
        self.mainToolbar.addAction(self.evalAction)

        self.logCommentAction = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(thisDir, 'Resources', 'message-plus.svg')),
            'Add comment to log')
        self.logCommentAction.triggered.connect(self.logCommentFromDialog)
        self.mainToolbar.addAction(self.logCommentAction)

        self.addToolBar(self.mainToolbar)

        self.setWindowTitle('ExperimentAutomatorGUI')

        self.mainLayout = QtWidgets.QSplitter()
        self.setCentralWidget(self.mainLayout)
        self.mainLayout.setOrientation(QtCore.Qt.Vertical)

        self.tblView = QtWidgets.QTableView()
        self.tblView.setModel(self.expModel)
        self.tblView.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tblView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tblView.customContextMenuRequested.connect(self._onTableContextMenuRequested)
        self.tblView.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.MinimumExpanding)
        self.tblView.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.mainLayout.addWidget(self.tblView)
        self.mainLayout.setStretchFactor(0, 2)

        self.logView = LogConsole()
        self.logView.addHandler(logging.getLogger(), level=logging.INFO)
        self.mainLayout.addWidget(self.logView)
        self.mainLayout.setStretchFactor(1, 1)
        
        QtCore.QTimer.singleShot(0, lambda: self.loadSettings())



    def closeEvent(self, event:QtGui.QCloseEvent):
        self._onAboutToClose()
        event.accept()

    def _onPlayPause(self):
        logger.debug('Play/pause triggered')
        if self.exp.isRunning:
            self.exp.stop()
        else:
            self.exp.start()

    def _onStartedRunning(self):
        thisDir, _ = os.path.split(os.path.realpath(__file__))
        self.playAction.setIcon(
            QtGui.QIcon(os.path.join(thisDir, 'Resources','baseline-pause-24px.svg')))
        self.playAction.setText('&Pause')
        self.elapsedTimeUpdateTimer.start()
        for obj in (self.elapsedTimeLabel, self.elapsedTimeField):
            obj.setVisible(True)

    def _onStoppedRunning(self):
        thisDir, _ = os.path.split(os.path.realpath(__file__))
        self.playAction.setIcon(
            QtGui.QIcon(os.path.join(thisDir, 'Resources', 'baseline-play_arrow-24px.svg')))
        self.playAction.setText('&Play')
        self.elapsedTimeUpdateTimer.stop()
        self.timeLastStarted = None
        self.elapsedTimeField.setText('')
        for obj in (self.elapsedTimeLabel, self.elapsedTimeField):
            obj.setVisible(False)

    def _onStartingAction(self):
        self.timeLastStarted = time.time()

    def _updateElapsedTime(self):
        if self.timeLastStarted is not None:
            self.elapsedTimeField.setText('%.1f s' % (time.time() - self.timeLastStarted,))
        else:
            self.elapsedTimeField.setText('')

    def logCommentFromDialog(self):
        logger.info('Getting user comment to add to log')
        resp, ok = QtWidgets.QInputDialog.getMultiLineText(None,
                                                  'Log comment',
                                                  'Enter message to add to log')
        if not ok:
            logger.info('Cancelled adding of comment to log')
            return

        logger.info('User added comment to log:\n<beginUserComment>\n%s\n<endUserComment>' % (resp,))

    def evalStr(self):
        logger.info('Getting user input to evaluate')
        resp, ok = QtWidgets.QInputDialog.getMultiLineText(None,
                                                           'Eval',
                                                           'Enter code to evaluate')
        if not ok:
            logger.info('Cancelled getting input to evaluate')
            return

        logger.info('Evaluating user input:\n<beginExtraEval>\n%s\n<endExtraEval>' % (resp,))

        try:
            exec(resp, globals(), self.exp.locals)
        except SyntaxError as err:
            error_class = err.__class__.__name__
            detail = err.args[0]
            line_number = err.lineno
            logger.error("%s at line %d: %s" % (error_class, line_number, detail))
        except Exception as err:
            error_class = err.__class__.__name__
            detail = err.args[0]
            cl, exc, tb = sys.exc_info()
            line_number = traceback.extract_tb(tb)[-1][1]
            logger.error("%s at line %d: %s" % (error_class, line_number, detail))

        logger.info('Done evaluating user input')

    def _scrollToCurrentAction(self):
        self.tblView.scrollTo(self.expModel.index(self.exp.currentRow, self.exp.currentCol))

    def _onTableContextMenuRequested(self, pos: QtCore.QPoint):
        selectedCellIndices = self.tblView.selectedIndexes()
        if len(selectedCellIndices) < 1:
            # no cells selected, don't open a menu
            return

        contextMenu = QtWidgets.QMenu('Context menu')

        if len(selectedCellIndices) == 1:
            row = selectedCellIndices[0].row()
            col = selectedCellIndices[0].column()

            action1 = QtWidgets.QAction('&Jump here')
            action1.triggered.connect(lambda *args, row=row, col=col: self.exp.jumpTo(location=(row, col)))
            contextMenu.addAction(action1)

        locs = [(index.row(), index.column()) for index in selectedCellIndices]

        if len(locs) > 1:
            # sort locs in typical order rather than the order in which they were selected
            locs.sort()

        action2 = QtWidgets.QAction('&Run action%s then stop' % ('s' if len(locs) > 1 else '',))
        action2.triggered.connect(lambda *args, locs=locs: self.exp.runActionsThenStop(locations=locs))
        contextMenu.addAction(action2)

        action3 = QtWidgets.QAction('&Toggle enabled')
        action3.triggered.connect(lambda *args, locs=locs: self.exp.toggleActionsEnabled(locations=locs))
        contextMenu.addAction(action3)

        contextMenu.exec_(self.tblView.mapToGlobal(pos))

        self.tblView.clearSelection()

    def _onAboutToClose(self):
        logger.info('Terminating child processes before closing')
        if False:
            pid = os.getpid()
            subprocess.run('taskkill /t /pid %d' % pid)
            time.sleep(2)
            subprocess.run('taskkill /f /t /pid %d' % pid)
        else:
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                subprocess.run('taskkill /t /pid %d' % child.pid)
            time.sleep(0.5)
            children = current_process.children(recursive=True)
            for child in children:
                subprocess.run('taskkill /f /t /pid %d' % child.pid)

        self.saveSettings()

    def _getPersistentSettingsPath(self) -> str:
        dir = os.getenv('LOCALAPPDATA')
        return os.path.join(dir, 'ExperimentAutomator', 'ExperimentAutomatorUserSettings')

    def loadSettings(self):
        settingsPath = self._getPersistentSettingsPath()
        ext = '.dat'
        if not os.path.exists(settingsPath + ext):
            logging.info('No settings to load')
            return

        try:
            with shelve.open(settingsPath, flag='r') as s:
                logger.info('Loading settings from %s' % (settingsPath,))
                self.restoreGeometry(s['window_geometry'])
                self.restoreState(s['window_state'])
        except Exception as e:
            logger.warning('Problem reading previous settings.')

    def saveSettings(self):
        settingsPath = self._getPersistentSettingsPath()
        dir, _ = os.path.split(settingsPath)
        os.makedirs(dir, exist_ok=True)

        logger.info('Saving settings to %s' % (settingsPath,))
        try:
            with shelve.open(settingsPath) as s:
                s['window_geometry'] = self.saveGeometry()
                s['window_state'] = self.saveState()
        except PermissionError as e:
            logger.error('Unable to save settings: could not open settings file for writing.')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s.%(msecs)03d %(filename)20s %(lineno)4d %(levelname)5s: %(message)s',
                        datefmt='%H:%M:%S')

    parser = argparse.ArgumentParser()
    parser.add_argument('--experimentTable',
                        help='Path to experiment definition (csv or xlsx)',
                        default=None)
    args = parser.parse_args()

    app = pg.mkQApp()

    if args.experimentTable is None:
        if False:
            # TODO: debug, delete
            args.experimentTable = os.path.join('Examples', 'MinimalExample.csv')
        else:
            args.experimentTable,_ = QtWidgets.QFileDialog.getOpenFileName(None, 'Open experiment table','..','Tables (*.csv *.xlsx)')

    mainWin = MainWindow(tablePath=args.experimentTable)
    mainWin.show()
    sys.exit(app.exec_())
