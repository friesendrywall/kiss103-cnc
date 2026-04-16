"""
m520_fid.py — REMAP handler for M520
--------------------------------------
M520 calculates the PCB correction offsets (and optionally rotation) from
previously stored fiducial positions.

G-code usage:
    M520 P1    ; single-fiducial: translation offset only (no rotation)
    M520 P2    ; two-fiducial:    midpoint translation + PCB rotation

Prerequisites:
    P1: M510 P1 must have been called successfully
    P2: M510 P1 and M510 P2 must both have been called successfully

Named parameters written:
    #<_calc_x_offset>  — X correction to apply to WCS (G10/G92)
    #<_calc_y_offset>  — Y correction to apply to WCS
    #<_pcb_rotation>   — PCB rotation in degrees (0.0 for P1 mode)
    #<_fid_fail>       — set to 1.0 if prerequisites not met

Offset conventions (both modes):
    Positive X offset means the PCB is shifted RIGHT of nominal.
    Positive Y offset means the PCB is shifted UP (in machine Y) of nominal.
    Apply to WCS with: G10 L2 P0 X[#<_calc_x_offset>] Y[#<_calc_y_offset>]
    (or add to existing WCS, depending on your workflow)
"""

import sys
import math

try:
    from interpreter import INTERP_OK, INTERP_EXECUTE_FINISH, INTERP_ERROR
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
            fid1_found = float(self.params.get('_fid1_found', 0.0))
        except Exception:
            fid1_found = 0.0

        if fid1_found != 1.0:
            sys.stderr.write("M520 ERROR: Fiducial 1 has not been detected (run M510 N1 first).\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        fid1_x        = float(self.params.get('_fid1_x',        0.0))
        fid1_y        = float(self.params.get('_fid1_y',        0.0))
        fid1_x_offset = float(self.params.get('_fid1_x_offset', 0.0))
        fid1_y_offset = float(self.params.get('_fid1_y_offset', 0.0))

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

        # ---- P2: two fiducials, midpoint translation + rotation -------------
        try:
            fid2_found = float(self.params.get('_fid2_found', 0.0))
        except Exception:
            fid2_found = 0.0

        if fid2_found != 1.0:
            sys.stderr.write("M520 ERROR: Fiducial 2 has not been detected (run M510 N2 first).\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        fid2_x        = float(self.params.get('_fid2_x',        0.0))
        fid2_y        = float(self.params.get('_fid2_y',        0.0))
        fid2_x_offset = float(self.params.get('_fid2_x_offset', 0.0))
        fid2_y_offset = float(self.params.get('_fid2_y_offset', 0.0))

        # Nominal positions (where machine was pointed for each fiducial)
        nom1_x, nom1_y = fid1_x, fid1_y
        nom2_x, nom2_y = fid2_x, fid2_y

        # Actual positions (nominal + camera-detected offset)
        act1_x = fid1_x + fid1_x_offset
        act1_y = fid1_y + fid1_y_offset
        act2_x = fid2_x + fid2_x_offset
        act2_y = fid2_y + fid2_y_offset

        # Rotation: angle of actual fid vector minus angle of nominal fid vector
        nom_dx = nom2_x - nom1_x
        nom_dy = nom2_y - nom1_y
        act_dx = act2_x - act1_x
        act_dy = act2_y - act1_y

        if abs(nom_dx) < 1e-9 and abs(nom_dy) < 1e-9:
            sys.stderr.write("M520 ERROR: Fiducial 1 and 2 nominal positions are identical — "
                             "cannot compute rotation.\n")
            self.params['_fid_fail'] = 1.0
            return INTERP_ERROR

        nom_angle = math.atan2(nom_dy, nom_dx)
        act_angle = math.atan2(act_dy, act_dx)
        rotation_deg = math.degrees(act_angle - nom_angle)

        # Translation: midpoint of actual positions minus midpoint of nominal positions
        calc_x = ((act1_x + act2_x) - (nom1_x + nom2_x)) / 2.0
        calc_y = ((act1_y + act2_y) - (nom1_y + nom2_y)) / 2.0

        self.params['_calc_x_offset'] = calc_x
        self.params['_calc_y_offset'] = calc_y
        self.params['_pcb_rotation']  = rotation_deg

        print("M520 P2: Rotation+Translation correction — "
              "X={:+.4f}\" Y={:+.4f}\" Rotation={:+.4f}°".format(
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
