############################
# **** IMPORT SECTION **** #
############################
import sys
import os
import linuxcnc
import subprocess

sys.path.insert(0, '/home/kiss/linuxcnc/configs/KISS103-MESA/qtvcp/plugins')
sys.path.insert(0, '/home/kiss/linuxcnc/configs/KISS103-MESA/qtvcp/widgets')

from PyQt5 import QtCore, QtWidgets

from qtvcp.widgets.mdi_line import MDILine as MDI_WIDGET
from gcode_editor_2 import GcodeEditor2 as GCODE
from mdi_haas import MDIHaas as MDI_HAAS
from qtvcp.widgets.stylesheeteditor import  StyleSheetEditor as SSE
from qtvcp.widgets.tool_offsetview import ToolOffsetView as TOOL_OFFSET
from qtvcp.widgets.origin_offsetview import OriginOffsetView as ORIGIN_OFFSET
from qtvcp.lib.keybindings import Keylookup
from qtvcp.core import Status, Action
from PyQt5.QtCore import QFileSystemWatcher
from PyQt5.QtGui import QColor, QIcon
from qtvcp.core import Qhal
from PyQt5.QtCore import QTimer
QHAL = Qhal()

# Set up logging
from qtvcp import logger
LOG = logger.getLogger(__name__)

# Set the log level for this module
#LOG.setLevel(logger.INFO) # One of DEBUG, INFO, WARNING, ERROR, CRITICAL

###########################################
# **** instantiate libraries section **** #
###########################################

KEYBIND = Keylookup()
STATUS = Status()
ACTION = Action()
STYLEEDITOR = SSE()
TOOL_TO_CAMERA_TAB = {
    1: 0,  # Tool 1 -> FIDUCIAL (index 0)
    2: 1,  # Tool 2 -> FLUX     (index 1)
    3: 1,  # Tool 3 -> DROPJET  (index 1) The FLUX and DROPJET use the same camera
    4: 2,  # Tool 4 -> SOLDER   (index 2)
}

###################################
# **** HANDLER CLASS SECTION **** #
###################################

class _ErrorToast(QtWidgets.QFrame):
    """Toast-style notification that floats over the main window."""

    dismissed = QtCore.pyqtSignal(object)

    def __init__(self, parent, text):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(
            "_ErrorToast { background: #b00020; border: 2px solid #700014; "
            "border-radius: 4px; } "
            "QLabel { color: #ffffff; font: 11pt 'Lato Heavy'; background: transparent; } "
            "QPushButton { color: #ffffff; background: transparent; border: none; "
            "font: 12pt 'Lato Heavy'; padding: 0px; } "
            "QPushButton:hover { color: #ffcccc; }"
        )
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self._text_lbl = QtWidgets.QLabel(text, self)
        self._text_lbl.setWordWrap(True)
        layout.addWidget(self._text_lbl, 1)
        close_btn = QtWidgets.QPushButton('X', self)
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(QtCore.Qt.PointingHandCursor)
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn, 0, QtCore.Qt.AlignTop)
        self.setFixedWidth(420)
        self.adjustSize()

    def _dismiss(self):
        self.dismissed.emit(self)
        self.hide()
        self.deleteLater()


class HandlerClass:

    ########################
    # **** INITIALIZE **** #
    ########################
    # widgets allows access to  widgets from the qtvcp files
    # at this point the widgets and hal pins are not instantiated
    def __init__(self, halcomp, widgets, paths):
        self.hal = halcomp
        self.w = widgets
        self.PATHS = paths
        self._error_toasts = []
        STATUS.emit('update-machine-log', "QT-Dragon started", None)

    ##########################################
    # Special Functions called from QTSCREEN
    ##########################################

    # at this point:
    # the widgets are instantiated.
    # the HAL pins are built but HAL is not set ready
    def initialized__(self):
        KEYBIND.add_call('Key_F12', 'on_keycall_F12')
        self._last_tool = None
        STATUS.connect('periodic', self.on_tool_changed)
        STATUS.connect('periodic', self._poll_errors)
        STATUS.connect('error', self._on_error)
        STATUS.connect('state-estop', lambda w: self._set_estop_style(True))
        STATUS.connect('state-estop-reset', lambda w: self._set_estop_style(False))
        self.w.SETTINGS.currentChanged.connect(self.tab_changed)
        self.w.GCODE.currentChanged.connect(self.gcode_tab_changed)
        offsets = ['G54','G55','G56','G57','G58','G59','G59.1','G59.2','G59.3']
        for offset in offsets:
            self.w.MACHINE_OFFSET.addItem(offset)
        self.w.MACHINE_OFFSET.currentIndexChanged.connect(self.offset_changed)

        self.qss_path = self.PATHS.XML.replace('.ui', '.qss')
        if os.path.exists(self.qss_path):
            self.watcher = QFileSystemWatcher([self.qss_path])
            # Connect the fileChanged signal to your reload function
            self.watcher.fileChanged.connect(lambda path: self.reload_qss(path))

        # self.w.gcodegraphics.setBackgroundColor(QColor(245, 244, 240))  # #f5f4f0
        # self.w.gcodegraphics.setFeedColor(QColor(0, 85, 255, 255))      # #0055ff, alpha must be >0
        # self.w.gcodegraphics.setRapidColor(QColor(0, 170, 255, 255))    # #00aaff

        self.w.CLEARSTATUS.clicked.connect(self.CLEARSTATUS_clicked)

        # External spin edit calls
        # preheater setpoint
        ###   self.pin_setpoint_set = QHAL.newpin('preheat-set-value', QHAL.HAL_FLOAT, QHAL.HAL_IN)
        ###   self.pin_setpoint_set.value_changed.connect(self.update_ph_setpoint)
        self.w.dj_freq.valueChanged.connect(self.update_djfreq)
        self.w.dj_dotsize.valueChanged.connect(self.update_djdot)
        self.w.preheat_setpoint.valueChanged.connect(self.on_ph_setpoint_changed)

        # djdot setpoint
        ## self.pin_djdot_set = QHAL.newpin('dj-dot-set-value', QHAL.HAL_FLOAT, QHAL.HAL_IN)
        ## self.pin_djdot_set.value_changed.connect(self.update_djdot)
        # preheater setpoint
        ## self.pin_djfreq_set = QHAL.newpin('dj-freq-set-value', QHAL.HAL_FLOAT, QHAL.HAL_IN)
        ## self.pin_djfreq_set.value_changed.connect(self.update_djfreq)
        # Fiducial parameter pins
        self.pin_fid_find      = QHAL.newpin('ext-fid-find',      QHAL.HAL_BIT,   QHAL.HAL_IN)
        self.pin_fid_find.value_changed.connect(self.update_fid_find)
        # Fiducial lighting
        self.pin_fid_light      = QHAL.newpin('ext-fid-light',      QHAL.HAL_FLOAT,   QHAL.HAL_IN)
        self.pin_fid_light.value_changed.connect(self.update_fid_lighting)

        self.pin_fid_is_square = QHAL.newpin('ext-fid-is-square', QHAL.HAL_BIT,   QHAL.HAL_IN)
        self.pin_fid_is_square.value_changed.connect(self.update_fid_is_square)
        self.pin_fid_size      = QHAL.newpin('ext-fid-size',      QHAL.HAL_FLOAT, QHAL.HAL_IN)
        self.pin_fid_size.value_changed.connect(self.update_fid_size)
        self.pin_fid_area      = QHAL.newpin('ext-fid-area',      QHAL.HAL_FLOAT, QHAL.HAL_IN)
        self.pin_fid_area.value_changed.connect(self.update_fid_area)
        self.pin_fid_tolerance = QHAL.newpin('ext-fid-tolerance', QHAL.HAL_FLOAT, QHAL.HAL_IN)
        self.pin_fid_tolerance.value_changed.connect(self.update_fid_tolerance)

        # Reverse connections: widget change → keep handler HAL_IN pins current
        ##  self.w.preheat_setpoint.valueChanged.connect(lambda v: self.hal.__setitem__('preheat-set-value', v))
        ## self.w.dj_dotsize.valueChanged.connect(      lambda v: self.hal.__setitem__('dj-dot-set-value',  v))
        ## self.w.dj_freq.valueChanged.connect(         lambda v: self.hal.__setitem__('dj-freq-set-value', v))
        self.w.fid_find.toggled.connect(             lambda v: self.hal.__setitem__('ext-fid-find',          v))
        self.w.fid_is_square.toggled.connect(        lambda v: self.hal.__setitem__('ext-fid-is-square',     v))
        self.w.fid_size.valueChanged.connect(        lambda v: self.hal.__setitem__('ext-fid-size',          v))
        self.w.fid_area.valueChanged.connect(        lambda v: self.hal.__setitem__('ext-fid-area',          v))
        self.w.fid_tolerance.valueChanged.connect(   lambda v: self.hal.__setitem__('ext-fid-tolerance',     v))
        self.w.fid_light_level.valueChanged.connect( lambda v: self.hal.__setitem__('ext-fid-light', v))

        self.w.btn_park.clicked.connect(self.btn_park_clicked)

        # Connect to any event that could change park-eligibility
        STATUS.connect('state-on',       lambda *a: self._update_park_btn())
        STATUS.connect('state-off',      lambda *a: self._update_park_btn())
        STATUS.connect('state-estop',    lambda *a: self._update_park_btn())
        STATUS.connect('state-estop-reset', lambda *a: self._update_park_btn())
        STATUS.connect('all-homed',      lambda *a: self._update_park_btn())
        STATUS.connect('not-all-homed',  lambda *a: self._update_park_btn())
        STATUS.connect('interp-idle',    lambda *a: self._update_park_btn())
        STATUS.connect('interp-run',     lambda *a: self._update_park_btn())

        self.w.btn_park.setEnabled(False)   # start disabled
        self.cmd = linuxcnc.command()

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_hal_changes)
        self.timer.start(250)
        self.w.setWindowTitle("KISS-103")
        icon_path = os.path.join(os.path.dirname(self.PATHS.XML), 'images', 'ACE_Icon.ico')
        self.w.setWindowIcon(QIcon(icon_path))

    def poll_hal_changes(self):
        dj_dot = self.hal.getvalue('motion.analog-out-00')
        dj_freq = self.hal.getvalue('motion.analog-out-01')
        ph_temp = self.hal.getvalue('motion.analog-out-03')

        self.w.preheat_setpoint.blockSignals(True)
        self.w.preheat_setpoint.setValue(ph_temp)
        self.w.preheat_setpoint.blockSignals(False)

        self.w.dj_freq.blockSignals(True)
        self.w.dj_freq.setValue(dj_freq)
        self.w.dj_freq.blockSignals(False)

        self.w.dj_dotsize.blockSignals(True)
        self.w.dj_dotsize.setValue(dj_dot)
        self.w.dj_dotsize.blockSignals(False)

        cycle_ms = self.hal.getvalue('global-cycle-time-ms')
        last_ms = self.hal.getvalue('global-last-cycle-ms')
        cycle_sec = cycle_ms / 1000.0
        last_sec = last_ms / 1000.0
        self.w.label_cycle.setText('Cycle: %d:%04.1f' % (int(cycle_sec) // 60, cycle_sec % 60))
        self.w.label_last.setText('Last: %d:%04.1f' % (int(last_sec) // 60, last_sec % 60))

    def on_ph_setpoint_changed(self, value):
        self.cmd.set_analog_output(3, float(value))

    def btn_park_clicked(self):
        ACTION.CALL_MDI("G90")
        ACTION.CALL_MDI("G53 G0 Z-3.5")
        ACTION.CALL_MDI("G53 G0 X0 Y0")

    def _update_park_btn(self):
        enabled = (STATUS.machine_is_on()
               and STATUS.is_all_homed()
               and STATUS.is_interp_idle())
        self.w.btn_park.setEnabled(enabled)

    def update_fid_lighting(self, value):
        self.w.fid_light_level.setValue(value)

    def update_ph_setpoint(self, value):
        self.w.preheat_setpoint.setValue(value)

    def update_djdot(self, value):
        self.cmd.set_analog_output(0, float(value))
        # self.w.dj_dotsize.setValue(value)

    def update_djfreq(self, value):
        self.cmd.set_analog_output(1, float(value))
        # self.w.dj_freq.setValue(value)

    def update_fid_find(self, value):
        self.w.fid_find.setChecked(value)

    def update_fid_is_square(self, value):
        self.w.fid_is_square.setChecked(value)

    def update_fid_size(self, value):
        self.w.fid_size.setValue(value)

    def update_fid_area(self, value):
        self.w.fid_area.setValue(value)

    def update_fid_tolerance(self, value):
        self.w.fid_tolerance.setValue(value)

    def processed_key_event__(self, receiver, event, is_pressed, key, code, shift, cntrl):
        # when typing in MDI, we don't want keybinding to call functions
        # so we catch and process the events directly.
        # We do want ESC, F1 and F2 to call keybinding functions though
        if code not in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_F1, QtCore.Qt.Key_F2,
                        QtCore.Qt.Key_F3, QtCore.Qt.Key_F5, QtCore.Qt.Key_F5):

            # search for the top widget of whatever widget received the event
            # then check if it's one we want the keypress events to go to
            flag = False
            receiver2 = receiver
            from PyQt5.QtWidgets import QDoubleSpinBox, QSpinBox, QLineEdit, QAbstractSpinBox
            while receiver2 is not None and not flag:
                if isinstance(receiver2, QtWidgets.QDialog):
                    flag = True
                    break
                if isinstance(receiver2, MDI_WIDGET):
                    flag = True
                    break
                if isinstance(receiver2, GCODE):
                    flag = True
                    break
                if isinstance(receiver2, MDI_HAAS):
                    flag = True
                    break
                if isinstance(receiver2, TOOL_OFFSET):
                    flag = True
                    break
                if isinstance(receiver2, ORIGIN_OFFSET):
                    flag = True
                    break
                if isinstance(receiver2, (QDoubleSpinBox, QSpinBox, QLineEdit, QAbstractSpinBox)):
                    flag = True
                    break
                receiver2 = receiver2.parent()

            if flag:
                if isinstance(receiver2, (GCODE, MDI_HAAS)):
                    if is_pressed:
                        receiver.keyPressEvent(event)
                        event.accept()
                    return True
                elif is_pressed:
                    receiver.keyPressEvent(event)
                    event.accept()
                    return True
                else:
                    event.accept()
                    return True

        if event.isAutoRepeat(): return True

        # ok if we got here then try keybindings function calls
        # KEYBINDING will call functions from handler file as
        # registered by KEYBIND.add_call(KEY,FUNCTION) above
        return KEYBIND.manage_function_calls(self, event, is_pressed, key, shift, cntrl)

    ########################
    # callbacks from STATUS #
    ########################

    def on_tool_changed(self, widget):
        tool_number = STATUS.stat.tool_in_spindle
        if tool_number == self._last_tool:
            return
        self._last_tool = tool_number
        tab_index = TOOL_TO_CAMERA_TAB.get(tool_number)
        if tab_index is not None:
            self.w.CAMERA.setCurrentIndex(tab_index)

    def _poll_errors(self, w):
        try:
            e = STATUS.poll_error()
        except Exception as ex:
            LOG.error('Error channel read failed: {}'.format(ex))
            return
        if e:
            kind, text = e
            STATUS.emit('error', kind, text)

    def _on_error(self, w, kind, text):
        is_error = kind in (linuxcnc.OPERATOR_ERROR, linuxcnc.NML_ERROR)
        prefix = 'ERROR: ' if is_error else ''
        STATUS.emit('update-machine-log', prefix + text, 'TIME')
        self.w.statusbar.showMessage(prefix + text.splitlines()[0], 5000)
        if is_error:
            self._show_error_popup(text)

    def _show_error_popup(self, text):
        toast = _ErrorToast(self.w, text)
        toast.dismissed.connect(self._toast_dismissed)
        self._error_toasts.append(toast)
        self._reflow_toasts()

    def _toast_dismissed(self, toast):
        if toast in self._error_toasts:
            self._error_toasts.remove(toast)
        self._reflow_toasts()

    def _reflow_toasts(self):
        y = 20
        for toast in self._error_toasts:
            x = self.w.width() - toast.width() - 20
            toast.move(x, y)
            toast.show()
            toast.raise_()
            y += toast.height() + 8

    def tab_changed(self, index):
        if self.w.SETTINGS.tabText(index) == 'TOOLS':
            self.w.tooloffsetview.setFocus()
        elif self.w.SETTINGS.tabText(index) == 'OFFSETS':
            self.w.originoffsetview.setFocus()
    
    def gcode_tab_changed(self, index):
        if self.w.GCODE.tabText(index) == 'EDIT':
            self.w.gcodeeditor.setFocus()

    def offset_changed(self, index):
        offsets = ['G54','G55','G56','G57','G58','G59','G59.1','G59.2','G59.3']
        
        # capture current mode
        current_mode = STATUS.stat.task_mode

        # switch to MDI, change offset, then restore
        ACTION.SET_MACHINE_STATE(True)
        ACTION.SET_MDI_MODE()
        ACTION.CALL_MDI(offsets[index])
      
        # restore previous mode
        if current_mode == linuxcnc.MODE_MANUAL:
            ACTION.SET_MANUAL_MODE()
        elif current_mode == linuxcnc.MODE_AUTO:
            ACTION.SET_AUTO_MODE()
        # if it was already MDI we can just leave it

    #######################
    # callbacks from form #
    #######################

    def _set_estop_style(self, active):
        self.w.actionbutton_5.setProperty('isEstopped', active)
        self.w.actionbutton_5.style().unpolish(self.w.actionbutton_5)
        self.w.actionbutton_5.style().polish(self.w.actionbutton_5)

    # Utilities tab
    def CLEARSTATUS_clicked(self):
        STATUS.emit('update-machine-log', None, 'DELETE')

    #####################
    # general functions #
    #####################

    # keyboard jogging from key binding calls
    # double the rate if fast is true
    def kb_jog(self, state, joint, direction, fast=False, linear=True):
        if not STATUS.is_man_mode() or not STATUS.machine_is_on():
            return
        if linear:
            distance = STATUS.get_jog_increment()
            rate = STATUS.get_jograte() / 60
        else:
            distance = STATUS.get_jog_increment_angular()
            rate = STATUS.get_jograte_angular() / 60
        if state:
            if fast:
                rate = rate * 2
            ACTION.JOG(joint, direction, rate, distance)
        else:
            ACTION.JOG(joint, 0, 0, 0)

    def reload_qss(self, path=None):
        # Re-add file to watcher if editor replaced it (delete+recreate)
        if path and path not in self.watcher.files():
            self.watcher.addPath(path)
        if os.path.exists(self.qss_path):
            with open(self.qss_path, 'r') as f:
                self.w.setStyleSheet(f.read())
            LOG.info(f"QSS reloaded from {self.qss_path}")

    #####################
    # KEY BINDING CALLS #
    #####################

    # Machine control
    def on_keycall_ESTOP(self, event, state, shift, cntrl):
        if state:
            ACTION.SET_ESTOP_STATE(STATUS.estop_is_clear())

    def on_keycall_POWER(self, event, state, shift, cntrl):
        if state:
            ACTION.SET_MACHINE_STATE(not STATUS.machine_is_on())

    def on_keycall_HOME(self, event, state, shift, cntrl):
        if state:
            if STATUS.is_all_homed():
                ACTION.SET_MACHINE_UNHOMED(-1)
            else:
                ACTION.SET_MACHINE_HOMING(-1)

    def on_keycall_ABORT(self, event, state, shift, cntrl):
        if state:
            self.cmd.abort()

    def on_keycall_F12(self, event, state, shift, cntrl):
        if state:
            STYLEEDITOR.load_dialog()

    # Linear Jogging
    def on_keycall_XPOS(self, event, state, shift, cntrl):
        self.kb_jog(state, 0, 1, shift)

    def on_keycall_XNEG(self, event, state, shift, cntrl):
        self.kb_jog(state, 0, -1, shift)

    def on_keycall_YPOS(self, event, state, shift, cntrl):
        self.kb_jog(state, 1, 1, shift)

    def on_keycall_YNEG(self, event, state, shift, cntrl):
        self.kb_jog(state, 1, -1, shift)

    def on_keycall_ZPOS(self, event, state, shift, cntrl):
        self.kb_jog(state, 2, 1, shift)

    def on_keycall_ZNEG(self, event, state, shift, cntrl):
        self.kb_jog(state, 2, -1, shift)

    def on_keycall_APOS(self, event, state, shift, cntrl):
        pass
        #self.kb_jog(state, 3, 1, shift, False)

    def on_keycall_ANEG(self, event, state, shift, cntrl):
        pass
        #self.kb_jog(state, 3, -1, shift, linear=False)

    ###########################
    # **** closing event **** #
    ###########################

    ##############################
    # required class boiler code #
    ##############################

    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, item, value):
        return setattr(self, item, value)

################################
# required handler boiler code #
################################

def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]