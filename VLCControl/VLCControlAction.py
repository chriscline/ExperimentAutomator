import typing as tp
import attr
import logging
import time

from ExperimentActions import ExperimentAction, NoninterruptibleAction
from . import VLCRemote

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class VLCControlAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'VLC'
    cmd: str = ''

    _vlc: VLCRemote = attr.ib(init=False, default=None)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()

    def _start(self):
        cmdAndArgs = self.cmd.split(' ', maxsplit=1)
        cmd = cmdAndArgs[0]
        args = cmdAndArgs[1:]

        if self._vlc is None:
            self._vlc = VLCRemote()

        if cmd in ('play', 'pause', 'enableRepeat'):
            assert len(args)==0
            logger.info('VLC %s' % cmd)
            getattr(self._vlc, cmd)()
        elif cmd == 'open':
            assert len(args)==1
            # arg should be a filepath to open
            filepath = self._evalStr(args[0])
            self._vlc.load(filepath)
            logger.info('VLC loaded %s' % filepath)
        else:
            raise NotImplementedError()

        self._onStop()  # return immediately, though may be playing in background

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(cmd=s, **kwargs)





