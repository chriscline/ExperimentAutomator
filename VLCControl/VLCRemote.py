import os
import sys
import subprocess
import typing as tp
import attr
import random, string
import logging
from telnetlib import Telnet
import time

logger = logging.getLogger(__name__)

from Configuration import globalConfiguration
from Misc import Singleton


@attr.s(auto_attribs=True)
class VLCRemote(metaclass=Singleton):
    _telnetPort: int = 4212
    _telnetPassword: str = ''
    _telnet: Telnet = attr.ib(init=False)

    def __attrs_post_init__(self):
        if len(self._telnetPassword) == 0:
            self._telnetPassword = ''.join(random.choices(
                string.ascii_letters + string.digits, k=16))

        self.launchVLC()

        self._telnet = Telnet(
            host='localhost',
            port=self._telnetPort,
        )

        self._telnet.read_until(b'Password: ')
        self._sendCommand(self._telnetPassword)

    def launchVLC(self):
        args = (globalConfiguration.VLCPath,
                '--extraintf', 'telnet',
                '--telnet-port', str(self._telnetPort),
                '--telnet-password', self._telnetPassword)

        p = subprocess.Popen(args)
        logger.info('Launched VLC')

    def _sendCommand(self, cmd: str):
        self._telnet.write(cmd.encode('ascii') + b'\n')

    def _getResponseToCommand(self, cmd: str):
        self._telnet.read_until('<dummy>'.encode('ascii'), timeout=0.1)
        self._sendCommand(cmd)
        return self._telnet.read_until('<dummy>'.encode('ascii'), timeout=0.1).decode('ascii')

    def play(self):
        self._sendCommand('play')

    def pause(self):
        # built-in VLC pause command toggles between pause and play
        # we want to only pause
        if self.isPlaying():
            self._sendCommand('pause')
        else:
            pass # do nothing, already paused

    def isPlaying(self):
        resp = self._getResponseToCommand('status')
        if 'state paused' in resp:
            return False
        elif 'state stopped' in resp:
            return False
        elif 'state playing' in resp:
            return True
        else:
            raise NotImplementedError()

    def enableRepeat(self):
        self._sendCommand('repeat on')

    def load(self, filepath: str):
        assert os.path.exists(filepath)
        self._sendCommand('clear')  # clear previous play item(s)
        self._sendCommand('enqueue %s' % filepath)
        self.pause()

    def loadAndPlay(self, filepath: str):
        assert os.path.exists(filepath)
        self._sendCommand('clear') # clear previous play item(s)
        self._sendCommand('add %s' % filepath)



if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s.%(msecs)03d %(filename)20s %(lineno)4d %(levelname)5s: %(message)s',
                        datefmt='%H:%M:%S')

    vlc = VLCRemote()
    print('todo')

