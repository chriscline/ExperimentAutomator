import typing as tp
import attr
import logging
import zmq

from ExperimentActions import ExperimentAction, NoninterruptibleAction
from Misc import Singleton

logger = logging.getLogger(__name__)

@attr.s(auto_attribs=True)
class ZMQPicturePresenterAutomator(metaclass=Singleton):
    _socket: tp.Optional[zmq.Socket] = None
    _port: int = 9879

    def changeImage(self, imageNumber: int):
        if self._socket is None:
            self._socket = zmq.Context().socket(zmq.REQ)
            self._socket.linger = 0
            self._socket.connect('tcp://localhost:%d' % (self._port,))

        self._socket.send_json(dict(
            type='showImage',
            imageNumber=imageNumber))

        evt = self._socket.poll(timeout=1000)
        if evt == 0:
            self._socket = None
            raise TimeoutError('No acknowledgement of message received')
        resp = self._socket.recv_json()
        if resp != 'ACK':
            raise RuntimeError('Unexpected response: %s' % resp)


@attr.s(auto_attribs=True)
class ZMQPicturePresenterAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'ZMQPicturePresenter'
    image: str = ''

    def _start(self):
        autom = ZMQPicturePresenterAutomator()
        imageNumber = int(self._evalStr(self.image))
        autom.changeImage(imageNumber=imageNumber)
        logger.info('Changed image to %d' % imageNumber)
        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(image=s, **kwargs)