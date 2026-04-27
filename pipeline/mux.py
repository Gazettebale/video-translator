"""Assemblage : recale les segments TTS sur les timestamps + remux dans la vidéo."""
from __future__ import annotations
import subprocess
from pathlib import Path
from rich.console import Console
from .transcribe import Segment

console = Console()


def _audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _atempo_chain(factor: float) -> str:
    """ffmpeg atempo accepte 0.5..2.0, on chaîne pour aller plus loin."""
    factor = max(0.5, min(factor, 4.0))
    if 0.5 <= factor <= 2.0:
        return f"atempo={factor:.4f}"
    chain = []
    remaining = factor
    while remaining > 2.0:
        chain.append("atempo=2.0")
        remaining /= 2.0
    chain.append(f"atempo={remaining:.4f}")
    return ",".join(chain)


def build_audio_track(
    segments: list[Segment],
    seg_paths: list[Path],
    work_dir: Path,
    total_duration: float,
    natural_pace: bool = True,
    max_stretch: float = 1.35,
) -> Path:
    """
    Construit une piste audio FR alignée sur les timestamps EN.

    - natural_pace=True : la voix garde son rythme naturel ; on insère des silences
      pour les pauses, on accepte le drift cumulatif (vidéo et audio peuvent se
      désynchroniser un peu mais la voix sonne humaine).
    - natural_pace=False : on étire/compresse l'audio FR avec atempo pour suivre les
      timestamps EN (synchro labiale meilleure mais voix robotique si gros écarts).
    - max_stretch : limite supérieure du facteur d'étirement (en mode strict).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    fitted_dir = work_dir / "fitted"
    fitted_dir.mkdir(exist_ok=True)

    parts: list[Path] = []
    cursor = 0.0

    for i, (seg, wav) in enumerate(zip(segments, seg_paths)):
        if seg.start > cursor + 0.05:
            sil = work_dir / f"sil_{i:04d}.wav"
            _silence_wav(sil, seg.start - cursor)
            parts.append(sil)
            cursor = seg.start

        target = max(seg.end - seg.start, 0.3)
        src_dur = _audio_duration(wav)
        if src_dur < 0.05:
            cursor += target
            sil = work_dir / f"silseg_{i:04d}.wav"
            _silence_wav(sil, target)
            parts.append(sil)
            continue

        if natural_pace:
            parts.append(wav)
            cursor += src_dur
            continue

        factor = src_dur / target
        if 0.85 <= factor <= 1.20:
            parts.append(wav)
            cursor += src_dur
        else:
            clamped = max(1.0 / max_stretch, min(factor, max_stretch))
            fitted = fitted_dir / f"fit_{i:04d}.wav"
            atempo = _atempo_chain(clamped)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav), "-filter:a", atempo,
                 "-ar", "24000", "-ac", "1", str(fitted)],
                check=True, capture_output=True,
            )
            parts.append(fitted)
            cursor += _audio_duration(fitted)

    if cursor < total_duration:
        tail = work_dir / "tail.wav"
        _silence_wav(tail, total_duration - cursor)
        parts.append(tail)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))
    full_audio = work_dir / "audio_fr.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-ar", "24000", "-ac", "1", str(full_audio)],
        check=True, capture_output=True,
    )
    return full_audio


def remux(
    video_path: Path,
    fr_audio: Path,
    output_path: Path,
    keep_original: bool = False,
):
    """Remplace l'audio EN par l'audio FR dans la vidéo."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if keep_original:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(fr_audio),
            "-map", "0:v", "-map", "1:a", "-map", "0:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-metadata:s:a:0", "language=fre",
            "-metadata:s:a:1", "language=eng",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(fr_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
    subprocess.run(cmd, check=True, capture_output=True)
    console.log(f"[green]✓[/] {output_path}")


def _silence_wav(path: Path, seconds: float):
    seconds = max(0.05, seconds)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds:.3f}", str(path)],
        check=True, capture_output=True,
    )


def video_duration(path: Path) -> float:
    return _audio_duration(path)
