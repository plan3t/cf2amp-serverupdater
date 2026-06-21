const state = {
  settings: null,
  currentJob: null,
};

const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("connectionState").textContent = text;
}

function logLine(message) {
  const log = $("liveLog");
  const time = new Date().toLocaleTimeString();
  log.textContent += `[${time}] ${message}\n`;
  log.scrollTop = log.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // keep default detail
    }
    throw new Error(detail);
  }
  return response.json();
}

function formToSettings() {
  let fallbackSources = [];
  const fallbackText = $("fallbackSources").value.trim();
  if (fallbackText) {
    fallbackSources = JSON.parse(fallbackText);
    if (!Array.isArray(fallbackSources)) {
      throw new Error("Fallback-Quellen mÃ¼ssen ein JSON-Array sein");
    }
  }
  return {
    source_type: $("sourceTypeInput").value,
    curseforge_api_key: $("apiKey").value,
    modpack_id: Number($("modpackId").value || 0),
    minecraft_version: $("minecraftVersion").value,
    amp_instances_dir: $("ampInstancesDir").value,
    server_dir: $("serverDirInput").value,
    local_server_pack: $("localServerPack").value,
    java_path: $("javaPath").value,
    java_opts: $("javaOpts").value,
    remove_missing: $("removeMissing").checked,
    prefer_server_pack: $("preferServerPack").checked,
    rollback_on_failure: $("rollbackOnFailure").checked,
    fallback_sources: fallbackSources,
  };
}

function fillSettings(settings) {
  state.settings = settings;
  $("sourceTypeInput").value = settings.source_type || "localServerPack";
  $("modpackId").value = settings.modpack_id || 0;
  $("minecraftVersion").value = settings.minecraft_version || "";
  $("ampInstancesDir").value = settings.amp_instances_dir || "";
  $("serverDirInput").value = settings.server_dir || "";
  $("localServerPack").value = settings.local_server_pack || "";
  $("javaPath").value = settings.java_path || "java";
  $("javaOpts").value = settings.java_opts || "";
  $("removeMissing").checked = Boolean(settings.remove_missing);
  $("preferServerPack").checked = Boolean(settings.prefer_server_pack);
  $("rollbackOnFailure").checked = Boolean(settings.rollback_on_failure);
  $("fallbackSources").value = JSON.stringify(settings.fallback_sources || [], null, 2);
  $("apiKeyState").textContent = settings.has_api_key ? "API-Key gespeichert" : "Kein API-Key gespeichert";
  $("serverDir").textContent = settings.server_dir || "-";
  $("sourceType").textContent = settings.source_type || "-";
}

async function loadSettings() {
  const settings = await api("/api/settings");
  fillSettings(settings);
}

async function saveSettings() {
  setStatus("Speichere");
  const settings = await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(formToSettings()),
  });
  $("apiKey").value = "";
  fillSettings(settings);
  await refreshState();
  setStatus("Gespeichert");
}

async function refreshState() {
  const payload = await api("/api/state");
  $("serverDir").textContent = payload.server_dir;
  $("installedVersion").textContent = payload.state.modpack_file_id || "-";
  $("managedCount").textContent = payload.state.managed_count;
  renderBackups(payload.backups);
}

async function scanInstances() {
  setStatus("Scanne AMP");
  const payload = await api(`/api/instances?path=${encodeURIComponent($("ampInstancesDir").value)}`);
  const container = $("instances");
  container.innerHTML = "";
  if (!payload.instances.length) {
    container.className = "list empty";
    container.textContent = "Keine Instanzen gefunden";
    return;
  }
  container.className = "list";
  for (const instance of payload.instances) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>${instance.name}</strong>
      <span>${instance.server_dir}</span>
      <small>${instance.detected ? "Minecraft-Layout erkannt" : instance.notes.join(" ")}</small>
      <div class="item-actions"><button type="button">Auswählen</button></div>
    `;
    item.querySelector("button").addEventListener("click", () => {
      $("serverDirInput").value = instance.server_dir;
      saveSettings().catch(showError);
    });
    container.appendChild(item);
  }
  setStatus("Bereit");
}

async function uploadServerPack(event) {
  event.preventDefault();
  const file = $("serverPackFile").files[0];
  if (!file) {
    showError(new Error("Bitte eine ZIP-Datei auswählen"));
    return;
  }
  const form = new FormData();
  form.append("file", file);
  setStatus("Upload");
  const payload = await api("/api/upload", { method: "POST", body: form });
  fillSettings(payload.settings);
  logLine(`Server-Pack hochgeladen: ${payload.path}`);
  if (payload.detected?.message) {
    logLine(payload.detected.message);
  }
  if (payload.detected?.source_type === "localCurseForgeExport") {
    logLine("Hinweis: Diese CurseForge Export-ZIP enthält keine Mod-JARs. Für Updates brauchst du eine echte Server-Pack-ZIP oder einen CurseForge Core API-Key.");
  }
  setStatus("Bereit");
}

async function searchModpacks() {
  const query = $("modpackSearch").value.trim();
  if (!query) {
    return;
  }
  setStatus("Suche");
  const payload = await api("/api/search", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
  const container = $("searchResults");
  container.innerHTML = "";
  for (const match of payload.matches) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>${match.name || "Unbenannt"}</strong>
      <span>ID ${match.id} · ${match.slug || ""}</span>
      <div class="item-actions"><button type="button">Verwenden</button></div>
    `;
    item.querySelector("button").addEventListener("click", () => {
      $("modpackId").value = match.id;
      $("sourceTypeInput").value = "curseforge";
      saveSettings().catch(showError);
    });
    container.appendChild(item);
  }
  setStatus("Bereit");
}

async function previewUpdate() {
  await saveSettings();
  setStatus("Berechne Diff");
  const payload = await api("/api/preview", { method: "POST", body: JSON.stringify({}) });
  $("targetVersion").textContent = `${payload.modpack_file.display_name} (${payload.modpack_file.id})`;
  $("addedCount").textContent = payload.summary.added;
  $("updatedCount").textContent = payload.summary.updated;
  $("removedCount").textContent = payload.summary.removed;
  $("unchangedCount").textContent = payload.summary.unchanged;
  renderDiff(payload.delta);
  setStatus("Bereit");
}

function renderDiff(delta) {
  const columns = [
    ["Neue Mods", delta.added || []],
    ["Aktualisierte Mods", delta.updated || []],
    ["Entfernte Mods", delta.removed || []],
  ];
  const container = $("diff");
  container.innerHTML = "";
  for (const [title, entries] of columns) {
    const column = document.createElement("div");
    column.className = "diff-column";
    const list = entries.map((entry) => {
      if (entry.from && entry.to) {
        return `<li>${entry.from.file_name || "alt"} → ${entry.to.file_name || "neu"}</li>`;
      }
      return `<li>${entry.file_name || entry.path || entry}</li>`;
    }).join("");
    column.innerHTML = `<h3>${title}</h3><ul>${list || "<li>Keine</li>"}</ul>`;
    container.appendChild(column);
  }
}

async function startUpdate(dryRun = false) {
  await saveSettings();
  $("liveLog").textContent = "";
  const job = await api("/api/jobs/update", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
  attachJob(job.id);
}

function attachJob(jobId) {
  state.currentJob = jobId;
  $("jobStatus").textContent = `Job ${jobId}`;
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    logLine(`${payload.step}: ${payload.message}`);
  };
  source.onerror = async () => {
    source.close();
    const job = await api(`/api/jobs/${jobId}`);
    $("jobStatus").textContent = `${job.kind}: ${job.status}`;
    if (job.error) {
      logLine(`error: ${job.error}`);
    }
    await refreshState();
  };
}

function renderBackups(backups) {
  const container = $("backups");
  container.innerHTML = "";
  if (!backups.length) {
    container.className = "list empty";
    container.textContent = "Keine Backups gefunden";
    return;
  }
  container.className = "list";
  for (const backup of backups) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>${backup.id}</strong>
      <span>${backup.path}</span>
      <div class="item-actions"><button class="danger" type="button">Rollback</button></div>
    `;
    item.querySelector("button").addEventListener("click", () => rollback(backup.path));
    container.appendChild(item);
  }
}

async function rollback(path) {
  if (!confirm(`Rollback auf ${path} durchführen?`)) {
    return;
  }
  const job = await api("/api/jobs/rollback", {
    method: "POST",
    body: JSON.stringify({ backup_dir: path }),
  });
  attachJob(job.id);
}

function showError(error) {
  setStatus("Fehler");
  logLine(`error: ${error.message}`);
}

window.addEventListener("DOMContentLoaded", () => {
  $("saveSettings").addEventListener("click", () => saveSettings().catch(showError));
  $("scanInstances").addEventListener("click", () => scanInstances().catch(showError));
  $("uploadForm").addEventListener("submit", (event) => uploadServerPack(event).catch(showError));
  $("searchModpacks").addEventListener("click", () => searchModpacks().catch(showError));
  $("previewUpdate").addEventListener("click", () => previewUpdate().catch(showError));
  $("dryRunUpdate").addEventListener("click", () => startUpdate(true).catch(showError));
  $("startUpdate").addEventListener("click", () => startUpdate(false).catch(showError));
  $("refreshState").addEventListener("click", () => refreshState().catch(showError));
  loadSettings().then(refreshState).catch(showError);
});
