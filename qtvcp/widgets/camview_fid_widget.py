#!/usr/bin/env python3
# Qtvcp camfidview
#
# Copyright (c) 2017  Chris Morley <chrisinnanaimo@hotmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# use open cv to do camera alignment

import os
import time
import _thread as Thread

import hal

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QImage

from qtvcp.widgets.widget_baseclass import _HalWidgetBase
from qtvcp import logger

if __name__ != '__main__':  # This avoids segfault when testing directly in python
    from qtvcp.core import Status, Info
    STATUS = Status()
    INFO = Info()
LOG = logger.getLogger(__name__)

# Suppress cryptic messages when checking for useable ports
os.environ["OPENCV_LOG_LEVEL"]="FATAL"

# If the library is missing don't crash the GUI
# send an error and just make a blank widget.
LIB_GOOD = True
try:
    import cv2 as CV
    DEFAULT_API = CV.CAP_ANY
except:
    LOG.error('Qtvcp Error with camfidview - is python3-opencv installed?')
    LIB_GOOD = False
    DEFAULT_API = 0

import numpy as np

# Fiducial state machine states
_FID_IDLE      = 'idle'
_FID_SEARCHING = 'searching'
_FID_FOUND     = 'found'
_FID_ERROR     = 'error'

_FID_TIMEOUT   = 1.0   # seconds before search gives up


class CamFidView(QtWidgets.QWidget, _HalWidgetBase):
    def __init__(self, parent=None):
        super(CamFidView, self).__init__(parent)
        self._qImageFormat = QImage.Format_RGB888
        self.video = None
        self.grabbed = None
        self.frame = None
        self._camNum = 0
        self._captureW = 640
        self._captureH = 480
        self.diameter = 20
        self.scale = 1
        self.scaleX = 1.0
        self.scaleY = 1.0
        self._aspectRatioW = 1
        self._aspectRatioH = 1
        # Crosshair and circle visibility
        self._showCrosshair = True
        self._showCircle = True
        # Mirror/flip
        self._mirrorH = False
        self._mirrorV = False
        # Crosshair appearance
        self._crossGap = 5
        self._crossLineWidth = 1
        self.setWindowTitle('Cam View')
        self.setGeometry(100, 100, 200, 200)
        self.text_color = QColor(255, 255, 255)
        self.circle_color = QtCore.Qt.red
        self.cross_color = QtCore.Qt.yellow
        self.cross_pointer_color = QtCore.Qt.white
        self.font = QFont("arial,helvetica", 40)
        if LIB_GOOD:
            self.text = 'No Image'
        else:
            self.text = 'Missing\npython-opencv\nLibrary'
        self.pix = None
        self.stopped = False

        # Fiducial detection state
        self._fid_state      = _FID_IDLE
        self._fid_read_prev  = False
        self._fid_search_t0  = 0.0
        self._fid_found_pos  = None   # (x, y, r) in zoomed-frame pixels when found
        self._frame_shape    = None   # (h, w) of last zoomed frame

        # trap so can run script directly to test
        try:
            if INFO.PROGRAM_PREFIX is not None:
                self.user_path = os.path.expanduser(INFO.PROGRAM_PREFIX)
        except:
            self.user_path = (os.path.join(os.path.expanduser('~'), 'linuxcnc/nc_files'))

    def _hal_init(self):
        if LIB_GOOD:
            STATUS.connect('periodic', self.nextFrameSlot)

        n = self.HAL_NAME_
        # --- Fiducial input pins ---
        self.hal_pin_fid_show     = self.HAL_GCOMP_.newpin(n + '.fid_show',     hal.HAL_BIT,   hal.HAL_IN)
        self.hal_pin_fid_read     = self.HAL_GCOMP_.newpin(n + '.fid_read',     hal.HAL_BIT,   hal.HAL_IN)
        self.hal_pin_fid_size     = self.HAL_GCOMP_.newpin(n + '.fid_size',     hal.HAL_FLOAT, hal.HAL_IN)
        self.hal_pin_fid_square   = self.HAL_GCOMP_.newpin(n + '.fid_square',    hal.HAL_BIT, hal.HAL_IN)
        self.hal_pin_fid_search     = self.HAL_GCOMP_.newpin(n + '.fid_search',     hal.HAL_FLOAT, hal.HAL_IN)
        self.hal_pin_fid_tol        = self.HAL_GCOMP_.newpin(n + '.fid_tol',        hal.HAL_FLOAT, hal.HAL_IN)
        self.hal_pin_pix_per_inch   = self.HAL_GCOMP_.newpin(n + '.pix_per_inch',   hal.HAL_FLOAT, hal.HAL_IN)
        self.hal_pin_pix_per_inch_y = self.HAL_GCOMP_.newpin(n + '.pix_per_inch_y', hal.HAL_FLOAT, hal.HAL_IN)

        # --- Fiducial output pins ---
        self.hal_pin_fid_found    = self.HAL_GCOMP_.newpin(n + '.fid_found',    hal.HAL_BIT,   hal.HAL_OUT)
        self.hal_pin_fid_error    = self.HAL_GCOMP_.newpin(n + '.fid_error',    hal.HAL_BIT,   hal.HAL_OUT)
        self.hal_pin_search_done  = self.HAL_GCOMP_.newpin(n + '.search_done',  hal.HAL_BIT,   hal.HAL_OUT)
        self.hal_pin_offset_x     = self.HAL_GCOMP_.newpin(n + '.offset_x',     hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal_pin_offset_y     = self.HAL_GCOMP_.newpin(n + '.offset_y',     hal.HAL_FLOAT, hal.HAL_OUT)

    ##################################
    # no button scroll = circle diameter
    # left button scroll = zoom
    ##################################
    def wheelEvent(self, event):
        super(CamFidView, self).wheelEvent(event)
        mouse_state = QtWidgets.qApp.mouseButtons()
        if event.angleDelta().y() < 0:
            if mouse_state == QtCore.Qt.NoButton:
                self.diameter -= 2
            if mouse_state == QtCore.Qt.LeftButton:
                self.scale -= .1
        else:
            if mouse_state == QtCore.Qt.NoButton:
                self.diameter += 2
            if mouse_state == QtCore.Qt.LeftButton:
                self.scale += .1
        self.limitChecks()

    def mouseDoubleClickEvent(self, event):
        if event.button() & QtCore.Qt.LeftButton:
            self.scale = 1
        elif event.button() & QtCore.Qt.MiddleButton:
            self.diameter = 20

    def zoom_in(self):
        if self.scale >= 5:
            return
        self.scale += 0.1

    def zoom_out(self, event):
        if self.scale <= 1:
            return
        self.scale -= 0.1

    def limitChecks(self):
        w = self.size().width()
        if self.diameter < 2: self.diameter = 2
        if self.diameter > w: self.diameter = w
        if self.scale < 1: self.scale = 1
        if self.scale > 5: self.scale = 5

    def nextFrameSlot(self, w):
        if not self.video: return
        if not self.isVisible(): return

        ret, frame = self.video.read()
        if not ret: return

        # set digital zoom
        frame = self.zoom(frame, self.scale)

        # apply mirror/flip
        if self._mirrorH and self._mirrorV:
            frame = CV.flip(frame, -1)
        elif self._mirrorH:
            frame = CV.flip(frame, 1)
        elif self._mirrorV:
            frame = CV.flip(frame, 0)

        # record frame dimensions for overlay mapping
        self._frame_shape = frame.shape[:2]   # (h, w)

        # --- Fiducial state machine ---
        if hasattr(self, 'hal_pin_fid_read'):
            self._update_fid_state(frame)

        # make a Q image
        self.pix = self.makeImage(frame, self._qImageFormat)

        # repaint the window
        self.update()

    # ------------------------------------------------------------------ #
    #  Fiducial detection state machine                                    #
    # ------------------------------------------------------------------ #

    def _update_fid_state(self, frame):
        fid_read = self.hal_pin_fid_read.get()

        if fid_read and not self._fid_read_prev:
            # Rising edge → start search
            self._fid_state     = _FID_SEARCHING
            self._fid_search_t0 = time.time()
            self._fid_found_pos = None

        elif not fid_read and self._fid_state != _FID_IDLE:
            # fid_read cleared → reset everything
            self._fid_state     = _FID_IDLE
            self._fid_found_pos = None
            self.hal_pin_fid_found.set(False)
            self.hal_pin_fid_error.set(False)
            self.hal_pin_search_done.set(False)
            self.hal_pin_offset_x.set(0.0)
            self.hal_pin_offset_y.set(0.0)

        self._fid_read_prev = fid_read

        if self._fid_state == _FID_SEARCHING:
            found, fx, fy, fr = self._detect_fiducial(frame)
            if found:
                self._fid_state     = _FID_FOUND
                self._fid_found_pos = (fx, fy, fr)
                fh, fw = frame.shape[:2]
                ppi_x = self.hal_pin_pix_per_inch.get()
                ppi_y = self._ppi_y()
                if ppi_x > 0:
                    self.hal_pin_offset_x.set( (fx - fw / 2.0) / ppi_x)
                if ppi_y > 0:
                    self.hal_pin_offset_y.set(-(fy - fh / 2.0) / ppi_y)
                self.hal_pin_fid_found.set(True)
                self.hal_pin_fid_error.set(False)
                self.hal_pin_search_done.set(True)
            elif time.time() - self._fid_search_t0 > _FID_TIMEOUT:
                self._fid_state     = _FID_ERROR
                self._fid_found_pos = None
                self.hal_pin_fid_found.set(False)
                self.hal_pin_fid_error.set(True)
                self.hal_pin_search_done.set(True)

    # ------------------------------------------------------------------ #
    #  Detection helpers                                                   #
    # ------------------------------------------------------------------ #

    def _ppi_y(self):
        """Return effective Y pixels-per-inch; falls back to X value when pin is 0."""
        v = self.hal_pin_pix_per_inch_y.get()
        return v if v > 0 else self.hal_pin_pix_per_inch.get()

    def _detect_fiducial(self, frame):
        """Return (found, x, y, r) in frame pixels, all ints."""
        ppi_x      = self.hal_pin_pix_per_inch.get()
        ppi_y      = self._ppi_y()
        fid_size   = self.hal_pin_fid_size.get()
        fid_search = self.hal_pin_fid_search.get()
        fid_square  = self.hal_pin_fid_square.get()
        fid_tol    = max(0.0, self.hal_pin_fid_tol.get()) / 100.0  # % → fraction

        if ppi_x <= 0 or fid_size <= 0 or fid_search <= 0:
            return False, 0, 0, 0

        # Search ROI: square in physical space, possibly rectangular in frame pixels
        fid_size_px  = fid_size  * ppi_x          # use X ppi for circle/square radius
        half_x = int(fid_search * ppi_x / 2)
        half_y = int(fid_search * ppi_y / 2)

        fh, fw = frame.shape[:2]
        fcx, fcy = fw // 2, fh // 2

        x1 = max(0, fcx - half_x)
        y1 = max(0, fcy - half_y)
        x2 = min(fw, fcx + half_x)
        y2 = min(fh, fcy + half_y)

        if x2 <= x1 or y2 <= y1:
            return False, 0, 0, 0

        roi = frame[y1:y2, x1:x2]

        if fid_square == 0:
            return self._detect_circle(roi, fid_size_px, fid_tol, x1, y1)
        else:
            return self._detect_square(roi, fid_size_px, fid_tol, x1, y1)

    def _detect_circle(self, roi, fid_size_px, tol, x1, y1):
        gray = CV.cvtColor(roi, CV.COLOR_BGR2GRAY)
        gray = CV.GaussianBlur(gray, (5, 5), 0)

        r     = fid_size_px / 2.0
        # Use tolerance for HoughCircles radius band; fall back to ±30% if tol is 0
        band  = tol if tol > 0 else 0.30
        min_r = max(1, int(r * (1.0 - band)))
        max_r = max(2, int(r * (1.0 + band)))

        circles = CV.HoughCircles(gray, CV.HOUGH_GRADIENT, dp=1,
                                   minDist=int(max(1, r * 1.5)),
                                   param1=100, param2=30,
                                   minRadius=min_r, maxRadius=max_r)
        if circles is None:
            return False, 0, 0, 0

        roi_cx = roi.shape[1] / 2.0
        roi_cy = roi.shape[0] / 2.0
        best = min(circles[0],
                   key=lambda c: (c[0] - roi_cx) ** 2 + (c[1] - roi_cy) ** 2)

        # Reject if found radius is outside tolerance band
        found_r = best[2]
        if abs(found_r - r) > r * band:
            return False, 0, 0, 0

        # Refine center: HoughCircles accumulator can fit a larger circle tangent to the
        # actual circle, shifting the center by (r_found - r_actual).  Re-derive the
        # center as the mean of Canny edge points, which is unaffected by that bias.
        cx_b, cy_b = int(best[0]), int(best[1])
        margin = int(found_r * 0.3) + 2
        sx = max(0, cx_b - int(found_r) - margin)
        sy = max(0, cy_b - int(found_r) - margin)
        ex = min(roi.shape[1], cx_b + int(found_r) + margin)
        ey = min(roi.shape[0], cy_b + int(found_r) + margin)
        sub = gray[sy:ey, sx:ex]
        edges = CV.Canny(sub, 50, 150)
        contours, _ = CV.findContours(edges, CV.RETR_EXTERNAL, CV.CHAIN_APPROX_NONE)
        if contours:
            expected_perim = 2.0 * np.pi * r
            best_cnt = min(contours,
                           key=lambda c: abs(CV.arcLength(c, True) - expected_perim))
            pts = best_cnt[:, 0, :]
            ref_cx = float(pts[:, 0].mean()) + sx
            ref_cy = float(pts[:, 1].mean()) + sy
            if (ref_cx - cx_b) ** 2 + (ref_cy - cy_b) ** 2 <= found_r ** 2:
                return True, int(x1 + ref_cx), int(y1 + ref_cy), int(found_r)

        return True, int(x1 + cx_b), int(y1 + cy_b), int(found_r)

    def _detect_square(self, roi, fid_size_px, tol, x1, y1):
        gray    = CV.cvtColor(roi, CV.COLOR_BGR2GRAY)
        blurred = CV.GaussianBlur(gray, (5, 5), 0)
        _, thresh = CV.threshold(blurred, 0, 255,
                                  CV.THRESH_BINARY + CV.THRESH_OTSU)
        contours, _ = CV.findContours(thresh, CV.RETR_LIST,
                                       CV.CHAIN_APPROX_SIMPLE)

        roi_cx      = roi.shape[1] / 2.0
        roi_cy      = roi.shape[0] / 2.0
        area_target = fid_size_px ** 2
        band        = tol if tol > 0 else 0.30
        best        = None
        best_dist   = float('inf')

        for cnt in contours:
            area = CV.contourArea(cnt)
            if area < area_target * (1.0 - band) ** 2:
                continue
            if area > area_target * (1.0 + band) ** 2:
                continue
            peri  = CV.arcLength(cnt, True)
            approx = CV.approxPolyDP(cnt, 0.04 * peri, True)
            if len(approx) != 4:
                continue
            bx, by, bw, bh = CV.boundingRect(cnt)
            if max(bw, bh) / max(1, min(bw, bh)) > 1.3:
                continue
            cx_cnt = bx + bw / 2.0
            cy_cnt = by + bh / 2.0
            d = (cx_cnt - roi_cx) ** 2 + (cy_cnt - roi_cy) ** 2
            if d < best_dist:
                best_dist = d
                # r = half the average side length
                best = (int(x1 + cx_cnt), int(y1 + cy_cnt), int((bw + bh) / 4))

        if best:
            return True, best[0], best[1], best[2]
        return False, 0, 0, 0

    # ------------------------------------------------------------------ #
    #  Image helpers                                                        #
    # ------------------------------------------------------------------ #

    def convertToRGB(self, img):
        return CV.cvtColor(img, CV.COLOR_BGR2RGB)

    def convertToGray(self, img):
        return CV.cvtColor(img, CV.COLOR_BGR2GRAY)

    def blur(self, img, B=7):
        return CV.GaussianBlur(img, (B, B), CV.BORDER_DEFAULT)

    def canny(self, img, x=125, y=175):
        return CV.Canny(img, x, y)

    def makeImage(self, image, qFormat=QImage.Format_RGB888):
        img = self.convertToRGB(image)
        return QImage(img, img.shape[1], img.shape[0], img.strides[0], qFormat)

    def makeCVImage(self, frame):
        CV.imshow('CV Image', frame)

    def rescaleFrame(self, frame, scale=1, scale_x=1.0, scale_y=1.0):
        x = scale_x * scale
        y = scale_y * scale
        return CV.resize(frame, None, fx=x, fy=y, interpolation=CV.INTER_CUBIC)

    def zoom(self, frame, scale):
        (oh, ow) = frame.shape[:2]
        frame = self.rescaleFrame(frame, scale, self.scaleX, self.scaleY)
        (h, w) = frame.shape[:2]
        ch = int(h / 2)
        cw = int(w / 2)
        coh = int(oh / 2)
        cow = int(ow / 2)
        return frame[ch-coh:ch+coh, cw-cow:cw+cow]

    def findCircles(self, frame):
        gray = CV.cvtColor(frame, CV.COLOR_BGR2GRAY)
        circles = CV.HoughCircles(gray, CV.cv.CV_HOUGH_GRADIENT, 1, 20, param1=50, param2=30, minRadius=10, maxRadius=15)
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for i in circles[0, :]:
                CV.circle(gray, (i[0], i[1]), i[2], (246, 11, 11), 1)
                CV.circle(gray, (i[0], i[1]), 2, (246, 11, 11), 1)
        CV.imshow('Circles', gray)

    def blobInit(self):
        detector = CV.SimpleBlobDetector()
        params = CV.SimpleBlobDetector_Params()
        params.filterByArea = True
        params.minArea = 20000
        params.maxArea = 40000
        params.filterByCircularity = True
        params.minCircularity = 0.5
        params.filterByConvexity = False
        params.filterByInertia = True
        params.minInertiaRatio = 0.8
        params.minDistBetweenBlobs = 200
        self.detector = CV.SimpleBlobDetector(params)

    def findBlob(self, image):
        overlay = image.copy()
        keypoints = self.detector.detect(image)
        for k in keypoints:
            CV.circle(overlay, (int(k.pt[0]), int(k.pt[1])), int(k.size / 2), (0, 0, 255), -1)
            CV.line(overlay, (int(k.pt[0])-20, int(k.pt[1])), (int(k.pt[0])+20, int(k.pt[1])), (0, 0, 0), 3)
            CV.line(overlay, (int(k.pt[0]), int(k.pt[1])-20), (int(k.pt[0]), int(k.pt[1])+20), (0, 0, 0), 3)
        opacity = 0.5
        CV.addWeighted(overlay, opacity, image, 1 - opacity, 0, image)
        CV.imshow("Output", image)

    # ------------------------------------------------------------------ #
    #  Qt events                                                            #
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        if LIB_GOOD:
            try:
                self.video = WebcamVideoStream(src=self._camNum)
                if not self.video.isOpened():
                    p = self.video.list_ports()[1]
                    self.text = 'Error with video {}\nAvailable ports:\n{}'.format(self._camNum, p)
                else:
                    if self._captureW > 0:
                        self.video.stream.set(CV.CAP_PROP_FRAME_WIDTH,  self._captureW)
                    if self._captureH > 0:
                        self.video.stream.set(CV.CAP_PROP_FRAME_HEIGHT, self._captureH)
                    self.video.start()
            except Exception as e:
                LOG.error('Video capture error: {}'.format(e))

    def hideEvent(self, event):
        if LIB_GOOD:
            try:
                self.video.stop()
            except:
                pass

    def resizeEvent(self, event):
        # Scale to the new size maintaining the configured aspect ratio.
        new_size = QtCore.QSize(self._aspectRatioW, self._aspectRatioH)
        new_size.scale(event.size(), QtCore.Qt.KeepAspectRatio)
        self.resize(new_size)

    def paintEvent(self, event):
        qp = QPainter()
        qp.begin(self)
        if self.pix:
            qp.drawImage(self.rect(), self.pix)
        self.drawText(event, qp)
        if self._showCircle:
            self.drawCircle(event, qp)
        if self._showCrosshair:
            self.drawCrossHair(event, qp)
        self.drawFidOverlay(qp)
        qp.end()

    # ------------------------------------------------------------------ #
    #  Drawing helpers                                                      #
    # ------------------------------------------------------------------ #

    def drawText(self, event, qp):
        qp.setPen(self.text_color)
        qp.setFont(self.font)
        if not self.pix:
            qp.drawText(self.rect(), QtCore.Qt.AlignCenter, self.text)

    def drawCircle(self, event, gp):
        size = self.size()
        w = size.width()
        h = size.height()
        radx = self.diameter / 2
        rady = self.diameter / 2
        gp.setPen(self.circle_color)
        center = QtCore.QPoint(w // 2, h // 2)
        gp.drawEllipse(center, radx, rady)

    def drawCrossHair(self, event, gp):
        size = self.size()
        w = size.width() // 2
        h = size.height() // 2
        pen0 = QPen(self.cross_pointer_color, self._crossLineWidth, QtCore.Qt.SolidLine)
        pen  = QPen(self.cross_color,         self._crossLineWidth, QtCore.Qt.SolidLine)
        gp.save()
        gp.translate(w, h)
        gp.setPen(pen0)
        gp.drawLine(0, 0 - self._crossGap, 0, -h)
        gp.setPen(pen)
        gp.drawLine(-w, 0, 0 - self._crossGap, 0)
        gp.drawLine(0 + self._crossGap, 0, w, 0)
        gp.drawLine(0, 0 + self._crossGap, 0, h)
        gp.restore()

    def _compute_image_rect(self):
        """Return the QRect within the widget where the frame is drawn,
        maintaining the frame's native aspect ratio (letterboxed if needed)."""
        ww, wh = self.width(), self.height()
        if self._frame_shape is None:
            return QtCore.QRect(0, 0, ww, wh)
        fh, fw = self._frame_shape
        if fh == 0 or fw == 0:
            return QtCore.QRect(0, 0, ww, wh)
        if ww * fh <= wh * fw:
            # width-constrained
            dw = ww
            dh = int(ww * fh / fw)
        else:
            # height-constrained
            dh = wh
            dw = int(wh * fw / fh)
        x = (ww - dw) // 2
        y = (wh - dh) // 2
        return QtCore.QRect(x, y, dw, dh)

    def drawFidOverlay(self, qp):
        """Draw fiducial overlays: search area, ghost/result fiducial."""
        # Guard: pins not yet created (called before _hal_init)
        if not hasattr(self, 'hal_pin_fid_show'):
            return
        if self._frame_shape is None:
            return

        fid_show  = self.hal_pin_fid_show.get()
        fid_read  = self.hal_pin_fid_read.get()

        if not fid_show and not fid_read:
            return

        ppi_x      = self.hal_pin_pix_per_inch.get()
        ppi_y      = self._ppi_y()
        fid_size   = self.hal_pin_fid_size.get()
        fid_search = self.hal_pin_fid_search.get()
        fid_square  = self.hal_pin_fid_square.get()

        if ppi_x <= 0 or ppi_y <= 0:
            return

        fh, fw = self._frame_shape
        ir = self._compute_image_rect()
        iw, ih = ir.width(), ir.height()
        ir_x, ir_y = float(ir.x()), float(ir.y())
        if fh == 0 or fw == 0 or iw == 0 or ih == 0:
            return

        # Frame pixel → image-rect pixel scale (guaranteed sx==sy when
        # frame and widget share the same aspect ratio).
        sx = iw / float(fw)
        sy = ih / float(fh)
        # Image-rect centre in widget coordinates
        wcx = ir_x + iw / 2.0
        wcy = ir_y + ih / 2.0

        qp.setBrush(QtCore.Qt.NoBrush)

        # --- Search area rectangle (green) ---
        if fid_search > 0:
            half_wx = fid_search * ppi_x * sx / 2.0
            half_wy = fid_search * ppi_y * sy / 2.0
            qp.setPen(QPen(QtCore.Qt.green, 2, QtCore.Qt.SolidLine))
            qp.drawRect(int(wcx - half_wx), int(wcy - half_wy),
                        int(half_wx * 2),   int(half_wy * 2))

        # --- Fiducial shape indicator ---
        if fid_size <= 0:
            return

        r_wx = fid_size * ppi_x * sx / 2.0   # expected half-size in image-rect pixels X
        r_wy = fid_size * ppi_y * sy / 2.0   # expected half-size in image-rect pixels Y

        if fid_read and self._fid_state == _FID_FOUND and self._fid_found_pos is not None:
            # Yellow outline at actual detected position/size
            fx, fy, fr = self._fid_found_pos
            wx = ir_x + fx * sx
            wy = ir_y + fy * sy
            wr = fr * sx
            qp.setPen(QPen(QtCore.Qt.yellow, 2, QtCore.Qt.SolidLine))
            if fid_square == 0:
                qp.drawEllipse(QtCore.QPointF(wx, wy), wr, wr)
            else:
                qp.drawRect(int(wx - wr), int(wy - wr), int(wr * 2), int(wr * 2))

            # Cross at detected centre — arms = half the detected radius, with small gap
            arm  = max(2.0, wr / 2.0)
            gap  = max(1.0, wr / 8.0)
            qp.setPen(QPen(QtCore.Qt.yellow, 1, QtCore.Qt.SolidLine))
            qp.drawLine(QtCore.QPointF(wx - arm, wy), QtCore.QPointF(wx - gap, wy))
            qp.drawLine(QtCore.QPointF(wx + gap, wy), QtCore.QPointF(wx + arm, wy))
            qp.drawLine(QtCore.QPointF(wx, wy - arm), QtCore.QPointF(wx, wy - gap))
            qp.drawLine(QtCore.QPointF(wx, wy + gap), QtCore.QPointF(wx, wy + arm))

        elif fid_read:
            # Red: actively searching or timed-out error — show expected size at centre
            qp.setPen(QPen(QtCore.Qt.red, 2, QtCore.Qt.SolidLine))
            if fid_square == 0:
                qp.drawEllipse(QtCore.QPointF(wcx, wcy), r_wx, r_wy)
            else:
                qp.drawRect(int(wcx - r_wx), int(wcy - r_wy),
                            int(r_wx * 2),   int(r_wy * 2))

        else:
            # fid_show only (no active read): white dashed ghost at centre
            qp.setPen(QPen(QtCore.Qt.white, 1, QtCore.Qt.DashLine))
            if fid_square == 0:
                qp.drawEllipse(QtCore.QPointF(wcx, wcy), r_wx, r_wy)
            else:
                qp.drawRect(int(wcx - r_wx), int(wcy - r_wy),
                            int(r_wx * 2),   int(r_wy * 2))

        # --- Offset / size readout (lower-left, green) when found ---
        if fid_read and self._fid_state == _FID_FOUND and self._fid_found_pos is not None:
            off_x = self.hal_pin_offset_x.get()
            off_y = self.hal_pin_offset_y.get()
            _, _, fr = self._fid_found_pos
            dia_in  = (fr * 2) / ppi_x if ppi_x > 0 else 0.0
            line1 = 'X: {:+.4f}"'.format(off_x)
            line2 = 'Y: {:+.4f}"'.format(off_y)
            line3 = 'D: {:.4f}"'.format(dia_in)
            font = QFont('monospace', 10)
            font.setBold(True)
            qp.setFont(font)
            fm     = qp.fontMetrics()
            lh     = fm.height()
            margin = 6
            # Draw lines bottom-up: D, Y, X
            for i, txt in enumerate((line3, line2, line1)):
                y = int(ir_y + ih) - margin - i * lh
                x = int(ir_x) + margin
                qp.setPen(QtCore.Qt.black)
                qp.drawText(x + 1, y + 1, txt)   # shadow for readability
                qp.setPen(QtCore.Qt.green)
                qp.drawText(x, y, txt)

    # ------------------------------------------------------------------ #
    #  Public helpers                                                       #
    # ------------------------------------------------------------------ #

    def setCircleColor(self, color):
        self.circle_color = color

    def setCrossColor(self, color):
        self.cross_color = color

    def setPointerColor(self, color):
        self.cross_pointer_color = color

    def saveImage(self):
        filepath = '{}/camImage.png'.format(self.user_path)
        self.video.writeFrame(filepath)

    #########################################################################
    # This is how designer can interact with our widget properties.
    # designer will show the pyqtProperty properties in the editor
    # it will use the get set and reset calls to do those actions
    #
    # These can also be set as  WIDGET.setProperty('property_name', data)
    ########################################################################

    def set_camnum(self, value):
        self._camNum = value
    def get_camnum(self):
        return self._camNum
    def reset_camnum(self):
        self._camNum = 0

    def set_capture_w(self, value):
        self._captureW = max(0, value)
    def get_capture_w(self):
        return self._captureW
    def reset_capture_w(self):
        self._captureW = 640

    def set_capture_h(self, value):
        self._captureH = max(0, value)
    def get_capture_h(self):
        return self._captureH
    def reset_capture_h(self):
        self._captureH = 480

    def set_aspect_w(self, value):
        self._aspectRatioW = max(1, value)
        self.updateGeometry()
    def get_aspect_w(self):
        return self._aspectRatioW
    def reset_aspect_w(self):
        self._aspectRatioW = 1

    def set_aspect_h(self, value):
        self._aspectRatioH = max(1, value)
        self.updateGeometry()
    def get_aspect_h(self):
        return self._aspectRatioH
    def reset_aspect_h(self):
        self._aspectRatioH = 1

    def set_show_crosshair(self, value):
        self._showCrosshair = value
        self.update()
    def get_show_crosshair(self):
        return self._showCrosshair
    def reset_show_crosshair(self):
        self._showCrosshair = True

    def set_show_circle(self, value):
        self._showCircle = value
        self.update()
    def get_show_circle(self):
        return self._showCircle
    def reset_show_circle(self):
        self._showCircle = True

    def set_cross_gap(self, value):
        self._crossGap = max(0, value)
        self.update()
    def get_cross_gap(self):
        return self._crossGap
    def reset_cross_gap(self):
        self._crossGap = 5

    def set_cross_line_width(self, value):
        self._crossLineWidth = max(1, value)
        self.update()
    def get_cross_line_width(self):
        return self._crossLineWidth
    def reset_cross_line_width(self):
        self._crossLineWidth = 1

    def set_mirror_h(self, value):
        self._mirrorH = value
        self.update()
    def get_mirror_h(self):
        return self._mirrorH
    def reset_mirror_h(self):
        self._mirrorH = False

    def set_mirror_v(self, value):
        self._mirrorV = value
        self.update()
    def get_mirror_v(self):
        return self._mirrorV
    def reset_mirror_v(self):
        self._mirrorV = False

    # designer will show these properties in this order:
    camera_number       = QtCore.pyqtProperty(int,  get_camnum,           set_camnum,           reset_camnum)
    capture_width       = QtCore.pyqtProperty(int,  get_capture_w,        set_capture_w,        reset_capture_w)
    capture_height      = QtCore.pyqtProperty(int,  get_capture_h,        set_capture_h,        reset_capture_h)
    aspect_ratio_width  = QtCore.pyqtProperty(int,  get_aspect_w,         set_aspect_w,         reset_aspect_w)
    aspect_ratio_height = QtCore.pyqtProperty(int,  get_aspect_h,         set_aspect_h,         reset_aspect_h)
    show_crosshair      = QtCore.pyqtProperty(bool, get_show_crosshair,   set_show_crosshair,   reset_show_crosshair)
    show_circle         = QtCore.pyqtProperty(bool, get_show_circle,      set_show_circle,      reset_show_circle)
    cross_gap           = QtCore.pyqtProperty(int,  get_cross_gap,        set_cross_gap,        reset_cross_gap)
    cross_line_width    = QtCore.pyqtProperty(int,  get_cross_line_width, set_cross_line_width, reset_cross_line_width)
    mirror_horizontal   = QtCore.pyqtProperty(bool, get_mirror_h,         set_mirror_h,         reset_mirror_h)
    mirror_vertical     = QtCore.pyqtProperty(bool, get_mirror_v,         set_mirror_v,         reset_mirror_v)


class WebcamVideoStream:
    def __init__(self, src=0, api=DEFAULT_API):
        self.stream = self.openStream(src, api)

        if not (self.stream.isOpened()):
            LOG.error('Could not open video device {}'.format(src))
            plist = self.list_ports()[1]
            if src not in plist:
                LOG.error('port number {}, is not a working port- trying: {}'.format(src, plist[0]))
            if plist != []:
                self.stream = self.openStream(plist[0], api)

        self.stopped = False
        self.grabbed = None
        self.frame = None

    def isOpened(self):
        try:
            return self.stream.isOpened()
        except:
            return False

    def openStream(self, src, api):
        try:
            stream = CV.VideoCapture(src, api)
        except:
            stream = CV.VideoCapture(src)
        return stream

    def start(self):
        Thread.start_new_thread(self._update, ())
        return self

    def _update(self):
        while True:
            if self.stopped:
                self.stream.release()
                return
            (self.grabbed, self.frame) = self.stream.read()

    def read(self):
        return (self.grabbed, self.frame)

    def stop(self):
        self.stopped = True

    def writeFrame(self, filepath):
        CV.imwrite(filepath, self.frame)
        print('saved camfidview image to: {}'.format(filepath))

    def list_ports(self):
        """
        Test the ports and returns a tuple with the available ports and the ones that are working.
        """
        non_working_ports = []
        dev_port = 0
        working_ports = []
        available_ports = []
        while len(non_working_ports) < 6:
            camera = CV.VideoCapture(dev_port)
            if not camera.isOpened():
                non_working_ports.append(dev_port)
                LOG.debug("Port %s is not working." % dev_port)
            else:
                is_reading, img = camera.read()
                w = camera.get(3)
                h = camera.get(4)
                if is_reading:
                    LOG.debug("Port %s is working and reads images (%s x %s)" % (dev_port, h, w))
                    working_ports.append(dev_port)
                else:
                    LOG.debug("Port %s for camera ( %s x %s) is present but does not read." % (dev_port, h, w))
                    available_ports.append(dev_port)
            dev_port += 1
        camera.release()
        return available_ports, working_ports, non_working_ports


class CamAngle(CamFidView):
    def __init__(self, parent=None):
        super(CamAngle, self).__init__(parent)

    def mouseDoubleClickEvent(self, event):
        if event.button() & QtCore.Qt.LeftButton:
            self.scale = 1
        elif event.button() & QtCore.Qt.MiddleButton:
            self.diameter = 40

    def wheelEvent(self, event):
        mouse_state = QtWidgets.qApp.mouseButtons()
        size = self.size()
        w = size.width()
        if event.angleDelta().y() < 0:
            if mouse_state == QtCore.Qt.NoButton:
                self.diameter -= 2
            if mouse_state == QtCore.Qt.LeftButton:
                self.scale -= .1
        else:
            if mouse_state == QtCore.Qt.NoButton:
                self.diameter += 2
            if mouse_state == QtCore.Qt.LeftButton:
                self.scale += .1
        if self.diameter < 2: self.diameter = 2
        if self.diameter > w: self.diameter = w
        if self.scale < 1: self.scale = 1
        if self.scale > 5: self.scale = 5


if __name__ == '__main__':

    import sys
    app = QtWidgets.QApplication(sys.argv)
    capture = CamAngle()
    capture.show()

    def jump():
        capture.nextFrameSlot(None)

    timer = QtCore.QTimer()
    timer.timeout.connect(jump)
    timer.start(10)
    sys.exit(app.exec_())
