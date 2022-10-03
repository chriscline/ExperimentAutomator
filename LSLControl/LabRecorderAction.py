import typing as tp
import attr
import logging
import time

from ExperimentActions import ExperimentAction, NoninterruptibleAction
from . import LabRecorderAutomator

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class LabRecorderAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'LabRecorder'
    cmd: str = ''

    _automator: LabRecorderAutomator = attr.ib(init=False)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self._automator = LabRecorderAutomator()

    def _start(self):
        cmdAndArgs = self.cmd.split(' ', maxsplit=1)
        cmd = cmdAndArgs[0]
        args = cmdAndArgs[1:]

        if cmd in ('launch', 'relaunch', 'start', 'stop'):
            assert len(args)==0
            if cmd == 'launch':
                self._automator.launch()
                logger.info('Launched LabRecorder')
            elif cmd == 'relaunch':
                self._automator.relaunch()
                logger.info('Relaunched LabRecorder')
            elif cmd == 'start':
                self._automator.setState(doStartRecording=True)
                logger.info('Started LabRecorder recording')
            elif cmd == 'stop':
                self._automator.setState(doStopPrevious=True)
                logger.info('Stopped LabRecorder recording')
        elif cmd in ('setFilename', 'setFilenameAndStart', 'setFilepath', 'setFilepathAndStart',
                     'addRequiredStream', 'removeRequiredStream'):
            assert len(args)==1
            if cmd == 'addRequiredStream':
                streamName = self._evalStr(args[0])
                self._automator.addRequiredStream(streamName)
                logger.info('Added new required stream (%s). Will not take effect until launch.' % streamName)
            elif cmd == 'removeRequiredStream':
                streamName = self._evalStr(args[0])
                self._automator.removeRequiredStream(streamName)
                logger.info('Removed required stream (%s). Will not take effect until launch.' % streamName)
            else:
                if cmd in ('setFilename', 'setFilenameAndStart'):
                    filename = self._evalStr(args[0])
                    filepath = None
                    logger.info('Set recorder filename to %s' % filename)
                elif cmd in ('setFilepath', 'setFilepathAndStart'):
                    filename = None
                    filepath = self._evalStr(args[0])
                    logger.info('Set recorder filepath to %s' % filepath)
                else:
                    raise NotImplementedError()
                self._automator.setState(
                    doStopPrevious=self._automator.isRecording,
                    filename=filename,
                    filepath=filepath,
                    doStartRecording= cmd in ('setFilenameAndStart', 'setFilepathAndStart'))
        else:
            raise NotImplementedError()

        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(cmd=s, **kwargs)

