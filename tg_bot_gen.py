"""
GummyFlux Telegram Bot Entry Point.
Modularized implementation located in D:\\AI\\bot\\
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from bot.main import main

if __name__ == "__main__":
    main()