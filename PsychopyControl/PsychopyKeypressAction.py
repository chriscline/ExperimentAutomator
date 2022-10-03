import typing as tp
import attr
import logging
import time
from pywinauto.application import Application

from ExperimentActions import ExperimentAction, NoninterruptibleAction

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class PsychopyKeypressAction(NoninterruptibleAction):
    key: tp.ClassVar[str] = 'PsychopyKeypress'
    keycode: str = ''  # format defined at https://pywinauto.readthedocs.io/en/latest/code/pywinauto.keyboard.html
    # e.g. '{down}' to press down arrow

    def __attrs_post_init__(self):
        super().__attrs_post_init__()

    def _start(self):
        prevWin = Application(backend="uia").connect(active_only=True).top_window()
        app = Application(backend='uia').connect(title='Psychopy', timeout=1)
        win = app.window(title='PsychoPy')
        win.set_focus() # note: for some reason, this doesn't seem to work and keypresses don't get captured correctly by Psychopy
        win.type_keys(self.keycode)
        raise NotImplementedError('This does not currently work...')
        prevWin.set_focus()
        logger.info('Typed %s in window %s of application %s' % (self.keycode, win.title, app.title))

        self._onStop()

    @classmethod
    def fromString(cls, s: str, **kwargs):
        return cls(keycode=s, **kwargs)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    action = PsychopyKeypressAction.fromString('{right}')
    action.start(locals())
    print('todo')