"""
m510_fid.py — REMAP handler for M510
--------------------------------------
M510 detects a PCB fiducial at the current camera position and stores the
WCS machine position plus the pixel-derived inch offset in named parameters.

G-code usage:
    M510 N<1|2> D<diameter_in>             ; circle fiducial
    M510 N<1|2> S<side_length_in>          ; square fiducial
    Optional: T<tolerance_%>  A<search_area_in>

    N = fiducial number (1 or 2)
    D = expected circle diameter in inches (mutually exclusive with S)
    S = expected square side length in inches (mutually exclusive with D)
    T = size tolerance in percent (default 10)
    A = search area half-width in inches (currently informational; reserved)

Named parameters written:
    For N=1: #<_fid1_x>, #<_fid1_y>, #<_fid1_x_offset>, #<_fid1_y_offset>,
             #<_fid1_found>, #<_fid1_conf>
    For N=2: same with fid2_ prefix
    #<_fid_fail> = 1.0 on detection failure
"""

import sys
import os
import subprocess

# REMAP return codes
try:
    from interpreter import INTERP_OK, INTERP_ERROR   # noqa: F401
except ImportError:
    INTERP_OK    = 0
    INTERP_ERROR = 1

# Ensure sibling modules are importable
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_MCODES = os.path.join(os.path.dirname(_HERE), 'm_codes')
if _MCODES not in sys.path:
    sys.path.insert(0, _MCODES)

from fid_detect import capture_frame, detect_fiducial_circle, detect_fiducial_square


def _halcmd_setp(pin, value):
    """Write a value to a HAL pin via halcmd. Silent on failure."""
    try:
        subprocess.run(
            ['halcmd', 'setp', 'camfidview.{}'.format(pin), str(value)],
            check=False, capture_output=True, timeout=2
        )
    except Exception:
        pass


def _get_wcs_position():
    """Return (wcs_x, wcs_y) in machine linear units (inches) for the current WCS.

    Uses linuxcnc.stat to read actual_position minus the active G5x WCS offset.
    Returns (0.0, 0.0) if linuxcnc module is unavailable (standalone test mode).
    """
    try:
        import linuxcnc
        s = linuxcnc.stat()
        s.poll()
        # actual_position is in machine (absolute) coordinates
        # g5x_offset is the active Work Coordinate System offset
        wcs_x = s.actual_position[0] - s.g5x_offset[0]
        wcs_y = s.actual_position[1] - s.g5x_offset[1]
        return wcs_x, wcs_y
    except Exception as e:
        sys.stderr.write("M510: could not read machine position: {}\n".format(e))
        return 0.0, 0.0


def m510_fid(self, **words):
    """M510 handler: detect fiducial, store WCS position + camera offset."""
    try:
        # ---- Parse word parameters ----------------------------------------
        n_word = words.get('n', None)
        d_word = words.get('d', None)   # circle diameter
        s_word = words.get('s', None)   # square size
        t_word = words.get('t', 10.0)  # tolerance percent, default 10%
        # a_word (search area) is accepted but reserved for future cropping use
        # a_word = words.get('a', None)

        if n_word is None:
            sys.stderr.write("M510 ERROR: N word (fiducial number 1 or 2) is required.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        fid_num = int(round(float(n_word)))
        if fid_num not in (1, 2):
            sys.stderr.write("M510 ERROR: N must be 1 or 2, got {}\n".format(fid_num))
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        if d_word is None and s_word is None:
            sys.stderr.write("M510 ERROR: Either D (circle diameter) or S (square size) is required.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        tolerance_pct = float(t_word) if t_word is not None else 10.0

        prefix = '_fid{}_'.format(fid_num)

        # ---- Get current WCS position BEFORE any motion --------------------
        wcs_x, wcs_y = _get_wcs_position()

        # ---- Capture camera frame ------------------------------------------
        frame = capture_frame()
        if frame is None:
            sys.stderr.write("M510 ERROR: Camera capture failed.\n")
            self.params[prefix + 'found'] = 0.0
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        # ---- Detect fiducial -----------------------------------------------
        if d_word is not None:
            diameter_in = float(d_word)
            print("M510: Detecting circle fiducial N{}, diameter={:.4f}\" tol=±{:.0f}%".format(
                fid_num, diameter_in, tolerance_pct))
            result = detect_fiducial_circle(frame, diameter_in, tolerance_pct)
        else:
            size_in = float(s_word)
            print("M510: Detecting square fiducial N{}, size={:.4f}\" tol=±{:.0f}%".format(
                fid_num, size_in, tolerance_pct))
            result = detect_fiducial_square(frame, size_in, tolerance_pct)

        # ---- Write named parameters ----------------------------------------
        self.params[prefix + 'x']        = wcs_x
        self.params[prefix + 'y']        = wcs_y
        self.params[prefix + 'found']    = 1.0 if result['found'] else 0.0
        self.params[prefix + 'conf']     = result['confidence']
        self.params[prefix + 'x_offset'] = result['offset_x_in']
        self.params[prefix + 'y_offset'] = result['offset_y_in']

        if not result['found']:
            sys.stderr.write("M510: Fiducial N{} NOT detected.\n".format(fid_num))
            self.params['_fid_fail'] = 1.0
            # Clear HAL found pin so widget overlay is not shown
            _halcmd_setp('fid{}-found'.format(fid_num), '0')
            return INTERP_ERROR

        # ---- Write HAL pins so widget can show overlay ---------------------
        _halcmd_setp('fid{}-cx-px'.format(fid_num),     '{:.2f}'.format(result['cx_px']))
        _halcmd_setp('fid{}-cy-px'.format(fid_num),     '{:.2f}'.format(result['cy_px']))
        _halcmd_setp('fid{}-radius-px'.format(fid_num), '{:.2f}'.format(result['radius_px']))
        _halcmd_setp('fid{}-x-offset'.format(fid_num),  '{:.6f}'.format(result['offset_x_in']))
        _halcmd_setp('fid{}-y-offset'.format(fid_num),  '{:.6f}'.format(result['offset_y_in']))
        # Set found pin last so widget trigger fires after data is ready
        _halcmd_setp('fid{}-found'.format(fid_num), '1')

        print("M510: Fiducial N{} found — "
              "WCS=({:+.4f}, {:+.4f})  "
              "offset X={:+.4f}\" Y={:+.4f}\"  "
              "confidence={:.0%}".format(
                  fid_num,
                  wcs_x, wcs_y,
                  result['offset_x_in'], result['offset_y_in'],
                  result['confidence']))

        return INTERP_OK

    except Exception as e:
        sys.stderr.write("M510 ERROR: {}\n".format(e))
        import traceback
        traceback.print_exc()
        try:
            self.params['_fid_fail'] = 1.0
        except Exception:
            pass
        return INTERP_ERROR
