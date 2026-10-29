# JavaScript dependencies — upstream projects and licensing

**Reviewed:** 2026-10-28. This reference covers JavaScript shipped in `probe/static/` and scripts referenced by the dashboard. It distinguishes a vendored upstream library from NetProbe-authored UI logic. See [PYTHON_DEPENDENCIES.md](PYTHON_DEPENDENCIES.md) for Python packages.

## Third-party JavaScript

| Shipped file | Upstream project | Version | License | Used for |
| --- | --- | --- | --- | --- |
| `probe/static/chart.js` | [Chart.js](https://www.chartjs.org/) by Chart.js Contributors | **4.5.1** (verified from file banner) | **MIT** | Browser-side time-series plots and dashboard charts |

**Upstream sources:** [Chart.js repository](https://github.com/chartjs/Chart.js) · [v4.5.1 tag](https://github.com/chartjs/Chart.js/tree/v4.5.1) · [v4.5.1 package metadata](https://github.com/chartjs/Chart.js/blob/v4.5.1/package.json) · [Upstream MIT license](https://github.com/chartjs/Chart.js/blob/v4.5.1/LICENSE.md).

The distributed `chart.js` file contains the Chart.js v4.5.1 banner. Its upstream package metadata declares MIT, and the full license text is reproduced in [CHARTJS_LICENSE.md](CHARTJS_LICENSE.md). Keep both the upstream copyright/license notice and the full license when redistributing a Docker image with this embedded library.

## NetProbe frontend files (application-owned, not external dependencies)

| File | Responsibility | License classification |
| --- | --- | --- |
| `probe/static/main.js` | Fetches monitoring history and live data, renders charts, handles manual Speedtest requests and logs | NetProbe project source; root [MIT LICENSE](../LICENSE) |
| `probe/static/dashboard.js` | Responsive dashboard navigation, metric cards, panel visibility and layout state | NetProbe project source; root MIT license |
| `probe/static/settings.js` | Settings editor, CSRF-aware requests, administrator account and Ookla installer controls | NetProbe project source; root MIT license |
| `probe/static/dashboard.css` | App-specific UI styles; CSS rather than JavaScript | NetProbe project source; root MIT license |

This classification reflects the files currently present in this repository. If externally sourced snippets or assets are introduced later, review their attribution independently.

## How Chart.js is loaded

The dashboard includes the local file through the Flask template, using `url_for('static', filename='chart.js')`. This is a **vendored browser asset**, not a Python `pip` package, a Node package installed during the Docker build, or a CDN dependency. No npm or frontend build tool is required to serve this version.

The active frontend also loads `main.js`, `dashboard.js`, and `settings.js` locally. The current repository does **not** use other third-party JS packages in its dashboard. Browser APIs (`fetch`, `localStorage`, canvas, etc.) are native web platform features, not additional JavaScript libraries.

## Publishing and upgrade checklist

1. When updating `chart.js`, record the exact version, upstream release URL, license, and any relevant changes in [CHANGELOG.md](CHANGELOG.md).
2. Preserve the third-party copyright header in the distributed JS bundle and a copy of its MIT license text; do not label the Chart.js implementation as NetProbe-authored code.
3. Check upstream security advisories and test chart rendering, tooltips and date/time ranges before upgrading.
4. Verify any new bundled JS, CSS, icons, fonts or images for separate licenses and notices.
5. For Docker Hub releases, inventory the actual bundled files. A dependency document is not a substitute for an audit of the built image.

NetProbe is independent of and is not endorsed by Chart.js or its contributors.
