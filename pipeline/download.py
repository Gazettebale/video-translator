"""Download video + extract audio via yt-dlp."""
from __future__ import annotations
import subprocess
from pathlib import Path
from rich.console import Console

console = Console()


def download_video(url: str, work_dir: Path) -> tuple[Path, Path, str]:
    """
    Télécharge une vidéo et extrait l'audio.
    Retourne (video_path, audio_path, title).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    video_template = str(work_dir / "%(title).80s.%(ext)s")

    console.log(f"[cyan]Téléchargement[/] {url}")
    subprocess.run(
        [
            "yt-dlp",
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "-o", video_template,
            "--no-playlist",
            "--restrict-filenames",
            "--concurrent-fragments", "16",
            "--retries", "5",
            url,
        ],
        check=True,
    )

    title_proc = subprocess.run(
        ["yt-dlp", "--print", "title", "--no-playlist", "--restrict-filenames", url],
        capture_output=True, text=True, check=True,
    )
    title = title_proc.stdout.strip()

    video_files = sorted(work_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not video_files:
        raise RuntimeError("Aucun fichier vidéo téléchargé.")
    video_path = video_files[0]

    audio_path = video_path.with_suffix(".wav")
    console.log(f"[cyan]Extraction audio[/] → {audio_path.name}")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path),
        ],
        check=True, capture_output=True,
    )

    return video_path, audio_path, title


def use_local_file(path: str, work_dir: Path) -> tuple[Path, Path, str]:
    """Utilise un fichier vidéo déjà présent localement."""
    video_path = Path(path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {video_path}")

    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / (video_path.stem + ".wav")
    console.log(f"[cyan]Extraction audio[/] {video_path.name}")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path),
        ],
        check=True, capture_output=True,
    )
    return video_path, audio_path, video_path.stem
