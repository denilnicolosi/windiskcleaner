"""PyInstaller entry script (it needs a plain script, not a package __main__)."""

import sys

from diskdiet.__main__ import main

sys.exit(main())
