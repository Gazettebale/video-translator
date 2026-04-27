const form = document.getElementById("job-form");
const submitBtn = document.getElementById("submit-btn");
const jobSection = document.getElementById("job-section");
const jobTitle = document.getElementById("job-title");
const progressList = document.getElementById("progress-list");
const progressBarWrap = document.getElementById("progress-bar-wrap");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressBarLabel = document.getElementById("progress-bar-label");
const jobCost = document.getElementById("job-cost");
const downloadRow = document.getElementById("download-row");
const downloadLink = document.getElementById("download-link");
const srtLink = document.getElementById("srt-link");
const costEstimate = document.getElementById("cost-estimate");
const historyList = document.getElementById("history-list");
const singleUrlLabel = document.getElementById("single-url-label");
const batchUrlsLabel = document.getElementById("batch-urls-label");

const STEP_LABELS = {
  started: "🛬 Téléchargement vidéo",
  downloaded: "✓ Vidéo téléchargée",
  transcribing: "🎙️ Transcription Whisper",
  transcribing_progress: "🎙️ Whisper",
  transcribed: "✓ Transcription terminée",
  translating: "🌐 Traduction EN→FR",
  translated: "✓ Traduction terminée",
  synthesizing: "🔊 Synthèse vocale FR",
  synthesized: "✓ Voix générée",
  muxing: "🎞️ Assemblage final",
  done: "✅ Terminé",
  error: "❌ Erreur",
  batch_item_start: "▶️ Vidéo",
  batch_item_done: "✓ Vidéo terminée",
};

document.querySelectorAll('input[name="mode"]').forEach((el) => {
  el.addEventListener("change", () => {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    singleUrlLabel.classList.toggle("hidden", mode !== "single");
    batchUrlsLabel.classList.toggle("hidden", mode !== "batch");
    document.getElementById("url").required = mode === "single";
  });
});

async function loadKeys() {
  const r = await fetch("/api/keys");
  const keys = await r.json();
  document.querySelectorAll("input[data-key]").forEach((el) => {
    const k = el.dataset.key;
    if (!keys[k]) {
      el.disabled = true;
      const span = el.parentElement.querySelector("span");
      if (span) span.innerHTML += ' <em class="muted">(clé manquante)</em>';
    }
  });
}

async function loadHistory() {
  const r = await fetch("/api/history");
  const items = await r.json();
  if (!items.length) {
    historyList.innerHTML = '<p class="muted">Aucune traduction pour l\'instant.</p>';
    return;
  }
  historyList.innerHTML = items
    .map(
      (it) => `
    <div class="history-item">
      <div style="flex: 1; min-width: 0; margin-right: 10px;">
        <a href="/output/${encodeURIComponent(it.output_file)}" download>${escapeHtml((it.title || it.output_file).replace(/\n/g, ' / '))}</a>
        <div class="meta">${formatDate(it.ts)} · ${it.quality_translation}/${it.quality_voice}${it.piper_voice ? '/' + it.piper_voice : ''}${it.natural_pace ? ' · naturel' : ' · strict'}${it.rerender_of ? ' · rerender' : ''}</div>
      </div>
      <div class="history-actions">
        <span>${it.total_cost_eur === 0 ? "Gratuit" : it.total_cost_eur.toFixed(3) + " €"}</span>
        ${it.srt_file ? `<a class="btn-mini" href="/output/${encodeURIComponent(it.srt_file)}" download>📝 SRT</a>` : ''}
        <button class="btn-mini" data-rerender-id="${it.id}">🔁 Re-render</button>
      </div>
    </div>`,
    )
    .join("");
  document.querySelectorAll("[data-rerender-id]").forEach((b) => {
    b.addEventListener("click", () => promptRerender(b.dataset.rerenderId));
  });
}

async function promptRerender(sourceId) {
  const voice = prompt("Voix Piper (siwis, tom, upmc) ?", "siwis");
  if (!voice) return;
  if (!["siwis", "tom", "upmc"].includes(voice)) {
    alert("Voix invalide");
    return;
  }
  const naturalAns = prompt("Mode naturel (oui/non) ?", "oui");
  const natural = naturalAns && naturalAns.toLowerCase().startsWith("o");
  const qualityAns = prompt("Traduction (free/premium) ?", "free");
  const quality = qualityAns === "premium" ? "premium" : "free";

  const r = await fetch("/api/rerender", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_job_id: sourceId,
      quality_translation: quality,
      voice,
      natural_pace: natural,
      keep_original_audio: false,
    }),
  });
  const { job_id } = await r.json();
  startTracking(job_id, "Re-render en cours");
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
function formatDate(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

function getFormData() {
  const fd = new FormData(form);
  return {
    url: (fd.get("url") || "").trim(),
    quality_translation: fd.get("quality_translation"),
    quality_voice: fd.get("quality_voice"),
    voice_clone: fd.get("voice_clone") === "on",
    piper_voice: fd.get("piper_voice"),
    keep_original_audio: fd.get("keep_original_audio") === "on",
    whisper_model: fd.get("whisper_model"),
    natural_pace: fd.get("natural_pace") === "on",
  };
}

async function updateEstimate() {
  const data = getFormData();
  if (!data.url) data.url = "https://placeholder";
  const r = await fetch("/api/estimate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const est = await r.json();
  costEstimate.textContent = est.total_cost_eur === 0 ? "0.00 € (gratuit)" : `${est.total_cost_eur.toFixed(3)} €`;
}

form.addEventListener("change", updateEstimate);

function resetJobUI() {
  progressList.innerHTML = "";
  jobCost.innerHTML = "";
  downloadRow.classList.add("hidden");
  jobTitle.textContent = "";
  progressBarWrap.classList.add("hidden");
  progressBarFill.style.width = "0%";
  progressBarLabel.textContent = "";
  jobSection.classList.remove("hidden");
}

function startTracking(job_id, title) {
  resetJobUI();
  if (title) jobTitle.textContent = title;
  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ En cours...";

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/jobs/${job_id}`);

  ws.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.event === "downloaded") jobTitle.textContent = ev.title;
    if (ev.event === "transcribing_progress") {
      progressBarWrap.classList.remove("hidden");
      progressBarFill.style.width = `${ev.percent}%`;
      progressBarLabel.textContent = `Whisper ${ev.percent}% (${ev.current_sec}s / ${ev.total_sec}s)`;
      return;
    }
    if (ev.event === "transcribed") {
      progressBarWrap.classList.add("hidden");
    }
    const label = STEP_LABELS[ev.event] || ev.event;
    const el = document.createElement("div");
    el.className = "progress-step active";
    let text = label;
    if (ev.message) text += " — " + ev.message;
    if (ev.event === "batch_item_start") text = `▶️ Vidéo ${ev.index}/${ev.total} — ${ev.url.slice(0, 50)}…`;
    if (ev.event === "batch_item_done") text = `✓ Vidéo ${ev.index}/${ev.total} terminée — ${(ev.total_cost_eur || 0).toFixed(3)} €`;
    el.textContent = text;
    progressList.appendChild(el);
    document.querySelectorAll(".progress-step.active").forEach((p, i, arr) => {
      if (i < arr.length - 1) { p.classList.remove("active"); p.classList.add("done"); }
    });

    if (ev.event === "done") {
      el.classList.remove("active"); el.classList.add("done");
      if (ev.total_cost_eur !== undefined) {
        jobCost.innerHTML = `💰 Coût total : <strong>${ev.total_cost_eur === 0 ? "Gratuit" : ev.total_cost_eur.toFixed(3) + " €"}</strong>`;
      }
      if (ev.output_file) {
        downloadLink.href = `/output/${encodeURIComponent(ev.output_file)}`;
        downloadRow.classList.remove("hidden");
        if (ev.srt_file) {
          srtLink.href = `/output/${encodeURIComponent(ev.srt_file)}`;
          srtLink.classList.remove("hidden");
        } else {
          srtLink.classList.add("hidden");
        }
      }
      submitBtn.disabled = false;
      submitBtn.textContent = "🚀 Lancer la traduction";
      loadHistory();
    } else if (ev.event === "error") {
      el.classList.remove("active"); el.classList.add("error");
      submitBtn.disabled = false;
      submitBtn.textContent = "🚀 Lancer la traduction";
    }
  };
  ws.onerror = () => {
    submitBtn.disabled = false;
    submitBtn.textContent = "🚀 Lancer la traduction";
  };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const data = getFormData();

  if (mode === "batch") {
    const urls = (document.getElementById("urls").value || "")
      .split("\n").map((s) => s.trim()).filter(Boolean);
    if (!urls.length) return alert("Aucune URL");
    const r = await fetch("/api/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, urls }),
    });
    const { job_id } = await r.json();
    startTracking(job_id, `Batch de ${urls.length} vidéos`);
  } else {
    if (!data.url) return;
    const r = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const { job_id } = await r.json();
    startTracking(job_id, "");
  }
});

loadKeys();
loadHistory();
updateEstimate();
