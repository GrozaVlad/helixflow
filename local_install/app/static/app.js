const jobsEl = document.querySelector("#jobs");
const form = document.querySelector("#job-form");
const submitStatus = document.querySelector("#submit-status");
let jobsSignature = "";

async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.text()) || response.statusText);
  return response.json();
}

async function checkHealth() {
  const el = document.querySelector("#health");
  try {
    const data = await getJSON("/api/health");
    el.textContent = data.cuda_available ? `GPU ready · ${data.gpu}` : "CUDA unavailable";
    el.classList.toggle("ok", data.cuda_available);
  } catch (error) { el.textContent = "Service unavailable"; }
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

async function loadLog(id) {
  const response = await fetch(`/api/jobs/${id}/log`);
  document.querySelector(`#log-${id}`).textContent = await response.text();
}

async function refreshJobs() {
  try {
    const jobs = await getJSON("/api/jobs");
    if (!jobs.length) return;
    const signature = JSON.stringify(jobs);
    if (signature === jobsSignature) return;
    const openLogs = new Set(
      [...jobsEl.querySelectorAll("details[open]")]
        .map(details => details.dataset.jobId)
        .filter(Boolean)
    );
    jobsSignature = signature;
    jobsEl.innerHTML = jobs.map(job => `
      <article class="job">
        <div class="job-head">
          <div><strong>${escapeHTML(job.filename)}</strong><div class="muted">${job.id} · ${new Date(job.created_at).toLocaleString()}</div></div>
          <span class="status ${job.status}">${job.status}</span>
        </div>
        <div class="files">${(job.files || []).map(file => `${file.toLowerCase().endsWith(".cif") ? `<button class="view-button" onclick='openViewer(${JSON.stringify(job.id)}, ${JSON.stringify(file)})'>View 3D</button>` : ""}<a href="/api/jobs/${job.id}/files/${encodeURI(file)}">${escapeHTML(file)}</a>`).join("")}</div>
        <details data-job-id="${job.id}" ${job.status === "failed" || openLogs.has(job.id) ? "open" : ""} ontoggle="if(this.open) loadLog('${job.id}')">
          <summary>Run log</summary><pre id="log-${job.id}">Loading…</pre>
        </details>
      </article>`).join("");
    for (const id of openLogs) {
      if (document.querySelector(`#log-${id}`)) loadLog(id);
    }
  } catch (error) { jobsEl.innerHTML = `<p class="muted">${escapeHTML(error.message)}</p>`; }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  submitStatus.textContent = " Submitting…";
  const data = new FormData(form);
  for (const name of ["use_msa_server", "use_potentials", "override"]) {
    data.set(name, form.elements[name].checked ? "true" : "false");
  }
  try {
    const job = await getJSON("/api/jobs", {method:"POST", body:data});
    submitStatus.textContent = ` Queued ${job.id}`;
    await refreshJobs();
  } catch (error) { submitStatus.textContent = ` ${error.message}`; }
});

document.querySelector("#refresh").addEventListener("click", refreshJobs);
checkHealth();
refreshJobs();
setInterval(refreshJobs, 5000);

