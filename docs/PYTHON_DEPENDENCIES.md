# Python dependencies — upstream projects and licensing

**Reviewed:** 2026-10-28. This is a human-readable attribution and maintenance reference for the direct Python packages installed by `probe/requirements.txt`. It is not a replacement for the actual upstream license files and not a legal opinion.

NetProbe's own source is distributed under the MIT license (see the root `LICENSE`). Installing another project as a dependency does **not** change that project's license or turn it into NetProbe-owned code. When publishing a container image, preserve applicable copyright/license notices and examine both direct and transitive dependencies.

## Direct Python requirements

| Package | Upstream / publisher | What NetProbe uses | Upstream license | Sources |
| --- | --- | --- | --- | --- |
| `Flask` | Pallets Projects | HTTP routes for dashboard templates, login, account setup, settings, monitoring JSON API | **BSD-3-Clause** | [PyPI](https://pypi.org/project/Flask/) · [Source / license](https://github.com/pallets/flask) |
| `gunicorn` | Gunicorn project (original author Benoît Chesneau) | WSGI server for the Flask app on loopback behind Nginx | **MIT** | [PyPI](https://pypi.org/project/gunicorn/) · [Source](https://github.com/benoitc/gunicorn) |
| `dnspython` | dnspython project (Bob Halley and contributors) | Per-server DNS resolver queries and response-time measurements (`dns.resolver`) | **ISC** | [PyPI](https://pypi.org/project/dnspython/) · [License](https://dnspython.readthedocs.io/en/latest/license.html) |
| `speedtest-cli` | Matt Martz (`sivel/speedtest-cli`) | Legacy Python Speedtest.net test backend (`import speedtest`) | **Apache-2.0** | [PyPI](https://pypi.org/project/speedtest-cli/) · [Source](https://github.com/sivel/speedtest-cli) |
| `psycopg2-binary` | Psycopg project (Federico Di Gregorio, Daniele Varrazzo and contributors) | Optional PostgreSQL connector (`import psycopg2`) | **LGPL with exceptions** | [PyPI](https://pypi.org/project/psycopg2-binary/) · [Source](https://github.com/psycopg/psycopg2) |

**Version note:** Packages are currently unpinned in `probe/requirements.txt`; verify the *actually installed versions and exact licenses* in a built image before any public release. The package metadata may change over time.

## Python standard-library components (not additional pip requirements)

`sqlite3`, `json`, `logging`, `os`, `re`, `shutil`, `statistics`, `subprocess`, `threading`, `time`, `pathlib`, `secrets`, `datetime`, and `collections` are provided by Python itself. SQLite support requires no separately listed pip package. The underlying SQLite library is included through the Python image; review its upstream notices as part of the final image inventory.

## Infrastructure and separate executable dependencies

- **Python:** official `python:3.15.2-slim-trixie` base image. [Python licensing](https://docs.python.org/3/license.html) · [Official Docker image](https://hub.docker.com/_/python).
- **Nginx:** Debian-installed reverse proxy and HTTPS endpoint; not a Python pip package. [Nginx licensing](https://nginx.org/LICENSE) · [Nginx website](https://nginx.org/).
- **Official Ookla Speedtest CLI:** **not** part of `requirements.txt` and **not** bundled in the default NetProbe image. It is proprietary and requires separate user review/acceptance before optional installation into a running container. See [OOKLA_BACKEND_NOTICE.md](OOKLA_BACKEND_NOTICE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). [EULA](https://www.speedtest.net/about/eula) · [Terms](https://www.speedtest.net/about/terms) · [Privacy](https://www.speedtest.net/about/privacy).
- **PostgreSQL server:** optional externally deployed database. `psycopg2-binary` is a *client adapter*, not the server.

## License and distribution review checklist

1. Keep the NetProbe root MIT `LICENSE` and the upstream packages' own license/copyright notices. The list above is attribution, **not** a complete set of required legal notices.
2. For BSD-3-Clause, ISC, MIT, and Apache-2.0 dependencies, check each license's conditions for reproducing copyright notices, license text, attribution and disclaimers. Apache-2.0 can also carry a NOTICE file.
3. For Psycopg, consult its actual LGPL-with-exceptions text and the distribution obligations applying to the specific package/build. The Psycopg maintainers advise building from source for production rather than treating `psycopg2-binary` as an indefinitely preferred production distribution.
4. Review *transitive pip packages*, Debian OS packages, Nginx, and libraries embedded in wheels. This document covers only the five direct pip requirements.
5. Generate a build-specific dependency inventory (versions and license metadata), run compatibility tests on Python 3.15, and revisit this document before shipping to Docker Hub.

## Inspect the actual container build

```bash
# The image must already have been built locally:
docker run --rm --entrypoint python netprobe:dev -m pip list
docker run --rm --entrypoint python netprobe:dev -m pip show Flask gunicorn dnspython speedtest-cli psycopg2-binary
```

Do not assume that a listed project license grants permission to redistribute Ookla's separate executable. Its rights and acceptance requirements are independent.
