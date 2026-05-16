"""
Continuous Word Link solver.

Watches the board for changes. When a new board appears:
  1. Hides the overlay so it doesn't interfere with the screenshot
  2. Waits 1 second (board settles)
  3. Solves and displays the best word
  4. Holds that suggestion until the board changes again

Usage:
  python3 runner.py
"""

import os
import select
import sys
import time
from collections import deque
from pathlib import Path
from typing import List, Optional, Tuple

from solver import load_word_set, build_trie, find_all_words, GRID_SIZE
from screen_reader import load_calibration, take_screenshot, take_screenshot_below, read_board
from overlay import WordLinkOverlay

THINK_DELAY      = 0.20  # seconds to wait after a confirmed board change
POLL_DELAY       = 0.10  # seconds between board checks
STABILITY_NEEDED = 2     # consecutive identical reads required to confirm a new board
TOP_N = 8

DOT_SYMS   = {1: "·", 2: "··", 3: "···", 4: "····"}
STEP_LABELS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯"


# ── display helpers ───────────────────────────────────────────────────────────

def _clear():
    os.system("clear" if os.name == "posix" else "cls")


def _render_board(
    letters: List[List[str]],
    dots: List[List[int]],
    path: Optional[List[Tuple[int, int]]] = None,
) -> str:
    path_map = {(r, c): i + 1 for i, (r, c) in enumerate(path)} if path else {}
    lines = []
    lines.append("  ┌────┬────┬────┬────┐")
    for r in range(GRID_SIZE):
        top_row = "  │"
        for c in range(GRID_SIZE):
            step = path_map.get((r, c))
            if step:
                top_row += f"\033[7m {STEP_LABELS[step - 1]}{letters[r][c]}\033[0m│"
            else:
                top_row += f"  {letters[r][c]} │"
        lines.append(top_row)
        dot_row = "  │"
        for c in range(GRID_SIZE):
            d = DOT_SYMS.get(dots[r][c], "?")
            dot_row += f"{d:^4}│"
        lines.append(dot_row)
        if r < GRID_SIZE - 1:
            lines.append("  ├────┼────┼────┼────┤")
        else:
            lines.append("  └────┴────┴────┴────┘")
    return "\n".join(lines)


def _path_str(path: List[Tuple[int, int]], letters: List[List[str]]) -> str:
    return "→".join(letters[r][c] for r, c in path)


def _print_results(
    letters: List[List[str]],
    dots: List[List[int]],
    words: List[Tuple[str, List[Tuple[int, int]], int]],
) -> None:
    _clear()
    best_path = words[0][1] if words else None
    print(_render_board(letters, dots, best_path))
    print()
    unknowns = [(r, c) for r in range(GRID_SIZE) for c in range(GRID_SIZE)
                if letters[r][c] == "?"]
    if unknowns:
        coords = ", ".join(f"row{r+1}col{c+1}" for r, c in unknowns)
        print(f"  ⚠  OCR missed: {coords} — words through those cells won't appear\n")
    if not words:
        print("  No words found — check calibration or board OCR.")
        return
    print(f"  {'WORD':<12} {'LEN':>3}  {'SCORE':>5}  PATH")
    print("  " + "─" * 52)
    for i, (word, path, score) in enumerate(words[:TOP_N]):
        marker = "▶ " if i == 0 else "  "
        p = _path_str(path, letters)
        print(f"  {marker}{word:<10} {len(word):>3}  {score:>5}  {p}")
    print()
    print(f"  {len(words)} words found.")
    print(f"  Enter → not a word (remove + show next)   Ctrl-C → quit")


# ── word removal ─────────────────────────────────────────────────────────────

def _remove_from_files(word: str) -> None:
    """Delete a word (case-insensitive) from both word list files on disk."""
    w = word.lower()
    for fname in ("words_common.txt", "words.txt"):
        p = Path(__file__).parent / fname
        if p.exists():
            lines = p.read_text().splitlines()
            p.write_text("\n".join(l for l in lines if l.strip().lower() != w) + "\n")


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    cal = load_calibration()
    if not cal:
        print("No calibration found. Run:  python3 calibrate.py")
        sys.exit(1)

    print("Loading word list…")
    words_set = load_word_set()
    print("Building trie…")
    trie = build_trie(words_set)
    print("Ready.\n")
    time.sleep(0.5)

    import subprocess

    print("Starting overlay…")
    overlay = None
    wid = 0

    # Test tkinter in a throwaway subprocess with a hard 5-second timeout.
    # If Tk hangs (common on some macOS Python builds), the subprocess is killed
    # cleanly and we fall back to terminal-only mode — main process never blocks.
    tk_ok = False
    try:
        probe = subprocess.run(
            [sys.executable, "-c",
             "import tkinter; r = tkinter.Tk(); r.destroy(); print('ok')"],
            timeout=5.0,
            capture_output=True,
            text=True,
        )
        tk_ok = probe.returncode == 0 and "ok" in probe.stdout
    except subprocess.TimeoutExpired:
        print("Overlay timed out — running in terminal-only mode.\n")
    except Exception:
        print("Overlay unavailable — running in terminal-only mode.\n")

    if tk_ok:
        try:
            overlay = WordLinkOverlay(cal)
            wid = overlay.window_id()
            print("Overlay ready. Watching board…\n")
        except Exception as e:
            print(f"Overlay failed ({e}) — running in terminal-only mode.\n")

    prev_letters: Optional[List[List[str]]] = None
    cached_words: List = []
    cur_letters:  Optional[List[List[str]]] = None
    cur_dots:     Optional[List[List[int]]] = None
    banned_words: set = set()   # removed this session; filtered from future solves
    # Rolling window of recent raw reads — board only confirmed when all agree
    recent: deque = deque(maxlen=STABILITY_NEEDED)

    def _tick():
        if overlay:
            overlay.tick()

    def _check_stdin() -> None:
        """If Enter was pressed, remove the top word and show the next one."""
        nonlocal cached_words
        try:
            if not select.select([sys.stdin], [], [], 0)[0]:
                return
            sys.stdin.readline()
            if not cached_words or cur_letters is None:
                return
            bad_word = cached_words[0][0]
            banned_words.add(bad_word)
            _remove_from_files(bad_word)
            cached_words = cached_words[1:]
            print(f"  ✗ Removed '{bad_word}'")
            if cached_words:
                if overlay:
                    overlay.show(cached_words[0][0], cached_words[0][1])
                _print_results(cur_letters, cur_dots, cached_words)
            else:
                if overlay:
                    overlay.clear()
                _clear()
                print(_render_board(cur_letters, cur_dots))
                print("\n  No more words.")
        except (EOFError, OSError):
            pass

    try:
        while True:
            img = take_screenshot_below(wid) if wid else take_screenshot()
            letters, dots = read_board(img, cal)

            recent.append(letters)

            board_stable = (
                len(recent) == STABILITY_NEEDED
                and all(r == recent[0] for r in recent)
            )

            if board_stable and letters != prev_letters:
                prev_letters = [row[:] for row in letters]
                cur_letters  = letters
                cur_dots     = dots

                deadline = time.time() + THINK_DELAY
                while time.time() < deadline:
                    _tick()
                    time.sleep(0.05)

                all_words    = find_all_words(letters, trie, dots)
                cached_words = [w for w in all_words if w[0] not in banned_words]
                if cached_words:
                    if overlay:
                        overlay.show(cached_words[0][0], cached_words[0][1])
                else:
                    if overlay:
                        overlay.clear()

                _print_results(letters, dots, cached_words)

            else:
                _check_stdin()
                deadline = time.time() + POLL_DELAY
                while time.time() < deadline:
                    _tick()
                    time.sleep(0.05)

    except KeyboardInterrupt:
        if overlay:
            overlay.close()
        print("\n  Bye!")


if __name__ == "__main__":
    main()
