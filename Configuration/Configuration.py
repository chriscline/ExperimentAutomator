"""
Define default settings here, and include logic for automatically loading machine-specific
settings if available.
"""
from pathlib import Path
import os
import socket
import importlib
import attr
import logging
import typing as tp
import re
import json

logger = logging.getLogger(__name__)

homeDir = str(Path.home())
thisDir, _ = os.path.split(os.path.realpath(__file__))
hostname = socket.gethostname()


@attr.s(auto_attribs=True)
class Configuration:
    _dicts: tp.List[tp.Dict[str, str]] = attr.ib(factory=list)
    _dictSourcePaths: tp.List[str] = attr.ib(factory=list)

    def getAttr(self, item, skipNumLevels: int = 0):
        for iD, d in enumerate(self._dicts):
            if iD < skipNumLevels:
                continue
            if item in d:
                val = d[item]
                # do some extra processing of value
                if isinstance(val, str):
                    if len(val) == 0:
                        pass
                    elif len(val) > 0 and val[0] == '~':
                        # expand home directory
                        val = os.path.expanduser(val)
                    elif len(val) > 1 and val[0:2] == './':
                        # expand "local" directories to be relative to source path
                        srcDir, _ = os.path.split(self._dictSourcePaths[iD])
                        val = os.path.join(srcDir, val[2:])
                    elif len(val) > 1 and val[0:2] == '..':
                        # expand "local" directories to be relative to source path
                        srcDir, _ = os.path.split(self._dictSourcePaths[iD])
                        val = os.path.join(srcDir, val)
                    else:
                        pass

                    regex = re.compile('<(\w+)>')
                    match = regex.search(val)
                    while match is not None:
                        subItem = match.group(1)
                        toReplace = '<%s>' % subItem
                        if subItem == item:
                            subVal = self.getAttr(subItem, skipNumLevels=iD+1)
                        else:
                            subVal = getattr(self, subItem)
                        val = val.replace(toReplace, subVal)
                        match = regex.search(val)


                return val
        raise KeyError('No configuration value for key %s' % item)

    def __getattr__(self, item):
        return self.getAttr(item)

    def clear(self):
        self._dicts = list()
        self._dictSourcePaths = list()

    def addConfiguration(self, pathToJson: str):
        with open(pathToJson,'r') as f:
            d = json.load(f)
        self._dicts.insert(0, d)
        self._dictSourcePaths.insert(0, pathToJson)

    def addDefaultConfiguration(self):
        self.addConfiguration(os.path.join(thisDir, 'DefaultConfiguration.json'))
        self._dicts.insert(0, dict(
            hostname=hostname,
        ))
        self._dictSourcePaths.insert(0, None)

    def addMachineConfiguration(self):
        configPath = os.path.join(thisDir,'MachineConfiguration-%s.json' % hostname)
        if os.path.exists(configPath):
            self.addConfiguration(configPath)
        else:
            logger.debug('No machine specific config for \'%s\'' % hostname)

    def resetToDefaultConfiguration(self):
        self.clear()
        self.addDefaultConfiguration()
        self.addMachineConfiguration()


globalConfiguration = Configuration()


def refreshGlobalConfiguration():
    global globalConfiguration
    globalConfiguration.resetToDefaultConfiguration()


refreshGlobalConfiguration()


if __name__ == '__main__':
    conf = globalConfiguration
    print(conf.DataBasePath)
