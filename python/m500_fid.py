"""
m500_fid.py — REMAP handler for M500
--------------------------------------
M500 resets fiducial HAL pins on the UI widget.

G-code usage:
    M500

Called automatically by LinuxCNC REMAP when the interpreter sees M500.
"""

import subprocess
import sys

try:
    from interpreter import INTERP_OK, INTERP_ERROR   # noqa: F401
except ImportError:
    INTERP_OK    = 0
    INTERP_ERROR = 1


def _halcmd_setp(pin, value):
    """Write a value to a HAL pin via halcmd. Silent on failure."""
    try:
        subprocess.run(
            ['halcmd', 'setp', pin, str(value)],
            check=False, capture_output=True, timeout=2
        )
    except Exception:
        pass


def m500_fid(self, **words):
    """M500 handler: reset fiducial HAL pins."""
    try:
        _halcmd_setp('qt_kiss.camfidview.fid_read',   0)

        print("M500: Fiducial state cleared.")
        return INTERP_OK

    except Exception as e:
        sys.stderr.write("M500 ERROR: {}\n".format(e))
        return INTERP_ERROR
