"""
m520_fid.py — REMAP handler for M520
--------------------------------------
M520 calculates the PCB correction offsets (and optionally rotation) from
previously stored fiducial positions.

G-code usage:
    M520 P1    ; single-fiducial: translation offset only (no rotation)
    M520 P2    ; two-fiducial:    fid1 translation + PCB rotation

Prerequisites:
    P1: M510 Q1 must have been called successfully
    P2: M510 Q1 and M510 Q2 must both have been called successfully

Named parameters written:
    #<_calc_x_offset>  — X correction to apply to WCS
    #<_calc_y_offset>  — Y correction to apply to WCS
    #<_pcb_rotation>   — PCB rotation in degrees (0.0 for P1 mode)
    #<_fid_fail>       — set to 1.0 if prerequisites not met

Applying the correction:
    P1: G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>]
    P2: G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>] R[#<_pcb_rotation>]

    G10 L2 R rotates the WCS around machine (0,0). calc_x/y account for this
    so that fiducial 1 maps exactly to its actual position after correction.
"""

import sys
import math

try:
    from interpreter import INTERP_OK, INTERP_ERROR
except ImportError:
    INTERP_OK    = 0
    INTERP_ERROR = 1


def m520_fid(self, **words):
    """M520 handler: compute PCB translation correction and (optionally) rotation."""
    try:
        p_word = words.get('p', None)
        if p_word is None:
            sys.stderr.write("M520 ERROR: P word required. Use M520P1 or M520P2.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        mode = int(round(float(p_word)))
        if mode not in (1, 2):
            sys.stderr.write("M520 ERROR: P must be 1 or 2, got {}\n".format(mode))
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        # ---- Read previously stored fiducial named parameters ---------------
        try:
            fid1_found = float(self.params['_fid1_found'])
        except (KeyError, TypeError, ValueError):
            fid1_found = 0.0

        if fid1_found != 1.0:
            sys.stderr.write("M520 ERROR: Fiducial 1 has not been detected (run M510 Q1 first).\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        try:
            fid1_x = float(self.params['_fid1_x'])
        except (KeyError, TypeError, ValueError):
            fid1_x = 0.0
        try:
            fid1_y = float(self.params['_fid1_y'])
        except (KeyError, TypeError, ValueError):
            fid1_y = 0.0
        try:
            fid1_x_offset = float(self.params['_fid1_x_offset'])
        except (KeyError, TypeError, ValueError):
            fid1_x_offset = 0.0
        try:
            fid1_y_offset = float(self.params['_fid1_y_offset'])
        except (KeyError, TypeError, ValueError):
            fid1_y_offset = 0.0

        # ---- P1: single fiducial, translation only --------------------------
        if mode == 1:
            calc_x = fid1_x_offset
            calc_y = fid1_y_offset
            rotation_deg = 0.0

            self.params['_calc_x_offset'] = calc_x
            self.params['_calc_y_offset'] = calc_y
            self.params['_pcb_rotation']  = rotation_deg

            print("M520 P1: Translation-only correction — "
                  "X={:+.4f}\" Y={:+.4f}\"".format(calc_x, calc_y))
            return INTERP_OK

        # ---- P2: two fiducials, rotation + shifted translation ---------------
        try:
            fid2_found = float(self.params['_fid2_found'])
        except (KeyError, TypeError, ValueError):
            fid2_found = 0.0

        if fid2_found != 1.0:
            sys.stderr.write("M520 ERROR: Fiducial 2 has not been detected (run M510 Q2 first).\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        try:
            fid2_x = float(self.params['_fid2_x'])
        except (KeyError, TypeError, ValueError):
            fid2_x = 0.0
        try:
            fid2_y = float(self.params['_fid2_y'])
        except (KeyError, TypeError, ValueError):
            fid2_y = 0.0
        try:
            fid2_x_offset = float(self.params['_fid2_x_offset'])
        except (KeyError, TypeError, ValueError):
            fid2_x_offset = 0.0
        try:
            fid2_y_offset = float(self.params['_fid2_y_offset'])
        except (KeyError, TypeError, ValueError):
            fid2_y_offset = 0.0

        # Nominal positions (where machine was pointed for each fiducial)
        nom1_x, nom1_y = fid1_x, fid1_y
        nom2_x, nom2_y = fid2_x, fid2_y

        # Actual positions (nominal + camera-detected offset)
        act1_x = fid1_x + fid1_x_offset
        act1_y = fid1_y + fid1_y_offset
        act2_x = fid2_x + fid2_x_offset
        act2_y = fid2_y + fid2_y_offset

        # Step 1 & 2: angles of nominal and actual fid vectors
        nom_dx = nom2_x - nom1_x
        nom_dy = nom2_y - nom1_y

        if abs(nom_dx) < 1e-9 and abs(nom_dy) < 1e-9:
            sys.stderr.write("M520 ERROR: Fiducial 1 and 2 nominal positions are identical — "
                             "cannot compute rotation.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        act_dx = act2_x - act1_x
        act_dy = act2_y - act1_y

        nom_angle = math.atan2(nom_dy, nom_dx)
        act_angle = math.atan2(act_dy, act_dx)

        # Step 3: rotation angle (positive = CCW)
        _MAX_ROTATION_DEG = 5.0
        rotation_deg = math.degrees(act_angle - nom_angle)
        if abs(rotation_deg) > _MAX_ROTATION_DEG:
            sys.stderr.write("M520 ERROR: Computed rotation {:.3f}deg exceeds limit of "
                             "+/-{}deg — check fiducial positions.\n".format(
                                 rotation_deg, _MAX_ROTATION_DEG))
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR
        theta = math.radians(rotation_deg)

        # Step 4: shifted offset — G10 L2 R rotates around WCS (0,0), so
        # translation must place fid1 at its actual position after rotation.
        # With G10 L2 P0 X[cx] Y[cy] R[rot], a move to (nom1_x, nom1_y) lands at:
        #   machine_x = cx + nom1_x*cos(theta) - nom1_y*sin(theta)
        #   machine_y = cy + nom1_x*sin(theta) + nom1_y*cos(theta)
        # Setting this equal to act1_x/y and solving:
        calc_x = nom1_x * (1 - math.cos(theta)) + nom1_y * math.sin(theta) + fid1_x_offset
        calc_y = nom1_y * (1 - math.cos(theta)) - nom1_x * math.sin(theta) + fid1_y_offset

        self.params['_calc_x_offset'] = calc_x
        self.params['_calc_y_offset'] = calc_y
        self.params['_pcb_rotation']  = rotation_deg

        print("M520 P2: Rotation+Translation correction — "
              "X={:+.4f}\" Y={:+.4f}\" Rotation={:+.4f}deg".format(
                  calc_x, calc_y, rotation_deg))
        return INTERP_OK

    except Exception as e:
        sys.stderr.write("M520 ERROR: {}\n".format(e))
        import traceback
        traceback.print_exc()
        try:
            self.params['_fid_fail'] = 1.0
        except Exception:
            pass
        return INTERP_ERROR
