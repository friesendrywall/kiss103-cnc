#!/usr/bin/env python3
"""
M110_calibrate.py  —  Calibration Routine for M110 Fiducial Vision System
--------------------------------------------------------------------------
Run this script ONCE from a terminal before using M110.py in production.
It opens the camera, detects a known-diameter circular object you place
in the field of view, computes PIXELS_PER_INCH, and writes the result
back into vision_constants.py automatically.

USAGE:
    python3 M110_calibrate.py

    The script will:
        1. Open a live preview window
        2. Prompt you to place a known-diameter object (drill bit shank,
           end mill, dowel pin, etc.) in the camera view
        3. Let you confirm the detected circle looks correct
        4. Save PIXELS_PER_INCH (and supporting data) to vision_constants.py

TIPS FOR A GOOD CALIBRATION:
    - Use a clean, round object with a KNOWN diameter:
        * A precision dowel pin  (e.g. 0.2500" ± 0.0001")
        * A drill bit shank      (e.g. 1/4" = 0.2500")
        * A gauge pin
    - Lay it flat so the camera sees a circular cross-section
    - Good lighting matters — avoid glare on shiny metal
    - The object should fill roughly 20–60% of the frame width
    - Run calibration with the same lighting you'll use in production

REQUIREMENTS:
    - Python 3.6+
    - opencv-python: pip3 install opencv-python
    - vision_constants.py in the same directory
"""

import sys
import os
import re
import math
import datetime
import importlib
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import vision_constants as VC
    importlib.reload(VC)
except ImportError:
    sys.stderr.write("ERROR: Cannot find vision_constants.py in {}\n".format(SCRIPT_DIR))
    sys.exit(1)

try:
    import cv2
    import numpy as np
except ImportError:
    sys.stderr.write("ERROR: opencv-python not installed. Run: pip3 install opencv-python\n")
    sys.exit(1)

CONSTANTS_FILE = os.path.join(SCRIPT_DIR, "vision_constants.py")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def update_constant(filepath, name, value):
    """
    Update a named constant in vision_constants.py in-place.
    Handles string, float, int, and None values.
    """
    with open(filepath, "r") as f:
        content = f.read()

    if isinstance(value, str):
        replacement = '{} = "{}"'.format(name, value)
    elif value is None:
        replacement = "{} = None".format(name)
    else:
        replacement = "{} = {}".format(name, repr(value))

    # Match the line: NAME = <anything>
    pattern = r"^{}\s*=\s*.*$".format(re.escape(name))
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

    if count == 0:
        sys.stderr.write("WARNING: Could not find '{}' in constants file to update.\n".format(name))
        return False

    with open(filepath, "w") as f:
        f.write(new_content)
    return True


def open_camera():
    cap = cv2.VideoCapture(VC.VIDEO_PORT, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("ERROR: Cannot open video device {}".format(VC.VIDEO_PORT))
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, VC.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VC.FRAME_HEIGHT)
    # Warm up
    for _ in range(VC.CAMERA_WARMUP_FRAMES):
        cap.grab()
    return cap


def detect_circles_in_frame(frame, min_r=5, max_r=None):
    """Run HoughCircles with current constants, return list of (cx, cy, r)."""
    h, w = frame.shape[:2]
    if max_r is None:
        max_r = min(w, h) // 2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = VC.BLUR_KERNEL_SIZE
    if k % 2 == 0:
        k += 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

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
        return []
    return [(int(c[0]), int(c[1]), int(c[2])) for c in np.round(circles[0, :]).astype("int")]


def draw_overlay(frame, circles, selected_idx=None):
    """Draw detected circles on frame. Highlight selected circle in green."""
    overlay = frame.copy()
    h, w = frame.shape[:2]

    # Frame center crosshair
    cv2.line(overlay, (w//2 - 20, h//2), (w//2 + 20, h//2), (0, 200, 255), 1)
    cv2.line(overlay, (w//2, h//2 - 20), (w//2, h//2 + 20), (0, 200, 255), 1)

    for i, (cx, cy, r) in enumerate(circles):
        if i == selected_idx:
            color = (0, 255, 0)
            thickness = 2
            label = "USE THIS  r={}px".format(r)
        else:
            color = (80, 80, 255)
            thickness = 1
            label = "r={}px".format(r)
        cv2.circle(overlay, (cx, cy), r, color, thickness)
        cv2.circle(overlay, (cx, cy), 3, color, -1)
        cv2.putText(overlay, label, (cx + r + 4, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    return overlay


# ---------------------------------------------------------------------------
# Calibration flow
# ---------------------------------------------------------------------------

def calibration_live_preview(known_diameter_in):
    """
    Open live camera preview. User can cycle through detected circles with
    SPACE to select. ENTER confirms. ESC aborts.

    Returns selected radius in pixels, or None if aborted.
    """
    print("\nOpening camera preview...")
    print("Controls:")
    print("  SPACE  — cycle to next detected circle")
    print("  ENTER  — confirm selected circle and save calibration")
    print("  R      — re-detect circles in current frame")
    print("  ESC    — abort calibration")
    print("")

    cap = open_camera()
    if cap is None:
        return None

    selected_idx = 0
    circles = []
    confirmed_radius = None

    # Create resizable window explicitly before the capture loop
    win_title = "M110 Calibration  —  place {:.4f}\" object in view".format(known_diameter_in)
    cv2.namedWindow(win_title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_title, VC.FRAME_WIDTH, VC.FRAME_HEIGHT)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Lost camera feed.")
            break

        # Re-detect every 15 frames for responsiveness
        if len(circles) == 0 or (cv2.getTickCount() % 15 == 0):
            circles = detect_circles_in_frame(frame)

        if circles:
            selected_idx = selected_idx % len(circles)
            display = draw_overlay(frame, circles, selected_idx)
            status = "Detected {} circle(s) | Selected: r={}px | SPACE=next  ENTER=confirm  ESC=abort".format(
                len(circles), circles[selected_idx][2])
        else:
            display = draw_overlay(frame, [])
            status = "No circles detected — adjust lighting/focus | ESC=abort"

        # Status bar at bottom
        cv2.rectangle(display, (0, display.shape[0]-28), (display.shape[1], display.shape[0]),
                      (30, 30, 30), -1)
        cv2.putText(display, status, (6, display.shape[0]-8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 220, 220), 1)

        cv2.imshow("M110 Calibration  —  place {:.4f}\" object in view".format(known_diameter_in),
                   display)

        key = cv2.waitKey(30) & 0xFF

        if key == 27:   # ESC
            print("Calibration aborted.")
            break
        elif key == ord(' ') and circles:
            selected_idx = (selected_idx + 1) % len(circles)
        elif key == ord('r') or key == ord('R'):
            circles = detect_circles_in_frame(frame)
            selected_idx = 0
        elif key == 13 and circles:   # ENTER
            confirmed_radius = circles[selected_idx][2]
            print("\nConfirmed: radius = {} px for {:.4f}\" diameter object.".format(
                confirmed_radius, known_diameter_in))
            break

    cap.release()
    cv2.destroyAllWindows()
    return confirmed_radius


def main():
    print("=" * 60)
    print("  M110 Vision System Calibration")
    print("=" * 60)
    print("")
    print("You will place a KNOWN-DIAMETER circular object in the camera")
    print("field of view. Good choices:")
    print("  • Precision dowel pin  (e.g. 0.2500\")")
    print("  • Drill bit shank      (e.g. 1/4\" = 0.2500\")")
    print("  • Gauge pin")
    print("  • End mill shank       (check the actual shank diameter)")
    print("")

    # --- Get known diameter from user --------------------------------------
    while True:
        try:
            raw = input("Enter the EXACT diameter of your calibration object (inches): ").strip()
            known_diameter_in = float(raw)
            if known_diameter_in <= 0:
                raise ValueError
            break
        except ValueError:
            print("  Please enter a positive number, e.g.  0.2500")

    print("")
    print("Using: {:.4f}\" ({:.4f} mm)".format(known_diameter_in, known_diameter_in * 25.4))
    print("")

    # --- Live preview and circle selection ---------------------------------
    confirmed_radius_px = calibration_live_preview(known_diameter_in)

    if confirmed_radius_px is None:
        print("Calibration not saved.")
        sys.exit(1)

    # --- Compute pixels per inch -------------------------------------------
    # diameter in pixels = 2 * radius
    diameter_px = confirmed_radius_px * 2.0
    pixels_per_inch = diameter_px / known_diameter_in

    print("")
    print("Calibration results:")
    print("  Calibration object diameter : {:.4f} in".format(known_diameter_in))
    print("  Detected radius             : {} px  ({:.1f} px diameter)".format(
        confirmed_radius_px, diameter_px))
    print("  PIXELS_PER_INCH             : {:.4f}".format(pixels_per_inch))
    print("  Field of view (approx)      : {:.4f} in W  x  {:.4f} in H".format(
        VC.FRAME_WIDTH  / pixels_per_inch,
        VC.FRAME_HEIGHT / pixels_per_inch))
    print("")

    # --- Confirm before saving ---------------------------------------------
    ans = input("Save these calibration values to vision_constants.py? [Y/n]: ").strip().lower()
    if ans and ans != "y":
        print("Calibration NOT saved.")
        sys.exit(0)

    # --- Write to vision_constants.py -------------------------------------
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    ok = True
    ok &= update_constant(CONSTANTS_FILE, "PIXELS_PER_INCH", round(pixels_per_inch, 6))
    ok &= update_constant(CONSTANTS_FILE, "CALIBRATION_OBJECT_DIAMETER_IN", round(known_diameter_in, 6))
    ok &= update_constant(CONSTANTS_FILE, "CALIBRATION_DETECTED_RADIUS_PX", float(confirmed_radius_px))
    ok &= update_constant(CONSTANTS_FILE, "CALIBRATION_TIMESTAMP", timestamp)

    if ok:
        print("")
        print("✓ Calibration saved to: {}".format(CONSTANTS_FILE))
        print("  PIXELS_PER_INCH = {:.4f}".format(pixels_per_inch))
        print("  Calibrated: {}".format(timestamp))
        print("")
        print("You can now use M110 Pxx.xxxx in your G-code.")
    else:
        print("ERROR: Some values could not be written. Check vision_constants.py manually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
