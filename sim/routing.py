#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sim.scalability import main


if __name__ == "__main__":
    raise SystemExit(main(routing=True))