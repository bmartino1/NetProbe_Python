// static/main.js

document.addEventListener("DOMContentLoaded", () => {
  const probeInterval =
    parseInt(document.body.getAttribute("data-probe-interval"), 10) || 30;

  const rangeSelect = document.getElementById("rangeSelect");
  const nextProbeEl = document.getElementById("nextProbe");
  const lastProbeEl = document.getElementById("lastProbe");
  const generalOutput = document.getElementById("generalOutput");
  const speedtestSummary = document.getElementById("speedtestSummary");

  const btnShowConfig = document.getElementById("btnShowConfig");
  const btnRunSpeedtest = document.getElementById("btnRunSpeedtest");

  let lastTimestamp = null;
  let currentLimit = parseInt(rangeSelect.value, 10) || 300;

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
    document.getElementById("cLatencyHistory").getContext("2d"),
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

  function clamp(val, max) {
    return Math.min(val, max);
  }

  // ----------------- Data refresh -----------------

  async function refreshData() {
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

    // Last/next probe text
    const lastDate = new Date(last.ts * 1000);
    lastProbeEl.textContent = `Last probe: ${lastDate.toLocaleString()}`;

    // Score gauge
    gScore.data.datasets[0].data = [score, 100 - score];
    gScore.update();

    // Loss gauge (0–100%)
    const lossGaugeVal = clamp(loss, 100);
    gLoss.data.datasets[0].data = [100 - lossGaugeVal, lossGaugeVal];
    gLoss.update();

    // Latency gauge (0–200 ms)
    const latencyGaugeVal = clamp(latency, 200);
    gLatency.data.datasets[0].data = [200 - latencyGaugeVal, latencyGaugeVal];
    gLatency.update();

    // Jitter gauge (0–100 ms)
    const jitterGaugeVal = clamp(jitter, 100);
    gJitter.data.datasets[0].data = [100 - jitterGaugeVal, jitterGaugeVal];
    gJitter.update();

    // DNS gauge (0–200 ms)
    const dnsGaugeVal = clamp(dns, 200);
    gDns.data.datasets[0].data = [200 - dnsGaugeVal, dnsGaugeVal];
    gDns.update();

    // Text labels
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
    cLossHistory.data.datasets[0].data = data.map((d) => d.avg_loss_pct);
    cLossHistory.update();

    cLatencyHistory.data.labels = labels;
    cLatencyHistory.data.datasets[0].data = data.map(
      (d) => d.avg_latency_ms
    );
    cLatencyHistory.update();

    cJitterHistory.data.labels = labels;
    cJitterHistory.data.datasets[0].data = data.map((d) => d.avg_jitter_ms);
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

  // ----------------- Speedtest Now -----------------

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
          "Speedtest failed: " + (json.error || "unknown error");
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
        const srvStr = `${s.name || ""} (${s.host || ""}) [${s.country || ""}]`;
        textLines.push(`Server: ${srvStr}`);
      }
      generalOutput.textContent = textLines.join("\n");
      speedtestSummary.textContent = `Speedtest: ${r.download_mbps?.toFixed(
        1
      )}↓ / ${r.upload_mbps?.toFixed(1)}↑ Mbps (ping ${r.ping_ms?.toFixed(
        1
      )} ms)`;
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
    const nextTs = lastTimestamp + probeInterval;
    let remaining = nextTs - nowSec;
    if (remaining < 0) remaining = 0;
    nextProbeEl.textContent = `Next probe in: ${remaining}s`;
  }

  // ----------------- Event wiring -----------------

  rangeSelect.addEventListener("change", () => {
    currentLimit = parseInt(rangeSelect.value, 10) || 300;
    refreshData();
  });

  btnShowConfig.addEventListener("click", showConfig);
  btnRunSpeedtest.addEventListener("click", runSpeedtestNow);

  // Initial loads
  refreshData();
  showConfig(); // populate general area once at load
  // Attempt to show latest speedtest if any
  fetch("/api/speedtest/latest")
    .then((r) => r.json())
    .then((j) => {
      if (j && j.result) {
        const r = j.result;
        speedtestSummary.textContent = `Speedtest: ${r.download_mbps?.toFixed(
          1
        )}↓ / ${r.upload_mbps?.toFixed(1)}↑ Mbps (ping ${r.ping_ms?.toFixed(
          1
        )} ms)`;
      }
    })
    .catch(() => {});

  // Periodic refresh & countdown
  setInterval(refreshData, Math.max(10, probeInterval)); // refresh at least every 10s
  setInterval(updateCountdown, 1000);
});
