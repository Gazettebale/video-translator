#!/usr/bin/env python3
"""Video Translator FR — CLI principal."""
from __future__ import annotations
import os
import sys
from pathlib import Path
import click
from dotenv import load_dotenv
from rich.console import Console

from pipeline.download import download_video, use_local_file
from pipeline.transcribe import transcribe
from pipeline.translate import translate
from pipeline.synthesize import synthesize_segments
from pipeline.mux import build_audio_track, remux, video_duration

console = Console()
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)


@click.command()
@click.argument("source")
@click.option("--quality", type=click.Choice(["free", "premium"]), default="free",
              help="free=Argos+Coqui local | premium=Claude+OpenAI")
@click.option("--voice-clone", is_flag=True, help="Cloner la voix originale (premium uniquement, ElevenLabs requis — pas dispo encore)")
@click.option("--piper-voice", type=click.Choice(["siwis", "tom", "upmc"]), default="siwis",
              help="Voix Piper FR (siwis=femme claire, tom=homme, upmc=mixte)")
@click.option("--keep-original-audio", is_flag=True, help="Garder l'audio EN dans le MP4 final")
@click.option("--strict-timing", is_flag=True, help="Forcer la synchro labiale (voix peut sonner robotique)")
@click.option("--output", type=click.Path(), default=None, help="Chemin MP4 de sortie")
@click.option("--whisper-model", default=None, help="tiny|base|small|medium|large-v3")
def main(source, quality, voice_clone, piper_voice, keep_original_audio, strict_timing, output, whisper_model):
    """SOURCE = URL (yt-dlp) ou chemin de fichier local."""
    work_dir = ROOT / "cache" / _slug(source)
    work_dir.mkdir(parents=True, exist_ok=True)

    is_url = source.startswith(("http://", "https://"))
    if is_url:
        video_path, audio_path, title = download_video(source, work_dir)
    else:
        video_path, audio_path, title = use_local_file(source, work_dir)

    console.rule(f"[bold]{title}[/]")
    console.log(f"Vidéo : {video_path}")
    console.log(f"Mode  : quality={quality} voice_clone={voice_clone}")

    model_size = whisper_model or os.getenv("WHISPER_MODEL", "large-v3")
    segments_en = transcribe(audio_path, work_dir / "transcript.json", model_size=model_size)
    console.log(f"[green]✓[/] Transcription : {len(segments_en)} segments")

    segments_fr, trad_cost = translate(segments_en, work_dir / "transcript.json", mode=quality)
    console.log(f"[green]✓[/] Traduction terminée (coût : {trad_cost:.3f} €)")

    seg_paths, tts_cost = synthesize_segments(
        segments_fr,
        audio_ref=audio_path if voice_clone else None,
        out_dir=work_dir / "tts",
        mode=quality,
        voice_clone=voice_clone,
        piper_voice=piper_voice,
    )
    console.log(f"[green]✓[/] Synthèse vocale (coût : {tts_cost:.3f} €)")

    total_dur = video_duration(video_path)
    fr_audio = build_audio_track(
        segments_fr, seg_paths, work_dir / "build", total_dur,
        natural_pace=not strict_timing,
    )

    out_path = Path(output) if output else ROOT / "output" / f"{video_path.stem}_FR.mp4"
    remux(video_path, fr_audio, out_path, keep_original=keep_original_audio)

    total_cost = trad_cost + tts_cost
    console.rule("[bold green]Terminé[/]")
    console.print(f"📁 Sortie : {out_path}")
    console.print(f"💰 Coût total : {total_cost:.3f} €")


def _slug(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    out = "".join(c if c in keep else "_" for c in s)[:80]
    return out or "video"


if __name__ == "__main__":
    main()
