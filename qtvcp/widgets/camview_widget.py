#!/usr/bin/env python3
# Qtvcp camview
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
    LOG.error('Qtvcp Error with camview - is python3-opencv installed?')
    LIB_GOOD = False
    DEFAULT_API = 0

import numpy as np


class CamView(QtWidgets.QWidget, _HalWidgetBase):
    def __init__(self, parent=None):
        super(CamView, self).__init__(parent)
        self._qImageFormat = QImage.Format_RGB888
        self.video = None
        self.grabbed = None
        self.frame = None
        self._camNum = 0
        self.diameter = 20
        self.scale = 1
        self.scaleX = 1.0
        self.scaleY = 1.0
        self._aspectRatioW = 1
        self._aspectRatioH = 1
        # Crosshair and circle visibility
        self._showCrosshair = True
        self._showCircle = True
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

        # trap so can run script directly to test
        try:
            if INFO.PROGRAM_PREFIX is not None:
                self.user_path = os.path.expanduser(INFO.PROGRAM_PREFIX)
        except:
            self.user_path = (os.path.join(os.path.expanduser('~'), 'linuxcnc/nc_files'))

    def _hal_init(self):
        if LIB_GOOD:
            STATUS.connect('periodic', self.nextFrameSlot)

    ##################################
    # no button scroll = circle diameter
    # left button scroll = zoom
    ##################################
    def wheelEvent(self, event):
        super(CamView, self).wheelEvent(event)
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

        # make a Q image
        self.pix = self.makeImage(frame, self._qImageFormat)

        # repaint the window
        self.update()

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

    def showEvent(self, event):
        if LIB_GOOD:
            try:
                self.video = WebcamVideoStream(src=self._camNum)
                if not self.video.isOpened():
                    p = self.video.list_ports()[1]
                    self.text = 'Error with video {}\nAvailable ports:\n{}'.format(self._camNum, p)
                else:
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
        qp.end()

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
        gp.translate(w, h)
        gp.setPen(pen0)
        gp.drawLine(0, 0 - self._crossGap, 0, -h)
        gp.setPen(pen)
        gp.drawLine(-w, 0, 0 - self._crossGap, 0)
        gp.drawLine(0 + self._crossGap, 0, w, 0)
        gp.drawLine(0, 0 + self._crossGap, 0, h)

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

    # designer will show these properties in this order:
    camera_number       = QtCore.pyqtProperty(int,  get_camnum,           set_camnum,           reset_camnum)
    aspect_ratio_width  = QtCore.pyqtProperty(int,  get_aspect_w,         set_aspect_w,         reset_aspect_w)
    aspect_ratio_height = QtCore.pyqtProperty(int,  get_aspect_h,         set_aspect_h,         reset_aspect_h)
    show_crosshair      = QtCore.pyqtProperty(bool, get_show_crosshair,   set_show_crosshair,   reset_show_crosshair)
    show_circle         = QtCore.pyqtProperty(bool, get_show_circle,      set_show_circle,      reset_show_circle)
    cross_gap           = QtCore.pyqtProperty(int,  get_cross_gap,        set_cross_gap,        reset_cross_gap)
    cross_line_width    = QtCore.pyqtProperty(int,  get_cross_line_width, set_cross_line_width, reset_cross_line_width)


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
        print('saved camview image to: {}'.format(filepath))

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


class CamAngle(CamView):
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