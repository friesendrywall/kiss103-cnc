"""
remap.py — LinuxCNC REMAP TOPLEVEL script
-----------------------------------------
Loaded by the interpreter at startup via:
    [PYTHON]
    TOPLEVEL = .../python/remap.py

Imports each M-code handler function so the interpreter can resolve
them by name from the REMAP= directives in the INI.
"""

import sys
import os

# Ensure this directory is on the path so sibling modules are importable
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Also ensure m_codes/ is on the path for vision_constants.py
_MCODES = os.path.join(os.path.dirname(_HERE), 'm_codes')
if _MCODES not in sys.path:
    sys.path.insert(0, _MCODES)

from m500_fid import m500_fid   # noqa: F401  (used by REMAP=M500 python=m500_fid)
from m510_fid import m510_fid   # noqa: F401  (used by REMAP=M510 python=m510_fid)
from m520_fid import m520_fid   # noqa: F401  (used by REMAP=M520 python=m520_fid)
