# Video Translator FR

Pipeline pour traduire des vidéos EN → FR avec audio synthétisé.

## Stack

- **Download** : yt-dlp
- **Transcription** : faster-whisper (local, Apple Silicon MPS)
- **Traduction** : Argos Translate (local, gratuit) ou Claude API (premium)
- **TTS** : Coqui XTTS-v2 (local, gratuit, voice clone) ou OpenAI TTS (premium)
- **Mux** : ffmpeg

## Setup

```bash
cd ~/Documents/GitHub/video-translator
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # remplir ANTHROPIC_API_KEY
```

## Usage

```bash
# Mode gratuit (Argos + Coqui local)
python translator.py "URL_VIDEO"

# Mode premium (Claude trad + meilleure qualité)
python translator.py "URL_VIDEO" --quality=premium

# Voice clone du speaker original
python translator.py "URL_VIDEO" --voice-clone

# Output custom
python translator.py "URL_VIDEO" --output mavideo_FR.mp4
```

## Structure

- `translator.py` — CLI principal
- `pipeline/download.py` — yt-dlp
- `pipeline/transcribe.py` — Whisper
- `pipeline/translate.py` — Argos / Claude
- `pipeline/synthesize.py` — Coqui XTTS / OpenAI TTS
- `pipeline/mux.py` — ffmpeg sync + remux
- `models/` — modèles ML (gitignored)
- `cache/` — transcripts intermédiaires (gitignored)
- `output/` — vidéos FR finales (gitignored)
