#!/usr/bin/env python3

from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtDesigner import QPyDesignerCustomWidgetPlugin
from mdi_haas import MDIHaas
from qtvcp.widgets.qtvcp_icons import Icon

ICON = Icon()


class MDIHaasPlugin(QPyDesignerCustomWidgetPlugin):

    def __init__(self, parent=None):
        super(MDIHaasPlugin, self).__init__(parent)
        self.initialized = False

    def initialize(self, core):
        if self.initialized:
            return
        self.initialized = True

    def isInitialized(self):
        return self.initialized

    def createWidget(self, parent):
        return MDIHaas(parent)

    def name(self):
        return "MDIHaas"

    def group(self):
        return "Linuxcnc - Controller"

    def icon(self):
        return QIcon(QPixmap(ICON.get_path('mdiline')))

    def toolTip(self):
        return "Haas-style MDI program builder widget"

    def whatsThis(self):
        return ""

    def isContainer(self):
        return False

    def domXml(self):
        return '<widget class="MDIHaas" name="mdihaas" />\n'

    def includeFile(self):
        return "mdi_haas"
