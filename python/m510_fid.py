"""
m510_fid.py — REMAP handler for M510
--------------------------------------
Jog the camera over a fiducial, then call M510. The current WCS position is
stored together with the pixel-derived inch offset from frame center.

G-code usage:
    M510 Q<1|2> D<diameter_in>          ; circle fiducial
    M510 Q<1|2> K<side_length_in>       ; square fiducial
    ; optional: E<tolerance_%>  P<search_area_in>

    Q = fiducial number (1 or 2)              [required]
    D = expected circle diameter, inches      [required if not K]
    K = expected square side length, inches   [required if not D]
    E = size tolerance in percent             [default 10]
    P = search area box, inches               [required]

Named parameters written (substitute 2 for second fiducial):
    #<_fid1_x>        WCS X when M510 Q1 was called
    #<_fid1_y>        WCS Y when M510 Q1 was called
    #<_fid1_x_offset> Camera X offset to fiducial, inches (+right)
    #<_fid1_y_offset> Camera Y offset to fiducial, inches (+up)
    #<_fid1_found>    1.0 if detected, 0.0 otherwise
    #<_fid_fail>      1.0 on any detection failure
"""

import sys
import time
import subprocess

try:
    from interpreter import INTERP_OK, INTERP_EXECUTE_FINISH, INTERP_ERROR   # noqa: F401
except ImportError:
    INTERP_OK    = 0
    INTERP_ERROR = 1

_CAM = 'qt_kiss.camfidview'   # HAL component prefix for the camera widget
_POLL_INTERVAL = 0.05           # seconds between search_done polls
_POLL_TIMEOUT  = 2.5           # seconds before giving up
_PARAM_SETTLE  = 0.25          # seconds for GUI to propagate settings through widget nets
_VISUAL_DELAY  = 0.5

def _halcmd_setp(pin, value):
    """Write a value to a HAL pin via halcmd. Silent on failure."""
    try:
        subprocess.run(
            ['halcmd', 'setp', pin, str(value)],
            check=False, capture_output=True, timeout=2
        )
    except Exception:
        pass


def _halcmd_getp(pin):
    """Read a HAL pin value via halcmd. Returns stripped string or None."""
    try:
        result = subprocess.run(
            ['halcmd', 'getp', pin],
            check=False, capture_output=True, timeout=2, text=True
        )
        return result.stdout.strip()
    except Exception:
        return None


def _get_wcs_position():
    """Return (wcs_x, wcs_y) in machine units for the current WCS."""
    try:
        import linuxcnc
        s = linuxcnc.stat()
        s.poll()
        wcs_x = s.actual_position[0] - s.g5x_offset[0]
        wcs_y = s.actual_position[1] - s.g5x_offset[1]
        return wcs_x, wcs_y
    except Exception as e:
        sys.stderr.write("M510: could not read WCS position: {}\n".format(e))
        return 0.0, 0.0


def m510_fid(self, **words):
    """M510 handler: detect fiducial, store WCS position + camera offset."""
    try:
        # ---- Parse and validate words ----------------------------------------
        q_word = words.get('q', None)
        d_word = words.get('d', None)
        k_word = words.get('k', None)
        e_word = words.get('e', 10.0)
        p_word = words.get('p', None)
        if q_word is None:
            sys.stderr.write("M510 ERROR: Q word (fiducial number 1 or 2) is required.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        fid_num = int(round(float(q_word)))
        if fid_num not in (1, 2):
            sys.stderr.write("M510 ERROR: Q must be 1 or 2, got {}\n".format(fid_num))
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        if d_word is None and k_word is None:
            sys.stderr.write("M510 ERROR: D (circle diameter) or K (square side) is required.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        if p_word is None:
            sys.stderr.write("M510 ERROR: P (search area, inches) is required.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        is_square  = k_word is not None
        fid_size   = float(k_word if is_square else d_word)
        fid_search = float(p_word)
        fid_tol    = float(e_word)
        prefix     = '_fid{}_'.format(fid_num)

        # ---- Store WCS position before any processing -----------------------
        wcs_x, wcs_y = _get_wcs_position()

        # ---- Configure widget via handler HAL_IN pins -----------------------
        # These flow through UI widgets via HAL nets to camfidview HAL_IN pins.
        # Direct setp of camfidview pins is blocked once nets are connected.
        _halcmd_setp('qt_kiss.ext-fid-is-square', 1 if is_square else 0)
        _halcmd_setp('qt_kiss.ext-fid-size',      fid_size)
        _halcmd_setp('qt_kiss.ext-fid-area',      fid_search)
        _halcmd_setp('qt_kiss.ext-fid-tolerance', fid_tol)
        yield INTERP_EXECUTE_FINISH
        time.sleep(_PARAM_SETTLE)
        _halcmd_setp('qt_kiss.ext-fid-find', 1)
        # Allow GUI to propagate settings through widget nets to camfidview
        # QApplication.processEvents()
        yield INTERP_EXECUTE_FINISH
        time.sleep(_PARAM_SETTLE)

        # Trigger detection via fid_find button → net fid-find → camfidview.fid_read
        # _halcmd_setp('qt_kiss.ext-fid-find', 1)

        # ---- Wait for search_done -------------------------------------------
        deadline = time.time() + _POLL_TIMEOUT
        search_done = False
        while time.time() < deadline:
            if _halcmd_getp(_CAM + '.search_done') == 'TRUE':
                search_done = True
                break
            yield INTERP_EXECUTE_FINISH
            time.sleep(_POLL_INTERVAL)

        fid_found = search_done and (_halcmd_getp(_CAM + '.fid_found') == 'TRUE')

        # ---- Read offsets if found ------------------------------------------
        offset_x = 0.0
        offset_y = 0.0
        if fid_found:
            try:
                offset_x = float(_halcmd_getp(_CAM + '.offset_x') or 0.0)
                offset_y = float(_halcmd_getp(_CAM + '.offset_y') or 0.0)
            except (TypeError, ValueError):
                pass

        # ---- Release detection trigger --------------------------------------
        yield INTERP_EXECUTE_FINISH
        time.sleep(_VISUAL_DELAY)
        _halcmd_setp('qt_kiss.ext-fid-find', 0)

        # ---- Write named parameters -----------------------------------------
        self.params[prefix + 'x']        = wcs_x
        self.params[prefix + 'y']        = wcs_y
        self.params[prefix + 'x_offset'] = offset_x
        self.params[prefix + 'y_offset'] = offset_y
        self.params[prefix + 'found']    = 1.0 if fid_found else 0.0

        if not fid_found:
            msg = "timeout" if not search_done else "not detected"
            sys.stderr.write("M510: Fiducial Q{} {} — {}\n".format(
                fid_num, 'circle' if not is_square else 'square', msg))
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        self.params['_fid_fail'] = 0.0
        print("M510: Fiducial Q{} found — "
              "WCS=({:+.4f}, {:+.4f})  "
              "offset X={:+.4f}\" Y={:+.4f}\"".format(
                  fid_num, wcs_x, wcs_y, offset_x, offset_y))
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
