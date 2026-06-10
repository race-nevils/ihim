"""Windowless startup shim — contract kept for start_ihim.vbs (shell:startup),
which runs `pythonw run_silent.py` from the main repo. All real logic lives
in run.py; this just quiets the log level for background operation.
"""

import sys

sys.argv = [sys.argv[0], "--log-level", "error"]

from run import main

if __name__ == "__main__":
    main()
