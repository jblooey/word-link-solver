"""
Diagnostic script — run this BEFORE runner.py to check if everything works.

    python3 debug_check.py

It will:
  1. Confirm calibration exists
  2. Take a screenshot and save it to debug_screenshot.png
  3. Run OCR on the board region and print what it sees
  4. Report any permission or import errors clearly
"""

import sys
import time
from pathlib import Path


def main():
    print("=" * 50)
    print("Word Link Solver — Diagnostic Check")
    print("=" * 50)
    print()

    # ── 1. calibration ────────────────────────────────
    print("[1/4] Checking calibration...")
    from screen_reader import load_calibration
    cal = load_calibration()
    if not cal:
        print("  ✗ No calibration file found.")
        print("    Fix: run  python3 calibrate.py  first.")
        sys.exit(1)
    print(f"  ✓ Calibration loaded. Board region: {cal['board']}")
    print()

    # ── 2. screenshot ─────────────────────────────────
    print("[2/4] Taking a screenshot...")
    try:
        from screen_reader import take_screenshot
        img = take_screenshot()
        print(f"  ✓ Screenshot captured: {img.shape[1]}×{img.shape[0]} pixels")
        # Save it so we can inspect it
        try:
            from PIL import Image
            Image.fromarray(img).save("debug_screenshot.png")
            print("  ✓ Saved to debug_screenshot.png — open it and check it shows your screen.")
        except Exception as e:
            print(f"  ⚠  Could not save PNG ({e}) — but screenshot still worked.")
    except Exception as e:
        print(f"  ✗ Screenshot FAILED: {e}")
        print("    Fix: System Settings → Privacy & Security → Screen Recording")
        print("         → enable Terminal (or iTerm2 / whatever you're using)")
        sys.exit(1)
    print()

    # ── 3. check if screenshot is blank ──────────────
    print("[3/4] Checking if screenshot has content...")
    import numpy as np
    brightness = img.mean()
    if brightness < 5:
        print("  ✗ Screenshot is nearly BLACK — screen recording permission is blocked.")
        print("    Fix: System Settings → Privacy & Security → Screen Recording")
        print("         → enable Terminal, then RESTART your terminal and try again.")
        sys.exit(1)
    elif brightness < 30:
        print(f"  ⚠  Screenshot looks very dark (avg brightness: {brightness:.1f}).")
        print("     This may indicate a permission issue or a very dark screen.")
    else:
        print(f"  ✓ Screenshot looks good (avg brightness: {brightness:.1f}).")
    print()

    # ── 4. OCR the board region ───────────────────────
    print("[4/4] Running OCR on board region...")
    from screen_reader import read_board
    try:
        letters, dots = read_board(img, cal)
        print("  Letters detected:")
        for row in letters:
            print("    " + "  ".join(row))
        unknown = sum(1 for row in letters for l in row if l == "?")
        if unknown == 16:
            print()
            print("  ✗ All 16 cells read as '?' — the game is not visible in the board region.")
            print("    Make sure Word Link is open and the board is on screen before running.")
            print("    Also confirm your calibration is correct for this screen/resolution.")
        elif unknown > 4:
            print(f"  ⚠  {unknown}/16 cells unrecognised. Run python3 calibrate.py again.")
        else:
            print(f"  ✓ {16 - unknown}/16 cells recognised.")
    except Exception as e:
        print(f"  ✗ OCR failed: {e}")
        sys.exit(1)
    print()

    print("=" * 50)
    print("Diagnostic complete. Open debug_screenshot.png and")
    print("check that it shows your screen with Word Link visible.")
    print("=" * 50)


if __name__ == "__main__":
    main()
