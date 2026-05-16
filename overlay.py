"""
Transparent click-through overlay for Word Link.

Draws the swipe path of the best word directly on top of the game:
  - Gold circle on the START cell (where to place your finger)
  - Numbered green circles on each subsequent cell
  - Arrows connecting cells in swipe order
  - Word label shown above the board
"""

import tkinter as tk
from typing import List, Tuple

GRID_SIZE = 4
START_COLOR  = "#FFD700"   # gold  — start here
STEP_COLOR   = "#00E676"   # green — subsequent cells
LINE_COLOR   = "#FFFFFF"   # white connecting arrows
TEXT_COLOR   = "#000000"   # black numbers inside circles
LABEL_COLOR  = "#FFD700"   # gold word label


class WordLinkOverlay:
    _TITLE = "__wl_overlay__"

    def __init__(self, cal: dict) -> None:
        bx1, by1, bx2, by2 = cal["board"]
        self.bx1     = bx1
        self.by1     = by1
        self.cell_w  = (bx2 - bx1) / GRID_SIZE
        self.cell_h  = (by2 - by1) / GRID_SIZE

        self.root = tk.Tk()
        self.root.title(self._TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparent", True)
        self.root.config(bg="systemTransparent")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(
            self.root, width=sw, height=sh,
            bg="systemTransparent", highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.update()
        self._set_click_through()

    def _set_click_through(self) -> None:
        try:
            from AppKit import NSApp
            for win in NSApp.windows():
                if str(win.title()) == self._TITLE:
                    win.setIgnoresMouseEvents_(True)
                    break
        except Exception:
            pass

    def window_id(self) -> int:
        """Return the Quartz window ID so callers can screenshot below us."""
        try:
            import Quartz
            wl = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
            )
            for win in wl:
                if win.get("kCGWindowName") == self._TITLE:
                    return int(win["kCGWindowNumber"])
        except Exception:
            pass
        return 0

    # ── geometry helpers ──────────────────────────────────────────────────────

    def _center(self, r: int, c: int) -> Tuple[float, float]:
        return (
            self.bx1 + (c + 0.5) * self.cell_w,
            self.by1 + (r + 0.5) * self.cell_h,
        )

    # ── drawing ───────────────────────────────────────────────────────────────

    def show(self, word: str, path: List[Tuple[int, int]]) -> None:
        """Render the word path on screen."""
        self.canvas.delete("all")
        if not path:
            self.root.update()
            return

        centers = [self._center(r, c) for r, c in path]
        radius    = min(self.cell_w, self.cell_h) * 0.30
        font_size = max(11, int(radius * 0.85))

        # ── connecting arrows (drawn behind circles) ──────────────────────
        for i in range(len(centers) - 1):
            x1, y1 = centers[i]
            x2, y2 = centers[i + 1]
            # Dark shadow
            self.canvas.create_line(
                x1 + 2, y1 + 2, x2 + 2, y2 + 2,
                fill="black", width=5, capstyle="round",
            )
            # White arrow
            self.canvas.create_line(
                x1, y1, x2, y2,
                fill=LINE_COLOR, width=3, capstyle="round",
                arrow="last", arrowshape=(14, 17, 5),
            )

        # ── circles at each cell ──────────────────────────────────────────
        for i, (cx, cy) in enumerate(centers):
            color = START_COLOR if i == 0 else STEP_COLOR
            label = "★" if i == 0 else str(i + 1)

            # Drop shadow
            self.canvas.create_oval(
                cx - radius + 2, cy - radius + 2,
                cx + radius + 2, cy + radius + 2,
                fill="black", outline="",
            )
            # Filled circle
            self.canvas.create_oval(
                cx - radius, cy - radius,
                cx + radius, cy + radius,
                fill=color, outline="white", width=2,
            )
            # Step number / star
            self.canvas.create_text(
                cx, cy, text=label,
                fill=TEXT_COLOR, font=("Arial", font_size, "bold"),
            )

        # ── word label above board ────────────────────────────────────────
        lx = self.bx1 + 2 * self.cell_w
        ly = max(22, self.by1 - 32)
        self.canvas.create_text(lx + 2, ly + 2, text=word,
                                 fill="black", font=("Arial", 22, "bold"))
        self.canvas.create_text(lx, ly, text=word,
                                 fill=LABEL_COLOR, font=("Arial", 22, "bold"))

        self.root.update()

    def clear(self) -> None:
        self.canvas.delete("all")
        self.root.update()

    def tick(self) -> None:
        """Keep tkinter event loop alive without blocking."""
        try:
            self.root.update()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
