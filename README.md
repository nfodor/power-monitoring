![Project Rhotko walkthrough](README-demo.gif)

<p align="center">
  <a href="https://github.com/nfodor/power-monitoring">
    <img src="https://img.shields.io/badge/GitHub-nfodor%2Fpower--monitoring-181717?logo=github" alt="GitHub repository" />
  </a>
</p>

# Raspberry Pi Power Monitor Dashboard (aka Project Rhotko)

Project Rhotko is your lightweight control center for Raspberry Pi rigs backed by the Geekworm X1200/X1206 UPS. It surfaces live power metrics, network health, bypass server telemetry (optional integration with setip.io infrastructure), and layers on notification delivery, USB power control, and CPU power-throttling toggles.

## Highlights
- Real-time gauges for battery, CPU, thermal and power draw.
- Built-in bypass notifier with Pushover hooks, alert history, and health heartbeats (setip.io-ready but optional).
- One-click USB high-current toggle plus CPU power-level throttling controls.
- Smart voltage fallback scripts to protect Pi sensors (see `setup-voltage-monitoring.sh`).
- Mobile-friendly UI that runs happily on headless Chromium or kiosk screens.

## Quick Start
1. `sudo ./install.sh` – installs Python deps and the `power-dashboard.service` unit.
2. Point a browser at `http://<pi-ip>:9434` for the live dashboard.
3. Open **Settings → Alerts** to drop in your Pushover keys (set up a free trial account at <https://pushover.net/pricing>) and adjust alert thresholds.
4. Visit **Settings → USB Power** to enable high-current output when you need to fast-charge devices or power hungry peripherals.
5. Optional: dial in **Settings → Throttling** and **Settings → Bypass Servers** for setip.io deployments or battery-first profiles.

## Key Files
- `dashboard_server.py` – Flask app/API powering the UI.
- `x1200_common.py` – shared MAX17040/X1200 hardware helpers.
- `setup-voltage-monitoring.sh` – smart voltage source selector service.

## Hardware Ecosystem
The dashboard is designed around the Geekworm X1200 series UPS ecosystem:

- **Geekworm X1200 UPS HAT** – Hot-swap 21700 Li-ion support, dual power inputs, and full MAX17040 telemetry.<br>
  <https://geekworm.com/products/x1200-ups-hat>
- **Geekworm X1206 UPS HAT** – Slimmer follow-up with integrated battery bay and USB-C power path.<br>
  <https://geekworm.com/products/x1206-ups-hat>
- **Armor & Portable Cases** – Aluminum enclosures and travel shells that pair with the X1200/X1206 stack for edge deployments.<br>
  <https://geekworm.com/collections/raspberry-pi-case>

Together they turn a Raspberry Pi into a self-powered edge node that can ride out brownouts, run on battery in the field, or tuck into a backpack. Hook it to a monitor/keyboard for on-site work, or leave it headless and reach it over VNC from an iPad for portable development, field data capture, or PoE-less sensor hubs.

For deeper troubleshooting or feature history, skim `VOLTAGE_MONITORING_UPDATE.md`, `COMPLETE_FEATURE_ANALYSIS.md`, and the scripts in this repo.

## Fun Extras
- There’s an art-themed easter egg tucked into the dashboard header—give it a click to discover the homage to artist Mark Rothko.
