"""
Screenshot + OCR for Word Link 4×4 grid.

Primary recognition: pixel-level template matching against images saved during
calibration (exact font, exact rendering — very accurate).
Fallback: pytesseract (used when no template exists for a letter yet).
"""

import json
import numpy as np
import pyautogui
import cv2
from pathlib import Path
from typing import Optional, List, Tuple

CALIBRATION_FILE = Path(__file__).parent / "word_link_calibration.json"
TEMPLATE_DIR     = Path(__file__).parent / "templates"
GRID_SIZE        = 4

# Similarity threshold for inverted cosine matching (0–1).
# Real matches score 0.93+; wrong matches score much lower.
MATCH_THRESHOLD = 0.70


# ── calibration I/O ───────────────────────────────────────────────────────────

def save_calibration(data: dict) -> None:
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_calibration() -> Optional[dict]:
    if CALIBRATION_FILE.exists():
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return None


# ── screenshot ────────────────────────────────────────────────────────────────

def take_screenshot() -> np.ndarray:
    return np.array(pyautogui.screenshot())


def take_screenshot_below(window_id: int) -> np.ndarray:
    """Capture the display excluding `window_id` (our overlay window).
    Avoids having to hide/show the overlay on every poll cycle."""
    try:
        import Quartz
        img_ref = Quartz.CGWindowListCreateImage(
            Quartz.CGRectInfinite,
            Quartz.kCGWindowListOptionOnScreenBelowWindow,
            window_id,
            Quartz.kCGWindowImageDefault,
        )
        if img_ref is None:
            return take_screenshot()
        w   = Quartz.CGImageGetWidth(img_ref)
        h   = Quartz.CGImageGetHeight(img_ref)
        bpr = Quartz.CGImageGetBytesPerRow(img_ref)
        raw = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img_ref))
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpr // 4, 4))
        return arr[:, :w, [2, 1, 0]]   # BGRA → RGB, trim row padding
    except Exception:
        return take_screenshot()


def detect_scale() -> float:
    logical_w, _ = pyautogui.size()
    return take_screenshot().shape[1] / logical_w


def _scale_box(box: list, scale: float) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return int(x1 * scale), int(y1 * scale), int(x2 * scale), int(y2 * scale)


# ── preprocessing ─────────────────────────────────────────────────────────────

def _preprocess_letter(cell: np.ndarray) -> np.ndarray:
    """
    Extract the letter from a tile and return a fixed-size binary image.

    Tiles have rounded-rectangle corners where the teal background shows
    through, creating dark pixels unrelated to the letter. Cropping the
    outer 15% on all sides removes those corner artifacts before searching
    for the letter's dark-pixel bounding box.

    Output is always 280×280 uint8 (0 = black letter, 255 = white background).
    """
    h, w = cell.shape[:2]
    gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY)

    # Strip outer 15% on all sides — eliminates rounded-corner teal artifacts
    b = int(min(h, w) * 0.15)
    inner = gray[b:h - b, b:w - b]
    ih, iw = inner.shape

    # Fixed threshold: letters are very dark (~30 gray), background is light
    # (~190 gray), dish shadow is ~150 gray. 100 cleanly separates letter from
    # everything else without Otsu accidentally capturing the dish shadow ring.
    letter_mask = inner < 100
    letter_mask[int(ih * 0.78):, :] = False   # exclude dot strip
    letter_mask[:int(ih * 0.02), :] = False    # exclude top sliver

    rows = np.where(np.any(letter_mask, axis=1))[0]
    cols = np.where(np.any(letter_mask, axis=0))[0]

    if len(rows) > 0 and len(cols) > 0:
        margin = max(4, int(min(ih, iw) * 0.05))
        r0 = max(0, int(rows[0]) - margin)
        r1 = min(ih, int(rows[-1]) + margin + 1)
        c0 = max(0, int(cols[0]) - margin)
        c1 = min(iw, int(cols[-1]) + margin + 1)
    else:
        r0, r1 = int(ih * 0.05), int(ih * 0.75)
        c0, c1 = int(iw * 0.10), int(iw * 0.90)

    letter_crop = inner[r0:r1, c0:c1]
    scaled = cv2.resize(letter_crop, (200, 200), interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(scaled, 128, 255, cv2.THRESH_BINARY)
    return cv2.copyMakeBorder(binary, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)


# ── template management ───────────────────────────────────────────────────────

# Module-level cache so we only load from disk once per session.
_template_cache: Optional[dict] = None


def _get_templates() -> dict:
    """Return cached templates, loading from disk on first call."""
    global _template_cache
    if _template_cache is None:
        _template_cache = {}
        if TEMPLATE_DIR.exists():
            for path in TEMPLATE_DIR.glob("*.png"):
                token = path.stem.upper()
                if token.isalpha():
                    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                    if img is not None:
                        # Invert: letter pixels → bright, background → 0.
                        # Cosine similarity then measures letter-shape overlap
                        # rather than background overlap, making it far more
                        # discriminative between visually similar letters.
                        inv = (255 - img).astype(np.float32)
                        vec = inv.ravel()
                        norm = np.linalg.norm(vec)
                        if norm > 0:
                            _template_cache[token] = (vec, norm)
    return _template_cache


def save_template(preprocessed: np.ndarray, letter: str) -> None:
    """Persist a preprocessed cell image as the template for this letter."""
    global _template_cache
    TEMPLATE_DIR.mkdir(exist_ok=True)
    cv2.imwrite(str(TEMPLATE_DIR / f"{letter.upper()}.png"), preprocessed)
    _template_cache = None   # invalidate cache so it reloads


def clear_templates() -> None:
    """Delete all saved templates (called at the start of calibration)."""
    global _template_cache
    if TEMPLATE_DIR.exists():
        for p in TEMPLATE_DIR.glob("?.png"):
            p.unlink()
    _template_cache = None


def _top_right_open_ratio(preprocessed: np.ndarray) -> float:
    """
    Dark pixel fraction in the upper-right opening zone of G/O.
    G has zero dark pixels here (the letter opens to the right);
    O has a thin arc stroke here (~0.018-0.033).
    Region chosen from measured pixel data: G=0.000, O=0.018-0.033.
    """
    h, w = preprocessed.shape
    region = preprocessed[int(h * 0.25):int(h * 0.45), int(w * 0.78):int(w * 0.93)]
    if region.size == 0:
        return 1.0
    return float((region < 128).sum()) / region.size


def _bottom_bar_ratio(preprocessed: np.ndarray) -> float:
    """
    Dark pixel fraction in the bottom-right area (avoiding the shared left vertical stroke).
    E's bottom horizontal bar extends here; F has nothing on the right side at the bottom.
    """
    h, w = preprocessed.shape
    region = preprocessed[int(h * 0.65):int(h * 0.88), int(w * 0.40):int(w * 0.88)]
    if region.size == 0:
        return 0.0
    return float((region < 128).sum()) / region.size


def _count_enclosed_white(preprocessed: np.ndarray) -> int:
    """
    Count white (background) regions that are completely enclosed by dark ink.
    Uses connected-components on the white pixels; any component that touches
    the image border is the outer background — everything else is an interior hole.

    B → 2  (one hole per bump)
    D → 1  (single interior cavity)
    S → 0  (both arcs are open; white connects to background)
    """
    binary = (preprocessed > 128).astype(np.uint8)   # white=1, black letter=0
    num_labels, labels = cv2.connectedComponents(binary, connectivity=4)

    h, w = labels.shape
    border_labels: set = set()
    border_labels.update(labels[0, :].tolist())
    border_labels.update(labels[-1, :].tolist())
    border_labels.update(labels[:, 0].tolist())
    border_labels.update(labels[:, -1].tolist())

    return sum(1 for i in range(1, num_labels) if i not in border_labels)


def _match_template(preprocessed: np.ndarray) -> Optional[str]:
    """
    Compare a preprocessed cell image against all saved templates using
    cosine similarity. Returns the best-matching letter if above threshold,
    else None (falls through to tesseract).
    """
    templates = _get_templates()
    if not templates:
        return None

    query = (255 - preprocessed).astype(np.float32).ravel()
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return None

    best_letter = None
    best_score  = MATCH_THRESHOLD  # minimum to accept

    for letter, (vec, norm) in templates.items():
        if len(vec) != len(query):
            continue
        score = float(np.dot(query, vec) / (q_norm * norm))
        if score > best_score:
            best_score  = score
            best_letter = letter

    return best_letter


# ── letter OCR (tesseract fallback) ───────────────────────────────────────────

def _tesseract_ocr(preprocessed: np.ndarray) -> str:
    """Single-letter recognition via pytesseract, trying multiple PSM modes."""
    try:
        import pytesseract
        from PIL import Image
        pil = Image.fromarray(preprocessed)
        whitelist = "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for psm in (8, 13, 7):
            text = pytesseract.image_to_string(
                pil, config=f"--psm {psm} --oem 3 {whitelist}"
            ).strip().upper()
            ch = next((c for c in text if c.isalpha()), None)
            if ch:
                return ch
        # Narrow-image heuristic: very thin binary blob → I
        cols = np.any(preprocessed < 128, axis=0)
        rows = np.any(preprocessed < 128, axis=1)
        if rows.sum() > 0 and cols.sum() / rows.sum() < 0.25:
            return "I"
    except Exception:
        pass
    return "?"


def _ocr_cell(cell: np.ndarray) -> str:
    """Recognize a single letter: template match first, tesseract fallback."""
    preprocessed = _preprocess_letter(cell)
    letter = _match_template(preprocessed)

    # G vs O: G=0.000, O=0.018-0.033 in the measured opening region
    if letter in ("O", "G"):
        ratio = _top_right_open_ratio(preprocessed)
        if ratio < 0.010:
            letter = "G"
        elif ratio > 0.014:
            letter = "O"

    # F vs E: E has a bottom bar extending right; F has nothing on the right at the bottom
    if letter in ("E", "F"):
        ratio = _bottom_bar_ratio(preprocessed)
        if ratio < 0.07:
            letter = "F"
        elif ratio > 0.14:
            letter = "E"

    # B / D / S disambiguation via enclosed white hole count (topological):
    #   B → 2 holes (one per bump)
    #   D → 1 hole  (single interior cavity)
    #   S → 0 holes (open arcs, white connects to background)
    if letter in ("B", "D", "S"):
        holes = _count_enclosed_white(preprocessed)
        if holes >= 2:
            letter = "B"
        elif holes == 1:
            letter = "D"
        else:
            letter = "S"

    if letter:
        return letter
    return _tesseract_ocr(preprocessed)


# ── dot counting ──────────────────────────────────────────────────────────────

def _count_dots(cell: np.ndarray) -> int:
    """Count 1–4 score dots in the bottom strip of a tile."""
    h, w = cell.shape[:2]
    strip = cell[int(h * 0.70) : int(h * 0.90), int(w * 0.10) : int(w * 0.90)]
    if strip.size == 0:
        return 1
    gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    num, _, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    sh, sw = strip.shape[:2]
    dots = 0
    for i in range(1, num):
        area = stats[i, cv2.CC_STAT_AREA]
        bw   = stats[i, cv2.CC_STAT_WIDTH]
        bh_  = stats[i, cv2.CC_STAT_HEIGHT]
        cx   = centroids[i][0]
        cy   = centroids[i][1]
        if bh_ == 0 or bw == 0:
            continue
        aspect = bw / bh_
        if (
            4 < area < 300
            and 0.4 < aspect < 2.5
            and sw * 0.05 < cx < sw * 0.95
            and sh * 0.1  < cy < sh * 0.9
        ):
            dots += 1
    return max(1, min(4, dots if dots else 1))


# ── board reading ─────────────────────────────────────────────────────────────

# Per-cell OCR cache: maps (r, c, pixel_hash) → (letter, dot_count).
# Avoids re-OCRing cells whose pixels haven't changed between polls.
_cell_ocr_cache: dict = {}


def read_board(
    img: np.ndarray, cal: dict
) -> Tuple[List[List[str]], List[List[int]]]:
    """
    OCR the 4×4 board from a screenshot.
    Returns:
        letters    — 4×4 list of uppercase chars ('?' if unrecognised)
        dot_scores — 4×4 list of int 1–4
    """
    scale = cal.get("scale", 1.0)
    bx1, by1, bx2, by2 = _scale_box(cal["board"], scale)
    region = img[by1:by2, bx1:bx2]
    h, w = region.shape[:2]
    cell_h = h / GRID_SIZE
    cell_w = w / GRID_SIZE

    letters: List[List[str]] = []
    dot_scores: List[List[int]] = []

    for r in range(GRID_SIZE):
        row_l, row_d = [], []
        for c in range(GRID_SIZE):
            y1 = int(r * cell_h)
            y2 = int((r + 1) * cell_h)
            x1 = int(c * cell_w)
            x2 = int((c + 1) * cell_w)
            cell = region[y1:y2, x1:x2]

            # Hash the raw cell pixels — if unchanged, skip expensive OCR
            cell_hash = cell.tobytes()
            cached = _cell_ocr_cache.get((r, c))
            if cached and cached[0] == cell_hash:
                letter, dot = cached[1], cached[2]
            else:
                letter = _ocr_cell(cell)
                dot    = _count_dots(cell)
                _cell_ocr_cache[(r, c)] = (cell_hash, letter, dot)

            row_l.append(letter)
            row_d.append(dot)
        letters.append(row_l)
        dot_scores.append(row_d)

    return letters, dot_scores


# ── debug helper ──────────────────────────────────────────────────────────────

def save_debug_cells(img: np.ndarray, cal: dict, out_dir: str = "debug_cells") -> None:
    """Save raw + preprocessed images for each cell to inspect OCR issues."""
    from PIL import Image
    Path(out_dir).mkdir(exist_ok=True)
    scale = cal.get("scale", 1.0)
    bx1, by1, bx2, by2 = _scale_box(cal["board"], scale)
    region = img[by1:by2, bx1:bx2]
    h, w = region.shape[:2]
    cell_h, cell_w = h / GRID_SIZE, w / GRID_SIZE
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            y1, y2 = int(r * cell_h), int((r + 1) * cell_h)
            x1, x2 = int(c * cell_w), int((c + 1) * cell_w)
            cell = region[y1:y2, x1:x2]
            Image.fromarray(cell).save(f"{out_dir}/cell_{r}{c}_raw.png")
            Image.fromarray(_preprocess_letter(cell)).save(f"{out_dir}/cell_{r}{c}_pre.png")
    print(f"Saved to {out_dir}/")
