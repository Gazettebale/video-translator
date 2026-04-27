"""Web UI pour Video Translator FR — FastAPI + WebSocket."""
from __future__ import annotations
import os
import asyncio
import uuid
import json
import time
import traceback
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)

from pipeline.download import download_video, use_local_file
from pipeline.transcribe import transcribe, Segment
from pipeline.translate import translate
from pipeline.synthesize import synthesize_segments
from pipeline.mux import build_audio_track, remux, video_duration
from pipeline.srt import write_srt

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
HISTORY_FILE = ROOT / "cache" / "history.json"
HISTORY_FILE.parent.mkdir(exist_ok=True)

app = FastAPI(title="Video Translator FR")

JOBS: dict[str, dict] = {}


class JobRequest(BaseModel):
    url: str
    quality_translation: str = "free"   # free | premium
    quality_voice: str = "free"          # free | premium
    voice_clone: bool = False
    piper_voice: str = "siwis"           # siwis | tom | upmc
    keep_original_audio: bool = False
    whisper_model: str = "large-v3"
    natural_pace: bool = True


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
    return []


def save_history(entries: list[dict]):
    HISTORY_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2))


def append_history(entry: dict):
    h = load_history()
    h.insert(0, entry)
    h = h[:50]
    save_history(h)


def estimate_cost(duration_sec: float, q_trans: str, q_voice: str) -> dict:
    """Estimation grossière pour preview avant lancement."""
    chars_per_min = 800
    duration_min = duration_sec / 60
    estimated_chars = duration_min * chars_per_min

    trans_cost = 0.0
    if q_trans == "premium":
        in_tokens = estimated_chars / 3
        out_tokens = estimated_chars / 3
        trans_cost = (in_tokens / 1_000_000 * 3.0 + out_tokens / 1_000_000 * 15.0) * 0.92

    voice_cost = 0.0
    if q_voice == "premium":
        voice_cost = (estimated_chars / 1_000_000) * 15.0 * 0.92

    return {
        "translation_cost_eur": round(trans_cost, 3),
        "voice_cost_eur": round(voice_cost, 3),
        "total_cost_eur": round(trans_cost + voice_cost, 3),
        "duration_min": round(duration_min, 1),
    }


async def run_job(job_id: str, req: JobRequest):
    job = JOBS[job_id]

    def push(event: str, **data):
        job["events"].append({"event": event, "ts": time.time(), **data})
        job["status_event"] = event

    try:
        push("started", message="Téléchargement de la vidéo...")
        work_dir = ROOT / "cache" / f"job_{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_event_loop()

        if req.url.startswith(("http://", "https://")):
            video_path, audio_path, title = await loop.run_in_executor(
                None, download_video, req.url, work_dir
            )
        else:
            video_path, audio_path, title = await loop.run_in_executor(
                None, use_local_file, req.url, work_dir
            )
        job["title"] = title
        push("downloaded", title=title)

        push("transcribing", message=f"Whisper ({req.whisper_model}) en cours...")

        last_pct = {"v": -1}
        def whisper_progress(current, total):
            pct = int((current / total) * 100) if total else 0
            if pct != last_pct["v"] and pct % 5 == 0:
                last_pct["v"] = pct
                push("transcribing_progress", percent=pct, current_sec=round(current, 1), total_sec=round(total, 1))

        segments_en = await loop.run_in_executor(
            None,
            lambda: transcribe(
                audio_path, work_dir / "transcript.json",
                model_size=req.whisper_model, progress_cb=whisper_progress,
            ),
        )
        push("transcribed", segments=len(segments_en))

        push("translating", message=f"Traduction ({req.quality_translation})...")
        segments_fr, trans_cost = await loop.run_in_executor(
            None,
            lambda: translate(segments_en, work_dir / "transcript.json", mode=req.quality_translation),
        )
        push("translated", cost_eur=round(trans_cost, 3))

        push("synthesizing", message=f"Synthèse vocale ({req.quality_voice})...")
        seg_paths, voice_cost = await loop.run_in_executor(
            None,
            lambda: synthesize_segments(
                segments_fr,
                audio_ref=audio_path if req.voice_clone else None,
                out_dir=work_dir / "tts",
                mode=req.quality_voice,
                voice_clone=req.voice_clone,
                piper_voice=req.piper_voice,
            ),
        )
        push("synthesized", cost_eur=round(voice_cost, 3))

        push("muxing", message="Assemblage final...")
        total_dur = video_duration(video_path)
        fr_audio = await loop.run_in_executor(
            None,
            lambda: build_audio_track(
                segments_fr, seg_paths, work_dir / "build", total_dur,
                natural_pace=req.natural_pace,
            ),
        )
        out_name = f"{video_path.stem}_FR_{job_id[:8]}.mp4"
        out_path = OUTPUT_DIR / out_name
        await loop.run_in_executor(
            None,
            lambda: remux(video_path, fr_audio, out_path, keep_original=req.keep_original_audio),
        )

        srt_name = f"{video_path.stem}_FR_{job_id[:8]}.srt"
        srt_path = OUTPUT_DIR / srt_name
        write_srt(segments_fr, srt_path)

        total_cost = round(trans_cost + voice_cost, 3)
        job["output_file"] = out_name
        job["srt_file"] = srt_name
        job["total_cost_eur"] = total_cost
        push("done", output_file=out_name, srt_file=srt_name, total_cost_eur=total_cost)

        append_history({
            "id": job_id,
            "title": title,
            "url": req.url,
            "output_file": out_name,
            "srt_file": srt_name,
            "total_cost_eur": total_cost,
            "quality_translation": req.quality_translation,
            "quality_voice": req.quality_voice,
            "piper_voice": req.piper_voice,
            "natural_pace": req.natural_pace,
            "ts": time.time(),
        })
    except Exception as e:
        push("error", message=str(e), traceback=traceback.format_exc())


@app.post("/api/jobs")
async def create_job(req: JobRequest):
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"id": job_id, "events": [], "status_event": "pending"}
    asyncio.create_task(run_job(job_id, req))
    return {"job_id": job_id}


class BatchRequest(BaseModel):
    urls: list[str]
    quality_translation: str = "free"
    quality_voice: str = "free"
    voice_clone: bool = False
    piper_voice: str = "siwis"
    keep_original_audio: bool = False
    whisper_model: str = "large-v3"
    natural_pace: bool = True


async def run_batch(batch_id: str, req: BatchRequest):
    batch = JOBS[batch_id]
    for i, url in enumerate(req.urls, 1):
        batch["events"].append({
            "event": "batch_item_start", "ts": time.time(),
            "index": i, "total": len(req.urls), "url": url,
        })
        sub = JobRequest(
            url=url,
            quality_translation=req.quality_translation,
            quality_voice=req.quality_voice,
            voice_clone=req.voice_clone,
            piper_voice=req.piper_voice,
            keep_original_audio=req.keep_original_audio,
            whisper_model=req.whisper_model,
            natural_pace=req.natural_pace,
        )
        sub_id = uuid.uuid4().hex
        JOBS[sub_id] = {"id": sub_id, "events": [], "status_event": "pending"}
        await run_job(sub_id, sub)
        batch["events"].append({
            "event": "batch_item_done", "ts": time.time(),
            "index": i, "total": len(req.urls),
            "child_job_id": sub_id,
            "output_file": JOBS[sub_id].get("output_file"),
            "srt_file": JOBS[sub_id].get("srt_file"),
            "total_cost_eur": JOBS[sub_id].get("total_cost_eur"),
        })
    batch["events"].append({"event": "done", "ts": time.time()})


@app.post("/api/batch")
async def create_batch(req: BatchRequest):
    if not req.urls:
        raise HTTPException(400, "Aucune URL fournie")
    batch_id = uuid.uuid4().hex
    JOBS[batch_id] = {"id": batch_id, "events": [], "status_event": "pending", "is_batch": True}
    asyncio.create_task(run_batch(batch_id, req))
    return {"job_id": batch_id, "count": len(req.urls)}


class RerenderRequest(BaseModel):
    source_job_id: str
    quality_translation: str = "free"
    voice: str = "siwis"
    natural_pace: bool = True
    keep_original_audio: bool = False


async def run_rerender(job_id: str, req: RerenderRequest):
    job = JOBS[job_id]
    def push(event: str, **data):
        job["events"].append({"event": event, "ts": time.time(), **data})

    try:
        src_dir = ROOT / "cache" / f"job_{req.source_job_id}"
        if not src_dir.exists():
            push("error", message=f"Job source introuvable : {req.source_job_id}")
            return

        transcript_file = src_dir / f"transcript_translate_{req.quality_translation}.json"
        if not transcript_file.exists():
            push("error", message=f"Pas de transcript {req.quality_translation} pour ce job source")
            return

        push("started", message="Régénération depuis cache...")
        loop = asyncio.get_event_loop()
        data = json.loads(transcript_file.read_text())
        segments_fr = [Segment(**s) for s in data["segments"]]

        video_files = list(src_dir.glob("*.mp4"))
        if not video_files:
            push("error", message="MP4 source manquant")
            return
        video_path = video_files[0]

        push("synthesizing", message=f"Synthèse Piper ({req.voice})...")
        seg_paths, _ = await loop.run_in_executor(
            None,
            lambda: synthesize_segments(
                segments_fr, audio_ref=None,
                out_dir=ROOT / "cache" / f"job_{job_id}" / "tts",
                mode="free", voice_clone=False, piper_voice=req.voice,
            ),
        )

        push("muxing", message="Assemblage final...")
        total_dur = video_duration(video_path)
        fr_audio = await loop.run_in_executor(
            None,
            lambda: build_audio_track(
                segments_fr, seg_paths,
                ROOT / "cache" / f"job_{job_id}" / "build", total_dur,
                natural_pace=req.natural_pace,
            ),
        )

        suffix = f"rerender_{req.quality_translation}_{req.voice}_{'natural' if req.natural_pace else 'strict'}_{job_id[:6]}"
        out_name = f"{video_path.stem}_FR_{suffix}.mp4"
        out_path = OUTPUT_DIR / out_name
        await loop.run_in_executor(
            None,
            lambda: remux(video_path, fr_audio, out_path, keep_original=req.keep_original_audio),
        )

        srt_name = f"{video_path.stem}_FR_{suffix}.srt"
        write_srt(segments_fr, OUTPUT_DIR / srt_name)

        job["output_file"] = out_name
        push("done", output_file=out_name, srt_file=srt_name, total_cost_eur=0.0)

        src_history = next((h for h in load_history() if h["id"] == req.source_job_id), {})
        title = src_history.get("title", video_path.stem) + f" [re-render {req.voice}]"
        append_history({
            "id": job_id,
            "title": title,
            "url": src_history.get("url", "(rerender)"),
            "output_file": out_name,
            "srt_file": srt_name,
            "total_cost_eur": 0.0,
            "quality_translation": req.quality_translation,
            "quality_voice": "free",
            "piper_voice": req.voice,
            "natural_pace": req.natural_pace,
            "rerender_of": req.source_job_id,
            "ts": time.time(),
        })
    except Exception as e:
        push("error", message=str(e), traceback=traceback.format_exc())


@app.post("/api/rerender")
async def create_rerender(req: RerenderRequest):
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"id": job_id, "events": [], "status_event": "pending"}
    asyncio.create_task(run_rerender(job_id, req))
    return {"job_id": job_id}


@app.get("/output/{filename}/srt")
async def download_srt(filename: str):
    """Routine pour télécharger le .srt associé à un .mp4"""
    base = filename.removesuffix(".mp4").removesuffix(".srt")
    srt = OUTPUT_DIR / f"{base}.srt"
    if not srt.exists():
        raise HTTPException(404, "SRT introuvable")
    return FileResponse(srt, media_type="text/plain", filename=srt.name)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job inconnu")
    return JOBS[job_id]


@app.get("/api/history")
async def get_history():
    return load_history()


@app.get("/api/keys")
async def get_keys():
    """Renvoie quelles clés API sont configurées (pour griser les options dans l'UI)."""
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
    }


@app.post("/api/estimate")
async def estimate(req: JobRequest):
    """Pour estimer un coût avant lancement, on suppose 30 min."""
    return estimate_cost(30 * 60, req.quality_translation, req.quality_voice)


@app.websocket("/ws/jobs/{job_id}")
async def ws_job(ws: WebSocket, job_id: str):
    await ws.accept()
    if job_id not in JOBS:
        await ws.send_json({"event": "error", "message": "Job inconnu"})
        await ws.close()
        return

    last_idx = 0
    try:
        while True:
            job = JOBS[job_id]
            events = job["events"]
            while last_idx < len(events):
                await ws.send_json(events[last_idx])
                last_idx += 1
            if events and events[-1]["event"] in ("done", "error"):
                break
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/output/{filename}")
async def download_output(filename: str):
    safe = OUTPUT_DIR / Path(filename).name
    if not safe.exists():
        raise HTTPException(404, "Fichier introuvable")
    return FileResponse(safe, media_type="video/mp4", filename=safe.name)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (ROOT / "static" / "index.html").read_text()


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
