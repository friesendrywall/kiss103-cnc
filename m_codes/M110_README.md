# M110 PCB Fiducial Vision System
## LinuxCNC User M-Code — Installation & Usage Guide

---

## Files

| File | Purpose |
|---|---|
| `M110.py` | The M-code itself — called from G-code with `M110 P<diameter>` |
| `M110_calibrate.py` | One-time calibration utility — run from terminal |
| `vision_constants.py` | All configuration and calibration values — edit here |

---

## Installation

### 1. Install OpenCV
```bash
pip3 install opencv-python
```

### 2. Copy files to your USER_M_PATH directory
LinuxCNC needs all three files in the same directory.  
Typically: `~/linuxcnc/ncfiles/` or wherever `USER_M_PATH` points in your INI.

```bash
cp M110.py M110_calibrate.py vision_constants.py ~/linuxcnc/ncfiles/
chmod +x ~/linuxcnc/ncfiles/M110.py
```

### 3. Verify USER_M_PATH in your INI file
In your machine's `.ini` file, under `[RS274NGC]`:
```ini
[RS274NGC]
USER_M_PATH = /home/youruser/linuxcnc/ncfiles
```

### 4. Confirm video port
```bash
ls /dev/video*
# Plug/unplug camera if unsure which port — watch which device appears
```
Update `VIDEO_PORT` in `vision_constants.py` if needed (default: `/dev/video0`).

---

## Calibration (required before first use)

Run from a terminal (NOT from inside LinuxCNC):
```bash
python3 ~/linuxcnc/ncfiles/M110_calibrate.py
```

**You will need:** a precision circular object with a known diameter:
- Precision dowel pin (e.g. 0.2500")
- Drill bit shank (measure actual shank, not nominal)
- Gauge pin

**Steps:**
1. Enter the exact diameter of your calibration object
2. Place the object in the camera's field of view
3. A live preview window opens — the script auto-detects circles
4. Press `SPACE` to cycle between detected circles if more than one is found
5. Press `ENTER` to confirm when the green circle matches your object
6. Press `Y` to save — `PIXELS_PER_INCH` is written to `vision_constants.py`

Re-run calibration if you:
- Change camera, lens, or zoom
- Change the camera mounting height
- Change `FRAME_WIDTH` / `FRAME_HEIGHT`

---

## G-Code Usage

```gcode
; Move spindle over approximate fiducial location first, then:
M110 P0.050          ; P = expected fiducial diameter in INCHES (0.050" is a common PCB fiducial)

; Check if found
O100 if [#<_vision_found> EQ 1.0]
    (DEBUG, Fiducial found! X offset=#<_vision_x_offset>  Y offset=#<_vision_y_offset>)
    G0 X[#<_vision_x_offset>] Y[#<_vision_y_offset>]    ; move to exact fiducial center
O100 else
    (DEBUG, WARNING: Fiducial not found - check camera and lighting)
O100 endif
```

### Named Parameters Written by M110

| Parameter | Type | Description |
|---|---|---|
| `#<_vision_x_offset>` | inches | X offset from center (+right) |
| `#<_vision_y_offset>` | inches | Y offset from center (+up) |
| `#<_vision_found>` | 1.0 / 0.0 | 1.0 if fiducial detected |
| `#<_vision_confidence>` | 0.0–1.0 | Radius match quality |
| `#<_vision_radius_px>` | pixels | Detected circle radius (debug) |

---

## Tuning Detection

If M110 fails to detect or gets false positives, edit `vision_constants.py`:

| Constant | Effect | Try if... |
|---|---|---|
| `HOUGH_PARAM2` | ↓ = more circles detected | Fiducial not found |
| `HOUGH_PARAM2` | ↑ = fewer, higher-confidence only | False positives |
| `RADIUS_MATCH_TOLERANCE` | Loosen/tighten size filter | Wrong circles selected |
| `BLUR_KERNEL_SIZE` | ↑ = smoother, less noise | Noisy/grainy image |
| `CAMERA_WARMUP_FRAMES` | ↑ = more auto-exposure time | Image too dark/bright initially |

---

## Testing Without LinuxCNC

You can test M110.py standalone from the terminal:
```bash
python3 M110.py P0.050
```
It will print the result instead of writing named parameters.

---

## Common PCB Fiducial Sizes

| Standard | Diameter |
|---|---|
| IPC-7351 Type 1 (common) | 0.039" (1.0 mm) |
| IPC-7351 Type 2 | 0.059" (1.5 mm) |
| Large fiducial | 0.079" (2.0 mm) |
| Small fiducial | 0.024" (0.6 mm) |

Use these as your `P` value in `M110 P<value>`.
