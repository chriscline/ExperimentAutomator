import typing as tp
import attr
import logging
import time
import os

from Configuration import globalConfiguration
from ExperimentActions import ExperimentAction, NoninterruptibleAction
from . import BVRecorderAutomator

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class BVRecorderAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'BVRecorder'
    cmd: str = ''

    _automator: BVRecorderAutomator = attr.ib(init=False)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self._automator = BVRecorderAutomator()

    def _start(self):
        cmdAndArgs = self.cmd.split(' ', maxsplit=1)
        cmd = cmdAndArgs[0]
        args = cmdAndArgs[1:]

        if cmd in ('stop', 'stopViewing', 'pause', 'resume', 'viewImpedance', 'viewData', 'performDCOffsetCorrection'):
            assert len(args)==0
            if cmd == 'stop':
                self._automator.stopRecording()
                logger.info('Stopped BV Recorder recording')
            elif cmd == 'stopViewing':
                self._automator.stopViewing()
                logger.info('Stopped BV Recorder viewing')
            elif cmd == 'pause':
                self._automator.pauseRecording()
                logger.info('Paused BV Recorder recording')
            elif cmd == 'resume':
                self._automator.resumeRecording()
                logger.info('Paused BV Recorder recording')
            elif cmd == 'viewImpedance':
                self._automator.viewImpedance()
                logger.info('Switched BV Recorder to view impedances')
            elif cmd == 'viewData':
                self._automator.viewData()
                logger.info('Switched BV Recorder to view data')
            elif cmd == 'performDCOffsetCorrection':
                self._automator.performDCOffsetCorrection()
                logger.info('Performed DC offset correction in BV Recorder')
            else:
                raise NotImplementedError()
        elif cmd in ('setFilenameAndStart', 'setFilepathAndStart', 'loadWorkspace', 'annotate'):
            assert len(args)==1
            if cmd in ('setFilenameAndStart', 'setFilepathAndStart'):
                if cmd == 'setFilenameAndStart':
                    # assume input is filename only, relative to config DataBasePath
                    filename = self._evalStr(args[0])
                    filepath = os.path.join(globalConfiguration.DataBasePath, filename)
                else:
                    # assume input is absolute filepath
                    filepath = self._evalStr(args[0])
                self._automator.startRecording(toFilepath=filepath)
                assert self._automator.isRecording
                logger.info('Set recorder filepath to %s and started recording' % filepath)
            elif cmd == 'loadWorkspace':
                # assume input is absolute path
                filepath = self._evalStr(args[0])
                self._automator.loadWorkspace(filepath=filepath)
                logger.info('Loaded recorded workspace from %s' % filepath)
            elif cmd == 'annotate':
                annotation = self._evalStr(args[0])
                self._automator.annotate(annotation)
                logger.info('Inserted annotation in recorder: %s' % annotation)
            else:
                raise NotImplementedError()
        else:
            raise NotImplementedError()

        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(cmd=s, **kwargs)

