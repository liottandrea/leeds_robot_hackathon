"""Puts the repo root on sys.path so examples can `import robot` etc.

Every example starts with `import _bootstrap  # noqa: F401`. This avoids an
install step -- run them from the repo root:

    python examples/01_hello_robot.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ohbot resolves ohbotData/ relative to the working directory, so every example
# must run from the repo root or it silently creates a second, uncalibrated copy.
if not os.path.exists(os.path.join(os.getcwd(), "config.yaml")):
    sys.stderr.write(
        "Run examples from the repo root:  python examples/{}\n".format(
            os.path.basename(sys.argv[0])
        )
    )
    sys.exit(1)
