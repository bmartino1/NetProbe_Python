# Optional official Ookla backend notice

NetProbe can optionally invoke the official Ookla `speedtest` executable. The
executable is separate third-party software and is **not** covered by NetProbe's
MIT License.

## Intended use and distribution boundary

Ookla's package repository describes the CLI as being for personal,
non-commercial use. NetProbe's optional Docker build path is therefore intended
for a private local home-lab image. Do not publish or redistribute an image that
contains the Ookla executable unless you have separate written permission from
Ookla allowing that distribution.

The default build keeps `INSTALL_OOKLA_SPEEDTEST=false` and uses the
redistributable Python backend.

## End-user acknowledgement at runtime

The Docker build installs the optional package only when explicitly requested.
It does **not** run `speedtest`, pass acceptance flags, or save any accepted state
inside the image.

Before NetProbe will invoke the Ookla backend, the end user must review:

- EULA: https://www.speedtest.net/about/eula
- Terms of Use: https://www.speedtest.net/about/terms
- Privacy Policy: https://www.speedtest.net/about/privacy

Then acknowledge at runtime using either method.

### Unraid/Docker environment

```env
SPEEDTEST_BACKEND=ookla
SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
```

The values `True`, `Yes`, `On`, and `1` remain accepted for compatibility with
unreleased test configurations, but `I_ACCEPT` is the documented value because
it makes the administrator's action explicit.

### Interactive persistent acknowledgement

```bash
docker exec -it <container-name> netprobe-ookla-accept
```

The helper displays the official links and requires the user to type exactly
`I ACCEPT`. It writes this marker by default:

```text
/data/ookla-eula-accepted.txt
```

Because `/data` is normally a persistent volume, the acknowledgement survives a
container recreation. Check or remove it with:

```bash
docker exec <container-name> netprobe-ookla-accept --status
docker exec <container-name> netprobe-ookla-accept --revoke
```

The location can be changed with:

```env
SPEEDTEST_OOKLA_ACCEPTANCE_FILE=/data/ookla-eula-accepted.txt
```

When acknowledgement is present, NetProbe passes `--accept-license` and
`--accept-gdpr` only when the official CLI is actually invoked.

## Local/private Docker build

```bash
docker build --pull --no-cache   --build-arg INSTALL_OOKLA_SPEEDTEST=true   -t bmmbmm01/netprobe:ookla-local ./probe
```

This local build contains `/usr/bin/speedtest`. Do not push it to a public
registry without separate redistribution permission.

## Project relationship

NetProbe is independent software. It is not affiliated with, sponsored by, or
endorsed by Ookla, LLC. Ookla and Speedtest names and marks belong to their
respective owner.
