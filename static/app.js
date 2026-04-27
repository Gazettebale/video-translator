const form = document.getElementById("job-form");
const submitBtn = document.getElementById("submit-btn");
const jobSection = document.getElementById("job-section");
const jobTitle = document.getElementById("job-title");
const progressList = document.getElementById("progress-list");
const jobCost = document.getElementById("job-cost");
const downloadLink = document.getElementById("download-link");
const costEstimate = document.getElementById("cost-estimate");
const historyList = document.getElementById("history-list");

const STEP_LABELS = {
  started: "🛬 Téléchargement vidéo",
  downloaded: "✓ Vidéo téléchargée",
  transcribing: "🎙️ Transcription Whisper",
  transcribed: "✓ Transcription terminée",
  translating: "🌐 Traduction EN→FR",
  translated: "✓ Traduction terminée",
  synthesizing: "🔊 Synthèse vocale FR",
  synthesized: "✓ Voix générée",
  muxing: "🎞️ Assemblage final",
  done: "✅ Terminé",
  error: "❌ Erreur",
};

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
      <div>
        <a href="/output/${it.output_file}" download>${escapeHtml(it.title || it.output_file)}</a>
        <div class="meta">${formatDate(it.ts)} · ${it.quality_translation}/${it.quality_voice}</div>
      </div>
      <div>${it.total_cost_eur === 0 ? "Gratuit" : it.total_cost_eur.toFixed(3) + " €"}</div>
    </div>`,
    )
    .join("");
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
    url: fd.get("url").trim(),
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
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = getFormData();
  if (!data.url) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ En cours...";
  progressList.innerHTML = "";
  jobCost.innerHTML = "";
  downloadLink.classList.add("hidden");
  jobTitle.textContent = "";
  jobSection.classList.remove("hidden");

  const r = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const { job_id } = await r.json();

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/jobs/${job_id}`);
  let totalCost = 0;
  const stepEls = {};

  ws.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.event === "downloaded") {
      jobTitle.textContent = ev.title;
    }
    const label = STEP_LABELS[ev.event] || ev.event;
    if (ev.event === "translated" || ev.event === "synthesized") {
      totalCost += ev.cost_eur || 0;
    }
    const el = document.createElement("div");
    el.className = "progress-step active";
    el.textContent = label + (ev.message ? " — " + ev.message : "");
    if (ev.event === "error" && ev.message) el.textContent += " — " + ev.message;
    progressList.appendChild(el);
    document.querySelectorAll(".progress-step.active").forEach((p, i, arr) => {
      if (i < arr.length - 1) { p.classList.remove("active"); p.classList.add("done"); }
    });

    if (ev.event === "done") {
      el.classList.remove("active"); el.classList.add("done");
      jobCost.innerHTML = `💰 Coût total : <strong>${ev.total_cost_eur === 0 ? "Gratuit" : ev.total_cost_eur.toFixed(3) + " €"}</strong>`;
      downloadLink.href = `/output/${ev.output_file}`;
      downloadLink.classList.remove("hidden");
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
});

loadKeys();
loadHistory();
updateEstimate();
