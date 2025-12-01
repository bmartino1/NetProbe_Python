// static/main.js

document.addEventListener("DOMContentLoaded", () => {
  const rawProbeInterval = parseInt(
    document.body.getAttribute("data-probe-interval"),
    10
  );
  const probeInterval =
    !isNaN(rawProbeInterval) && rawProbeInterval > 0
      ? rawProbeInterval
      : 30;

  const nextProbeEl = document.getElementById("nextProbe");
  const lastProbeEl = document.getElementById("lastProbe");
  const generalOutput = document.getElementById("generalOutput");
  const speedtestSummary = document.getElementById("speedtestSummary");

  const btnShowConfig = document.getElementById("btnShowConfig");
  const btnRunSpeedtest = document.getElementById("btnRunSpeedtest");
  const rangeSelects = document.querySelectorAll(".range-select");

  let lastTimestamp = null;
  let currentLimit = 0; // computed from range selection

  // ----------------- Range → limit helper -----------------

  function rangeValueToLimit(value) {
    const secondsMap = {
      "5s": 5,
      "10s": 10,
      "15s": 15,
      "30s": 30,
      "45s": 45,
      "60s": 60,
      "5m": 5 * 60,
      "15m": 15 * 60,
      "1h": 60 * 60,
      "3h": 3 * 60 * 60,
      "6h": 6 * 60 * 60,
      "12h": 12 * 60 * 60,
      "24h": 24 * 60 * 60,
      "1w": 7 * 24 * 60 * 60,
      "1m": 30 * 24 * 60 * 60,
      "1y": 365 * 24 * 60 * 60,
    };
    const secs = secondsMap[value] || 60 * 60;
    const points = Math.floor(secs / probeInterval);
    return Math.max(10, Math.min(points, 10000));
  }

  function initCurrentLimit() {
    if (rangeSelects.length === 0) {
      currentLimit = 2880;
    } else {
      currentLimit = rangeValueToLimit(rangeSelects[0].value);
    }
  }

  initCurrentLimit();

  // ----------------- Charts & Gauges -----------------

  function makeGauge(ctx, label) {
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: [label, "Remaining"],
        datasets: [
          {
            data: [0, 100],
          },
        ],
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

  const gScore = makeGauge(
    document.getElementById("gScore").getContext("2d"),
    "Score"
  );
  const gLoss = makeGauge(
    document.getElementById("gLoss").getContext("2d"),
    "Loss"
  );
  const gLatency = makeGauge(
    document.getElementById("gLatency").getContext("2d"),
    "Latency"
  );
  const gJitter = makeGauge(
    document.getElementById("gJitter").getContext("2d"),
    "Jitter"
  );
  const gDns = makeGauge(
    document.getElementById("gDns").getContext("2d"),
    "DNS"
  );

  const gSpeed = makeGauge(
    document.getElementById("gSpeed").getContext("2d"),
    "Bandwidth"
  );

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
        scales: {
          x: {
            ticks: { maxTicksLimit: 8 },
          },
          y: {
            beginAtZero: true,
          },
        },
      },
    });
  }

  const cScoreHistory = makeHistoryChart(
    document.getElementById("cScoreHistory").getContext("2d"),
    "Score"
  );
  const cLossHistory = makeHistoryChart(
    document.getElementById("cLossHistory").getContext("2d"),
    "Loss %"
  );
  const cLatencyHistory = makeHistoryChart(
    document
      .getElementById("cLatencyHistory")
      .getContext("2d"),
    "Latency ms"
  );
  const cJitterHistory = makeHistoryChart(
    document.getElementById("cJitterHistory").getContext("2d"),
    "Jitter ms"
  );
  const cDnsHistory = makeHistoryChart(
    document.getElementById("cDnsHistory").getContext("2d"),
    "DNS ms"
  );

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
        scales: {
          x: {
            ticks: { maxTicksLimit: 8 },
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

  // ----------------- Probe data refresh -----------------

  async function refreshProbeData() {
    const res = await fetch(`/api/score/recent?limit=${currentLimit}`);
    const json = await res.json();
    const data = json.data || [];
    if (!data.length) {
      generalOutput.textContent =
        "No probe data yet. Waiting for first measurement…";
      return;
    }

    const last = data[data.length - 1];
    lastTimestamp = last.ts;

    const score = last.score || 0;
    const loss = last.avg_loss_pct || 0;
    const latency = last.avg_latency_ms || 0;
    const jitter = last.avg_jitter_ms || 0;
    const dns = last.avg_dns_latency_ms || 0;

    const lastDate = new Date(last.ts * 1000);
    lastProbeEl.textContent = `Last probe: ${lastDate.toLocaleString()}`;

    // Gauges
    gScore.data.datasets[0].data = [score, 100 - score];
    gScore.update();

    const lossGaugeVal = clamp(loss, 100);
    gLoss.data.datasets[0].data = [100 - lossGaugeVal, lossGaugeVal];
    gLoss.update();

    const latencyGaugeVal = clamp(latency, 200);
    gLatency.data.datasets[0].data = [
      200 - latencyGaugeVal,
      latencyGaugeVal,
    ];
    gLatency.update();

    const jitterGaugeVal = clamp(jitter, 100);
    gJitter.data.datasets[0].data = [
      100 - jitterGaugeVal,
      jitterGaugeVal,
    ];
    gJitter.update();

    const dnsGaugeVal = clamp(dns, 200);
    gDns.data.datasets[0].data = [200 - dnsGaugeVal, dnsGaugeVal];
    gDns.update();

    // Gauge text
    document.getElementById(
      "gScoreText"
    ).innerText = `Score: ${score.toFixed(1)}%`;
    document.getElementById(
      "gLossText"
    ).innerText = `Loss: ${loss.toFixed(2)} %`;
    document.getElementById(
      "gLatencyText"
    ).innerText = `Latency: ${latency.toFixed(1)} ms`;
    document.getElementById(
      "gJitterText"
    ).innerText = `Jitter: ${jitter.toFixed(1)} ms`;
    document.getElementById(
      "gDnsText"
    ).innerText = `DNS: ${dns.toFixed(1)} ms`;

    // History charts
    const labels = data.map((d) =>
      new Date(d.ts * 1000).toLocaleTimeString()
    );

    cScoreHistory.data.labels = labels;
    cScoreHistory.data.datasets[0].data = data.map((d) => d.score);
    cScoreHistory.update();

    cLossHistory.data.labels = labels;
    cLossHistory.data.datasets[0].data = data.map(
      (d) => d.avg_loss_pct
    );
    cLossHistory.update();

    cLatencyHistory.data.labels = labels;
    cLatencyHistory.data.datasets[0].data = data.map(
      (d) => d.avg_latency_ms
    );
    cLatencyHistory.update();

    cJitterHistory.data.labels = labels;
    cJitterHistory.data.datasets[0].data = data.map(
      (d) => d.avg_jitter_ms
    );
    cJitterHistory.update();

    cDnsHistory.data.labels = labels;
    cDnsHistory.data.datasets[0].data = data.map(
      (d) => d.avg_dns_latency_ms
    );
    cDnsHistory.update();
  }

  // ----------------- Config / Env display -----------------

  async function showConfig() {
    generalOutput.textContent = "Loading config / env…";
    const res = await fetch("/api/config");
    const cfg = await res.json();

    const lines = [];

    lines.push("== Probe Settings ==");
    lines.push(`Probe interval: ${cfg.probe_interval}s`);
    lines.push(`Ping count per target: ${cfg.ping_count}`);
    lines.push(`Timezone: ${cfg.app_timezone}`);
    lines.push("");

    lines.push("== Ping Targets ==");
    if (cfg.gateway_ip) lines.push(`Gateway: ${cfg.gateway_ip}`);
    if (cfg.router_ip) lines.push(`Router: ${cfg.router_ip}`);
    if (cfg.sites && cfg.sites.length)
      lines.push(`Sites: ${cfg.sites.join(", ")}`);
    lines.push("");

    lines.push("== DNS ==");
    lines.push(`Test domain: ${cfg.dns_test_site}`);
    if (cfg.dns_servers && cfg.dns_servers.length)
      lines.push(`Servers: ${cfg.dns_servers.join(", ")}`);
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

    generalOutput.textContent = lines.join("\n");
  }

  // ----------------- Speedtest handling -----------------

  async function refreshSpeedtestHistory() {
    const res = await fetch(
      `/api/speedtest/history?limit=${currentLimit}`
    );
    const json = await res.json();
    const tests = json.tests || [];
    if (!tests.length) {
      return;
    }

    const labels = tests.map((t) =>
      new Date(t.ts * 1000).toLocaleTimeString()
    );
    const downs = tests.map((t) => t.download_mbps);
    const ups = tests.map((t) => t.upload_mbps);

    cSpeedHistory.data.labels = labels;
    cSpeedHistory.data.datasets[0].data = downs;
    cSpeedHistory.data.datasets[1].data = ups;
    cSpeedHistory.update();

    // Update bandwidth gauge to show most recent test
    const last = tests[tests.length - 1];
    const maxMbps = Math.max(...downs, ...ups, 1);
    const used = clamp(
      (last.download_mbps / maxMbps) * 100,
      100
    );
    gSpeed.data.datasets[0].data = [used, 100 - used];
    gSpeed.update();

    document.getElementById(
      "gSpeedText"
    ).innerText = `Down: ${last.download_mbps.toFixed(
      1
    )} Mbps\nUp: ${last.upload_mbps.toFixed(1)} Mbps`;
  }

  async function refreshSpeedtestSummaryOnce() {
    try {
      const res = await fetch("/api/speedtest/latest");
      const json = await res.json();
      const r = json.result;
      if (!r) return;
      speedtestSummary.textContent = `Speedtest: ${r.download_mbps?.toFixed(
        1
      )}↓ / ${r.upload_mbps?.toFixed(1)}↑ Mbps (ping ${r.ping_ms?.toFixed(
        1
      )} ms)`;
    } catch (e) {
      // ignore
    }
  }

  async function runSpeedtestNow() {
    generalOutput.textContent = "Running speedtest… this can take a bit…";
    speedtestSummary.textContent = "Speedtest: running…";

    try {
      const res = await fetch("/api/speedtest/run", {
        method: "POST",
      });
      if (!res.ok) {
        const errText = await res.text();
        generalOutput.textContent =
          "Speedtest failed: " + (errText || res.status);
        speedtestSummary.textContent = "Speedtest: failed";
        return;
      }
      const json = await res.json();
      if (!json.success) {
        generalOutput.textContent =
          "Speedtest failed: " + (json.error || "unknownerror");
        speedtestSummary.textContent = "Speedtest: failed";
        return;
      }
      const r = json.result;
      const ts = new Date(r.timestamp * 1000).toLocaleString();
      const textLines = [
        "== Manual Speedtest Result ==",
        `Time: ${ts}`,
        `Ping: ${r.ping_ms?.toFixed(1)} ms`,
        `Download: ${r.download_mbps?.toFixed(2)} Mbps`,
        `Upload: ${r.upload_mbps?.toFixed(2)} Mbps`,
      ];
      if (r.server) {
        const s = r.server;
        const srvStr = `${s.name || ""} (${s.host || ""}) [${
          s.country || ""
        }]`;
        textLines.push(`Server: ${srvStr}`);
      }
      generalOutput.textContent = textLines.join("\n");
      speedtestSummary.textContent = `Speedtest: ${r.download_mbps?.toFixed(
        1
      )}↓ / ${r.upload_mbps?.toFixed(1)}↑ Mbps (ping ${r.ping_ms?.toFixed(
        1
      )} ms)`;

      // refresh chart / gauge with new result in DB
      refreshSpeedtestHistory();
    } catch (e) {
      generalOutput.textContent = "Speedtest error: " + e;
      speedtestSummary.textContent = "Speedtest: error";
    }
  }

  // ----------------- Countdown -----------------

  function updateCountdown() {
    if (!lastTimestamp) {
      nextProbeEl.textContent = "Next probe in: waiting for first sample…";
      return;
    }
    const nowSec = Math.floor(Date.now() / 1000);
    let elapsed = nowSec - lastTimestamp;
    if (elapsed < 0) elapsed = 0;
    let remaining = probeInterval - (elapsed % probeInterval);
    if (remaining === probeInterval) remaining = 0;
    nextProbeEl.textContent = `Next probe in: ${remaining}s`;
  }

  // ----------------- Event wiring -----------------

  // Range selects: keep all in sync; change one → update all & refresh
  rangeSelects.forEach((sel) => {
    sel.addEventListener("change", () => {
      const value = sel.value;
      rangeSelects.forEach((s) => {
        s.value = value;
      });
      currentLimit = rangeValueToLimit(value);
      refreshProbeData();
      refreshSpeedtestHistory();
    });
  });

  btnShowConfig.addEventListener("click", showConfig);
  btnRunSpeedtest.addEventListener("click", runSpeedtestNow);

  // ----------------- Initial loads -----------------

  refreshProbeData();
  refreshSpeedtestHistory();
  refreshSpeedtestSummaryOnce();
  showConfig(); // populate general area

  // Periodic refresh & countdown
  setInterval(
    () => {
      refreshProbeData();
      refreshSpeedtestHistory();
      refreshSpeedtestSummaryOnce();
    },
    Math.max(10 * 1000, probeInterval * 1000)
  );
  setInterval(updateCountdown, 1000);
});
