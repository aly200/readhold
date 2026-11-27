"""Double-click (or point a desktop shortcut at this with pythonw) to open Readhold with no console window."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from readhold.__main__ import main  # noqa: E402

main([])
