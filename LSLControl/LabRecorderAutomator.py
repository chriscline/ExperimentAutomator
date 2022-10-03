import pywinauto
from pywinauto.application import Application
import os
import argparse
import logging
import attr
import typing as tp
import socket
import subprocess
import tempfile
import time

from Configuration import globalConfiguration
from Misc import Singleton

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class LabRecorderAutomator(metaclass=Singleton):
    """
    Uses LabRecorder's RCS interface, and GUI automation for a few things the current RCS protocol can't do.

    Note that this does not do any verification of commands being received or streams being available, and
    user-initiated changes in the GUI are not tracked here, due to limitations of the RCS interface.
    """

    _needsLaunch: bool = False
    _requiredStreams: tp.List[str] = attr.ib(factory=list)
    _rcsPort: int = 22345

    _cachedWin: tp.Any = None
    _cachedWinObj: tp.Any = None
    _cachedApp: tp.Any = None

    _proc: tp.Optional[subprocess.Popen] = attr.ib(init=False, default=None)
    _sock: tp.Optional[socket.socket] = attr.ib(init=False, default=None)

    _studyRoot: tp.Optional[str] = None
    _filename: tp.Optional[str] = None
    _isRecording: bool = False  # RCS protocol doesn't allow us to get recording state, so track what we think state is here

    def _createConfig(self) -> str:
        """Returns path to config file"""

        if self._studyRoot is None:
            self._studyRoot = globalConfiguration.DataBasePath
        if self._filename is None:
            self._filename = 'untitled.xdf'

        configContents = ''
        configContents += "StudyRoot=%s\n" % (self._studyRoot,)
        configContents += "PathTemplate=%s\n" % (self._filename,)
        configContents += 'RequiredStreams=%s\n' % (','.join(['"%s"' % stream for stream in self._requiredStreams]), )
        configContents += 'SessionBlocks=[]\n'
        configContents += 'OnlineSync=[]\n'
        configContents += 'RCSEnabled=1\n'
        configContents += 'RCSPort=%d\n' % self._rcsPort
        configContents += 'AutoStart=\n'

        tmpFile = tempfile.NamedTemporaryFile(suffix='.cfg', delete=False)
        tmpFile.close()
        tmpFilepath = tmpFile.name
        print(tmpFilepath)
        with open(tmpFilepath, 'w') as f:
            f.write(configContents)

        return tmpFilepath

    @property
    def isRecording(self):
        return self._isRecording  # note this is just our guess of state, may be incorrect

    def addRequiredStream(self, stream):
        self._requiredStreams.append(stream)
        self._needsLaunch = True

    def removeRequiredStream(self, stream):
        self._requiredStreams.remove(stream)
        self._needsLaunch = True

    def launch(self):
        labRecorderPath = globalConfiguration.LabRecorderPath
        assert labRecorderPath is not None
        args = [labRecorderPath]

        withConfigPath = self._createConfig()
        args.extend(['-c', withConfigPath])

        logger.info('Tmp config path: %s' % withConfigPath)

        self._proc = subprocess.Popen(args)

        # connect to remote control interface
        self._sock = socket.create_connection(('localhost', self._rcsPort))

        self._needsLaunch = False

    def relaunch(self):
        if self._proc is not None:
            self._needsLaunch = False
            self.setState(doStopPrevious=self._isRecording)
            time.sleep(0.5)
            self._sock.close()
            self._sock = None
            self._proc.terminate()
            self._proc = None
            self._cachedApp = None
            self._cachedWin = None
            self._cachedWinObj = None

        self.launch()

    def setState(self,
                 doStopPrevious: bool = False,
                 filename: tp.Optional[str] = None,
                 filepath: tp.Optional[str] = None,
                 doStartRecording: bool = False,
                 doAltTabRefocus: bool = True
                 ):

        if not doAltTabRefocus:
            logger.debug('Looking for current top window')
            prevWin = Application(backend="uia").connect(active_only=True).top_window().wrapper_object()
            logger.debug('found top window')

        if self._needsLaunch:
            logger.warning('Recorder was not launched after changing a launch-only setting. Relaunching now.')
            self.relaunch()

        assert self._proc is not None and self._proc.poll() is None

        if self._cachedApp is None:
            logger.debug('Looking for lab recorder app')
            app = Application(backend="uia").connect(title='Lab Recorder', timeout=1)
            self._cachedApp = app
        else:
            app = self._cachedApp

        if self._cachedWin is None:
            logger.debug('Looking for lab recorder window')
            win = app.window(title='Lab Recorder')
            if True:
                winObj = win.wrapper_object()
            else:
                winObj = None
            self._cachedWin = win
            self._cachedWinObj = winObj
        else:
            logger.info('Using cached window object')
            win = self._cachedWin
            winObj = self._cachedWinObj

        logger.debug('Looking for start and stop buttons')
        if winObj is not None:
            # optimization to speed up automation

            startBtn = pywinauto.Desktop('uia').window(parent=winObj, title='Start', control_type='Button',
                                                       top_level_only=False).wrapper_object()

            studyRootEdit = pywinauto.Desktop('uia').window(
                parent=winObj,
                auto_id='MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.rootEdit',
                control_type='Edit',
                top_level_only=False).wrapper_object()
            fileTemplateEdit = pywinauto.Desktop('uia').window(
                parent=winObj,
                auto_id='MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.lineEdit_template',
                control_type='Edit',
                top_level_only=False).wrapper_object()

            stopBtn = pywinauto.Desktop('uia').window(parent=winObj, title='Stop', control_type='Button', top_level_only=False).wrapper_object()

        else:
            startBtn = win.StartButton
            studyRootEdit = win.StudyRootEdit.wrapper_object()
            fileTemplateEdit = win.TemplateEdit.wrapper_object()
            stopBtn = win.StopButton

        if doStopPrevious:
            logger.info("Stopping previous recording")
            if False:
                self._sock.sendall(b'stop\n')
            else:
                logger.info("Stopping previous recording")
                try:
                    stopBtn.click()
                except AttributeError as e:
                    logger.info('Unable to stop previous recording (already stopped?)')
            self._isRecording = False  # note that this isn't verified

        assert(filename is None or filepath is None)

        if filename is not None or filepath is not None:

            if filename is not None:
                self._filename = filename
            else:
                self._studyRoot, self._filename = os.path.split(filepath)

            if not self._filename.endswith('.xdf'):
                self._filename += '.xdf'  # make sure we specify extension

            logger.info("Setting storage path to %s" % os.path.join(self._studyRoot, self._filename))
            if False:
                # current version of RCS protocol forces a toLower conversion on filename, which we may not want
                #  so use GUI automation instead for now
                self._sock.sendall(('filename {root:%s} {template:%s}\n' % (self._studyRoot, self._filename,)).encode('utf-8'))
            else:
                studyRootEdit.set_text(self._studyRoot)
                fileTemplateEdit.set_text(self._filename)

        if doStartRecording:
            logger.info("Starting new recording")
            if False:
                # note: in current version, the RCS-specific start also runs selectAllStreams, which we may not want
                #  so use GUI automation instead for now
                self._sock.sendall(b'start\n')
            else:
                startBtn.click()
            self._isRecording = True  # note that this isn't verified

        if doAltTabRefocus:
            pywinauto.keyboard.send_keys('%{TAB}')
        else:
            logger.debug('Restoring focus to previous window')
            prevWin.set_focus()
            logger.debug('Done')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s.%(msecs)03d %(filename)20s %(lineno)4d %(levelname)5s: %(message)s',
                        datefmt='%H:%M:%S')

    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", help="Storage location filename (keep previous dir) (no extension)")
    parser.add_argument("--filepath", help="Storage location path (ignore previous dir) (with extension)")
    parser.add_argument("--stopPrevious", help="Stop previous recording", action="store_true")
    parser.add_argument("--startRecording", help="Start recording", action="store_true")
    args = parser.parse_args()

    cls = LabRecorderAutomator()
    cls.setState(
        doStopPrevious=args.stopPrevious,
        filename=args.filename,
        filepath=args.filepath,
        doStartRecording=args.startRecording,
    )