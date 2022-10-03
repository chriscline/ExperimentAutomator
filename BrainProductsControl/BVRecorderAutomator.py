import os
import logging
import attr
import typing as tp
import time
import pywin
import shutil

import win32com.client

from Misc import Singleton

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class BVRecorderAutomator(metaclass=Singleton):
    comObj: win32com.client.DispatchBaseClass = attr.ib(init=False, default=None)

    def __attrs_post_init__(self):
        pass

    def _renewComObjIfNeeded(self):
        if self.comObj is not None:
            # try to access a property that only works if it is valid
            try:
                self.comObj.Version
                return
            except Exception as e:
                raise NotImplementedError()  # TODO: catch specific exception caused by crash during COM obj operation

        logger.debug('Renewed COM obj')
        self.comObj = win32com.client.Dispatch('VisionRecorder.Application')

    def quit(self):
        self._renewComObjIfNeeded()
        self.comObj.Quit()

    def resumeRecording(self):
        assert self.getProgramState() in ('paused',)
        self.comObj.Acquisition.Continue()

    def pauseRecording(self):
        assert self.isRecording
        self.comObj.Acquisition.Pause()

    def startRecording(self, toFilepath: str, moveBeforeOverwrite: bool = True):
        # TODO: test what happens if filepath already exists (does it prompt to append vs overwrite?)

        if self.getProgramState() not in ('monitoring',):
            # must be in monitoring mode before starting recording
            self.viewData()
            time.sleep(10)  # give some time for view to start, otherwise recording silently fails...
            assert self.getProgramState() in ('monitoring',)

        # script interface does not automatically add .eeg extension, so add it here
        toFilepath, ext = os.path.splitext(toFilepath)
        if ext == '.eeg':
            toFilepath = toFilepath + ext
        elif ext in ('.vhdr', '.vmrk', ''):
            toFilepath = toFilepath + '.eeg'
            logger.info('toFilepath extension changed to %s' % toFilepath)
        else:
            toFilepath = toFilepath + ext + '.eeg'
            logger.info('toFilepath extension changed to %s' % toFilepath)

        # note: if toFilepath already exists, it is overwritten (not appended to!)
        if os.path.exists(toFilepath):
            if moveBeforeOverwrite:
                prevFilepath = toFilepath
                prevFilepath, ext = os.path.splitext(prevFilepath)
                iO = 1
                newFilepath = prevFilepath + '_old'
                while os.path.exists(newFilepath + ext):
                    iO += 1
                    newFilepath = prevFilepath + '_old_%d' % iO
                logger.info('Moving previous recording to %s to avoid overwrite', newFilepath)
                for ext in ('.eeg','.vhdr','.vmrk'):
                    shutil.move(prevFilepath + ext, newFilepath + ext)
                    # (note this does not correctly rename the contents of the vmrk and vhdr files to link to the correct data file)
            else:
                logger.warning('Overwriting previous recording at %s', toFilepath)

        self.comObj.Acquisition.StartRecording(toFilepath)

    def stopRecording(self):
        self._renewComObjIfNeeded()
        self.comObj.Acquisition.StopRecording()

    def stopViewing(self):
        self._renewComObjIfNeeded()
        self.comObj.Acquisition.StopViewing()

    def viewData(self):
        self._renewComObjIfNeeded()
        self.comObj.Acquisition.ViewData()

    def viewImpedance(self):
        self._renewComObjIfNeeded()
        self.comObj.Acquisition.ViewImpedance()

    def annotate(self, description: str, markerType: tp.Optional[str] = None):
        assert self.getProgramState() in ('monitoring', 'recording', 'paused')
        if self.getProgramState() not in ('recording',):
            logger.warning('Set an annotation (%s) but not recording' % description)
        if markerType is not None:
            self.comObj.Acquisition.SetMarker(description, markerType)
        else:
            self.comObj.Acquisition.SetMarker(description)

    def performDCOffsetCorrection(self):
        self._renewComObjIfNeeded()
        assert self.getProgramState() in ('monitoring', 'recording', 'paused')
        self.comObj.Acquisition.DCCorrection()

    def getAcquisitionState(self) -> str:
        self._renewComObjIfNeeded()
        stateCode = self.comObj.Acquisition.GetAcquisitionState()
        stateCodeToState = {
            0: 'stopped',
            1: 'running',
            2: 'warning',
            3: 'error'
        }
        return stateCodeToState[stateCode]

    def getProgramState(self) -> str:
        self._renewComObjIfNeeded()
        stateCode = self.comObj.State
        stateCodeToState = {
            0: 'idle',
            1: 'monitoring',
            2: 'testSignal',
            3: 'impedanceCheck',
            4: 'recording',
            5: 'recordingTest',
            6: 'paused',
            7: 'pausedAndTestSignal',
            8: 'pausedAndImpedanceCheck'
        }
        return stateCodeToState[stateCode]

    @property
    def isRecording(self) -> bool:
        if True:
            return self.getProgramState() == 'recording'
        else:
            # TODO: make sure state is indeed 'running' only when recording
            return self.getAcquisitionState() == 'running'

    def loadWorkspace(self, filepath: str):
        if not os.path.exists(filepath):
            raise FileNotFoundError("Workspace file not found at %s" % filepath)

        if self.getProgramState() not in ('idle',):
            self.stopViewing()

        self.comObj.CurrentWorkspace.Load(filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s.%(msecs)03d %(filename)20s %(lineno)4d %(levelname)5s: %(message)s',
                        datefmt='%H:%M:%S')
    o = BVRecorderAutomator()
    o.getProgramState()
    print('pause')
    o.getProgramState()
    print('todo')
