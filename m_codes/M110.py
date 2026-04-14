#!/usr/bin/env python3
"""
M110.py  —  LinuxCNC User M-Code: PCB Fiducial Vision Centering
----------------------------------------------------------------
Captures a frame from the configured video port, detects a solid circular
fiducial (copper dot), and writes the X/Y offset from frame center to
LinuxCNC named parameters.

USAGE (from G-code):
    M110 P0.050        ; P = expected fiducial diameter in INCHES

    After execution, read results with:
        #<_vision_x_offset>   ; X offset in inches (positive = fiducial is RIGHT of center)
        #<_vision_y_offset>   ; Y offset in inches (positive = fiducial is ABOVE center)
        #<_vision_found>      ; 1.0 if fiducial detected, 0.0 if not found
        #<_vision_confidence> ; 0.0–1.0, how closely radius matched expected size

EXAMPLE G-CODE USAGE:
    M110 P0.050
    #<found> = #<_vision_found>
    (DEBUG, Vision found: #<found>)
    G0 X[#<_vision_x_offset>] Y[#<_vision_y_offset>]   ; move to fiducial center

INSTALLATION:
    1. Place M110.py in your USER_M_PATH directory (e.g. ~/linuxcnc/ncfiles/)
    2. Place vision_constants.py in the same directory
    3. Run M110_calibrate.py once before production use
    4. Ensure opencv-python is installed: pip3 install opencv-python

CALIBRATION:
    Run M110_calibrate.py separately (from terminal or as M111 if desired).
    You must calibrate before reliable inch-unit offsets are available.

REQUIREMENTS:
    - Python 3.6+
    - opencv-python (cv2)
    - LinuxCNC with USER_M_PATH configured

Author: Generated for LinuxCNC fiducial vision project
"""

import sys
import os
import math
import importlib
import cv2

# ---------------------------------------------------------------------------
# Locate vision_constants.py relative to this script
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import vision_constants as VC
    # Reload so any runtime edits to constants are picked up
    importlib.reload(VC)
except ImportError:
    sys.stderr.write("M110 ERROR: Cannot find vision_constants.py in {}\n".format(SCRIPT_DIR))
    sys.exit(1)

try:
    import cv2
    import numpy as np
except ImportError:
    sys.stderr.write("M110 ERROR: opencv-python not installed. Run: pip3 install opencv-python\n")
    sys.exit(1)

# ---------------------------------------------------------------------------
# LinuxCNC parameter interface
# ---------------------------------------------------------------------------
try:
    import linuxcnc
    LINUXCNC_AVAILABLE = True
except ImportError:
    # Allow standalone testing outside of LinuxCNC environment
    LINUXCNC_AVAILABLE = False
    sys.stderr.write("M110 WARNING: linuxcnc module not found — running in standalone test mode.\n")


def set_named_param(h, name, value):
    """Write a named parameter via the LinuxCNC HAL/stat interface."""
    if LINUXCNC_AVAILABLE:
        try:
            h[name] = value
        except Exception as e:
            sys.stderr.write("M110 WARNING: Could not set parameter {}: {}\n".format(name, e))
    else:
        print("  [param] #{} = {}".format(name, value))


# ---------------------------------------------------------------------------
# Core detection function
# ---------------------------------------------------------------------------

def detect_fiducial(frame, expected_diameter_in):
    """
    Detect the largest solid circular fiducial in the frame that best matches
    the expected diameter.

    Args:
        frame: OpenCV BGR image (numpy array)
        expected_diameter_in: expected fiducial diameter in inches (float)

    Returns:
        dict with keys:
            found        (bool)
            cx_px        center X in pixels (float, relative to frame top-left)
            cy_px        center Y in pixels
            radius_px    detected radius in pixels
            confidence   0.0–1.0 match quality
            offset_x_in  X offset from frame center in inches (+right)
            offset_y_in  Y offset from frame center in inches (+up in machine coords)
    """
    result = {
        "found": False,
        "cx_px": 0.0, "cy_px": 0.0, "radius_px": 0.0,
        "confidence": 0.0,
        "offset_x_in": 0.0, "offset_y_in": 0.0
    }

    h, w = frame.shape[:2]
    frame_cx = w / 2.0
    frame_cy = h / 2.0

    # --- Compute expected radius in pixels (requires calibration) -----------
    if VC.PIXELS_PER_INCH is None:
        sys.stderr.write("M110 WARNING: PIXELS_PER_INCH not calibrated. "
                         "Run M110_calibrate.py first. Offsets will be approximate.\n")
        # Fall back to a rough estimate so detection still runs
        ppi = min(w, h) / 0.5   # assume FOV is ~0.5 inch wide — very rough
    else:
        ppi = VC.PIXELS_PER_INCH

    expected_radius_px = (expected_diameter_in / 2.0) * ppi

    # --- Pre-process image ---------------------------------------------------
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Gaussian blur to reduce noise before edge detection
    k = VC.BLUR_KERNEL_SIZE
    if k % 2 == 0:
        k += 1   # ensure odd
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    # --- HoughCircles detection ----------------------------------------------
    min_r = max(3, int(expected_radius_px * (1.0 - VC.RADIUS_MATCH_TOLERANCE)))
    max_r = int(expected_radius_px * (1.0 + VC.RADIUS_MATCH_TOLERANCE))

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=VC.HOUGH_DP,
        minDist=VC.HOUGH_MIN_DIST,
        param1=VC.HOUGH_PARAM1,
        param2=VC.HOUGH_PARAM2,
        minRadius=min_r,
        maxRadius=max_r
    )

    if circles is None:
        sys.stderr.write("M110: No circles detected in frame. "
                         "Check lighting, focus, or adjust HOUGH_PARAM2 in vision_constants.py\n")
        return result

    circles = np.round(circles[0, :]).astype("int")

    # --- Pick the best match (closest radius to expected) -------------------
    best = None
    best_score = float("inf")

    for (cx, cy, r) in circles:
        radius_error = abs(r - expected_radius_px)
        # Also prefer circles closer to frame center (helps avoid edge artifacts)
        dist_from_center = math.hypot(cx - frame_cx, cy - frame_cy)
        score = radius_error + dist_from_center * 0.1
        if score < best_score:
            best_score = score
            best = (cx, cy, r)

    if best is None:
        return result

    cx_px, cy_px, r_px = best

    # --- Confidence: how close was the radius match -------------------------
    radius_error_fraction = abs(r_px - expected_radius_px) / expected_radius_px
    confidence = max(0.0, 1.0 - radius_error_fraction)

    # --- Convert pixel offsets to inches ------------------------------------
    # Pixel offset from frame center (pixels, +right, +down in image coords)
    dx_px = cx_px - frame_cx
    dy_px = cy_px - frame_cy

    # Convert to inches
    dx_in = dx_px / ppi
    dy_in = dy_px / ppi

    # Apply camera mount offset correction
    dx_in += VC.CAM_OFFSET_X
    dy_in += VC.CAM_OFFSET_Y

    # Flip Y: image Y increases downward, machine Y increases upward
    dy_in = -dy_in

    result.update({
        "found": True,
        "cx_px": float(cx_px),
        "cy_px": float(cy_px),
        "radius_px": float(r_px),
        "confidence": confidence,
        "offset_x_in": dx_in,
        "offset_y_in": dy_in
    })
    return result


# ---------------------------------------------------------------------------
# Camera capture
# ---------------------------------------------------------------------------

def capture_frame(port):
    """Open video port, warm up, capture one frame, release."""
    cap = cv2.VideoCapture(port, cv2.CAP_V4L2)
    if not cap.isOpened():
        sys.stderr.write("M110 ERROR: Cannot open video device {}\n".format(port))
        return None

    # Set resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, VC.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VC.FRAME_HEIGHT)

    # Warm-up: discard first N frames so auto-exposure settles
    for _ in range(VC.CAMERA_WARMUP_FRAMES):
        cap.grab()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        sys.stderr.write("M110 ERROR: Failed to capture frame from {}\n".format(port))
        return None

    return frame


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    # --- Parse P parameter (expected fiducial diameter in inches) -----------
    # LinuxCNC passes argv as: M110.py [P value] [Q value] ...
    # Convention: sys.argv[1] = P word value
    expected_diameter_in = None

    if len(sys.argv) >= 2:
        try:
            expected_diameter_in = float(sys.argv[1])
        except ValueError:
            pass

    # Also accept named --P= style for testing
    for arg in sys.argv[1:]:
        if arg.upper().startswith("P"):
            try:
                expected_diameter_in = float(arg[1:])
            except ValueError:
                pass

    if expected_diameter_in is None or expected_diameter_in <= 0:
        sys.stderr.write("M110 ERROR: P parameter required (expected fiducial diameter in inches).\n"
                         "  Usage: M110 P0.050\n")
        sys.exit(1)

    print("M110: Fiducial vision centering — diameter={:.4f} in, port={}".format(
        expected_diameter_in, VC.VIDEO_PORT))

    # --- Set up LinuxCNC named parameter handle -----------------------------
    if LINUXCNC_AVAILABLE:
        try:
            h = linuxcnc.command()
        except Exception as e:
            sys.stderr.write("M110 WARNING: Could not connect to LinuxCNC: {}\n".format(e))
            h = {}
    else:
        h = {}

    # --- Capture frame ------------------------------------------------------
    frame = capture_frame(VC.VIDEO_PORT)

    if frame is None:
        # Write failure state to named params and exit
        _write_failure(h)
        sys.exit(1)

    # --- Detect fiducial ----------------------------------------------------
    result = detect_fiducial(frame, expected_diameter_in)

    # --- Write named parameters ---------------------------------------------
    if LINUXCNC_AVAILABLE:
        # Use linuxcnc stat to set named parameters via MDI/interp
        # Named parameters are written via the interpreter's parameter store
        _write_named_params_linuxcnc(result)
    else:
        _print_result(result)

    if result["found"]:
        print("M110: Fiducial found — "
              "offset X={:+.4f} in  Y={:+.4f} in  confidence={:.0%}".format(
              result["offset_x_in"], result["offset_y_in"], result["confidence"]))
    else:
        print("M110: Fiducial NOT found.")

    return 0 if result["found"] else 1


def _write_named_params_linuxcnc(result):
    """
    Write results to LinuxCNC named global parameters.
    These are accessible in G-code as #<_vision_x_offset> etc.
    Uses the linuxcnc.command() interface to set parameters.
    """
    try:
        c = linuxcnc.command()
        stat = linuxcnc.stat()
        stat.poll()

        def mdi(cmd):
            c.mdi(cmd)
            c.wait_complete()

        if result["found"]:
            mdi("#<_vision_x_offset>   = {:+.6f}".format(result["offset_x_in"]))
            mdi("#<_vision_y_offset>   = {:+.6f}".format(result["offset_y_in"]))
            mdi("#<_vision_found>      = 1.0")
            mdi("#<_vision_confidence> = {:.4f}".format(result["confidence"]))
            mdi("#<_vision_radius_px>  = {:.2f}".format(result["radius_px"]))
        else:
            _write_failure_mdi(mdi)

    except Exception as e:
        sys.stderr.write("M110 ERROR writing named parameters: {}\n".format(e))


def _write_failure_mdi(mdi_fn):
    mdi_fn("#<_vision_x_offset>   = 0.0")
    mdi_fn("#<_vision_y_offset>   = 0.0")
    mdi_fn("#<_vision_found>      = 0.0")
    mdi_fn("#<_vision_confidence> = 0.0")
    mdi_fn("#<_vision_radius_px>  = 0.0")


def _write_failure(h):
    print("M110: Writing failure state to named parameters.")
    if LINUXCNC_AVAILABLE:
        try:
            c = linuxcnc.command()
            def mdi(cmd): c.mdi(cmd); c.wait_complete()
            _write_failure_mdi(mdi)
        except Exception:
            pass


def _print_result(result):
    """Standalone test mode output."""
    print("\n  --- M110 Result ---")
    print("  Found:       {}".format(result["found"]))
    print("  X offset:    {:+.4f} in".format(result["offset_x_in"]))
    print("  Y offset:    {:+.4f} in".format(result["offset_y_in"]))
    print("  Confidence:  {:.0%}".format(result["confidence"]))
    print("  Radius (px): {:.1f}".format(result["radius_px"]))
    print("")
    print("  Named params that would be set:")
    print("    #<_vision_x_offset>   = {:+.6f}".format(result["offset_x_in"]))
    print("    #<_vision_y_offset>   = {:+.6f}".format(result["offset_y_in"]))
    print("    #<_vision_found>      = {}".format(1.0 if result["found"] else 0.0))
    print("    #<_vision_confidence> = {:.4f}".format(result["confidence"]))


if __name__ == "__main__":
    sys.exit(main())
