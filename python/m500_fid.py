"""
m500_fid.py — REMAP handler for M500
--------------------------------------
M500 clears all fiducial state: named parameters and HAL overlay pins.

G-code usage:
    M500

Called automatically by LinuxCNC REMAP when the interpreter sees M500.
"""

import subprocess
import sys

# REMAP return codes are available as globals in the interpreter context
# but we can also define safe fallbacks for import-time use.
try:
    from interpreter import INTERP_OK, INTERP_ERROR   # noqa: F401
except ImportError:
    INTERP_OK    = 0
    INTERP_ERROR = 1


# Named parameters to clear (all fiducial-related globals)
_NAMED_PARAMS = [
    '_fid1_x', '_fid1_y', '_fid1_x_offset', '_fid1_y_offset',
    '_fid1_found', '_fid1_conf',
    '_fid2_x', '_fid2_y', '_fid2_x_offset', '_fid2_y_offset',
    '_fid2_found', '_fid2_conf',
    '_pcb_rotation',
    '_calc_x_offset', '_calc_y_offset',
    '_fid_fail',
]

# HAL float/bit pins to reset on the camfidview component
_HAL_FLOAT_PINS = [
    'fid1-cx-px', 'fid1-cy-px', 'fid1-radius-px',
    'fid1-x-offset', 'fid1-y-offset',
    'fid2-cx-px', 'fid2-cy-px', 'fid2-radius-px',
    'fid2-x-offset', 'fid2-y-offset',
]
_HAL_BIT_PINS = ['fid1-found', 'fid2-found']


def _halcmd_setp(pin, value):
    """Write a value to a HAL pin via halcmd. Silent on failure (GUI may not be running)."""
    try:
        subprocess.run(
            ['halcmd', 'setp', 'camfidview.{}'.format(pin), str(value)],
            check=False, capture_output=True, timeout=2
        )
    except Exception:
        pass


def m500_fid(self, **words):
    """M500 handler: clear all fiducial named parameters and reset widget HAL pins."""
    try:
        # Clear named parameters via interpreter params dict
        for name in _NAMED_PARAMS:
            try:
                self.params[name] = 0.0
            except Exception as e:
                sys.stderr.write("M500: could not clear param {}: {}\n".format(name, e))

        # Reset HAL overlay pins so the widget clears any displayed overlay
        for pin in _HAL_FLOAT_PINS:
            _halcmd_setp(pin, '0.0')
        for pin in _HAL_BIT_PINS:
            _halcmd_setp(pin, '0')

        print("M500: Fiducial state cleared.")
        return INTERP_OK

    except Exception as e:
        sys.stderr.write("M500 ERROR: {}\n".format(e))
        return INTERP_ERROR
