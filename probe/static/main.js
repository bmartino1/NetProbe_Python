// static/main.js

document.addEventListener("DOMContentLoaded", () => {
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

  async function refresh() {
    const res = await fetch("/api/score/recent?limit=300");
    const json = await res.json();
    const data = json.data || [];
    if (!data.length) return;

    const last = data[data.length - 1];

    const score = last.score || 0;
    const loss = last.avg_loss_pct || 0;
    const latency = last.avg_latency_ms || 0;
    const jitter = last.avg_jitter_ms || 0;
    const dns = last.avg_dns_latency_ms || 0;

    // Score gauge
    gScore.data.datasets[0].data = [score, 100 - score];
    gScore.update();

    function clamp(val, max) {
      return Math.min(val, max);
    }

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
    cLatencyHistory.data.datasets[0].data = data.map((d) => d.avg_latency_ms);
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

  refresh();
  setInterval(refresh, 30000);
});
