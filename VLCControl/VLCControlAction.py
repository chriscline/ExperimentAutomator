import typing as tp
import attr
import logging
import time

from ExperimentActions import ExperimentAction, NoninterruptibleAction
from . import VLCRemote
from Misc import Singleton

logger = logging.getLogger(__name__)



@attr.s(auto_attribs=True)
class _VLCRemoteManager(metaclass=Singleton):
    """
    Singleton class to manage potentially multiple VLC instances each with their own remote.
    """
    _remotes: dict[str | None, VLCRemote] = attr.ib(init=False, factory=dict)

    def __attrs_post_init__(self):
        pass

    def hasRemote(self, key: str) -> bool:
        return key in self._remotes

    def getRemote(self, key: str | None = None) -> VLCRemote:
        if key not in self._remotes:
            port = 4212 + len(self._remotes)
            logger.debug(f'Instantiating VLCRemote {key} on port {port}')
            self._remotes[key] = VLCRemote(playerTitle=key, 
                                           telnetPort=port)

        return self._remotes[key]


@attr.s(auto_attribs=True)
class VLCControlAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'VLC'
    cmd: str = ''

    _remoteManager: _VLCRemoteManager = attr.ib(init=False, factory=_VLCRemoteManager)
    _vlc: VLCRemote | None = attr.ib(init=False, default=None)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()

    def _start(self):
        cmdAndArgs = self.cmd.split(' ')
        cmd = cmdAndArgs[0]
        args = cmdAndArgs[1:]

        if cmd == 'instance':
            # first arg is an instanceKey (or variable / statement without spaces referring to an instanceKey) referencing a specific player instance
            instanceKey = self._evalStr(args[0])
            logger.info(f'Operating on VLC instance {instanceKey}')
            vlc = self._remoteManager.getRemote(key=instanceKey)
            cmd = args[1]  # next arg is command to apply to specified instance
            args = args[2:]  # everything else is args for the command
            
        else:
            # get default instance
            logger.info('Operating on default VLC instance')
            vlc = self._remoteManager.getRemote()

        if cmd in ('play', 'pause', 'enableRepeat'):
            assert len(args)==0
            logger.info('VLC %s' % cmd)
            getattr(vlc, cmd)()
        elif cmd == 'open':
            # re-join args since spaces may have been included in path
            args = [' '.join(args)]

            assert len(args)==1
            # arg should be a filepath to open
            filepath = self._evalStr(args[0])
            vlc.load(filepath)
            logger.info('VLC loaded %s' % filepath)
        elif cmd == 'getVolume':
            assert len(args)==1
            # arg should be a variable name to which to save volume
            destVarName = args[0]
            
            volume = vlc.getVolume()
            logger.info(f'Got volume = {volume}')

            exec(f'{destVarName} = {volume}', globals(), self.locals)

        elif cmd == 'setVolume':
            assert len(args)==1
            # arg should be a numeric value or a variable name containing a numeric value
            newVolume = float(self._evalStr(args[0]))
            logger.info(f'Setting volume = {newVolume}')
            vlc.setVolume(newVolume)

        else:
            raise NotImplementedError()

        self._onStop()  # return immediately, though may be playing in background

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(cmd=s, **kwargs)





