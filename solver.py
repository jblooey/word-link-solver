"""
Boggle-style word finder for a 4×4 letter grid.

Words are found by swiping through adjacent cells (including diagonals).
Each cell can only be used once per word.
"""

from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path

GRID_SIZE = 4
MIN_LEN = 3

# Precomputed adjacency for speed
def _adj(r: int, c: int) -> List[Tuple[int, int]]:
    return [
        (r + dr, c + dc)
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if (dr or dc) and 0 <= r + dr < GRID_SIZE and 0 <= c + dc < GRID_SIZE
    ]

_NEIGHBORS = [[_adj(r, c) for c in range(GRID_SIZE)] for r in range(GRID_SIZE)]


def load_word_set(path: Optional[str] = None) -> Set[str]:
    """Load words from file. Prefers words_common.txt (frequency-filtered, ~42k words)
    over the full ENABLE list to match real word game vocabulary."""
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates += [
        Path(__file__).parent / "words_common.txt",   # frequency-filtered (preferred)
        Path(__file__).parent / "words.txt",           # full ENABLE fallback
        Path("/usr/share/dict/words"),
    ]
    for p in candidates:
        if p.exists():
            words = set()
            with open(p) as f:
                for line in f:
                    w = line.strip()
                    if MIN_LEN <= len(w) <= 16 and w.isalpha() and w.islower():
                        words.add(w.upper())
            print(f"  Loaded {len(words):,} words from {p.name}")
            return words
    raise FileNotFoundError("No word list found. Run: bash download_words.sh")


def build_trie(words: Set[str]) -> Dict:
    """Build prefix trie for O(1) prefix pruning during DFS."""
    root: Dict = {}
    for word in words:
        node = root
        for ch in word:
            node = node.setdefault(ch, {})
        node[""] = True  # end-of-word marker
    return root


def find_all_words(
    letters: List[List[str]],
    trie: Dict,
    dot_scores: Optional[List[List[int]]] = None,
) -> List[Tuple[str, List[Tuple[int, int]], int]]:
    """
    DFS over grid to find every valid word.
    Returns list of (word, path, score) sorted by (length desc, score desc).
    Score = word_length + sum of dot values along path.
    """
    best: Dict[str, Tuple[List[Tuple[int, int]], int]] = {}

    def dfs(r: int, c: int, visited: Set, word: str, node: Dict, path: List):
        ch = letters[r][c]  # may be multi-char like "QU"
        cur = node
        for char in ch:
            if char not in cur:
                return
            cur = cur[char]
        node = cur
        word = word + ch
        path = path + [(r, c)]

        if "" in node and len(word) >= MIN_LEN:
            n = len(word)
            total_dots = sum(dot_scores[pr][pc] for pr, pc in path) if dot_scores else n
            score = (15 * n - 10) * total_dots
            if word not in best or score > best[word][1]:
                best[word] = (path[:], score)

        visited.add((r, c))
        for nr, nc in _NEIGHBORS[r][c]:
            if (nr, nc) not in visited:
                dfs(nr, nc, visited, word, node, path)
        visited.discard((r, c))

    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            dfs(r, c, set(), "", trie, [])

    results = [(w, p, s) for w, (p, s) in best.items()]
    results.sort(key=lambda x: (-x[2], -len(x[0]), x[0]))
    return results
