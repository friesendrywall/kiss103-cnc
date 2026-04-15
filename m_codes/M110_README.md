# PCB Fiducial Vision System
## LinuxCNC M-Code Reference — M110 / M500 / M510 / M520

---

## Files

| File | Purpose |
|---|---|
| `M110.py` | Single-shot centering: move to fiducial, detect offset — `M110 P<diameter>` |
| `M110_calibrate.py` | One-time calibration utility — run from terminal |
| `vision_constants.py` | All configuration and calibration values — edit here |
| `../python/m500_fid.py` | REMAP handler for M500 (clear state) |
| `../python/m510_fid.py` | REMAP handler for M510 (detect and store fiducial) |
| `../python/m520_fid.py` | REMAP handler for M520 (calculate correction) |
| `../python/fid_detect.py` | Shared OpenCV detection (circle + square) |

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

Use these as your `P` value in `M110 P<value>` or `D` value in `M510 N1 D<value>`.

---

## Two-Fiducial Workflow — M500 / M510 / M520

These three remapped M-codes provide full PCB alignment: detect two fiducials, then
compute the XY translation offset and (optionally) the PCB rotation angle.

### M500 — Clear State

```gcode
M500
```

Zeros all fiducial named parameters and clears the camera widget overlay.
Call this at the start of a new board alignment sequence.

---

### M510 — Detect and Store a Fiducial

```gcode
M510 N<1|2> D<diameter> T<tolerance%> A<search_area>   ; circle fiducial
M510 N<1|2> S<side_length> T<tolerance%> A<search_area> ; square fiducial
```

Jog the machine so the camera is over the fiducial, then call M510.
The current WCS position is recorded alongside the detected pixel offset.

| Word | Required | Description |
|---|---|---|
| `N` | Yes | Fiducial number: `1` or `2` |
| `D` | One of D or S | Expected circle diameter in inches |
| `S` | One of D or S | Expected square side length in inches |
| `T` | No (default 10) | Size tolerance in percent — e.g. `T10` = ±10% |
| `A` | No | Search area half-width in inches (reserved for future crop) |

**Example:**
```gcode
M510 N1 D0.039 T15 A0.5     ; detect 1.0 mm circle fiducial, ±15% tolerance
M510 N2 D0.039 T15 A0.5     ; detect second fiducial
```

**Named parameters written (replace `1` with `2` for second fiducial):**

| Parameter | Description |
|---|---|
| `#<_fid1_x>` | WCS X position when M510 N1 was called |
| `#<_fid1_y>` | WCS Y position when M510 N1 was called |
| `#<_fid1_x_offset>` | Camera X offset to fiducial center, inches (+right) |
| `#<_fid1_y_offset>` | Camera Y offset to fiducial center, inches (+up) |
| `#<_fid1_found>` | `1.0` if detected, `0.0` if not |
| `#<_fid1_conf>` | Detection confidence, 0.0–1.0 |
| `#<_fid_fail>` | Set to `1.0` on any detection failure |

The `CamFidView` widget will show a green overlay circle with the offset label
for 5 seconds after each successful M510 call.

---

### M520 — Calculate Correction Offsets

```gcode
M520 P1    ; single fiducial — translation only, no rotation
M520 P2    ; two fiducials  — midpoint translation + PCB rotation
```

Must be called after the required M510 calls.

| Mode | Prerequisites | What it calculates |
|---|---|---|
| `P1` | M510 N1 | `calc_x/y_offset` = fid1 camera offsets |
| `P2` | M510 N1 and M510 N2 | midpoint translation + `pcb_rotation` angle |

**Named parameters written:**

| Parameter | Description |
|---|---|
| `#<_calc_x_offset>` | X correction to apply to WCS, inches |
| `#<_calc_y_offset>` | Y correction to apply to WCS, inches |
| `#<_pcb_rotation>` | PCB rotation in degrees (`0.0` for P1 mode) |
| `#<_fid_fail>` | Set to `1.0` if required fiducials were not detected |

**Applying the correction** (typical usage):
```gcode
; shift the active WCS by the detected offset:
G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>]
```

---

### Full Two-Fiducial Example

```gcode
M500                              ; clear previous state
G0 X1.500 Y0.750                  ; move to nominal fid 1 location
M510 N1 D0.039 T15 A0.5          ; detect fid 1
O100 if [#<_fid_fail> EQ 1.0]
    (DEBUG, Fiducial 1 not found — aborting)
    M2
O100 endif

G0 X5.500 Y0.750                  ; move to nominal fid 2 location
M510 N2 D0.039 T15 A0.5          ; detect fid 2
O101 if [#<_fid_fail> EQ 1.0]
    (DEBUG, Fiducial 2 not found — aborting)
    M2
O101 endif

M520 P2                           ; compute rotation + translation
(DEBUG, PCB rotation = #<_pcb_rotation> degrees)
(DEBUG, X offset = #<_calc_x_offset>)
(DEBUG, Y offset = #<_calc_y_offset>)

G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>]
; continue with corrected program...
```
