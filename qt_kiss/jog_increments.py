#!/usr/bin/env python3
# qtvcp - JogIncrements Widget  (vertical rate + increment button panel)
#
# Drop-in replacement for the original combo-box JogIncrements.
# Class name kept as JogIncrements so existing .ui files need no changes.
#
# Vertical column, all buttons mutually exclusive:
#   [100 in/min ]
#   [ 10 in/min ]
#   [  1 in/min ]
#   ─────────────
#   [  0.001"   ]
#   [   0.01"   ]
#   [    0.1"   ]
#
# Selecting a rate button  → continuous jog at that speed
# Selecting a step button  → stepped jog (increment mode)
#
# No inline stylesheet – styling is handled entirely by the application .qss.
# Rate buttons carry  property role="rate"
# Step buttons carry  property role="incr"
#
# Copyright (c) 2024  – GPL v2 or later
#################################################################################

from PyQt5 import QtCore, QtWidgets

from qtvcp.widgets.widget_baseclass import _HalWidgetBase
from qtvcp.core import Status, Info
from qtvcp import logger

STATUS = Status()
INFO   = Info()
LOG    = logger.getLogger(__name__)
# LOG.setLevel(logger.DEBUG)


def _fmt(value):
    """Tidy numeric label – drops trailing zeros."""
    if value == int(value):
        return str(int(value))
    return "{:g}".format(value)


class JogIncrements(QtWidgets.QWidget, _HalWidgetBase):
    """
    Vertical jog control panel.

    Top group    – rate buttons (fast→slow) → continuous jog at that speed
    Bottom group – step buttons (fine→coarse) → incremental jog

    1 in/min sits directly above 0.001" so related speeds are adjacent.
    All six buttons share one exclusive QButtonGroup.
    Base values are always stored in imperial so unit switching never drifts.
    """

    def __init__(self, parent=None):
        super(JogIncrements, self).__init__(parent)

        # base values always stored in imperial, fast→slow order
        self._rate_base = [250.0, 10.0, 1.0]    # in/min
        self._incr_base = [0.001, 0.01, 0.1]     # inches

        self._is_metric = False
        self._block     = False

        self._setup_ui()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rate_display(self):
        if self._is_metric:
            return [round(v * 25.4, 4) for v in self._rate_base]
        return list(self._rate_base)

    def _incr_display(self):
        if self._is_metric:
            return [round(v * 25.4, 6) for v in self._incr_base]
        return list(self._incr_base)

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(2)
        root.setContentsMargins(4, 4, 4, 4)

        # One exclusive group for all six buttons
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        # ── Rate buttons (ids 0-2, displayed fast→slow) ────────────────────
        self._rate_btns = []
        for i in range(3):
            btn = QtWidgets.QPushButton()
            btn.setCheckable(True)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                              QtWidgets.QSizePolicy.Expanding)
            btn.setProperty("role", "rate")
            self._group.addButton(btn, i)
            root.addWidget(btn)
            self._rate_btns.append(btn)

        # ── Divider ────────────────────────────────────────────────────────
        # divider = QtWidgets.QFrame()
        # divider.setFrameShape(QtWidgets.QFrame.HLine)
        # divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        # root.addWidget(divider)

        # ── Increment buttons (ids 3-5, fine→coarse) ──────────────────────
        self._incr_btns = []
        for i in range(3):
            btn = QtWidgets.QPushButton()
            btn.setCheckable(True)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                              QtWidgets.QSizePolicy.Expanding)
            btn.setProperty("role", "incr")
            self._group.addButton(btn, i + 3)
            root.addWidget(btn)
            self._incr_btns.append(btn)

        self._refresh_labels()

        # Default: middle rate (continuous at 10 in/min)
        self._rate_btns[1].setChecked(True)

        self._group.buttonClicked[int].connect(self._on_clicked)

    def _refresh_labels(self):
        unit_r = "mm/min" if self._is_metric else "in/min"
        unit_i = "mm"     if self._is_metric else '"'

        for i, btn in enumerate(self._rate_btns):
            btn.setText("{} {}".format(_fmt(self._rate_display()[i]), unit_r))

        for i, btn in enumerate(self._incr_btns):
            btn.setText("{}{}".format(_fmt(self._incr_display()[i]), unit_i))

    # ── qtvcp hal init ────────────────────────────────────────────────────────

    def _hal_init(self):
        STATUS.connect('metric-mode-changed',
                       self._on_units_changed)
        STATUS.connect('jograte-changed',
                       lambda w, v: self._sync_rate(v))
        STATUS.connect('jogincrement-changed',
                       lambda w, v, t: self._sync_incr(v))

        self._on_clicked(self._group.checkedId())

    # ── unit switch ───────────────────────────────────────────────────────────

    def _on_units_changed(self, w, is_metric):
        self._is_metric = bool(is_metric)
        self._refresh_labels()
        self._on_clicked(self._group.checkedId())

    # ── unified click handler ─────────────────────────────────────────────────

    def _on_clicked(self, btn_id):
        if self._block or btn_id < 0:
            return

        if btn_id <= 2:
            # Rate button – continuous jog
            rate = self._rate_display()[btn_id]
            STATUS.set_jograte(rate)
            STATUS.set_jog_increments(0.0, "Continuous")
            LOG.debug("Continuous rate {}: {} {}".format(
                btn_id, rate, "mm/min" if self._is_metric else "in/min"))
        else:
            # Increment button – stepped jog
            idx  = btn_id - 3
            inc  = self._incr_display()[idx]
            unit = "mm" if self._is_metric else '"'
            text = "{}{}".format(_fmt(inc), unit)
            STATUS.set_jog_increments(inc, text)
            LOG.debug("Step btn {}: {} ({})".format(btn_id, inc, text))

    # ── STATUS sync-back ──────────────────────────────────────────────────────

    def _sync_rate(self, value):
        for i, v in enumerate(self._rate_display()):
            if round(v, 4) == round(value, 4):
                self._block = True
                self._rate_btns[i].setChecked(True)
                self._block = False
                return

    def _sync_incr(self, value):
        if round(value, 6) == 0.0:
            return  # continuous – already reflected by rate button
        for i, v in enumerate(self._incr_display()):
            if round(v, 6) == round(value, 6):
                self._block = True
                self._incr_btns[i].setChecked(True)
                self._block = False
                return

    # ── Qt Designer pyqtProperties ────────────────────────────────────────────

    def _set_rate(self, i, v):
        self._rate_base[i] = v
        self._refresh_labels()

    def _set_incr(self, i, v):
        self._incr_base[i] = v
        self._refresh_labels()

    def get_rate_fast(self):       return self._rate_base[0]
    def set_rate_fast(self, v):    self._set_rate(0, v)
    def reset_rate_fast(self):     self._set_rate(0, 100.0)
    rate_fast = QtCore.pyqtProperty(float, get_rate_fast, set_rate_fast, reset_rate_fast)

    def get_rate_mid(self):        return self._rate_base[1]
    def set_rate_mid(self, v):     self._set_rate(1, v)
    def reset_rate_mid(self):      self._set_rate(1, 10.0)
    rate_mid  = QtCore.pyqtProperty(float, get_rate_mid,  set_rate_mid,  reset_rate_mid)

    def get_rate_slow(self):       return self._rate_base[2]
    def set_rate_slow(self, v):    self._set_rate(2, v)
    def reset_rate_slow(self):     self._set_rate(2, 1.0)
    rate_slow = QtCore.pyqtProperty(float, get_rate_slow, set_rate_slow, reset_rate_slow)

    def get_incr_fine(self):       return self._incr_base[0]
    def set_incr_fine(self, v):    self._set_incr(0, v)
    def reset_incr_fine(self):     self._set_incr(0, 0.001)
    incr_fine   = QtCore.pyqtProperty(float, get_incr_fine,   set_incr_fine,   reset_incr_fine)

    def get_incr_mid(self):        return self._incr_base[1]
    def set_incr_mid(self, v):     self._set_incr(1, v)
    def reset_incr_mid(self):      self._set_incr(1, 0.01)
    incr_mid    = QtCore.pyqtProperty(float, get_incr_mid,    set_incr_mid,    reset_incr_mid)

    def get_incr_coarse(self):     return self._incr_base[2]
    def set_incr_coarse(self, v):  self._set_incr(2, v)
    def reset_incr_coarse(self):   self._set_incr(2, 0.1)
    incr_coarse = QtCore.pyqtProperty(float, get_incr_coarse, set_incr_coarse, reset_incr_coarse)


# ── standalone preview ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    w = JogIncrements()
    w.setWindowTitle("JogIncrements – preview")
    w.resize(140, 300)
    w.show()
    sys.exit(app.exec_())
