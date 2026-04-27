#!/usr/bin/env bash
# Wrapper pour lancer Video Translator FR
# Installe avec : ln -s ~/Documents/GitHub/video-translator/translator.sh /usr/local/bin/translator

set -e
PROJECT_DIR="$HOME/Documents/GitHub/video-translator"
PORT=8765

cd "$PROJECT_DIR"

if [[ ! -d venv ]]; then
  echo "❌ venv manquant. Run: python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# Tue ancienne instance si elle tourne
EXISTING=$(lsof -ti:$PORT 2>/dev/null || true)
if [[ -n "$EXISTING" ]]; then
  echo "⚠️  Serveur déjà sur :$PORT (PID $EXISTING) — kill et redémarre"
  kill "$EXISTING" 2>/dev/null || true
  sleep 1
fi

source venv/bin/activate

# Si arg "open" passé, ouvre le navigateur après 2s
if [[ "$1" == "open" ]]; then
  ( sleep 2 && open "http://127.0.0.1:$PORT" ) &
fi

echo "🚀 Video Translator FR → http://127.0.0.1:$PORT"
exec python webui.py
