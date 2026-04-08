// static/main.js

// Netprobe frontend updates in this revision:
// 1. Show fuller date + time labels on charts so month/day context is visible.
// 2. Display multi-domain DNS test targets from DNS_TEST_SITES.
// 3. Surface configured speedtest server details from SPEEDTEST_SERVER.

document.addEventListener("DOMContentLoaded", () => {
  const rawProbeInterval = parseInt(
    document.body.getAttribute("data-probe-interval"),
    10
  );
  const probeInterval =
    !isNaN(rawProbeInterval) && rawProbeInterval > 0 ? rawProbeInterval : 30;

  const nextProbeEl = document.getElementById("nextProbe");
  const lastProbeEl = document.getElementById("lastProbe");
  const generalOutput = document.getElementById("generalOutput");
  const speedtestSummary = document.getElementById("speedtestSummary");
  const dbBackendEl = document.getElementById("dbBackend");

  const btnShowConfig = document.getElementById("btnShowConfig");
  const btnRunSpeedtest = document.getElementById("btnRunSpeedtest");
  const rangeSelects = document.querySelectorAll(".range-select");
  const panelToggles = document.querySelectorAll(".panel-toggle");
  const dnsSeriesControls = document.getElementById("dns-series-controls");

  let lastTimestamp = null;
  let currentLimit = 0;

  // DNS per-server label + dataset bookkeeping.
  let dnsServerLabels = {}; // ip -> label for checkboxes/legend
  let dnsServerOrder = []; // ordered array of IPs in chart order
  let dnsDatasetsInitialized = false;

  // ----------------- Range -> limit helper -----------------

  function rangeValueToLimit(value) {
    const secondsMap = {
      "5s": 5,
      "10s": 10,
      "15s": 15,
      "30s": 30,
      "45s": 45,
      "60s": 60,
      "5m": 5 * 60,
      "10min": 10 * 60,
      "15m": 15 * 60,
      "20min": 20 * 60,
      "30m": 30 * 60,
      "45min": 45 * 60,
      "1h": 60 * 60,
      "3h": 3 * 60 * 60,
      "6h": 6 * 60 * 60,
      "9h": 9 * 60 * 60,
      "12h": 12 * 60 * 60,
      "24h": 24 * 60 * 60,
      "3d": 3 * 24 * 60 * 60,
      "5d": 5 * 24 * 60 * 60,
      "1w": 7 * 24 * 60 * 60,
      "2w": 14 * 24 * 60 * 60,
      "3w": 21 * 24 * 60 * 60,
      "1m": 30 * 24 * 60 * 60,
      "1mo": 30 * 24 * 60 * 60,
      "2mo": 60 * 24 * 60 * 60,
      "3mo": 90 * 24 * 60 * 60,
      "4mo": 120 * 24 * 60 * 60,
      "5mo": 150 * 24 * 60 * 60,
      "6mo": 180 * 24 * 60 * 60,
      "7mo": 210 * 24 * 60 * 60,
      "8mo": 240 * 24 * 60 * 60,
      "9mo": 270 * 24 * 60 * 60,
      "10mo": 300 * 24 * 60 * 60,
      "11mo": 330 * 24 * 60 * 60,
      "12mo": 365 * 24 * 60 * 60,
      "1y": 365 * 24 * 60 * 60,
    };

    const secs = secondsMap[value] || 60 * 60;
    const points = Math.floor(secs / probeInterval);
    return Math.max(10, Math.min(points, 10000));
  }

  function initCurrentLimit() {
    currentLimit = rangeSelects.length === 0 ? 2880 : rangeValueToLimit(rangeSelects[0].value);
  }

  initCurrentLimit();

  // ----------------- Time label helpers -----------------

  function formatTickLabelFromTs(tsSeconds, index, totalCount) {
    const date = new Date(tsSeconds * 1000);

    // For short windows, keep the label compact.
    if (totalCount <= 48) {
      return date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }

    // For larger windows, alternate between slightly denser labels.
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
    });
  }

  function buildTimeLabels(rows) {
    return rows.map((row, index) => formatTickLabelFromTs(row.ts, index, rows.length));
  }

  function formatFullTimestamp(tsSeconds) {
    return new Date(tsSeconds * 1000).toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  // ----------------- Charts & Gauges -----------------

  function makeGauge(ctx, label) {
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: [label, "Remaining"],
        datasets: [{ data: [0, 100] }],
      },
      options: {
        circumference: 180,
        rotation: 270,
        cutout: "70%",
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        },
      },
    });
  }

  function makeHistoryChart(ctx, label) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label,
            data: [],
            fill: false,
            tension: 0.1,
          },
        ],
      },
      options: {
        maintainAspectRatio: true,
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              maxRotation: 0,
              autoSkip: true,
            },
          },
          y: {
            beginAtZero: true,
          },
        },
      },
    });
  }

  const gScore = makeGauge(document.getElementById("gScore").getContext("2d"), "Score");
  const gLoss = makeGauge(document.getElementById("gLoss").getContext("2d"), "Loss");
  const gLatency = makeGauge(document.getElementById("gLatency").getContext("2d"), "Latency");
  const gJitter = makeGauge(document.getElementById("gJitter").getContext("2d"), "Jitter");
  const gDns = makeGauge(document.getElementById("gDns").getContext("2d"), "DNS");
  const gSpeed = makeGauge(document.getElementById("gSpeed").getContext("2d"), "Bandwidth");

  const cScoreHistory = makeHistoryChart(document.getElementById("cScoreHistory").getContext("2d"), "Score");
  const cLossHistory = makeHistoryChart(document.getElementById("cLossHistory").getContext("2d"), "Loss %");
  const cLatencyHistory = makeHistoryChart(document.getElementById("cLatencyHistory").getContext("2d"), "Latency ms");
  const cJitterHistory = makeHistoryChart(document.getElementById("cJitterHistory").getContext("2d"), "Jitter ms");
  const cDnsHistory = makeHistoryChart(document.getElementById("cDnsHistory").getContext("2d"), "DNS ms");

  const cSpeedHistory = new Chart(
    document.getElementById("cSpeedHistory").getContext("2d"),
    {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Download Mbps",
            data: [],
            fill: false,
            tension: 0.1,
          },
          {
            label: "Upload Mbps",
            data: [],
            fill: false,
            tension: 0.1,
          },
        ],
      },
      options: {
        maintainAspectRatio: true,
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              maxRotation: 0,
              autoSkip: true,
            },
          },
          y: {
            beginAtZero: true,
          },
        },
      },
    }
  );

  function clamp(val, max) {
    return Math.min(val, max);
  }

  // ----------------- DNS per-server helpers -----------------

  function ensureDnsDatasets(servers) {
    if (!cDnsHistory || !Array.isArray(servers) || !servers.length) return;
    if (dnsDatasetsInitialized) return;

    dnsServerOrder = servers.slice();
    cDnsHistory.data.datasets = [];
    if (dnsSeriesControls) dnsSeriesControls.innerHTML = "";

    servers.forEach((ip, idx) => {
      const label = dnsServerLabels[ip] || ip;

      cDnsHistory.data.datasets.push({
        label,
        data: [],
        fill: false,
        tension: 0.1,
        hidden: false,
      });

      if (dnsSeriesControls) {
        const wrapper = document.createElement("label");
        wrapper.className = "dns-series-label";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = true;
        cb.dataset.dnsIndex = String(idx);

        const span = document.createElement("span");
        span.textContent = label;

        wrapper.appendChild(cb);
        wrapper.appendChild(span);
        dnsSeriesControls.appendChild(wrapper);

        cb.addEventListener("change", () => {
          const i = parseInt(cb.dataset.dnsIndex, 10);
          if (!isNaN(i) && cDnsHistory.data.datasets[i] !== undefined) {
            cDnsHistory.data.datasets[i].hidden = !cb.checked;
            cDnsHistory.update();
          }
        });
      }
    });

    dnsDatasetsInitialized = true;
  }

  // ----------------- Probe data refresh -----------------

  async function refreshProbeData() {
    const res = await fetch(`/api/score/recent?limit=${currentLimit}`);
    const json = await res.json();
    const data = json.data || [];

    if (!data.length) {
      generalOutput.textContent = "No probe data yet. Waiting for first measurement...";
      return;
    }

    const last = data[data.length - 1];
    lastTimestamp = last.ts;

    const score = last.score || 0;
    const loss = last.avg_loss_pct || 0;
    const latency = last.avg_latency_ms || 0;
    const jitter = last.avg_jitter_ms || 0;
    const dns = last.avg_dns_latency_ms || 0;

    lastProbeEl.textContent = `Last probe: ${formatFullTimestamp(last.ts)}`;

    gScore.data.datasets[0].data = [score, 100 - score];
    gScore.update();

    const lossGaugeVal = clamp(loss, 100);
    gLoss.data.datasets[0].data = [100 - lossGaugeVal, lossGaugeVal];
    gLoss.update();

    const latencyGaugeVal = clamp(latency, 200);
    gLatency.data.datasets[0].data = [200 - latencyGaugeVal, latencyGaugeVal];
    gLatency.update();

    const jitterGaugeVal = clamp(jitter, 100);
    gJitter.data.datasets[0].data = [100 - jitterGaugeVal, jitterGaugeVal];
    gJitter.update();

    const dnsGaugeVal = clamp(dns, 200);
    gDns.data.datasets[0].data = [200 - dnsGaugeVal, dnsGaugeVal];
    gDns.update();

    document.getElementById("gScoreText").innerText = `Score: ${score.toFixed(1)}%`;
    document.getElementById("gLossText").innerText = `Loss: ${loss.toFixed(2)} %`;
    document.getElementById("gLatencyText").innerText = `Latency: ${latency.toFixed(1)} ms`;
    document.getElementById("gJitterText").innerText = `Jitter: ${jitter.toFixed(1)} ms`;
    document.getElementById("gDnsText").innerText = `DNS: ${dns.toFixed(1)} ms`;

    const labels = buildTimeLabels(data);

    cScoreHistory.data.labels = labels;
    cScoreHistory.data.datasets[0].data = data.map((d) => d.score);
    cScoreHistory.update();

    cLossHistory.data.labels = labels;
    cLossHistory.data.datasets[0].data = data.map((d) => d.avg_loss_pct);
    cLossHistory.update();

    cLatencyHistory.data.labels = labels;
    cLatencyHistory.data.datasets[0].data = data.map((d) => d.avg_latency_ms);
    cLatencyHistory.update();

    cJitterHistory.data.labels = labels;
    cJitterHistory.data.datasets[0].data = data.map((d) => d.avg_jitter_ms);
    cJitterHistory.update();

    cDnsHistory.data.labels = labels;

    const firstRowWithDns = data.find((row) => row.dns_per_server && Object.keys(row.dns_per_server).length);
    if (firstRowWithDns && firstRowWithDns.dns_per_server) {
      const servers = Object.keys(firstRowWithDns.dns_per_server);
      ensureDnsDatasets(servers);

      dnsServerOrder.forEach((ip, idx) => {
        const series = data.map((d) => {
          if (!d.dns_per_server) return null;
          const value = d.dns_per_server[ip];
          return typeof value === "number" ? value : null;
        });
        if (cDnsHistory.data.datasets[idx]) {
          cDnsHistory.data.datasets[idx].data = series;
        }
      });
    } else {
      if (!dnsDatasetsInitialized) {
        cDnsHistory.data.datasets = [
          {
            label: "DNS ms",
            data: [],
            fill: false,
            tension: 0.1,
          },
        ];
        dnsDatasetsInitialized = true;
      }
      cDnsHistory.data.datasets[0].data = data.map((d) => d.avg_dns_latency_ms);
    }
    cDnsHistory.update();
  }

  // ----------------- Config / Env display -----------------

  async function showConfig() {
    generalOutput.textContent = "Loading config / env...";
    const res = await fetch("/api/config");
    const cfg = await res.json();

    if (dbBackendEl && cfg.db_engine) {
      dbBackendEl.textContent = `DB: ${cfg.db_engine}`;
    } else if (dbBackendEl) {
      dbBackendEl.textContent = "DB: sqlite";
    }

    const lines = [];
    lines.push("== Probe Settings ==");
    lines.push(`DB engine: ${cfg.db_engine || "sqlite"}`);
    lines.push(`Probe interval: ${cfg.probe_interval}s`);
    lines.push(`Ping count per target: ${cfg.ping_count}`);
    lines.push(`Timezone: ${cfg.app_timezone}`);
    lines.push("");

    lines.push("== Ping Targets ==");
    if (cfg.gateway_ip) lines.push(`Gateway: ${cfg.gateway_ip}`);
    if (cfg.router_ip) lines.push(`Router: ${cfg.router_ip}`);
    if (cfg.sites && cfg.sites.length) lines.push(`Sites: ${cfg.sites.join(", ")}`);
    lines.push("");

    lines.push("== DNS ==");
    if (Array.isArray(cfg.dns_test_sites) && cfg.dns_test_sites.length) {
      lines.push(`Test domains: ${cfg.dns_test_sites.join(", ")}`);
    } else if (cfg.dns_test_site) {
      lines.push(`Test domain: ${cfg.dns_test_site}`);
    }

    dnsServerLabels = {};
    if (Array.isArray(cfg.dns_servers_detail)) {
      cfg.dns_servers_detail.forEach((server) => {
        if (!server || !server.ip) return;
        const label = server.name ? `${server.name} (${server.ip})` : server.ip;
        dnsServerLabels[server.ip] = label;
      });

      const displayList = cfg.dns_servers_detail
        .map((server) => {
          if (!server || !server.ip) return null;
          return server.name ? `${server.name} (${server.ip})` : server.ip;
        })
        .filter(Boolean);

      if (displayList.length) {
        lines.push(`Servers: ${displayList.join(", ")}`);
      }
    } else if (Array.isArray(cfg.dns_servers)) {
      cfg.dns_servers.forEach((ip) => {
        dnsServerLabels[ip] = ip;
      });
      if (cfg.dns_servers.length) {
        lines.push(`Servers: ${cfg.dns_servers.join(", ")}`);
      }
    }
    lines.push("");

    lines.push("== Score Weights ==");
    lines.push(`Loss: ${cfg.weight_loss}`);
    lines.push(`Latency: ${cfg.weight_latency}`);
    lines.push(`Jitter: ${cfg.weight_jitter}`);
    lines.push(`DNS Latency: ${cfg.weight_dns_latency}`);
    lines.push("");

    lines.push("== Score Thresholds ==");
    lines.push(`Loss: ${cfg.threshold_loss}%`);
    lines.push(`Latency: ${cfg.threshold_latency} ms`);
    lines.push(`Jitter: ${cfg.threshold_jitter} ms`);
    lines.push(`DNS Latency: ${cfg.threshold_dns_latency} ms`);
    lines.push("");

    lines.push("== Speedtest ==");
    lines.push(`Enabled: ${cfg.speedtest_enabled}`);
    lines.push(`Interval: ${cfg.speedtest_interval}s`);
    lines.push(`Requested server ID: ${cfg.speedtest_server || "auto"}`);

    generalOutput.textContent = lines.join("
");
  }

  // ----------------- Speedtest handling -----------------

  async function refreshSpeedtestHistory() {
    const res = await fetch(`/api/speedtest/history?limit=${currentLimit}`);
    const json = await res.json();
    const tests = json.tests || [];
    if (!tests.length) return;

    const labels = tests.map((t) => formatTickLabelFromTs(t.ts, 0, tests.length));
    const downs = tests.map((t) => t.download_mbps);
    const ups = tests.map((t) => t.upload_mbps);

    cSpeedHistory.data.labels = labels;
    cSpeedHistory.data.datasets[0].data = downs;
    cSpeedHistory.data.datasets[1].data = ups;
    cSpeedHistory.update();

    const last = tests[tests.length - 1];
    const maxMbps = Math.max(...downs, ...ups, 1);
    const used = clamp((last.download_mbps / maxMbps) * 100, 100);
    gSpeed.data.datasets[0].data = [used, 100 - used];
    gSpeed.update();

    document.getElementById("gSpeedText").innerText = `Down: ${last.download_mbps.toFixed(1)} Mbps
Up: ${last.upload_mbps.toFixed(1)} Mbps`;
  }

  async function refreshSpeedtestSummaryOnce() {
    try {
      const res = await fetch("/api/speedtest/latest");
      const json = await res.json();
      const r = json.result;
      if (!r) return;

      const serverBits = [];
      if (r.server?.name) serverBits.push(r.server.name);
      if (r.server?.country) serverBits.push(r.server.country);
      const serverText = serverBits.length ? ` via ${serverBits.join(", ")}` : "";
      const requestedText = r.requested_server_id ? ` [requested ${r.requested_server_id}]` : "";

      speedtestSummary.textContent = `Speedtest: ${r.download_mbps?.toFixed(1)}↓ / ${r.upload_mbps?.toFixed(1)}↑ Mbps (ping ${r.ping_ms?.toFixed(1)} ms)${serverText}${requestedText}`;
    } catch (e) {
      // ignore summary refresh errors
    }
  }

  async function runSpeedtestNow() {
    generalOutput.textContent = "Running speedtest... this can take a bit...";
    speedtestSummary.textContent = "Speedtest: running...";

    try {
      const res = await fetch("/api/speedtest/run", { method: "POST" });
      if (!res.ok) {
        const errText = await res.text();
        generalOutput.textContent = "Speedtest failed: " + (errText || res.status);
        speedtestSummary.textContent = "Speedtest: failed";
        return;
      }

      const json = await res.json();
      if (!json.success) {
        generalOutput.textContent = "Speedtest failed: " + (json.error || "unknown error");
        speedtestSummary.textContent = "Speedtest: failed";
        return;
      }

      const r = json.result;
      const textLines = [
        "== Manual Speedtest Result ==",
        `Time: ${formatFullTimestamp(r.timestamp)}`,
        `Ping: ${r.ping_ms?.toFixed(1)} ms`,
        `Download: ${r.download_mbps?.toFixed(2)} Mbps`,
        `Upload: ${r.upload_mbps?.toFixed(2)} Mbps`,
        `Requested server ID: ${r.requested_server_id || "auto"}`,
      ];

      if (r.server) {
        const serverDisplay = [
          r.server.id ? `id ${r.server.id}` : null,
          r.server.name || null,
          r.server.host || null,
          r.server.country || null,
        ]
          .filter(Boolean)
          .join(" | ");
        textLines.push(`Resolved server: ${serverDisplay}`);
      }

      generalOutput.textContent = textLines.join("
");
      refreshSpeedtestHistory();
      refreshSpeedtestSummaryOnce();
    } catch (e) {
      generalOutput.textContent = "Speedtest error: " + e;
      speedtestSummary.textContent = "Speedtest: error";
    }
  }

  // ----------------- Countdown -----------------

  function updateCountdown() {
    if (!lastTimestamp) {
      nextProbeEl.textContent = "Next probe in: waiting for first sample...";
      return;
    }

    const nowSec = Math.floor(Date.now() / 1000);
    let elapsed = nowSec - lastTimestamp;
    if (elapsed < 0) elapsed = 0;

    let remaining = probeInterval - (elapsed % probeInterval);
    if (remaining === probeInterval) remaining = 0;
    nextProbeEl.textContent = `Next probe in: ${remaining}s`;
  }

  // ----------------- Panel visibility -----------------

  function applyPanelVisibilityFromStorage() {
    const saved = localStorage.getItem("netprobe_panel_vis");
    let visibility = {};

    if (saved) {
      try {
        visibility = JSON.parse(saved);
      } catch (_) {
        visibility = {};
      }
    }

    panelToggles.forEach((cb) => {
      const targetId = cb.getAttribute("data-target");
      const panel = document.getElementById(targetId);
      if (!panel) return;

      const shouldShow = visibility[targetId] !== undefined ? visibility[targetId] : true;
      cb.checked = shouldShow;
      panel.style.display = shouldShow ? "" : "none";
    });
  }

  function savePanelVisibility() {
    const visibility = {};
    panelToggles.forEach((cb) => {
      const targetId = cb.getAttribute("data-target");
      visibility[targetId] = cb.checked;
    });
    localStorage.setItem("netprobe_panel_vis", JSON.stringify(visibility));
  }

  panelToggles.forEach((cb) => {
    cb.addEventListener("change", () => {
      const targetId = cb.getAttribute("data-target");
      const panel = document.getElementById(targetId);
      if (!panel) return;
      panel.style.display = cb.checked ? "" : "none";
      savePanelVisibility();
    });
  });

  applyPanelVisibilityFromStorage();

  // ----------------- Event wiring -----------------

  rangeSelects.forEach((sel) => {
    sel.addEventListener("change", () => {
      const value = sel.value;
      rangeSelects.forEach((other) => {
        other.value = value;
      });
      currentLimit = rangeValueToLimit(value);
      refreshProbeData();
      refreshSpeedtestHistory();
    });
  });

  btnShowConfig.addEventListener("click", () => {
    showConfig();
  });
  btnRunSpeedtest.addEventListener("click", runSpeedtestNow);

  // ----------------- Initial loads -----------------

  showConfig()
    .catch(() => {
      // ignore config load errors; UI can still continue
    })
    .finally(() => {
      refreshProbeData();
      refreshSpeedtestHistory();
      refreshSpeedtestSummaryOnce();
    });

  setInterval(() => {
    refreshProbeData();
    refreshSpeedtestHistory();
    refreshSpeedtestSummaryOnce();
  }, Math.max(10 * 1000, probeInterval * 1000));

  setInterval(updateCountdown, 1000);
});
