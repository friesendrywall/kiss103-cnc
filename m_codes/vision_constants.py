"""
vision_constants.py
-------------------
Shared configuration for LinuxCNC M110 fiducial vision system.
Edit the USER CONFIGURATION section below to match your setup.
Calibration values are written automatically by M110_calibrate.py.

Location: place this file in the same directory as M110.py and M110_calibrate.py
          (typically ~/linuxcnc/ncfiles/ or the directory set in [RS274NGC] USER_M_PATH)
"""

# ---------------------------------------------------------------------------
# USER CONFIGURATION — edit these to match your hardware
# ---------------------------------------------------------------------------

# Video device port
VIDEO_PORT = "/dev/video0"
CAMERA_BACKEND = 200

# Camera capture resolution (pixels). Must match your camera's actual output.
# Common values: (640, 480), (1280, 720), (1920, 1080)
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480

# Number of frames to grab before sampling (allows camera to auto-adjust)
CAMERA_WARMUP_FRAMES = 5

# Camera offset from spindle/WCS center (inches).
# Since the camera is centered on the tool, both are 0.0.
# Update these if you ever add a separate camera mount with a known offset.
CAM_OFFSET_X = 0.0   # positive = camera is to the RIGHT of spindle
CAM_OFFSET_Y = 0.0   # positive = camera is ABOVE spindle (in machine Y)

# ---------------------------------------------------------------------------
# DETECTION TUNING — adjust if detection is unreliable
# ---------------------------------------------------------------------------

# Gaussian blur kernel size (must be odd). Higher = smoother, less noise sensitive.
BLUR_KERNEL_SIZE = 5

# Canny edge thresholds. Lower threshold1 = catches more edges (may add noise).
CANNY_THRESH1 = 50
CANNY_THRESH2 = 150

# HoughCircles parameters
# dp: inverse ratio of accumulator resolution to image resolution (1 = same)
HOUGH_DP = 1.2
# minDist: minimum distance between detected circle centers (pixels).
#          Prevents multiple detections of the same fiducial.
HOUGH_MIN_DIST = 30
# param1: upper Canny threshold passed to HoughCircles
HOUGH_PARAM1 = 60
# param2: accumulator threshold — LOWER = more circles detected (more false positives)
#         HIGHER = fewer, more confident circles only
HOUGH_PARAM2 = 35

# Tolerance: how closely a detected circle's radius must match the expected
# radius (derived from P parameter) to be accepted, as a fraction (0.0–1.0).
# 0.30 means ±30% of the expected radius is acceptable.
RADIUS_MATCH_TOLERANCE = 0.30

# ---------------------------------------------------------------------------
# CALIBRATION VALUES — written by M110_calibrate.py, do not edit manually
# ---------------------------------------------------------------------------

# Pixels per inch — computed during calibration.
# Until calibration is run, a rough default is used (not reliable for production).
PIXELS_PER_INCH = 960.0

# Diameter of the calibration object used (inches), recorded at calibration time.
CALIBRATION_OBJECT_DIAMETER_IN = 0.05

# Detected radius of the calibration object (pixels), recorded at calibration time.
CALIBRATION_DETECTED_RADIUS_PX = 24.0

# ISO 8601 timestamp of last calibration run.
CALIBRATION_TIMESTAMP = "2026-04-14T14:51:31"

# ---------------------------------------------------------------------------
# SQUARE FIDUCIAL DETECTION — used by M510 S parameter
# ---------------------------------------------------------------------------

# Gaussian blur kernel size for square detection pre-processing (must be odd).
SQUARE_BLUR_KERNEL_SIZE = 5

# Offset added to the Otsu-computed threshold (0 = pure Otsu).
# Increase to make thresholding stricter (fewer false-positive contours).
SQUARE_OTSU_OFFSET = 0

# Acceptable bounding-rect width/height aspect ratio range for a square.
# 1.0 is a perfect square; allow some tolerance for PCB manufacturing variation.
SQUARE_MIN_ASPECT = 0.80
SQUARE_MAX_ASPECT = 1.20
