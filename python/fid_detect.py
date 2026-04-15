"""
fid_detect.py — Shared fiducial detection functions
----------------------------------------------------
Used by m510_fid.py (M510 REMAP handler).

Two detection modes:
  detect_fiducial_circle() — HoughCircles on copper dot (same algorithm as M110.py)
  detect_fiducial_square() — Otsu threshold + contour bounding-rect for square pads

Both return a uniform result dict:
    {
        'found':        bool,
        'cx_px':        float,   # center X in pixels, from frame top-left
        'cy_px':        float,   # center Y in pixels
        'radius_px':    float,   # circle radius  OR  half-diagonal of square (pixels)
        'confidence':   float,   # 0.0–1.0
        'offset_x_in':  float,   # +right from frame center, in inches
        'offset_y_in':  float,   # +up from frame center, in machine Y direction
    }
"""

import math
import sys
import os

try:
    import cv2
    import numpy as np
except ImportError:
    raise ImportError("fid_detect requires opencv-python (cv2). Run: pip3 install opencv-python")

# ---------------------------------------------------------------------------
# Locate vision_constants relative to this file (or m_codes/)
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_MCODES = os.path.join(os.path.dirname(_HERE), 'm_codes')
for _p in (_HERE, _MCODES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import importlib
import vision_constants as VC
importlib.reload(VC)  # pick up any runtime edits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_result():
    return {
        'found': False,
        'cx_px': 0.0, 'cy_px': 0.0, 'radius_px': 0.0,
        'confidence': 0.0,
        'offset_x_in': 0.0, 'offset_y_in': 0.0,
    }


def _pixel_to_inch_offset(cx_px, cy_px, frame_w, frame_h, ppi):
    """Convert pixel center to machine-coordinate inch offset from frame center.

    Returns (dx_in, dy_in) where:
        dx_in  positive = fiducial is to the RIGHT of center
        dy_in  positive = fiducial is ABOVE center (machine Y up)
    """
    dx_px = cx_px - frame_w / 2.0
    dy_px = cy_px - frame_h / 2.0

    dx_in = dx_px / ppi + VC.CAM_OFFSET_X
    dy_in = -(dy_px / ppi) + VC.CAM_OFFSET_Y   # image Y is flipped vs machine Y

    return dx_in, dy_in


# ---------------------------------------------------------------------------
# Circle detection
# ---------------------------------------------------------------------------

def detect_fiducial_circle(frame, diameter_in, tolerance_pct):
    """Detect a solid circular fiducial using HoughCircles.

    Args:
        frame:         OpenCV BGR image (numpy array)
        diameter_in:   Expected fiducial diameter in inches
        tolerance_pct: Acceptable radius deviation as a percentage (e.g. 10 → ±10%)

    Returns:
        result dict (see module docstring)
    """
    result = _empty_result()
    importlib.reload(VC)  # refresh calibration values

    ppi = VC.PIXELS_PER_INCH
    if ppi is None or ppi <= 0:
        sys.stderr.write("fid_detect ERROR: PIXELS_PER_INCH not calibrated in vision_constants.py\n")
        return result

    h, w = frame.shape[:2]
    expected_r_px = (diameter_in / 2.0) * ppi
    tol_frac = tolerance_pct / 100.0
    min_r = max(3, int(expected_r_px * (1.0 - tol_frac)))
    max_r = max(min_r + 1, int(expected_r_px * (1.0 + tol_frac)))

    # Pre-process
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = VC.BLUR_KERNEL_SIZE if (VC.BLUR_KERNEL_SIZE % 2 == 1) else VC.BLUR_KERNEL_SIZE + 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=VC.HOUGH_DP,
        minDist=VC.HOUGH_MIN_DIST,
        param1=VC.HOUGH_PARAM1,
        param2=VC.HOUGH_PARAM2,
        minRadius=min_r,
        maxRadius=max_r,
    )

    if circles is None:
        sys.stderr.write("fid_detect: No circles found. Check lighting/focus or tune HOUGH_PARAM2.\n")
        return result

    circles = np.round(circles[0, :]).astype('int')

    # Pick best: minimise weighted sum of radius error + distance from frame center
    frame_cx, frame_cy = w / 2.0, h / 2.0
    best, best_score = None, float('inf')
    for (cx, cy, r) in circles:
        r_err = abs(r - expected_r_px)
        dist  = math.hypot(cx - frame_cx, cy - frame_cy)
        score = r_err + dist * 0.1
        if score < best_score:
            best_score = score
            best = (cx, cy, r)

    if best is None:
        return result

    cx_px, cy_px, r_px = best
    r_err_frac = abs(r_px - expected_r_px) / expected_r_px
    confidence = max(0.0, 1.0 - r_err_frac)

    dx_in, dy_in = _pixel_to_inch_offset(cx_px, cy_px, w, h, ppi)

    result.update({
        'found':       True,
        'cx_px':       float(cx_px),
        'cy_px':       float(cy_px),
        'radius_px':   float(r_px),
        'confidence':  confidence,
        'offset_x_in': dx_in,
        'offset_y_in': dy_in,
    })
    return result


# ---------------------------------------------------------------------------
# Square detection
# ---------------------------------------------------------------------------

def detect_fiducial_square(frame, size_in, tolerance_pct):
    """Detect a filled square copper fiducial using contour analysis.

    Args:
        frame:         OpenCV BGR image (numpy array)
        size_in:       Expected square side length in inches
        tolerance_pct: Acceptable area deviation as a percentage (e.g. 10 → ±10%)

    Returns:
        result dict (see module docstring)
    """
    result = _empty_result()
    importlib.reload(VC)

    ppi = VC.PIXELS_PER_INCH
    if ppi is None or ppi <= 0:
        sys.stderr.write("fid_detect ERROR: PIXELS_PER_INCH not calibrated.\n")
        return result

    h, w = frame.shape[:2]
    expected_side_px   = size_in * ppi
    expected_area_px   = expected_side_px ** 2
    tol_frac           = tolerance_pct / 100.0
    min_area           = expected_area_px * (1.0 - tol_frac)
    max_area           = expected_area_px * (1.0 + tol_frac)
    min_asp            = getattr(VC, 'SQUARE_MIN_ASPECT', 0.80)
    max_asp            = getattr(VC, 'SQUARE_MAX_ASPECT', 1.20)

    # Pre-process
    gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k       = getattr(VC, 'SQUARE_BLUR_KERNEL_SIZE', 5)
    k       = k if k % 2 == 1 else k + 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    # Otsu threshold
    offset   = getattr(VC, 'SQUARE_OTSU_OFFSET', 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if offset != 0:
        thresh_val = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[0]
        _, binary = cv2.threshold(blurred, int(thresh_val) + offset, 255, cv2.THRESH_BINARY_INV)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        sys.stderr.write("fid_detect: No contours found for square detection.\n")
        return result

    frame_cx, frame_cy = w / 2.0, h / 2.0
    best, best_dist = None, float('inf')

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (min_area <= area <= max_area):
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw / float(bh) if bh > 0 else 0
        if not (min_asp <= aspect <= max_asp):
            continue

        # Center of bounding rect
        cx = x + bw / 2.0
        cy = y + bh / 2.0
        dist = math.hypot(cx - frame_cx, cy - frame_cy)

        if dist < best_dist:
            best_dist = dist
            best = (cx, cy, bw, bh, area)

    if best is None:
        sys.stderr.write("fid_detect: No square contour matched size/aspect criteria.\n")
        return result

    cx_px, cy_px, bw, bh, area = best
    # Confidence: how close area is to expected
    area_err_frac = abs(area - expected_area_px) / expected_area_px
    confidence    = max(0.0, 1.0 - area_err_frac)
    # Use half-diagonal as 'radius' for overlay circle sizing
    radius_px     = math.hypot(bw, bh) / 2.0

    dx_in, dy_in = _pixel_to_inch_offset(cx_px, cy_px, w, h, ppi)

    result.update({
        'found':       True,
        'cx_px':       float(cx_px),
        'cy_px':       float(cy_px),
        'radius_px':   radius_px,
        'confidence':  confidence,
        'offset_x_in': dx_in,
        'offset_y_in': dy_in,
    })
    return result


# ---------------------------------------------------------------------------
# Camera capture (shared with m510)
# ---------------------------------------------------------------------------

def capture_frame():
    """Open the configured video device, warm up, capture one frame, release.

    Returns the frame (numpy array) or None on failure.
    """
    importlib.reload(VC)
    port = VC.VIDEO_PORT
    backend = getattr(VC, 'CAMERA_BACKEND', cv2.CAP_V4L2)

    cap = cv2.VideoCapture(port, backend)
    if not cap.isOpened():
        sys.stderr.write("fid_detect ERROR: Cannot open video device {}\n".format(port))
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  VC.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VC.FRAME_HEIGHT)

    for _ in range(VC.CAMERA_WARMUP_FRAMES):
        cap.grab()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        sys.stderr.write("fid_detect ERROR: Failed to capture frame from {}\n".format(port))
        return None

    return frame
