#!/usr/bin/env python3
"""
Sprint churn scenario — backward-compatibility wrapper.

The unified emu/churn.py now handles all topologies (grid, sprint, etc.)
based on the "topology" key in the JSON config.

This wrapper is equivalent to:
  sudo python3 emu/churn.py --config scenarios/churn_sprint.json
"""

import sys
import os

from mininet.log import setLogLevel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from emu.churn import main

if __name__ == "__main__":
    setLogLevel("info")
    main()
