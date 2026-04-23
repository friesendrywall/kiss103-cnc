#!/usr/bin/env python3
#
# QTVcp Widget - Haas-style MDI program builder
# Lets the user accumulate MDI lines into a mini program, then run it.
#

import linuxcnc

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QSizePolicy)
from PyQt5.QtCore import QSize
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
        self._queue = []
        self._running = False
        self._awaiting = False
        self._saw_non_idle = False
        self._idle_streak = 0
        self._wait_ticks = 0
        self._marker_handle = None
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

        # Button row
        btn_row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.setMinimumWidth(120)
        self.clear_btn.clicked.connect(self._clear_program)
        self.run_btn = QPushButton("Run")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setMinimumWidth(120)
        self.run_btn.clicked.connect(self._run_program)
        self.run_btn.setEnabled(False)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.run_btn)
        layout.addLayout(btn_row)

    def _hal_init(self):
        STATUS.connect('state-off',       lambda w: self._abort_queue())
        STATUS.connect('state-estop',     lambda w: self._abort_queue())
        STATUS.connect('all-homed',       lambda w: self._update_buttons())
        STATUS.connect('interp-idle',     lambda w: self._update_buttons())
        STATUS.connect('interp-run',      lambda w: self.run_btn.setEnabled(False))
        STATUS.connect('mode-mdi',        lambda w: self._update_buttons())
        STATUS.connect('mode-auto',       lambda w: self.run_btn.setEnabled(False))
        STATUS.connect('mode-manual',     lambda w: self.run_btn.setEnabled(False))
        STATUS.connect('periodic',        self._on_periodic)
        STATUS.connect('error',           self._on_error_abort)

    def _update_buttons(self):
        machine_ready = STATUS.machine_is_on() and (
            STATUS.is_all_homed() or INFO.NO_HOME_REQUIRED)
        in_mdi = STATUS.is_mdi_mode()
        has_content = bool(self.editor.text().strip())
        self.run_btn.setEnabled(
            machine_ready and in_mdi and has_content and not self._running)

    def _clear_program(self):
        self._abort_queue()
        self.editor.setText('')
        self.run_btn.setEnabled(False)

    def _run_program(self):
        lines = self.editor.text().splitlines()
        self._queue = [(i, l.strip()) for i, l in enumerate(lines) if l.strip()]
        if not self._queue:
            return
        ACTION.SET_MDI_MODE()
        self._running = True
        self._awaiting = False
        self._update_buttons()
        self._fire_next()

    def _fire_next(self):
        if not self._queue:
            self._running = False
            self._awaiting = False
            self._clear_highlight()
            self._update_buttons()
            return
        line_idx, text = self._queue.pop(0)
        self._highlight(line_idx)
        self._awaiting = True
        self._saw_non_idle = False
        self._idle_streak = 0
        self._wait_ticks = 0
        try:
            ACTION.CALL_MDI(text)
        except Exception as e:
            LOG.error('MDIHaas CALL_MDI raised: {}'.format(e))
            self._abort_queue()

    def _on_periodic(self, w):
        if not (self._running and self._awaiting):
            return
        self._wait_ticks += 1
        if STATUS.is_interp_idle():
            if self._saw_non_idle:
                self._idle_streak += 1
                if self._idle_streak >= 2:
                    self._awaiting = False
                    self._fire_next()
            elif self._wait_ticks >= 5:
                # safety: command finished between ticks without us seeing non-idle
                self._awaiting = False
                self._fire_next()
        else:
            self._saw_non_idle = True
            self._idle_streak = 0

    def _on_error_abort(self, w, kind, text):
        if self._running and kind in (linuxcnc.OPERATOR_ERROR, linuxcnc.NML_ERROR):
            self._abort_queue()

    def _abort_queue(self):
        self._queue = []
        self._running = False
        self._awaiting = False
        self._saw_non_idle = False
        self._idle_streak = 0
        self._wait_ticks = 0
        self._clear_highlight()
        self._update_buttons()

    def _highlight(self, line):
        self._clear_highlight()
        self._marker_handle = self.editor.markerAdd(line, self.editor.CURRENT_MARKER_NUM)
        self.editor.ensureLineVisible(line)

    def _clear_highlight(self):
        if self._marker_handle is not None:
            self.editor.markerDeleteHandle(self._marker_handle)
            self._marker_handle = None


def main():
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MDIHaas()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
