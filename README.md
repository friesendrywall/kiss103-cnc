#SETUP 
To allow local saving of custom packages, we'll do just one edit in root,
add to usr/lib/python3/dist-packages/qtvcp/plugins/qtvcp_plugin.py
```bash
import user_plugins
from user_plugins import *
```
in ~/.designer/plugins/python add user_plugins.py

```bash
import sys
sys.path.insert(0, '/home/kiss/linuxcnc/configs/KISS103-MESA/qtvcp/plugins')
sys.path.insert(0, '/home/kiss/linuxcnc/configs/KISS103-MESA/qtvcp/widgets')

from camview_fid_plugin import CamViewFiducialPlugin

# add more here
```
