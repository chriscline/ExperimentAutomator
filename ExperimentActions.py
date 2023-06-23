from command_runner import command_runner, command_runner_threaded
from concurrent.futures import Future
import queue
from qtpy import QtCore, QtGui, QtWidgets
import typing as tp
import attr
import json
import logging
import time
import pyttsx3
import subprocess
import os
import shutil
import sys
import pyperclip
import traceback

logger = logging.getLogger(__name__)
logging.getLogger('command_runner').setLevel(logging.INFO)

Locals = tp.Dict[str, tp.Any]


@attr.s(auto_attribs=True)
class ExperimentAction(QtCore.QObject):
    key: tp.ClassVar[str] = ''

    locals: Locals = attr.ib(factory=dict)

    onExceptionWhileRunning: tp.Optional[tp.Callable[[object, Exception,], str]] = attr.ib(default=None, repr=False)
    """
    Given this action and an exception, return 'continue', 'stop', or 'raise' to indicate how to proceed; 
    if no callback specified, exception will always be raised.
    """

    sigStarting: tp.ClassVar[QtCore.Signal] = QtCore.Signal()
    sigStopping: tp.ClassVar[QtCore.Signal] = QtCore.Signal(object, dict)  # emits (self, locals)
    sigPauseRequested: tp.ClassVar[QtCore.Signal] = QtCore.Signal()

    _parentWin: tp.Optional[QtWidgets.QWidget] = None

    _didStart: bool = False
    _didStop: bool = False

    def __attrs_post_init__(self):
        logger.debug('Initing parent ExperimentAction')
        QtCore.QObject.__init__(self, parent=None)

    def start(self, locals: Locals):
        self.locals = locals
        self.sigStarting.emit()
        self._start()
        self._didStart = True

    def stop(self):
        """ Request early stop. """
        raise NotImplementedError("Should be implemented by subclass")

    def _start(self):
        raise NotImplementedError("Should be implemented by subclass")

    def _onStop(self):
        self.sigStopping.emit(self, self.locals)
        self._didStop = True
        logger.debug('Finished action %s' % self)

    def _evalStr(self, s) -> str:
        try:
            out = eval(s, globals(), self.locals)
        except (NameError, SyntaxError):
            out = s
        return out

    def __str__(self):
        d = attr.asdict(self, filter=lambda attrib, val: attrib.name not in ('onExceptionWhileRunning',) and attrib.init)
        keysToExclude = ['locals']
        for key in d:
            if key[0] == '_':
                keysToExclude.append(key)
        for key in keysToExclude:
            d.pop(key)

        return '%s: %s' % (type(self).__name__, str(d))

    @property
    def didStart(self):
        return self._didStart

    @property
    def didStop(self):
        return self._didStop

    @classmethod
    def fromString(cls, s: str, **kwargs):
        raise NotImplementedError("Should be implemented by subclass")


@attr.s(auto_attribs=True)
class NoninterruptibleAction(ExperimentAction):
    def stop(self):
        logger.warning('Early stop requested, but not supported by this action. Ignoring.')


@attr.s(auto_attribs=True)
class EvalAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'eval'
    evalStr: str = ''

    def __attrs_post_init__(self):
        return super().__attrs_post_init__()

    def _start(self):
        if len(self.evalStr) > 0:
            logger.info('Evaluating \'%s\'' % self.evalStr)
            try:
                exec(self.evalStr, globals(), self.locals)
            except SyntaxError as err:
                error_class = err.__class__.__name__
                detail = err.args[0]
                line_number = err.lineno
                logger.error("%s at line %d: %s" % (error_class, line_number, detail))
                raise err
            except Exception as err:
                error_class = err.__class__.__name__
                detail = err.args[0]
                cl, exc, tb = sys.exc_info()
                line_number = traceback.extract_tb(tb)[-1][1]
                logger.error("%s at line %d: %s" % (error_class, line_number, detail))
                raise err
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(evalStr=s, **kwargs)


class ControlFlowConditionResult(Exception):
    value: bool

    def __init__(self, value: bool):
        self.value = value


@attr.s(auto_attribs=True)
class ControlFlowAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'controlFlow'
    cmdAndConditionStr: str = ''

    _conditionResult: bool = attr.ib(init=False, default=None)

    def _start(self):
        assert len(self.cmdAndConditionStr) > 0
        s = self.cmdAndConditionStr
        if ' ' in s:
            cmd, conditionStr = s.split(' ', maxsplit=1)
        else:
            cmd = s
            conditionStr = ''

        if cmd in ('if', 'elif', 'while'):
            assert len(conditionStr) > 0
            conditionResult = bool(self._evalStr(conditionStr))
        elif cmd in ('else',):
            assert len(conditionStr) == 0
            conditionResult = True
        elif cmd in ('end',):
            assert len(conditionStr) == 0
            conditionResult = False
        else:
            raise NotImplementedError()

        logger.info('Result of controlFlow "%s": %s' % (cmd, conditionResult))

        self._conditionResult = conditionResult  # up to caller to actually check this value

        self._onStop()

    @property
    def conditionResult(self):
        return self._conditionResult

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(cmdAndConditionStr=s, **kwargs)


@attr.s(auto_attribs=True)
class LogAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'log'
    logStr: str = ''

    def _start(self):
        if len(self.logStr) > 0:
            logStr = self._evalStr(self.logStr)
            logger.info(logStr)
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(logStr=s, **kwargs)


@attr.s(auto_attribs=True)
class SpeakAction(ExperimentAction):
    key: tp.ClassVar[str] = 'speak'
    speakStr: str = ''

    _engine: tp.Optional[pyttsx3.Engine] = attr.ib(default=None)
    _callbackToken: dict = attr.ib(init=False, default=None)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        if self._engine is None:
            self._engine = pyttsx3.init()

    def _start(self):
        speakStr = self._evalStr(self.speakStr)
        self._engine.say(speakStr)
        logger.info('Speaking \'%s\'' % speakStr)
        self._callbackToken = self._engine.connect('finished-utterance', self._onFinishedSpeaking)
        self._engine.startLoop()

    def stop(self):
        logger.debug('Speech terminated early')
        if self._engine._inLoop:  # note: using undocumented private variable...
            self._engine.stop()
        else:
            self._onStop()

    def _onFinishedSpeaking(self, name: str, completed: bool):
        logger.debug('Finished speaking')
        self._engine.disconnect(self._callbackToken)
        self._engine.endLoop()
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(speakStr=s, **kwargs)


@attr.s(auto_attribs=True)
class MessageBoxAction(ExperimentAction):
    key: tp.ClassVar[str] = 'messageBox'
    msgStr: str = ''

    def _start(self):
        msgStr = self._evalStr(self.msgStr)
        msgBox = QtWidgets.QMessageBox(parent=self._parentWin)
        msgBox.setWindowTitle('ExperimentAutomator')
        msgBox.setText(msgStr)
        logger.info('Displaying message box: \'%s\'' % msgStr)
        contBtn = msgBox.addButton("Continue", QtWidgets.QMessageBox.AcceptRole)
        stopBtn = msgBox.addButton("Stop", QtWidgets.QMessageBox.RejectRole)
        msgBox.setDefaultButton(contBtn)

        msgBox.exec_()

        if msgBox.clickedButton() == stopBtn:
            self.sigPauseRequested.emit()
        elif msgBox.clickedButton() == contBtn:
            self._onStop()
        else:
            raise NotImplementedError()

    def stop(self):
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(msgStr=s, **kwargs)

@attr.s(auto_attribs=True)
class GetInputAction(ExperimentAction):
    key: tp.ClassVar[str] = 'getInput'
    variableName: str = ''

    def _start(self):
        logger.info('Getting user input for \'%s\'' % self.variableName)
        resp, ok = QtWidgets.QInputDialog.getText(self._parentWin,
                                                  "Get input",
                                                  "%s = ?" % self.variableName)
        if not ok:
            self.sigPauseRequested.emit()
            return

        logger.info('Setting %s = \'%s\' from user input' % (self.variableName, resp))
        # assume input doesn't have both ' and "
        delim = '\'' if '\'' not in resp else '"'
        exec('%s = %s%s%s' % (self.variableName, delim, resp, delim), globals(), self.locals)
        self._onStop()

    def stop(self):
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        assert s.isidentifier()
        return cls(variableName=s, **kwargs)


@attr.s(auto_attribs=True)
class CopyToClipboardAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'copyToClipboard'
    copyStr: str = ''

    def _start(self):
        copyStr = self._evalStr(self.copyStr)
        if False:
            clipboard = QtGui.QGuiApplication.clipboard()
            clipboard.setText(copyStr)
        else:
            pyperclip.copy(copyStr)
        logger.info('Copied to clipboard: \'%s\'' % copyStr)
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(copyStr=s, **kwargs)


@attr.s(auto_attribs=True)
class WaitAction(ExperimentAction):
    key: tp.ClassVar[str] = 'wait'
    duration: tp.Optional[float] = None

    _timer: tp.Optional[QtCore.QTimer] = attr.ib(default=None, init=False)
    _hasStarted: bool = False

    def _start(self):
        if self.duration is not None:
            self._timer = QtCore.QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._onStop)
            duration = int(round(self.duration*1e3))
            self._timer.setInterval(int(round(self.duration*1e3)))
            logger.info('Waiting for %s s' % (duration/1.e3,))
            self._timer.start()
        else:
            if not self.didStart:
                logger.info("Pausing")
                self.sigPauseRequested.emit()
            else:
                # assume we already paused and this is now resuming
                self._onStop()
                return

    def stop(self):
        logger.debug("Wait terminated.")
        if self._timer is not None:
            self._timer.stop()

        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        if s == 'pause':
            duration = None
        else:
            duration = float(s)
        return cls(duration=duration, **kwargs)


@attr.s(auto_attribs=True)
class RunScriptAction(ExperimentAction):
    key: tp.ClassVar[str] = 'runScript'
    scriptPathAndArgs: str = ''

    _runningScript: str = ''
    _proc: tp.Optional[subprocess.Popen] = attr.ib(init=False, default=None)
    _procFuture: tp.Optional[Future] = attr.ib(init=False, default=None)
    _procStdoutQueue: queue.Queue = attr.ib(init=False, factory=queue.Queue)
    _procStderrQueue: queue.Queue = attr.ib(init=False, factory=queue.Queue)
    _timer: tp.Optional[QtCore.QTimer] = attr.ib(default=None, init=False)

    def _start(self):
        assert self._proc is None
        self._runningScript = self._evalStr(self.scriptPathAndArgs)

        if True:
            # run in separate command window
            if '.bat' in self._runningScript:
                # hack for weird windows start quote escaping when running a bat file...
                cmd = 'start /w cmd /c %s' % self._runningScript
            else:
                if False:
                    cmd = 'start /w "" ' + self._runningScript
                else:
                    cmd = self._runningScript

            def setProc(proc):
                logger.debug(f'Setting proc to {proc}')
                self._proc = proc

            self._procFuture = command_runner_threaded(cmd,
                                                       stdout=self._procStdoutQueue,
                                                       stderr=self._procStderrQueue,
                                                       method='poller',
                                                       process_callback=setProc,
                                                       )

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(100)

        logger.info('Process started, waiting for it to finish: %s' % (self._runningScript,))
        self._timer.start()

    def _onProcessReturned(self, ret):
        assert ret is not None
        # TODO: print return code, generate error if return code indicates error
        if ret != 0:
            raise RuntimeError('Process returned error: %s' % (ret,))
        else:
            logger.info('Process returned: %s' % (ret,))
        self._timer.stop()
        self._onStop()

    def _setProc(self, proc: subprocess.Popen):
        assert self._proc is None
        self._proc = proc

    def _pollProcOutput(self):
        while True:
            try:
                stdout_line = self._procStdoutQueue.get(block=False)
            except queue.Empty:
                break
            else:
                if stdout_line is None:
                    break
                else:
                    logger.info('Subprocess output: %s' % (stdout_line.rstrip('\r\n')))

        while True:
            try:
                stderr_line = self._procStderrQueue.get(block=False)
            except queue.Empty:
                break
            else:
                if stderr_line is None:
                    break
                else:
                    logger.error('Subprocess error output: %s' % (stderr_line.rstrip('\r\n')))

    def _poll(self):

        assert self._procFuture is not None

        self._pollProcOutput()

        if not self._procFuture.done():
            # process still running
            return
        else:
            ret, output = self._procFuture.result()
            try:
                self._onProcessReturned(ret)
            except Exception as e:
                if self.onExceptionWhileRunning is not None:
                    howToProceed = self.onExceptionWhileRunning(self, e)
                    if howToProceed == 'raise':
                        raise e
                    elif howToProceed == 'stop':
                        self._timer.stop()
                        self._onStop()
                    elif howToProceed == 'continue':
                        # process finished, register stop anyways
                        self._timer.stop()
                        self._onStop()
                    else:
                        raise NotImplementedError
                else:
                    raise e

    def stop(self):
        assert self._procFuture is not None
        while self._proc is None and not self._procFuture.done():
            # wait for command_runner to start process
            time.sleep(0.1)
        self._timer.stop()
        if not self._procFuture.done():
            assert self._proc is not None
            if True:
                # adapted from https://stackoverflow.com/a/32814686
                subprocess.run('taskkill /pid %d /T /F' % self._proc.pid)
            else:
                # this kills process but not children of `start`
                self._proc.terminate()
            # TODO: maybe use command_runner `on_stop` callback instead

        ret, output = self._procFuture.result()  # will block until finished

        self._pollProcOutput()

        logger.info('Process terminated early: %s' % (self._runningScript,))
        self._procFuture = None
        self._proc = None
        self._runningScript = ''
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(scriptPathAndArgs=s, **kwargs)


@attr.s(auto_attribs=True)
class RunScriptInBackgroundAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'runScriptInBackground'
    scriptPathAndArgs: str = ''

    def _start(self):
        self._runningScript = self._evalStr(self.scriptPathAndArgs)

        if '.bat' in self._runningScript:
            # hack for weird windows start quote escaping when running a bat file...
            cmd = 'start /w call %s' % self._runningScript
        else:
            cmd = 'start /w "" ' + self._runningScript
        subprocess.Popen(cmd,
                         shell=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)

        logger.info('Process started in background: %s' % (self._runningScript,))
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(scriptPathAndArgs=s, **kwargs)


ActionTypes = [
    EvalAction,
    WaitAction,
    ControlFlowAction,
    LogAction,
    SpeakAction,
    MessageBoxAction,
    GetInputAction,
    CopyToClipboardAction,
    RunScriptAction,
    RunScriptInBackgroundAction,
]