# `bin/` — manually installed binaries

## go2rtc (required only for live video)

`go2rtc` is **not** bundled and is **never downloaded automatically** — fetching
and executing a binary at runtime is a supply-chain risk worth avoiding even in
a small internal tool. Install it yourself, once:

This machine is **macOS on Apple Silicon (arm64)**, so:

```bash
curl -L -o /tmp/go2rtc.zip https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_mac_arm64.zip
unzip -o /tmp/go2rtc.zip -d bin/
chmod +x bin/go2rtc
```

Then start it from the portal: **Jobs → Start restreamer (go2rtc)**.

macOS Gatekeeper will block an unsigned downloaded binary on first run. If it
does: `xattr -d com.apple.quarantine bin/go2rtc`

### What breaks without it

Only **live video** in Live Monitoring. Everything else works with go2rtc
absent: heatmaps, service points, person counts, detection overlays, all
Insights charts, discovery, and the whole recorded-metrics pipeline.
