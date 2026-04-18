#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
#    Gcode display / edit widget for QT_VCP
#    Copyright 2016 Chris Morley
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import os
import re

from PyQt5.QtCore import pyqtProperty, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QFontMetrics, QColor, QIcon
from PyQt5.QtWidgets import QWidget, \
        QVBoxLayout, QLineEdit, QHBoxLayout, QMessageBox, \
        QFrame, QLabel, QPushButton

from qtvcp.widgets.widget_baseclass import _HalWidgetBase
from qtvcp.core import Status, Info, Action
from qtvcp import logger

STATUS = Status()
INFO = Info()
ACTION = Action()
LOG = logger.getLogger(__name__)

try:
    from PyQt5.Qsci import QsciScintilla, QsciLexerCustom, QsciLexerPython
except ImportError as e:
    LOG.critical("Can't import QsciScintilla - is package python3-pyqt5.qsci installed?", exc_info=e)
    sys.exit(1)


class GcodeLexer(QsciLexerCustom):
    def __init__(self, parent):
        super(GcodeLexer, self).__init__(parent)
        self._styles = {
            0: 'Default',
            1: 'Comment',
            2: 'Gcode',
            3: 'Mcode',
            4: 'Axis',
            5: 'Other',
            6: 'AxisValue',
            7: 'OtherValue',
        }
        for key, value in self._styles.items():
            setattr(self, value, key)

    def language(self):
        return "G-code"

    def description(self, style):
        return self._styles.get(style, "")

    def styleText(self, start, end):
        editor = self.editor()
        if editor is None:
            return
        self.startStyling(start)
        source = ''
        if end > editor.length():
            end = editor.length()
        if end > start:
            if sys.hexversion >= 0x02060000:
                source = bytearray(end - start)
                editor.SendScintilla(
                    editor.SCI_GETTEXTRANGE, start, end, source)
                source = source.decode("utf-8", "ignore")
            else:
                source = str(editor.text())[start:end]
        if not source:
            return

        re_tokens = {
            1: r"(?:[N]\d+|\(.*?\)|;.*)",
            2: r"[G]\d{1,2}\.\d|[G]\d{1,2}",
            3: r"[M]\d{1,3}",
            4: r"[XYZABCUVW]{1}(?:[+-]?[\d\.]+|\#\<.*\>|\[.*\]|\#\d+)",
            5: r"[EFHIJKDQLRPST$]{1}(?:[+-]?[\d\.]+|\#\<.*\>|\[.*\]|\#\d+)",
            0: r"\s+|\w+|\W",
        }

        re_comment_cmd = r"(?:\(\s*(?:print,|debug,|msg,|logopen,|logappend,|logclose|log,|pyrun,|pyreload|abort,|probeopen|probeclose)|^\s*\;py,)"
        re_string = "|".join(re_tokens.values())
        p = re.compile(re_string, re.IGNORECASE)

        for line in source.splitlines(True):
            token_list = [(token, len(bytearray(token, "utf-8"))) for token in p.findall(line)]
            num_comment_cmds = len(re.findall(re_comment_cmd, line, re.IGNORECASE))
            for token in token_list:
                if re.match(re_tokens[self.Comment], token[0], re.IGNORECASE):
                    m = re.search(re_comment_cmd, token[0], re.IGNORECASE)
                    if m:
                        num_comment_cmds -= 1
                    if m and num_comment_cmds == 0:
                        self.setStyling(1, self.Comment)
                        self.setStyling(m.span()[1] - 1, self.Other)
                        self.setStyling(len(token[0]) - m.span()[1], self.Comment)
                    else:
                        self.setStyling(token[1], self.Comment)
                elif re.match(re_tokens[self.Gcode], token[0], re.IGNORECASE):
                    self.setStyling(token[1], self.Gcode)
                elif re.match(re_tokens[self.Mcode], token[0], re.IGNORECASE):
                    self.setStyling(token[1], self.Mcode)
                elif re.match(re_tokens[self.Axis], token[0], re.IGNORECASE):
                    self.setStyling(1, self.Axis)
                    self.setStyling(token[1] - 1, self.AxisValue)
                elif re.match(re_tokens[self.Other], token[0], re.IGNORECASE):
                    self.setStyling(1, self.Other)
                    self.setStyling(token[1] - 1, self.OtherValue)
                else:
                    self.setStyling(token[1], self.Default)


class EditorBase(QsciScintilla):
    CURRENT_MARKER_NUM = 0
    USER_MARKER_NUM = 1

    _styleFont = {
        0: QFont("Courier", 11),
    }

    _styleColor = {
        0: QColor("#000000"),
        1: QColor("#434d3f"),
        2: QColor("#ba220b"),
        3: QColor("#f56b1b"),
        4: QColor("#1883c9"),
        5: QColor("#dd30f0"),
        6: QColor("#0e5482"),
        7: QColor("#a420b3"),
        "Margins":  QColor("#666769"),
    }

    _styleBackgroundColor = QColor("#c0c0c0")
    _styleMarginsBackgroundColor = QColor("#cccccc")
    _styleMarkerBackgroundColor = QColor("#a5a526")
    _styleSelectionBackgroundColor = QColor("#001111")
    _styleSelectionForegroundColor = QColor("#ffffff")
    _styleSyntaxHighlightEnabled = True

    def __init__(self, parent=None):
        super(EditorBase, self).__init__(parent)
        self.lexer = None
        self.lexer_num_styles = 0
        self._lastUserLine = 0
        self.setReadOnly(True)
        self.set_lexer("g-code")
        self._marginWidth = '00000'
        self.setMarginWidth(0, self._marginWidth)
        self.linesChanged.connect(self.on_lines_changed)
        self.setMarginLineNumbers(0, True)
        self.marginClicked.connect(self.on_margin_clicked)
        self.setMarginMarkerMask(0, 0b1111)
        self.setMarginSensitivity(0, True)
        self.setMarginWidth(1, 0)
        self.currentHandle = self.markerDefine(QsciScintilla.Background,
                          self.CURRENT_MARKER_NUM)
        self.setColorMarkerBackground(self.getColorMarkerBackground())
        self.userHandle = self.markerDefine(QsciScintilla.Background,
                          self.USER_MARKER_NUM)
        self.setMarkerBackgroundColor(QColor("#ffc0c0"), self.USER_MARKER_NUM)
        self.setBraceMatching(QsciScintilla.SloppyBraceMatch)
        self.setCaretLineVisible(False)
        self.SendScintilla(QsciScintilla.SCI_GETCARETLINEVISIBLEALWAYS, True)
        self.setCaretLineBackgroundColor(QColor("#ffe4e4"))
        self.ensureLineVisible(True)
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTH, 700)
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTHTRACKING)
        self.setMinimumSize(200, 100)
        self.filepath = None

    def set_lexer(self, lexer_type=None):
        self.lexer = None
        self.lexer_num_styles = 0
        if lexer_type is None or not self._styleSyntaxHighlightEnabled:
            self.lexer = None
        elif lexer_type.lower() == "g-code":
            self.lexer = GcodeLexer(self)
        elif lexer_type.lower() == "python":
            self.lexer = QsciLexerPython(self)
        if self.lexer is not None:
            while self.lexer.description(self.lexer_num_styles) != "":
                self.lexer_num_styles += 1
        self.setLexer(self.lexer)
        self.refresh_styles()

    def refresh_styles(self):
        self.setDefaultFont(self.getDefaultFont())
        self.set_font_colors()
        self.setColorBackground(self.getColorBackground())
        self.setColorMarginsBackground(self.getColorMarginsBackground())
        self.setSelectionBackgroundColor(self.getColorSelectionBackground())
        self.setSelectionForegroundColor(self.getColorSelectionForeground())

    def set_font_colors(self):
        self.setColor(self.getColor0())
        self.setColorMarginsForeground(self.getColorMarginsForeground())
        if self.lexer is not None:
            for i in range(0, self.lexer_num_styles):
                self.lexer.setColor(self._styleColor.get(i, self._styleColor[0]), i)

    def set_margin_width(self):
        self.setMarginWidth(0, self._marginWidth)

    def set_margin_metric(self, width):
        fontmetrics = QFontMetrics(self.getFontMargins())
        self.setMarginWidth(0, fontmetrics.width("0" * width) + 6)

    def on_lines_changed(self):
        if len(str(self.lines())) < 3:
            self._marginWidth = '0000'
        else:
            self._marginWidth = str(self.lines())+'0'
        self.setMarginWidth(0, self._marginWidth)

    def on_margin_clicked(self, nmargin, nline, modifiers):
        if self.markersAtLine(nline) != 2:
            self.markerDelete(self._lastUserLine, self.USER_MARKER_NUM)
            self.markerAdd(nline, self.USER_MARKER_NUM)
        elif self._lastUserLine != nline:
            self.markerAdd(nline, self.USER_MARKER_NUM)
            self.markerDelete(self._lastUserLine, self.USER_MARKER_NUM)
        else:
            self.markerDelete(self._lastUserLine, self.USER_MARKER_NUM)
            self._lastUserLine = 0
            return
        self._lastUserLine = nline

    def mouseDoubleClickEvent(self, event):
        pass

    def new_text(self):
        self.setText('')

    def load_text(self, filepath):
        self.filepath = filepath
        if filepath is None:
            return
        try:
            fp = os.path.expanduser(filepath)
            with open(fp) as f:
                self.setText(f.read())
        except OSError as e:
            LOG.error("load_text(): {}".format(e))
            self.setText('')
            return
        except Exception as e:
            LOG.error("load_text(): {}".format(e))
            self.setText('')
            return
        self.ensureCursorVisible()
        self.SendScintilla(QsciScintilla.SCI_VERTICALCENTRECARET)
        self.setModified(False)

    def save_text(self):
        try:
            with open(self.filepath + 'text', "w") as f:
                f.write(self.text())
        except OSError as e:
            LOG.error("save_text(): {}".format(e))

    def replace_text(self, text):
        self.replace(text)

    def search(self, text, re=False, case=False, word=False, wrap=False, fwd=True):
        self.findFirst(text, re, case, word, wrap, fwd)

    def search_Next(self):
        self.SendScintilla(QsciScintilla.SCI_SEARCHANCHOR)
        self.findNext()

    def getColor0(self):
        return self._styleColor[0]
    def setColor0(self, value):
        self._styleColor[0] = value
        self.setColor(value)
        if self.lexer is not None:
            self.lexer.setColor(value, 0)
    styleColor0 = pyqtProperty(QColor, getColor0, setColor0)

    def getColor1(self):
        return self._styleColor.get(1, self._styleColor[0])
    def setColor1(self, value):
        self._styleColor[1] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 1)
    styleColor1 = pyqtProperty(QColor, getColor1, setColor1)

    def getColor2(self):
        return self._styleColor.get(2, self._styleColor[0])
    def setColor2(self, value):
        self._styleColor[2] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 2)
    styleColor2 = pyqtProperty(QColor, getColor2, setColor2)

    def getColor3(self):
        return self._styleColor.get(3, self._styleColor[0])
    def setColor3(self, value):
        self._styleColor[3] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 3)
    styleColor3 = pyqtProperty(QColor, getColor3, setColor3)

    def getColor4(self):
        return self._styleColor.get(4, self._styleColor[0])
    def setColor4(self, value):
        self._styleColor[4] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 4)
    styleColor4 = pyqtProperty(QColor, getColor4, setColor4)

    def getColor5(self):
        return self._styleColor.get(5, self._styleColor[0])
    def setColor5(self, value):
        self._styleColor[5] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 5)
    styleColor5 = pyqtProperty(QColor, getColor5, setColor5)

    def getColor6(self):
        return self._styleColor.get(6, self._styleColor[0])
    def setColor6(self, value):
        self._styleColor[6] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 6)
    styleColor6 = pyqtProperty(QColor, getColor6, setColor6)

    def getColor7(self):
        return self._styleColor.get(7, self._styleColor[0])
    def setColor7(self, value):
        self._styleColor[7] = value
        if self.lexer is not None:
            self.lexer.setColor(value, 7)
    styleColor7 = pyqtProperty(QColor, getColor7, setColor7)

    def getColorMarginsForeground(self):
        return self._styleColor.get("Margins", self._styleColor[0])
    def setColorMarginsForeground(self, value):
        super(EditorBase, self).setMarginsForegroundColor(value)
        self._styleColor["Margins"] = value
    styleColorMarginText = pyqtProperty(QColor, getColorMarginsForeground, setColorMarginsForeground)

    def getColorBackground(self):
        return self._styleBackgroundColor
    def setColorBackground(self, color):
        self._styleBackgroundColor = color
        self.setPaper(color)
        if self.lexer is not None:
            self.lexer.setDefaultPaper(color)
            for i in range(0, self.lexer_num_styles):
                self.lexer.setPaper(color, i)
    styleColorBackground = pyqtProperty(QColor, getColorBackground, setColorBackground)

    def setColorMarginsBackground(self, color):
        super(EditorBase, self).setMarginsBackgroundColor(color)
        self._styleMarginsBackgroundColor = color
    def getColorMarginsBackground(self):
        return self._styleMarginsBackgroundColor
    styleColorMarginBackground = pyqtProperty(QColor, getColorMarginsBackground, setColorMarginsBackground)

    def getColorSelectionBackground(self):
        return self._styleSelectionBackgroundColor
    def setColorSelectionBackground(self, value):
        self._styleSelectionBackgroundColor = value
        self.setSelectionBackgroundColor(value)
    styleColorSelectionBackground = pyqtProperty(QColor, getColorSelectionBackground, setColorSelectionBackground)

    def getColorSelectionForeground(self):
        return self._styleSelectionForegroundColor
    def setColorSelectionForeground(self, value):
        self._styleSelectionForegroundColor = value
        self.setSelectionForegroundColor(value)
    styleColorSelectionText = pyqtProperty(QColor, getColorSelectionForeground, setColorSelectionForeground)

    def getColorMarkerBackground(self):
        return self._styleMarkerBackgroundColor
    def setColorMarkerBackground(self, value):
        self._styleMarkerBackgroundColor = value
        self.setMarkerBackgroundColor(value, self.CURRENT_MARKER_NUM)
    styleColorMarkerBackground = pyqtProperty(QColor, getColorMarkerBackground, setColorMarkerBackground)

    def setDefaultFont(self, value):
        self._styleFont[0] = value
        self.setFont(value)
        self.setFontMargins(self.getFontMargins())
        if self.lexer is not None:
            self.lexer.setFont(value)
            for i in range(0, self.lexer_num_styles):
                self.lexer.setFont(self._styleFont.get(i, self._styleFont[0]), i)
    def getDefaultFont(self):
        return self._styleFont[0]
    styleFont = pyqtProperty(QFont, getDefaultFont, setDefaultFont)

    def getFont0(self):
        return self._styleFont[0]
    def setFont0(self, value):
        self._styleFont[0] = value
        self.setFont(value)
        if self.lexer is not None:
            self.lexer.setFont(value, 0)
    styleFont0 = pyqtProperty(QFont, getFont0, setFont0)

    def getFont1(self):
        return self._styleFont.get(1, self._styleFont[0])
    def setFont1(self, value):
        self._styleFont[1] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 1)
    styleFont1 = pyqtProperty(QFont, getFont1, setFont1)

    def getFont2(self):
        return self._styleFont.get(2, self._styleFont[0])
    def setFont2(self, value):
        self._styleFont[2] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 2)
    styleFont2 = pyqtProperty(QFont, getFont2, setFont2)

    def getFont3(self):
        return self._styleFont.get(3, self._styleFont[0])
    def setFont3(self, value):
        self._styleFont[3] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 3)
    styleFont3 = pyqtProperty(QFont, getFont3, setFont3)

    def getFont4(self):
        return self._styleFont.get(4, self._styleFont[0])
    def setFont4(self, value):
        self._styleFont[4] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 4)
    styleFont4 = pyqtProperty(QFont, getFont4, setFont4)

    def getFont5(self):
        return self._styleFont.get(5, self._styleFont[0])
    def setFont5(self, value):
        self._styleFont[5] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 5)
    styleFont5 = pyqtProperty(QFont, getFont5, setFont5)

    def getFont6(self):
        return self._styleFont.get(6, self._styleFont[0])
    def setFont6(self, value):
        self._styleFont[6] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 6)
    styleFont6 = pyqtProperty(QFont, getFont6, setFont6)

    def getFont7(self):
        return self._styleFont.get(7, self._styleFont[0])
    def setFont7(self, value):
        self._styleFont[7] = value
        if self.lexer is not None:
            self.lexer.setFont(value, 7)
    styleFont7 = pyqtProperty(QFont, getFont7, setFont7)

    def getFontMargins(self):
        return self._styleFont.get("Margins", self._styleFont[0])
    def setFontMargins(self, value):
        self._styleFont["Margins"] = value
        self.setMarginsFont(value)
    styleFontMargin = pyqtProperty(QFont, getFontMargins, setFontMargins)

    def getSyntaxHighlightEnabled(self):
        return self._styleSyntaxHighlightEnabled
    def setSyntaxHighlightEnabled(self, value):
        if value is not self._styleSyntaxHighlightEnabled:
            self._styleSyntaxHighlightEnabled = value
            if not value:
                self.set_lexer(None)
            else:
                self.set_lexer("g-code")
    styleSyntaxHighlightEnabled = pyqtProperty(bool, getSyntaxHighlightEnabled, setSyntaxHighlightEnabled)


class GcodeDisplay(EditorBase, _HalWidgetBase):
    CURRENT_MARKER_NUM = 0
    USER_MARKER_NUM = 1

    def __init__(self, parent=None):
        super(GcodeDisplay, self).__init__(parent)
        self.idle_line_reset = False
        self._last_filename = None
        self.auto_show_mdi = True
        self.auto_show_manual = False
        self.auto_show_preference = True
        self.last_line = 0
        self._last_auto_scroll = 0

    def _hal_init(self):
        self.cursorPositionChanged.connect(self.line_changed)
        if self.auto_show_mdi:
            STATUS.connect('mode-mdi', self.load_mdi)
            STATUS.connect('mdi-history-changed', self.load_mdi)
            STATUS.connect('mode-auto', self.reload_last)
            STATUS.connect('move-text-lineup', self.select_lineup)
            STATUS.connect('move-text-linedown', self.select_linedown)
            STATUS.connect('mode-manual', self.load_manual)
        if self.auto_show_manual:
            STATUS.connect('mode-manual', self.load_manual)
            STATUS.connect('machine-log-changed', self.load_manual)
        if self.auto_show_preference:
            STATUS.connect('show-preference', self.load_preference)
        STATUS.connect('file-loaded', self.load_program)
        STATUS.connect('reload-display', self.load_program)
        STATUS.connect('line-changed', self.external_highlight_request)
        STATUS.connect('graphics-line-selected', self.external_highlight_request)
        STATUS.connect('command-stopped', lambda w: self.run_stopped())
        if self.idle_line_reset:
            STATUS.connect('interp_idle', lambda w: self.set_line_number(0))
        self.markerDeleteHandle(self.currentHandle)

    def load_program(self, w, filename=None):
        if filename is None:
            filename = self._last_filename
        else:
            self._last_filename = filename
        self.load_text(filename)
        self.setCursorPosition(0, 0)
        self.markerDeleteHandle(self.currentHandle)
        self.setModified(False)
        self._lastUserLine = 0

    def reload_last(self, w):
        self.load_text(STATUS.old['file'])
        self.setCursorPosition(0, 0)
        self.verticalScrollBar().setValue(self._last_auto_scroll)
        if self._lastUserLine >0:
            self.markerAdd(self._lastUserLine, self.USER_MARKER_NUM)

    def load_mdi(self, w):
        if STATUS.get_previous_mode() == STATUS.AUTO:
            self._last_auto_scroll = self.verticalScrollBar().value()
        self.load_text(INFO.MDI_HISTORY_PATH)
        self._last_filename = INFO.MDI_HISTORY_PATH
        self.setCursorPosition(self.lines(), 0)

    def load_manual(self, w):
        if STATUS.get_previous_mode() == STATUS.AUTO:
            self._last_auto_scroll = self.verticalScrollBar().value()
        if self.auto_show_manual and STATUS.is_man_mode():
            self.load_text(INFO.MACHINE_LOG_HISTORY_PATH)
            self.setCursorPosition(self.lines(), 0)

    def load_preference(self, w):
        self.load_text(self.PATHS_.PREFS_FILENAME)
        self.setCursorPosition(self.lines(), 0)

    def external_highlight_request(self, w, line):
        if line in (-1, None):
            return
        if STATUS.is_auto_running():
            self.highlight_line(None, line-1)
            return
        self.ensureLineVisible(line-1)
        self.moveMarker(line-1)
        self.selectAll(False)

    def moveMarker(self, line):
        if STATUS.stat.file == '':
            self.last_line = 0
            return
        self.markerDeleteHandle(self.currentHandle)
        self.currentHandle = self.markerAdd(line, self.CURRENT_MARKER_NUM)
        self.last_line = line

    def highlight_line(self, w, line):
        LOG.verbose('editor: highlight line {}'.format(line))
        if STATUS.is_auto_running():
            if not STATUS.old['file'] == self._last_filename:
                self.load_text(STATUS.old['file'])
                self._last_filename = STATUS.old['file']
            self.emit_percent(round(line*100/self.lines()))
        self.moveMarker(line)
        self.setCursorPosition(line, 0)
        self.ensureCursorVisible()
        self.SendScintilla(QsciScintilla.SCI_VERTICALCENTRECARET)

    def emit_percent(self, percent):
        pass

    def run_stopped(self):
        self.emit_percent(-1)

    def set_line_number(self, line):
        STATUS.emit('gcode-line-selected', line+1)

    def line_changed(self, line, index):
        LOG.verbose('Line changed: {}'.format(line))
        if STATUS.is_auto_running() is False:
            if STATUS.is_mdi_mode():
                line_text = str(self.text(line)).strip()
                STATUS.emit('mdi-line-selected', line_text, self._last_filename)
            else:
                self.moveMarker(line)
                self.set_line_number(line)

    def select_lineup(self, w):
        line, col = self.getCursorPosition()
        self.setCursorPosition(line-1, 0)
        self.highlight_line(None, line-1)

    def select_linedown(self, w):
        line, col = self.getCursorPosition()
        self.setCursorPosition(line+1, 0)
        self.highlight_line(None, line+1)

    def jump_line(self, jump):
        line, col = self.getCursorPosition()
        line = line + jump
        if line <0:
            line = 0
        elif line > self.lines():
            line = self.lines()
        self.setCursorPosition(line, 0)
        self.highlight_line(None, line)

    def zoomIn(self):
        super().zoomIn()
        self.set_margin_width()
    def zoomOut(self):
        super().zoomOut()
        self.set_margin_width()

    def set_auto_show_mdi(self, data):
        self.auto_show_mdi = data
    def get_auto_show_mdi(self):
        return self.auto_show_mdi
    def reset_auto_show_mdi(self):
        self.auto_show_mdi = True
    auto_show_mdi_status = pyqtProperty(bool, get_auto_show_mdi, set_auto_show_mdi, reset_auto_show_mdi)

    def set_auto_show_manual(self, data):
        self.auto_show_manual = data
    def get_auto_show_manual(self):
        return self.auto_show_manual
    def reset_auto_show_manual(self):
        self.auto_show_manual = True
    auto_show_manual_status = pyqtProperty(bool, get_auto_show_manual, set_auto_show_manual, reset_auto_show_manual)


class GcodeEditor2(QWidget, _HalWidgetBase):
    percentDone = pyqtSignal(int)

    def __init__(self, parent=None):
        super(GcodeEditor2, self).__init__(parent)
        self.load_dialog_code = 'LOAD'
        self.save_dialog_code = 'SAVE'
        STATUS.connect('general',self.returnFromDialog)

        self.isCaseSensitive = 0

        self.setMinimumSize(QSize(300, 200))
        self.setWindowTitle("PyQt5 editor test example")

        lay = QVBoxLayout()
        lay.setContentsMargins(0,0,0,0)
        self.setLayout(lay)

        # make editor
        self.editor = GcodeDisplay(self)

        # class patch editor's function to ours
        self.editor.emit_percent = self.emit_percent

        self.editor.setReadOnly(True)
        self.editor.setModified(False)

        # add widgets
        lay.addWidget(self.editor)
        lay.addWidget(self.createGroup())

        # Overlay toggle button - floats over the editor in the top-right corner
        self._toggleButton = QPushButton('EDIT', self)
        self._toggleButton.setFixedSize(60, 25)
        self._toggleButton.clicked.connect(self._toggleEditMode)
        self._toggleButton.raise_()

        self.readOnlyMode()

    def resizeEvent(self, event):
        super(GcodeEditor2, self).resizeEvent(event)
        self._positionToggleButton()

    def _positionToggleButton(self):
        btn = self._toggleButton
        btn.move(self.width() - btn.width() - 10, 10)
        btn.raise_()

    def _toggleEditMode(self):
        if self.editor.isReadOnly():
            self.editMode()
        else:
            self.exitCall()

    def createGroup(self):
        self.bottomMenu = QFrame()

        ICO_SIZE = QSize(16, 16)
        BTN_SIZE = 25  # square icon buttons

        self.searchText = QLineEdit(self)
        self.searchText.setStatusTip('Text to search for')
        self.replaceText = QLineEdit(self)
        self.replaceText.setStatusTip('Replace search text with this text')

        def _iconBtn(theme, tip, slot, checkable=False):
            btn = QPushButton(self)
            btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            btn.setIcon(QIcon.fromTheme(theme))
            btn.setIconSize(ICO_SIZE)
            btn.setToolTip(tip)
            btn.setStatusTip(tip)
            btn.setCheckable(checkable)
            btn.clicked.connect(slot)
            return btn

        undoButton     = _iconBtn('edit-undo',        'Undo',                  self.undoCall)
        redoButton     = _iconBtn('edit-redo',        'Redo',                  self.redoCall)
        findButton     = _iconBtn('edit-find',        'Find next',             self.findCall)
        previousButton = _iconBtn('go-previous',      'Find previous',         self.previousCall)
        replaceButton  = _iconBtn('edit-find-replace','Replace',               self.replaceCall)
        self.caseButton = _iconBtn('format-text-bold','Match case (toggle)',   self.caseCall, checkable=True)

        self.bottomBox = QHBoxLayout()
        self.bottomBox.setContentsMargins(4, 4, 4, 4)
        self.bottomBox.setSpacing(4)
        self.bottomBox.addWidget(undoButton)
        self.bottomBox.addWidget(redoButton)
        self.bottomBox.addWidget(findButton)
        self.bottomBox.addWidget(previousButton)
        self.bottomBox.addWidget(replaceButton)
        self.bottomBox.addWidget(self.caseButton)
        self.bottomBox.addWidget(self.searchText)
        self.bottomBox.addWidget(self.replaceText)
        self.bottomMenu.setLayout(self.bottomBox)

        return self.bottomMenu

    def caseCall(self):
        self.case()
    def case(self):
        self.isCaseSensitive -=1
        self.isCaseSensitive *=-1

    def exitCall(self):
        self.exit()
    def exit(self):
        if self.editor.isModified():
            if self.killCheck():
                self._saveToCurrentFile()
                self.readOnlyMode()
        else:
            self.readOnlyMode()

    def _saveToCurrentFile(self):
        fname = self.editor._last_filename
        if fname:
            saved = ACTION.SAVE_PROGRAM(self.editor.text(), fname)
            if saved is not None:
                self.editor.setModified(False)
                ACTION.OPEN_PROGRAM(saved)
        else:
            LOG.error("_saveToCurrentFile(): no filename to save to")

    def findCall(self):
        self.find()
    def find(self):
        self.editor.search(str(self.searchText.text()),
                             re=False, case=self.isCaseSensitive,
                             word=False, wrap= True, fwd=True)

    def previousCall(self):
        self.previous()
    def previous(self):
        self.editor.setCursorPosition(self.editor.getSelection()[0],
                                      self.editor.getSelection()[1])
        self.editor.search(str(self.searchText.text()),
                           re=False, case=self.isCaseSensitive,
                           word=False, wrap=True, fwd=False)

    def gcodeLexerCall(self):
        self.gcodeLexer()
    def gcodeLexer(self):
        self.editor.set_lexer("g-code")

    def nextCall(self):
        self.next()
    def next(self):
        self.editor.search(str(self.searchText.text()),
                             re=False, case=self.isCaseSensitive,
                             word=False, wrap=True, fwd=False)
        self.editor.search_Next()

    def newCall(self):
        self.new()
    def new(self):
        if self.editor.isModified():
            result = self.killCheck()
            if result:
                self.editor.new_text()
        else:
            self.editor.new_text()

    def openCall(self):
        self.open()
    def open(self):
        self.getFileName()
    def openReturn(self,f):
        ACTION.OPEN_PROGRAM(f)
        self.editor.setModified(False)

    def redoCall(self):
        self.redo()
    def redo(self):
        self.editor.redo()

    def replaceCall(self):
        self.replace()
    def replace(self):
        self.editor.replace_text(str(self.replaceText.text()))
        self.editor.search(str(self.searchText.text()),
                             re=False, case=self.isCaseSensitive,
                             word=False, wrap=True, fwd=True)

    def saveCall(self):
        self.save()
    def save(self):
        self.getSaveFileName()
    def saveReturn(self, fname):
        saved = ACTION.SAVE_PROGRAM(self.editor.text(), fname)
        if saved is not None:
            self.editor.setModified(False)
            ACTION.OPEN_PROGRAM(saved)

    def undoCall(self):
        self.undo()
    def undo(self):
        self.editor.undo()

    def _hal_init(self):
        self.bottomMenu.setObjectName('%sBottomButtonFrame'% self.objectName())
        self.editor.setObjectName('{}_display'.format( self.objectName()))

    def editMode(self):
        self.bottomMenu.show()
        self.editor.setReadOnly(False)
        self._toggleButton.setText('EXIT')
        self._positionToggleButton()

    def readOnlyMode(self):
        self.bottomMenu.hide()
        self.editor.setReadOnly(True)
        self._toggleButton.setText('EDIT')
        self._positionToggleButton()

    def getFileName(self):
        mess = {'NAME':self.load_dialog_code,'ID':'%s__' % self.objectName(),
            'TITLE':'Load Editor'}
        STATUS.emit('dialog-request', mess)

    def getSaveFileName(self):
        mess = {'NAME':self.save_dialog_code,'ID':'%s__' % self.objectName(),
            'TITLE':'Save Editor', 'FILENAME':self.editor._last_filename}
        STATUS.emit('dialog-request', mess)

    def returnFromDialog(self, w, message):
        if message.get('NAME') == self.load_dialog_code:
            path = message.get('RETURN')
            code = bool(message.get('ID') == '%s__'% self.objectName())
            if path and code:
                self.openReturn(path)
        elif message.get('NAME') == self.save_dialog_code:
            path = message.get('RETURN')
            code = bool(message.get('ID') == '%s__'% self.objectName())
            if path and code:
                self.saveReturn(path)

    def killCheck(self):
        choice = QMessageBox.question(self, 'Save changes?',
                                            "This file has been modified. Save and exit?",
                                            QMessageBox.Yes | QMessageBox.No)
        if choice == QMessageBox.Yes:
            return True
        else:
            return False

    def emit_percent(self, percent):
        self.percentDone.emit(int(percent))

    def select_lineup(self):
        self.editor.select_lineup(None)

    def select_linedown(self):
        self.editor.select_linedown(None)

    def select_line(self, line):
        self.editor.highlight_line(None, line)

    def jump_line(self, jump):
        self.editor.jump_line(jump)

    def get_line(self):
        return self.editor.getCursorPosition()[0] +1

    def set_margin_metric(self,width):
        self.editor.set_margin_metric(width)

    def set_font(self, font):
        self.editor.setDefaultFont(font)

    def isReadOnly(self):
        return self.editor.isReadOnly()

    def set_auto_show_mdi(self, data):
        self.editor.auto_show_mdi = data
    def get_auto_show_mdi(self):
        return self.editor.auto_show_mdi
    def reset_auto_show_mdi(self):
        self.editor.auto_show_mdi = True
    auto_show_mdi_status = pyqtProperty(bool, get_auto_show_mdi, set_auto_show_mdi, reset_auto_show_mdi)

    def set_auto_show_manual(self, data):
        self.editor.auto_show_manual = data
    def get_auto_show_manual(self):
        return self.editor.auto_show_manual
    def reset_auto_show_manual(self):
        self.editor.auto_show_manual = True
    auto_show_manual_status = pyqtProperty(bool, get_auto_show_manual, set_auto_show_manual, reset_auto_show_manual)

GcodeEditor = GcodeEditor2

if __name__ == "__main__":
    from PyQt5.QtWidgets import *
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *

    app = QApplication(sys.argv)
    w = GcodeEditor2()
    w.editMode()

    if len(sys.argv) > 1:
        w.editor.load_text(sys.argv[1])

    w.show()
    sys.exit(app.exec_())