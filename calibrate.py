"""
One-time calibration for Word Link.

  python3 calibrate.py

Hover at the two board corners. The script auto-detects all 16 letters,
lets you correct any wrong ones, then saves both the board coordinates
AND pixel templates from that exact screenshot so future detection is
anchored to your actual game rendering.
"""

import time
import pyautogui
from screen_reader import (
    save_calibration, take_screenshot, detect_scale,
    save_template, _preprocess_letter,
    _scale_box, _count_dots, _match_template, GRID_SIZE,
)


def calibrate():
    def _capture(label: str):
        print(f"\n  >> Hover cursor at: {label}")
        input("     Press Enter to capture...")
        pos = pyautogui.position()
        print(f"     Captured: ({pos.x}, {pos.y})")
        return pos.x, pos.y

    print("=" * 54)
    print("   WORD LINK — SCREEN CALIBRATION")
    print("=" * 54)
    print()
    print("Before starting:")
    print("  1. Open iPhone Mirroring / Zoom and launch Word Link.")
    print("  2. Make sure the 4×4 letter grid is fully visible.")
    print()
    input("Press Enter when ready...")

    scale = detect_scale()
    print(f"\n  Display scale: {scale:.1f}x {'(retina)' if scale > 1 else ''}")

    print("\n── Board corners ─────────────────────────────────────")
    print("  Hover at the EXACT corners of the 4×4 letter grid.")
    bx1, by1 = _capture("TOP-LEFT corner of the letter grid")
    bx2, by2 = _capture("BOTTOM-RIGHT corner of the letter grid")

    cal = {"board": [bx1, by1, bx2, by2], "scale": scale}

    print("\n  Taking screenshot...")
    time.sleep(0.3)
    img = take_screenshot()

    # Crop and split into cells
    bx1s, by1s, bx2s, by2s = _scale_box(cal["board"], scale)
    region = img[by1s:by2s, bx1s:bx2s]
    h, w = region.shape[:2]
    cell_h, cell_w = h / GRID_SIZE, w / GRID_SIZE

    cells = []
    for r in range(GRID_SIZE):
        row_cells = []
        for c in range(GRID_SIZE):
            y1, y2 = int(r * cell_h), int((r + 1) * cell_h)
            x1, x2 = int(c * cell_w), int((c + 1) * cell_w)
            row_cells.append(region[y1:y2, x1:x2])
        cells.append(row_cells)

    # Auto-detect letters
    preprocessed = [[_preprocess_letter(cells[r][c]) for c in range(GRID_SIZE)]
                    for r in range(GRID_SIZE)]
    detected = [[(_match_template(preprocessed[r][c]) or '?') for c in range(GRID_SIZE)]
                for r in range(GRID_SIZE)]

    dot_chars = {1: "·", 2: "··", 3: "···", 4: "····"}

    # ── row-by-row confirm / correct ─────────────────────────────────────────
    def _parse_tokens(raw: str) -> list:
        tokens, i = [], 0
        while i < len(raw):
            if raw[i:i+2] == "QU":
                tokens.append("QU"); i += 2
            elif raw[i].isalpha():
                tokens.append(raw[i]); i += 1
            else:
                i += 1
        return tokens

    print()
    print("── Confirm detected letters ──────────────────────────")
    print("  Press Enter to accept a row, or type the correct")
    print("  letters to override (e.g. EPUC or AQUB for Qu tile).")
    print()

    final_letters = []
    for r in range(GRID_SIZE):
        dots_str = "  ".join(dot_chars.get(_count_dots(cells[r][c]), "?")
                             for c in range(GRID_SIZE))
        det_str  = " ".join(f"{detected[r][c]:2s}" for c in range(GRID_SIZE))
        print(f"  Row {r+1} dots:     {dots_str}")
        print(f"  Row {r+1} detected: {det_str}")

        while True:
            raw = input(f"  Row {r+1} (Enter=accept): ").strip().upper().replace(" ", "")
            if raw == "":
                row_letters = detected[r][:]
                break
            tokens = _parse_tokens(raw)
            if len(tokens) == GRID_SIZE:
                row_letters = tokens
                break
            print(f"  ✗  Need exactly {GRID_SIZE} tiles.")
        final_letters.append(row_letters)
        print()

    # ── save templates from this exact screenshot ─────────────────────────────
    saved_letters = set()
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            letter = final_letters[r][c]
            if letter != '?' and letter not in saved_letters:
                save_template(preprocessed[r][c], letter)
                saved_letters.add(letter)

    print(f"  Templates updated for: {' '.join(sorted(saved_letters))}")

    # ── show final board ──────────────────────────────────────────────────────
    print("\n  Final board:")
    for r in range(GRID_SIZE):
        row_str = "  "
        for c in range(GRID_SIZE):
            d = dot_chars.get(_count_dots(cells[r][c]), "?")
            row_str += f"  {final_letters[r][c]}({d})"
        print(row_str)

    ans = input("\n  Save calibration? (y/n): ").strip().lower()
    if ans == "y":
        save_calibration(cal)
        print("\n  Saved! Run:  python3 runner.py")
    else:
        print("  Discarded. Re-run calibrate.py to try again.")


if __name__ == "__main__":
    calibrate()
