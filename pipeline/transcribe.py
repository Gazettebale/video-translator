"""Transcription audio EN avec faster-whisper."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from rich.console import Console

console = Console()


@dataclass
class Segment:
    start: float
    end: float
    text: str


def transcribe(
    audio_path: Path,
    cache_path: Path,
    model_size: str = "large-v3",
    device: str = "auto",
    language: str = "en",
    progress_cb=None,
) -> list[Segment]:
    """
    Transcrit l'audio en segments timestampés.
    Cache le résultat dans cache_path (JSON).
    progress_cb(current_sec, total_sec) appelé au fil des segments.
    """
    if cache_path.exists():
        console.log(f"[yellow]Cache hit transcription[/] {cache_path.name}")
        data = json.loads(cache_path.read_text())
        return [Segment(**s) for s in data]

    from faster_whisper import WhisperModel  # lazy import

    if device == "auto":
        try:
            import torch
            device = "cpu"
            compute_type = "int8"
            if torch.backends.mps.is_available():
                device = "cpu"
                compute_type = "int8"
        except Exception:
            device = "cpu"
            compute_type = "int8"
    else:
        compute_type = "int8" if device == "cpu" else "float16"

    console.log(f"[cyan]Whisper[/] modèle={model_size} device={device}")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
    )
    console.log(f"[green]Audio détecté[/] langue={info.language} durée={info.duration:.1f}s")

    segments = []
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_every = 30

    def flush_checkpoint():
        cache_path.write_text(json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2))

    total = info.duration
    for s in segments_iter:
        seg = Segment(start=s.start, end=s.end, text=s.text.strip())
        segments.append(seg)
        console.log(f"  [{seg.start:6.1f}s] {seg.text[:80]}")
        if progress_cb:
            try:
                progress_cb(seg.end, total)
            except Exception:
                pass
        if len(segments) % checkpoint_every == 0:
            flush_checkpoint()

    flush_checkpoint()
    return segments
