#!/bin/bash
# Download the ENABLE word list (172k common English words, public domain).
# This is the word list used by many word games.

set -e
URL="https://raw.githubusercontent.com/dolph/dictionary/master/enable1.txt"
OUT="words.txt"

echo "Downloading ENABLE word list..."
curl -fsSL "$URL" -o "$OUT"
echo "Done — $(wc -l < "$OUT" | tr -d ' ') words saved to $OUT"
