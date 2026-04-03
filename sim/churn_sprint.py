#!/usr/bin/env python3
"""
Sprint churn scenario -- backward-compatibility wrapper.

The unified sim/churn.py now handles all topologies (grid, sprint, etc.)
based on the "topology" key in the JSON config.

This wrapper is equivalent to:
  python3 sim/churn.py --config experiments/prefix_scale/scenarios/sprint_twostep_sim_0to50.json
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sim.churn import main

if __name__ == "__main__":
    main()
