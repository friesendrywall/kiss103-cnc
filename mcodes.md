# M-Code Reference — KISS103-MESA

All custom M-codes live in `m_codes/`. M100–M199 are standard user M-codes
executed directly from `USER_M_PATH`. M500–M520 are Python REMAP handlers
defined in `python/`.

---

## M110 — Single-Shot Fiducial Centering

Move the camera over a fiducial, then call M110 to detect its offset from
frame center. Results are written as named parameters for use in G-code.

```gcode
M110 P<diameter_in>
```

| Word | Description |
|---|---|
| `P` | Expected fiducial diameter in inches |

**Parameters written:**

| Parameter | Description |
|---|---|
| `#<_vision_x_offset>` | X offset to fiducial center, inches (+right) |
| `#<_vision_y_offset>` | Y offset to fiducial center, inches (+up) |
| `#<_vision_found>` | `1.0` if detected |
| `#<_vision_confidence>` | Detection confidence 0.0–1.0 |
| `#<_vision_radius_px>` | Detected radius in pixels (debug) |

**Example:**
```gcode
M110 P0.039
O100 if [#<_vision_found> EQ 1.0]
    G0 X[#<_vision_x_offset>] Y[#<_vision_y_offset>]
O100 endif
```

See `m_codes/M110_README.md` for calibration instructions and tuning.

---

## M150 — Preheater Setpoint

```gcode
M150 P<value>
```

| Word | Range | Description |
|---|---|---|
| `P` | 25–125 | Preheater temperature setpoint (°C) |

---

## M160 — Dropjet Dot Size

```gcode
M160 P<value>
```

| Word | Range | Description |
|---|---|---|
| `P` | 1–25 | Dropjet dot size |

---

## M170 — Dropjet Frequency

```gcode
M170 P<value>
```

| Word | Range | Description |
|---|---|---|
| `P` | 1–100 | Dropjet pulse frequency (Hz) |

---

## M500 — Clear Fiducial State

Zeros all fiducial named parameters and clears the camera widget overlay.
Call at the start of every new board alignment sequence.

```gcode
M500
```

---

## M510 — Detect and Store a Fiducial

Jog the camera over the fiducial, then call M510. The current WCS position
is stored together with the pixel-derived inch offset from frame center.

```gcode
M510 Q<1|2> D<diameter>                  ; circle fiducial
M510 Q<1|2> S<side_length>               ; square fiducial
; optional: E<tolerance_%>  P<search_area_in>
```
| Word | Required | Default | Description |
|---|---|---|---|
| `Q` | Yes | — | Fiducial number: `1` or `2` |
| `D` | One of D/K | — | Expected circle diameter, inches |
| `K` | One of D/K | — | Expected square side length, inches |
| `E` | No | `10` | Size tolerance in percent (e.g. `E15` = ±15%) |
| `P` | Yes | — | Search area box, inches |

**Parameters written** (substitute `2` for second fiducial):

| Parameter | Description |
|---|---|
| `#<_fid1_x>` | WCS X when M510 N1 was called |
| `#<_fid1_y>` | WCS Y when M510 N1 was called |
| `#<_fid1_x_offset>` | Camera X offset to fiducial, inches (+right) |
| `#<_fid1_y_offset>` | Camera Y offset to fiducial, inches (+up) |
| `#<_fid1_found>` | `1.0` if detected |
| `#<_fid_fail>` | `1.0` on any detection failure |

The `CamFidView` widget shows a green overlay circle with offset label until fid_read is cleared

**Example:**
```gcode
M510 Q1 D0.050 E15 P0.25
M510 Q2 D0.050 E15 P0.25
```

---

## M520 — Calculate PCB Correction

Must be called after the required M510 calls. Computes the corrective XY
offset and (P2 only) the PCB rotation angle.  It then applies this to the current active work offset

```gcode
M520 P1    ; single fiducial — translation offset only
M520 P2    ; two fiducials  — translation offset + rotation
```

| Mode | Prerequisites | Calculates |
|---|---|---|
| `P1` | M510 Q1 | Translation from fid1 camera offsets |
| `P2` | M510 Q1 + M510 Q2 | First fid offset translation + PCB rotation angle |

**Parameters written:**

| Parameter | Description |
|---|---|
| `#<_calc_x_offset>` | X correction to apply to WCS, inches |
| `#<_calc_y_offset>` | Y correction to apply to WCS, inches |
| `#<_pcb_rotation>` | PCB rotation in degrees (`0.0` for P1 mode) |
| `#<_fid_fail>` | `1.0` if required fiducials were not detected |

**Applying the correction:**
```gcode
; P1 (translation only):
G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>]
; P2 (rotation + translation — G10 L2 R rotates around machine 0,0):
G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>] R[#<_pcb_rotation>]
```

---

## Full Two-Fiducial Alignment Example

```gcode
M500                                      ; clear previous state

G0 X1.500 Y0.750                          ; move to nominal fid 1 position
M510 Q1 D0.050 E15 P0.25                  ; detect fid 1
O100 if [#<_fid_fail> EQ 1.0]
    (DEBUG, Fiducial 1 not found - aborting)
    M2
O100 endif

G0 X5.500 Y0.750                          ; move to nominal fid 2 position
M510 Q2 D0.050 E15 P0.25                  ; detect fid 2
O101 if [#<_fid_fail> EQ 1.0]
    (DEBUG, Fiducial 2 not found - aborting)
    M2
O101 endif

M520 P2                                   ; compute rotation + translation
(DEBUG, PCB rotation = #<_pcb_rotation> degrees)
(DEBUG, X correction = #<_calc_x_offset>  Y correction = #<_calc_y_offset>)

G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>] R[#<_pcb_rotation>]

; continue with board program using corrected WCS...
```

---

## Common PCB Fiducial Sizes

| Standard | Diameter |
|---|---|
| IPC-7351 Type 1 | 0.039" (1.0 mm) |
| IPC-7351 Type 2 | 0.059" (1.5 mm) |
| Large | 0.079" (2.0 mm) |
| Small | 0.024" (0.6 mm) |
