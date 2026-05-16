# Word Link Solver

Real-time solver for the Word Link game. Reads the board from your screen, finds the highest-scoring word, and highlights it with an overlay.

## Setup

**Requirements:** macOS, Python 3, Homebrew

```bash
# 1. Install tesseract OCR
brew install tesseract

# 2. Install Python dependencies
pip3 install -r requirements.txt

# 3. Download the word list
bash download_words.sh

# 4. Calibrate to your screen (run once)
python3 calibrate.py

# 5. Run
python3 runner.py
```

## Controls

- **Enter** — mark the suggested word as invalid (removes it and shows the next best word)
- **Ctrl-C** — quit
