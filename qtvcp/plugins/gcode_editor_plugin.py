from PyQt5 import QtGui
from PyQt5.QtDesigner import QPyDesignerCustomWidgetPlugin
from gcode_editor_2 import GcodeEditor2
from qtvcp.widgets.qtvcp_icons import Icon

####################################
# Gcode editor
####################################
class GcodeEditorPlugin_2(QPyDesignerCustomWidgetPlugin):
    def __init__(self, parent=None):
        super(GcodeEditorPlugin_2, self).__init__(parent)
        self.initialized = False

    def initialize(self, formEditor):
        if self.initialized:
            return
        self.initialized = True

    def isInitialized(self):
        return self.initialized

    def createWidget(self, parent):
        return GcodeEditor2(parent)

    def name(self):
        return "GcodeEditor2"

    def group(self):
        return "Linuxcnc - Controller"

    def icon(self):
        return QtGui.QIcon(QtGui.QPixmap(Icon().get_path('gcodeeditor')))

    def toolTip(self):
        return "Gcode display / editor Widget"

    def whatsThis(self):
        return ""

    def isContainer(self):
        return True

    def domXml(self):
        return '<widget class="GcodeEditor2" name="gcodeeditor" />\n'

    def includeFile(self):
        return "gcode_editor_2"
