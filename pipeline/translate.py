"""Traduction EN→FR : Argos (local, gratuit) ou Claude API (premium)."""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Literal
from rich.console import Console
from .transcribe import Segment

console = Console()

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_INPUT_PER_M = 3.0
CLAUDE_OUTPUT_PER_M = 15.0


def translate(
    segments: list[Segment],
    cache_path: Path,
    mode: Literal["free", "premium"] = "free",
) -> tuple[list[Segment], float]:
    """
    Traduit les segments EN→FR. Conserve les timestamps.
    Retourne (segments_fr, coût_en_eur).
    """
    cache_key = cache_path.parent / f"{cache_path.stem}_translate_{mode}.json"
    if cache_key.exists():
        console.log(f"[yellow]Cache hit traduction[/] {cache_key.name}")
        data = json.loads(cache_key.read_text())
        return [Segment(**s) for s in data["segments"]], data.get("cost_eur", 0.0)

    if mode == "premium":
        translated, cost = _translate_claude(segments)
    else:
        translated = _translate_argos(segments)
        cost = 0.0

    cache_key.write_text(json.dumps(
        {"segments": [s.__dict__ for s in translated], "cost_eur": cost},
        ensure_ascii=False, indent=2,
    ))
    return translated, cost


def _translate_argos(segments: list[Segment]) -> list[Segment]:
    import argostranslate.package
    import argostranslate.translate

    installed = argostranslate.translate.get_installed_languages()
    en = next((l for l in installed if l.code == "en"), None)
    fr = next((l for l in installed if l.code == "fr"), None)

    if not en or not fr or not en.get_translation(fr):
        console.log("[cyan]Argos[/] téléchargement modèle EN→FR")
        argostranslate.package.update_package_index()
        avail = argostranslate.package.get_available_packages()
        pkg = next(p for p in avail if p.from_code == "en" and p.to_code == "fr")
        argostranslate.package.install_from_path(pkg.download())
        installed = argostranslate.translate.get_installed_languages()
        en = next(l for l in installed if l.code == "en")
        fr = next(l for l in installed if l.code == "fr")

    translator = en.get_translation(fr)
    out = []
    for i, seg in enumerate(segments, 1):
        text_fr = translator.translate(seg.text)
        out.append(Segment(start=seg.start, end=seg.end, text=text_fr))
        if i % 10 == 0:
            console.log(f"  Argos {i}/{len(segments)}")
    return out


def _translate_claude(segments: list[Segment]) -> tuple[list[Segment], float]:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY manquant dans .env")
    client = Anthropic(api_key=api_key)

    BATCH = 30
    out: list[Segment] = []
    total_in = total_out = 0

    for i in range(0, len(segments), BATCH):
        chunk = segments[i:i + BATCH]
        numbered = "\n".join(f"[{j+1}] {s.text}" for j, s in enumerate(chunk))

        prompt = (
            "Tu traduis des sous-titres EN→FR pour une conférence technique. "
            "Garde le ton naturel, traduis le jargon dev/IA correctement (ne traduis pas les noms propres ni les commandes). "
            "Réponds UNIQUEMENT avec les lignes traduites, même format [N] texte, sans commentaire.\n\n"
            f"{numbered}"
        )

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        total_in += msg.usage.input_tokens
        total_out += msg.usage.output_tokens
        text = msg.content[0].text.strip()

        translations = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and "]" in line:
                idx_str, _, payload = line[1:].partition("]")
                try:
                    translations[int(idx_str)] = payload.strip()
                except ValueError:
                    pass

        for j, seg in enumerate(chunk, 1):
            t = translations.get(j, seg.text)
            out.append(Segment(start=seg.start, end=seg.end, text=t))
        console.log(f"  Claude batch {i//BATCH + 1} ({len(chunk)} segments)")

    cost_usd = (total_in / 1_000_000) * CLAUDE_INPUT_PER_M + (total_out / 1_000_000) * CLAUDE_OUTPUT_PER_M
    cost_eur = cost_usd * 0.92
    console.log(f"[green]Claude[/] in={total_in} out={total_out} → {cost_eur:.3f} €")
    return out, cost_eur
