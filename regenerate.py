#!/usr/bin/env python3
"""Regénère l'audio FR d'un job existant avec de nouvelles options TTS/timing.

Usage:
    python regenerate.py <job_id> [--voice siwis|tom|upmc] [--strict-timing] [--quality free|premium]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import click
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)

from pipeline.transcribe import Segment
from pipeline.synthesize import synthesize_segments
from pipeline.mux import build_audio_track, remux, video_duration

console = Console()
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@click.command()
@click.argument("job_id")
@click.option("--voice", type=click.Choice(["siwis", "tom", "upmc"]), default="siwis")
@click.option("--strict-timing", is_flag=True, help="Forcer la synchro labiale (sinon mode naturel)")
@click.option("--quality", type=click.Choice(["free", "premium"]), default="free",
              help="Quel transcript de traduction utiliser")
@click.option("--suffix", default=None, help="Suffixe du fichier de sortie")
def main(job_id, voice, strict_timing, quality, suffix):
    work_dir = ROOT / "cache" / f"job_{job_id}"
    if not work_dir.exists():
        console.print(f"[red]Job introuvable : {work_dir}[/]")
        sys.exit(1)

    transcript_file = work_dir / f"transcript_translate_{quality}.json"
    if not transcript_file.exists():
        console.print(f"[red]Pas de transcript {quality} pour ce job. Disponibles :[/]")
        for f in work_dir.glob("transcript_translate_*.json"):
            console.print(f"  - {f.name}")
        sys.exit(1)

    data = json.loads(transcript_file.read_text())
    segments_fr = [Segment(**s) for s in data["segments"]]
    console.log(f"[green]✓[/] {len(segments_fr)} segments chargés depuis cache")

    video_files = list(work_dir.glob("*.mp4"))
    audio_files = list(work_dir.glob("*.wav"))
    if not video_files or not audio_files:
        console.print("[red]MP4 ou WAV originaux manquants dans le cache du job[/]")
        sys.exit(1)
    video_path = video_files[0]
    audio_path = audio_files[0]

    tts_dir = work_dir / f"tts_{voice}"
    seg_paths, _ = synthesize_segments(
        segments_fr, audio_ref=None, out_dir=tts_dir,
        mode="free", voice_clone=False, piper_voice=voice,
    )

    build_subdir = work_dir / f"build_{voice}_{'strict' if strict_timing else 'natural'}"
    total_dur = video_duration(video_path)
    fr_audio = build_audio_track(
        segments_fr, seg_paths, build_subdir, total_dur,
        natural_pace=not strict_timing,
    )

    suffix = suffix or f"{quality}_{voice}_{'strict' if strict_timing else 'natural'}"
    out_path = OUTPUT_DIR / f"{video_path.stem}_FR_{suffix}.mp4"
    remux(video_path, fr_audio, out_path, keep_original=False)
    console.print(f"[bold green]✓ {out_path}[/]")


if __name__ == "__main__":
    main()
