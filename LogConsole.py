import sys
import os
from PySide2 import QtCore, QtGui, QtWidgets
import typing as tp
import attr
import pandas as pd
import logging
import time


class _LogConsoleHandler(logging.Handler):
    def __init__(self, parent):
        logging.Handler.__init__(self)
        self.parent = parent

    def emit(self, record):
        self.parent.write(self.format(record))


class LogConsole(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.textEdit = QtWidgets.QTextEdit(self)
        self.textEdit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.textEdit.setReadOnly(True)

        font = QtGui.QFont('Lucida Console')
        font.setStyleHint(QtGui.QFont.Monospace)
        self.textEdit.setFont(font)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.textEdit)

    def addHandler(self, log=None, level=logging.NOTSET,
                   format='%(asctime)s.%(msecs)03d %(filename)20s %(lineno)4d %(levelname)5s: %(message)s',
                   datefmt='%H:%M:%S'):
        if log is None:
            log = logging.getLogger()

        handler = _LogConsoleHandler(parent = self)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(fmt=format, datefmt=datefmt))
        log.addHandler(handler)

    def write(self, s: str):
        if ' ERROR: ' in s:
            clr = QtGui.QColor(255, 0, 0)
        elif ' WARNING: ' in s:
            clr = QtGui.QColor(200, 100, 0)
        elif ' DEBUG: ' in s:
            clr = QtGui.QColor(150, 150, 150)
        else:
            clr = QtGui.QColor(0, 0, 0)
        self.textEdit.setTextColor(clr)
        self.textEdit.append(s)
        self.repaint()  # make sure that a blocking operation immediately after log doesn't prevent log from printing
        # (however, with rapid log messages this could cause performance issues)


