"use strict";

const TOKEN_STORAGE_KEY = "picture-frame-token";
const SECTION_TITLES = {
  dashboard: "Dashboard",
  immich: "Immich",
  albums: "Albums",
  display: "Display",
  storage: "Storage",
  advanced: "Advanced",
};

const state = {
  authRequired: false,
  token: null,
  currentSection: "dashboard",
  toastTimer: null,
};

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    state.token = null;
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    showLogin();
    throw new Error("Authentication required");
  }
  let data = null;
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    data = await res.json();
  }
  if (!res.ok) {
    const message = (data && (data.error || data.message)) || res.statusText;
    throw new Error(message);
  }
  return data;
}

function showToast(message, kind) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("ok", "error");
  if (kind) toast.classList.add(kind);
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 3500);
}

function selectSection(name) {
  state.currentSection = name;
  document.querySelectorAll("[data-section-body]").forEach((node) => {
    node.hidden = node.id !== `section-${name}`;
  });
  document.querySelectorAll(".nav-item").forEach((node) => {
    node.classList.toggle("active", node.dataset.section === name);
  });
  document.getElementById("pageTitle").textContent = SECTION_TITLES[name] || "Dashboard";
  if (name === "albums") {
    app.loadAlbums().catch((err) => showToast(err.message, "error"));
  }
}

function setSelectedValues(select, values) {
  const selected = new Set(values || []);
  Array.from(select.options).forEach((opt) => {
    opt.selected = selected.has(opt.value);
  });
}

function getSelectedValues(select) {
  return Array.from(select.options)
    .filter((opt) => opt.selected)
    .map((opt) => opt.value);
}

function formatRelative(iso) {
  if (!iso) return "Never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const delta = (Date.now() - then) / 1000;
  if (delta < 60) return `${Math.max(0, Math.floor(delta))}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function formatCountdown(seconds) {
  if (seconds == null) return "—";
  if (seconds <= 0) return "any moment";
  if (seconds < 60) return `in ${Math.floor(seconds)}s`;
  if (seconds < 3600) return `in ${Math.floor(seconds / 60)}m`;
  return `in ${Math.floor(seconds / 3600)}h`;
}

function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function renderStorage(cache) {
  if (!cache) return;
  document.getElementById("storageFiles").textContent = cache.cached_files ?? 0;
  document.getElementById("storageCached").textContent = formatBytes(cache.cached_bytes);
  const disk = cache.disk || {};
  document.getElementById("storageUsed").textContent = formatBytes(disk.used_bytes);
  document.getElementById("storageFree").textContent = formatBytes(disk.free_bytes);

  document.getElementById("maxDiskPct").value = cache.max_disk_usage_percent;
  document.getElementById("minFreeMb").value = cache.min_free_space_mb;

  const cap = Number(cache.max_disk_usage_percent) || 100;
  const used = Number(disk.used_percent) || 0;
  const fill = document.getElementById("diskBar");
  fill.style.width = `${Math.min(100, used).toFixed(1)}%`;
  fill.classList.remove("warn", "bad");
  if (used >= cap) fill.classList.add("bad");
  else if (used >= cap * 0.9) fill.classList.add("warn");

  document.getElementById("diskCap").style.left = `${Math.min(100, cap)}%`;

  const pill = document.getElementById("storagePill");
  pill.textContent = `${used.toFixed(1)}% used · cap ${cap}%`;
  pill.className = "pill " + (used >= cap ? "bad" : used >= cap * 0.9 ? "warn" : "ok");

  document.getElementById("storageHint").textContent =
    `Directory: ${cache.directory}. Cap at ${cap}%, min ${cache.min_free_space_mb} MB free — oldest cached photos are evicted first when either limit would be crossed.`;
}

function renderStatus(data) {
  document.getElementById("statImages").textContent = data.image_count ?? "—";
  document.getElementById("statLastSync").textContent = formatRelative(data.last_sync);
  document.getElementById("statInterval").textContent =
    data.sync_interval_minutes ? `every ${data.sync_interval_minutes} min` : "—";

  let nextSyncText = "—";
  if (data.sync_interval_minutes) {
    if (!data.last_sync) {
      nextSyncText = "any moment";
    } else {
      const intervalMs = data.sync_interval_minutes * 60 * 1000;
      const nextAt = new Date(data.last_sync).getTime() + intervalMs;
      nextSyncText = formatCountdown((nextAt - Date.now()) / 1000);
    }
  }
  document.getElementById("statNextSync").textContent = nextSyncText;

  const conn = document.getElementById("connStatus");
  if (data.immich_configured) {
    conn.textContent = "Connected";
    conn.className = "pill ok";
  } else {
    conn.textContent = "Immich not configured";
    conn.className = "pill warn";
  }

  const immichBadge = document.getElementById("immichBadge");
  immichBadge.textContent = data.immich_configured ? "Configured" : "Not configured";
  immichBadge.className = `pill ${data.immich_configured ? "ok" : "warn"}`;

  if (data.immich_base_url) {
    document.getElementById("baseUrl").value = data.immich_base_url;
  }

  const lastSyncBox = document.getElementById("lastSyncBox");
  if (data.last_error) {
    lastSyncBox.textContent = `Last error: ${data.last_error}`;
  } else if (data.last_sync_stats && Object.keys(data.last_sync_stats).length) {
    lastSyncBox.textContent = JSON.stringify(
      { at: data.last_sync, stats: data.last_sync_stats },
      null,
      2
    );
  } else {
    lastSyncBox.textContent = "No sync yet.";
  }

  if (data.display) {
    document.getElementById("slideSeconds").value = data.display.slide_seconds;
    document.getElementById("transitionSeconds").value = data.display.transition_seconds;
    document.getElementById("displayMode").value = data.display.mode;
  }

  if (data.sync_interval_minutes) {
    document.getElementById("syncInterval").value = data.sync_interval_minutes;
  }

  if (Array.isArray(data.albums)) {
    const select = document.getElementById("albumSelect");
    setSelectedValues(select, data.albums);
  }

  renderStorage(data.cache);

  document.getElementById("statusBox").textContent = JSON.stringify(data, null, 2);
}

const app = {
  async refreshStatus() {
    try {
      const data = await api("/status");
      renderStatus(data);
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async saveImmich() {
    const payload = {
      base_url: document.getElementById("baseUrl").value.trim(),
      api_key: document.getElementById("apiKey").value.trim(),
    };
    try {
      await api("/config/immich", { method: "POST", body: JSON.stringify(payload) });
      document.getElementById("apiKey").value = "";
      showToast("Immich connection saved", "ok");
      await this.refreshStatus();
      await this.loadAlbums();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async loadAlbums() {
    const select = document.getElementById("albumSelect");
    const previous = getSelectedValues(select);
    try {
      const data = await api("/immich/albums");
      const albums = (data.result && data.result.albums) || [];
      select.innerHTML = "";
      for (const album of albums) {
        const opt = document.createElement("option");
        opt.value = album.id;
        const count = album.asset_count ? ` (${album.asset_count})` : "";
        const shared = album.is_shared ? " · shared" : "";
        opt.textContent = `${album.title}${count}${shared}`;
        select.appendChild(opt);
      }
      setSelectedValues(select, previous);
      const status = await api("/status");
      if (Array.isArray(status.albums)) {
        setSelectedValues(select, status.albums);
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async saveAlbums() {
    const select = document.getElementById("albumSelect");
    const payload = {
      albums: getSelectedValues(select),
      sync_now: document.getElementById("syncNow").checked,
    };
    try {
      await api("/config/albums", { method: "POST", body: JSON.stringify(payload) });
      showToast("Albums saved", "ok");
      await this.refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async saveSync() {
    const payload = {
      interval_minutes: Number(document.getElementById("syncInterval").value),
    };
    try {
      const data = await api("/config/sync", { method: "POST", body: JSON.stringify(payload) });
      showToast(`Sync interval set to ${data.result.interval_minutes} min`, "ok");
      await this.refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async saveCache() {
    const payload = {
      max_disk_usage_percent: Number(document.getElementById("maxDiskPct").value),
      min_free_space_mb: Number(document.getElementById("minFreeMb").value),
    };
    try {
      await api("/config/cache", { method: "POST", body: JSON.stringify(payload) });
      showToast("Cache settings saved", "ok");
      await this.refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async saveDisplay() {
    const payload = {
      slide_seconds: Number(document.getElementById("slideSeconds").value),
      transition_seconds: Number(document.getElementById("transitionSeconds").value),
      mode: document.getElementById("displayMode").value,
    };
    try {
      await api("/config/display", { method: "POST", body: JSON.stringify(payload) });
      showToast("Display settings saved", "ok");
      await this.refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async syncNow() {
    showToast("Sync started…");
    try {
      const data = await api("/sync", { method: "POST" });
      showToast(`Sync done: ${JSON.stringify(data.result)}`, "ok");
      await this.refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  async stopServer() {
    if (!confirm("Stop the picture frame service? You'll need to restart it manually.")) {
      return;
    }
    try {
      await api("/stop", { method: "POST", headers: { "X-Allow-Stop": "true" } });
      showToast("Stop signal sent");
    } catch (err) {
      showToast(err.message, "error");
    }
  },

  logout() {
    state.token = null;
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    showLogin();
  },
};

window.app = app;

function hideLogin() {
  document.getElementById("loginOverlay").hidden = true;
  document.getElementById("appShell").hidden = false;
}

function showLogin() {
  document.getElementById("appShell").hidden = true;
  document.getElementById("loginOverlay").hidden = false;
  document.getElementById("loginToken").focus();
}

async function attemptLogin(token) {
  state.token = token;
  try {
    await api("/status");
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
    document.getElementById("loginError").hidden = true;
    hideLogin();
    boot();
  } catch (err) {
    state.token = null;
    const error = document.getElementById("loginError");
    error.textContent = err.message || "Invalid token";
    error.hidden = false;
  }
}

async function boot() {
  await app.refreshStatus();
  await app.loadAlbums().catch(() => {});
  // Poll status every 5s for live updates.
  setInterval(() => app.refreshStatus().catch(() => {}), 5000);
}

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".nav-item").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      const section = node.dataset.section;
      history.replaceState(null, "", `#${section}`);
      selectSection(section);
    });
  });

  const initialSection = window.location.hash.replace("#", "") || "dashboard";
  selectSection(SECTION_TITLES[initialSection] ? initialSection : "dashboard");

  document.getElementById("loginSubmit").addEventListener("click", async () => {
    const token = document.getElementById("loginToken").value.trim();
    if (!token) return;
    await attemptLogin(token);
  });
  document.getElementById("loginToken").addEventListener("keydown", (event) => {
    if (event.key === "Enter") document.getElementById("loginSubmit").click();
  });
  document.getElementById("logoutBtn").addEventListener("click", () => app.logout());

  const authInfo = await fetch("/auth/config").then((res) => res.json()).catch(() => ({}));
  state.authRequired = !!authInfo.auth_required;

  if (state.authRequired) {
    document.getElementById("logoutBtn").hidden = false;
    const stored = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) {
      await attemptLogin(stored);
    } else {
      showLogin();
    }
  } else {
    hideLogin();
    boot();
  }
});
