#!/usr/bin/env python3
#
# QTVcp Widget - Haas-style MDI program builder
# Lets the user accumulate MDI lines into a mini program, then run it.
#

import os
import tempfile

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QLineEdit, QPushButton, QLabel, QSizePolicy)
from PyQt5.QtCore import pyqtProperty, QSize
from PyQt5.QtGui import QIcon

from qtvcp.widgets.widget_baseclass import _HalWidgetBase
from qtvcp.widgets.gcode_editor import EditorBase
from qtvcp.core import Status, Action, Info
from qtvcp import logger

STATUS = Status()
ACTION = Action()
INFO = Info()
LOG = logger.getLogger(__name__)


class MDIHaas(QWidget, _HalWidgetBase):
    """Haas-style MDI: accumulate commands into a program buffer, then run."""

    def __init__(self, parent=None):
        super(MDIHaas, self).__init__(parent)
        self._temp_file = None
        self._auto_run = True
        self._add_m2 = True
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar: undo / redo
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        def _iconBtn(theme, tip, slot):
            btn = QPushButton()
            btn.setFixedSize(25, 25)
            btn.setIcon(QIcon.fromTheme(theme))
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            return btn

        toolbar.addWidget(_iconBtn('edit-undo', 'Undo', lambda: self.editor.undo()))
        toolbar.addWidget(_iconBtn('edit-redo', 'Redo', lambda: self.editor.redo()))
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Program buffer — EditorBase for G-code syntax highlight + line numbers
        self.editor = EditorBase(self)
        self.editor.setReadOnly(False)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.editor.setMinimumSize(QSize(200, 100))
        layout.addWidget(self.editor)

        # Entry row
        entry_row = QHBoxLayout()
        lbl = QLabel("MDI:")
        lbl.setFixedWidth(36)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Enter command and press Enter to add to program")
        self.entry.returnPressed.connect(self._add_line)
        entry_row.addWidget(lbl)
        entry_row.addWidget(self.entry)
        layout.addLayout(entry_row)

        # Button row
        btn_row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_program)
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._run_program)
        self.run_btn.setEnabled(False)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.run_btn)
        layout.addLayout(btn_row)

    def _hal_init(self):
        STATUS.connect('state-off',    lambda w: self._set_active(False))
        STATUS.connect('state-estop',  lambda w: self._set_active(False))
        STATUS.connect('all-homed',    lambda w: self._update_buttons())
        STATUS.connect('interp-idle',  lambda w: self._update_buttons())
        STATUS.connect('interp-run',   lambda w: self.run_btn.setEnabled(False))
        STATUS.connect('mode-mdi',     lambda w: self._update_buttons())
        STATUS.connect('mode-auto',    lambda w: self.run_btn.setEnabled(False))
        STATUS.connect('mode-manual',  lambda w: self.run_btn.setEnabled(False))

    def _set_active(self, enabled):
        self.entry.setEnabled(enabled)
        self.run_btn.setEnabled(False)

    def _update_buttons(self):
        machine_ready = STATUS.machine_is_on() and (
            STATUS.is_all_homed() or INFO.NO_HOME_REQUIRED)
        in_mdi = STATUS.is_mdi_mode()
        has_content = bool(self.editor.text().strip())
        self.entry.setEnabled(machine_ready)
        self.run_btn.setEnabled(machine_ready and in_mdi and has_content)

    def _add_line(self):
        text = self.entry.text().strip()
        if not text:
            return
        current = self.editor.text()
        if current and not current.endswith('\n'):
            self.editor.append('\n')
        self.editor.append(text + '\n')
        self.entry.clear()
        self.editor.setCursorPosition(self.editor.lines(), 0)
        try:
            self._update_buttons()
        except Exception:
            pass

    def _clear_program(self):
        self.editor.setText('')
        self.run_btn.setEnabled(False)
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.remove(self._temp_file)
            except Exception:
                pass
            self._temp_file = None

    def _run_program(self):
        content = self.editor.text().strip()
        if not content:
            return
        try:
            fd, path = tempfile.mkstemp(suffix='.ngc', prefix='mdi_haas_')
            with os.fdopen(fd, 'w') as f:
                f.write('%\n')
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped:
                        f.write(stripped + '\n')
                if self._add_m2:
                    f.write('M2\n')
                f.write('%\n')

            if self._temp_file and os.path.exists(self._temp_file):
                try:
                    os.remove(self._temp_file)
                except Exception:
                    pass
            self._temp_file = path

            ACTION.OPEN_PROGRAM(path)
            if self._auto_run:
                ACTION.RUN(0)

        except Exception as e:
            LOG.error('MDIHaas run error: {}'.format(e))
            ACTION.SET_ERROR_MESSAGE('MDI Haas run error:\n{}\n'.format(e))

    ###########################################################################
    # pyqtProperty interface for Qt Designer
    ###########################################################################

    def set_auto_run(self, val):
        self._auto_run = val
    def get_auto_run(self):
        return self._auto_run
    def reset_auto_run(self):
        self._auto_run = True
    auto_run = pyqtProperty(bool, get_auto_run, set_auto_run, reset_auto_run)

    def set_add_m2(self, val):
        self._add_m2 = val
    def get_add_m2(self):
        return self._add_m2
    def reset_add_m2(self):
        self._add_m2 = True
    add_m2_footer = pyqtProperty(bool, get_add_m2, set_add_m2, reset_add_m2)


def main():
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MDIHaas()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
