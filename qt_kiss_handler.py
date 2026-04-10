############################
# **** IMPORT SECTION **** #
############################
import sys
import os
import linuxcnc

from PyQt5 import QtCore, QtWidgets

from qtvcp.widgets.mdi_line import MDILine as MDI_WIDGET
from qtvcp.widgets.gcode_editor import GcodeEditor as GCODE
from qtvcp.widgets.stylesheeteditor import  StyleSheetEditor as SSE
from qtvcp.widgets.tool_offsetview import ToolOffsetView as TOOL_OFFSET
from qtvcp.widgets.origin_offsetview import OriginOffsetView as ORIGIN_OFFSET
from qtvcp.lib.keybindings import Keylookup
from qtvcp.core import Status, Action
from PyQt5.QtCore import QFileSystemWatcher
from PyQt5.QtGui import QColor

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

        self.w.gcodegraphics.setBackgroundColor(QColor(245, 244, 240))  # #f5f4f0
        self.w.gcodegraphics.setFeedColor(QColor(0, 85, 255, 255))      # #0055ff, alpha must be >0
        self.w.gcodegraphics.setRapidColor(QColor(0, 170, 255, 255))    # #00aaff

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
                if isinstance(receiver2, TOOL_OFFSET):
                    flag = True
                    break
                if isinstance(receiver2, ORIGIN_OFFSET):
                    flag = True
                    break
                receiver2 = receiver2.parent()

            if flag:
                if isinstance(receiver2, GCODE):
                    # if in manual do our keybindings - otherwise
                    # send events to gcode widget
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
            if STATUS.stat.interp_state == linuxcnc.INTERP_IDLE:
                self.w.close()
            else:
                self.cmnd.abort()

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