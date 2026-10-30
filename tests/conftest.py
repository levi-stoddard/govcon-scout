"""Pytest setup: put the project root on sys.path so tests import modules directly."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
