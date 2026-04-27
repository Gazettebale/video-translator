"""TTS FR : Piper (local, gratuit) ou OpenAI TTS (premium)."""
from __future__ import annotations
import os
import wave
import urllib.request
import subprocess
from pathlib import Path
from typing import Literal
from rich.console import Console
from .transcribe import Segment

console = Console()

OPENAI_TTS_PER_1M_CHARS = 15.0

PIPER_VOICES = {
    "siwis": {
        "name": "fr_FR-siwis-medium",
        "url_base": "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium",
        "files": ["fr_FR-siwis-medium.onnx", "fr_FR-siwis-medium.onnx.json"],
    },
    "tom": {
        "name": "fr_FR-tom-medium",
        "url_base": "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/tom/medium",
        "files": ["fr_FR-tom-medium.onnx", "fr_FR-tom-medium.onnx.json"],
    },
    "upmc": {
        "name": "fr_FR-upmc-medium",
        "url_base": "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium",
        "files": ["fr_FR-upmc-medium.onnx", "fr_FR-upmc-medium.onnx.json"],
    },
}


def synthesize_segments(
    segments: list[Segment],
    audio_ref: Path | None,
    out_dir: Path,
    mode: Literal["free", "premium"] = "free",
    voice_clone: bool = False,
    piper_voice: str = "siwis",
    models_dir: Path | None = None,
) -> tuple[list[Path], float]:
    """
    Synthétise chaque segment en audio FR.
    Retourne (chemins_wav_par_segment, coût_eur).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if mode == "premium":
        return _synth_openai(segments, out_dir)
    if voice_clone:
        console.log("[yellow]voice-clone n'est pas dispo en mode free (Piper). Utilisation voix par défaut.[/]")
    return _synth_piper(segments, out_dir, piper_voice, models_dir), 0.0


def _ensure_piper_model(voice_key: str, models_dir: Path) -> Path:
    if voice_key not in PIPER_VOICES:
        raise ValueError(f"Voix Piper inconnue : {voice_key}")
    cfg = PIPER_VOICES[voice_key]
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = models_dir / cfg["files"][0]

    for fname in cfg["files"]:
        target = models_dir / fname
        if target.exists():
            continue
        url = f"{cfg['url_base']}/{fname}?download=true"
        console.log(f"[cyan]Download Piper[/] {fname}")
        urllib.request.urlretrieve(url, target)
    return onnx_path


def _synth_piper(
    segments: list[Segment],
    out_dir: Path,
    voice_key: str,
    models_dir: Path | None,
) -> list[Path]:
    from piper import PiperVoice

    if models_dir is None:
        models_dir = Path(__file__).parent.parent / "models" / "piper"
    onnx_path = _ensure_piper_model(voice_key, models_dir)

    console.log(f"[cyan]Piper[/] voix={PIPER_VOICES[voice_key]['name']}")
    voice = PiperVoice.load(str(onnx_path))

    paths = []
    for i, seg in enumerate(segments, 1):
        wav_out = out_dir / f"seg_{i:04d}.wav"
        if not seg.text.strip():
            _silence(wav_out, 0.1)
            paths.append(wav_out)
            continue
        with wave.open(str(wav_out), "wb") as wf:
            voice.synthesize_wav(seg.text, wf)
        paths.append(wav_out)
        if i % 10 == 0:
            console.log(f"  Piper {i}/{len(segments)}")
    return paths


def _synth_openai(segments: list[Segment], out_dir: Path) -> tuple[list[Path], float]:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY manquant dans .env (mode premium TTS)")
    client = OpenAI(api_key=api_key)

    paths = []
    total_chars = 0
    for i, seg in enumerate(segments, 1):
        wav_out = out_dir / f"seg_{i:04d}.wav"
        if not seg.text.strip():
            _silence(wav_out, 0.1)
            paths.append(wav_out)
            continue
        mp3_tmp = wav_out.with_suffix(".mp3")
        with client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="onyx",
            input=seg.text,
            response_format="mp3",
        ) as resp:
            resp.stream_to_file(str(mp3_tmp))
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_tmp), "-ar", "24000", "-ac", "1", str(wav_out)],
            check=True, capture_output=True,
        )
        mp3_tmp.unlink(missing_ok=True)
        total_chars += len(seg.text)
        paths.append(wav_out)
        if i % 10 == 0:
            console.log(f"  OpenAI TTS {i}/{len(segments)}")

    cost_usd = (total_chars / 1_000_000) * OPENAI_TTS_PER_1M_CHARS
    cost_eur = cost_usd * 0.92
    console.log(f"[green]OpenAI TTS[/] {total_chars} chars → {cost_eur:.3f} €")
    return paths, cost_eur


def _silence(path: Path, seconds: float):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
         "-t", str(seconds), str(path)],
        check=True, capture_output=True,
    )
