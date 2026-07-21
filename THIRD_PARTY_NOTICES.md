# Third-party notices

NetProbe source code and project documentation are licensed under the MIT
License in `LICENSE`. That license does not apply to separately licensed
third-party executables.

## Python `speedtest-cli`

The default backend uses the Python `speedtest-cli` package from the archived
`sivel/speedtest-cli` project. That package is distributed under its own
Apache-2.0 license.

## Official Ookla Speedtest CLI

NetProbe can optionally invoke the official Ookla `speedtest` executable. It is
proprietary third-party software, is not licensed under NetProbe's MIT License,
and is described by Ookla's package repository as being for personal,
non-commercial use.

Official resources:

- EULA: https://www.speedtest.net/about/eula
- Terms of Use: https://www.speedtest.net/about/terms
- Privacy Policy: https://www.speedtest.net/about/privacy
- CLI packages: https://packagecloud.io/ookla/speedtest-cli

The default Docker build does not contain the official executable. A user may
create a private local build with `INSTALL_OOKLA_SPEEDTEST=true`, subject to
Ookla's terms. Do not publish or redistribute that derived image without
separate permission allowing redistribution.

The image build never pre-accepts the terms. NetProbe requires an explicit
runtime acknowledgement before invoking the official backend:

```env
SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
```

Alternatively, the end user may run `netprobe-ookla-accept` interactively and
store the acknowledgement in the mounted `/data` volume. NetProbe then passes
`--accept-license` and `--accept-gdpr` when executing the CLI.

This acknowledgement mechanism does not relicense the executable or grant
redistribution or commercial-use rights.

NetProbe is independent software and is not affiliated with, sponsored by, or
endorsed by Ookla, LLC.
