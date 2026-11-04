"""Run the membership test suite. Exit 0 = all scenarios passed."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_membership import main

if __name__ == "__main__":
    sys.exit(main())
