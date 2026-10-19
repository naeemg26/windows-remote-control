# PC Remote Control

A self-hosted web app for controlling your Windows PC from any browser on your local network — phone, tablet, or another computer. No cloud, no accounts, no subscriptions.

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue.svg)
![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

---

## Features

| Category | Actions |
|---|---|
| **Power** | Lock session, Sleep, Hibernate, Log off, Restart, Shutdown, Cancel shutdown |
| **Volume** | Set level (slider + quick presets), Toggle mute, Sync current level |
| **Program Blocker** | Block any `.exe` by name, auto-kill every 3 seconds, kill admin-elevated processes, live kill log |

**Dual-server architecture** — runs two instances simultaneously from one double-click:
- **Port 5000** — normal privileges (power, volume, non-elevated processes)
- **Port 5001** — elevated/Administrator (everything above + killing admin-level processes like games or browsers launched as Administrator)

---

## Repository Structure

```
windows-remote-control/
├── pc_control_server.py   # Flask API server (runs on the Windows PC)
├── pc_remote.html         # Web UI (open in any browser)
├── launch.bat             # One-click launcher: starts both normal + admin instances
├── requirements.txt       # Python dependencies
├── .gitignore
└── README.md
```

---

## Requirements

- **Windows 10 or 11** (the server is Windows-only)
- **Python 3.9 or later** — [python.org](https://www.python.org/downloads/) — check *Add to PATH* during install
- A browser on any device on the same network (client can be any OS)

---

## Quick Start

### 1. Clone or download

```bash
git clone https://github.com/naeemg26/windows-remote-control.git
cd windows-remote-control
```

Or download the ZIP and extract it anywhere on your Windows PC.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set your secret token

Open `pc_control_server.py` and change line 22:

```python
SECRET_TOKEN = "change-me-please"   # ← replace with something only you know
```

Use the same token in the web app when connecting.

### 4. Launch

Double-click **`launch.bat`**.

- A terminal window opens for the normal server (port 5000) — no UAC prompt.
- A UAC prompt appears for the admin server (port 5001) — click **Yes**.

Both servers start automatically. You can close the first terminal window once both are confirmed running.

### 5. Open the web app

Open `pc_remote.html` in any browser — on your PC, phone, or tablet.

- Enter your PC's local IP address (e.g. `http://192.168.1.50`) in the address field.  
  Find your IP by running `ipconfig` in Command Prompt and looking for **IPv4 Address**.
- Enter your secret token.
- Click **Connect**. Both status pills (Normal · :5000 and Admin · :5001) should turn green.

---

## Usage

### Power tab

| Button | What it does |
|---|---|
| Lock now | Locks the Windows session immediately (`LockWorkStation`) |
| Sleep | Suspends to RAM (`SetSuspendState`) |
| Hibernate | Saves session to disk and powers off (`shutdown /h`) |
| Log off | Signs out the current user (`shutdown /l /f`) |
| Restart | Reboots the PC (`shutdown /r /f /t 0`) |
| Shut down | Powers off the PC (`shutdown /s /f /t 0`) |
| Cancel | Aborts a scheduled shutdown/restart (`shutdown /a`) |

Log off, Restart, and Shut down require a confirmation click before executing.

### Volume tab

- **Slider** — drag to the desired level, press *Set volume*.
- **↻ Sync** — reads the current system volume and updates the slider.
- **Toggle mute** — mutes or unmutes the default audio endpoint.
- **Quick set** — 0 / 25 / 50 / 75 / 100% presets, applied instantly.

Volume control requires `comtypes` (included in `requirements.txt`). It communicates with the Windows Audio API via `IMMDeviceEnumerator` → `IAudioEndpointVolume` COM interfaces directly, with no dependency on `pycaw`.

### Blocker tab

1. **Add a program** — type a process name (e.g. `chrome`, `steam`, `notepad`) in the input field and press *Add*. The `.exe` extension is added automatically if omitted.
2. **Running processes** — press *Refresh processes* to see every process currently running. Click any row to add it to the blocklist instantly.
3. **Enable the toggle** — once enabled, the server scans all running processes every 3 seconds and terminates any that match the blocklist.
4. **Kill blocked now** — manually triggers an immediate kill pass without waiting for the next scan cycle.
5. **Kill log** — shows the last 10 terminations (time, exe name, PID). Auto-refreshes every 5 seconds while the Blocker tab is open.

The blocklist is saved to `blocklist.json` in the same folder as the server and persists across restarts.

#### Killing admin-elevated processes

Programs launched *Run as administrator* (e.g. some games, cheat-protection software) run at a higher integrity level than a normal process. A normal `taskkill` call cannot touch them. The admin server instance (port 5001) runs with elevated privileges, so it can open process handles with `PROCESS_TERMINATE` rights and kill them. If the Admin pill in the web app is **offline or orange**, admin-elevated processes will not be killable.

---

## Configuration

All configuration is at the top of `pc_control_server.py`:

| Variable | Default | Description |
|---|---|---|
| `SECRET_TOKEN` | `"change-me-please"` | Shared secret sent in the `X-Auth-Token` header. Change before use. |
| `BLOCKLIST_FILE` | `"blocklist.json"` | Path to the persisted blocklist. Relative to the script's location. |
| `BLOCK_INTERVAL` | `3` | Seconds between process scans when the blocker is enabled. |

The server port is set by the `--port` command-line argument (default `5000`). `launch.bat` passes `--port 5000` for the normal instance and `--port 5001` for the admin instance automatically.

---

## Running manually (without launch.bat)

**Normal instance:**
```bash
python pc_control_server.py --port 5000
```

**Admin instance** (in an elevated Command Prompt — right-click → *Run as administrator*):
```bash
python pc_control_server.py --port 5001
```

You can run only one instance if you don't need to kill admin-elevated processes.

---

## Security

> **This tool is designed for trusted local networks only.** Do not expose either server port to the internet.

- Every request requires the `X-Auth-Token` header to match `SECRET_TOKEN`. Requests without it receive HTTP 401.
- CORS is enabled (required for the standalone HTML file to call the API). On a local network this is acceptable; tighten `CORS(app, origins=["http://your-pc-ip:*"])` if desired.
- For remote access outside your home network, use a VPN (WireGuard, Tailscale) rather than port-forwarding.
- The token is transmitted in plain HTTP. If you run this over Wi-Fi on a shared network, consider adding HTTPS via a self-signed certificate or a local reverse proxy (e.g. Caddy).

---

## API Reference

All endpoints require the header:
```
X-Auth-Token: <your-secret-token>
```

All responses are JSON with at minimum `{ "success": true|false, "message": "..." }`.

### Status

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status` | Health check. Returns `hostname` and `is_admin`. |

### Power

| Method | Endpoint | Body | Description |
|---|---|---|---|
| POST | `/lock` | — | Lock the session |
| POST | `/sleep` | — | Sleep |
| POST | `/hibernate` | — | Hibernate |
| POST | `/logout` | — | Log off current user |
| POST | `/shutdown` | `{ "delay": 0 }` | Shut down (delay in seconds) |
| POST | `/restart` | `{ "delay": 0 }` | Restart (delay in seconds) |
| POST | `/cancel-shutdown` | — | Cancel pending shutdown/restart |

### Volume

| Method | Endpoint | Body | Description |
|---|---|---|---|
| POST | `/volume` | `{ "level": 0–100 }` | Set master volume |
| POST | `/mute` | — | Toggle mute |
| GET | `/volume/get` | — | Get current level and mute state |

`/volume/get` response: `{ "success": true, "level": 72, "muted": false }`

### Program Blocker

| Method | Endpoint | Body | Description |
|---|---|---|---|
| GET | `/blocker/status` | — | Get enabled state, blocklist, last 10 kill log entries |
| POST | `/blocker/toggle` | — | Enable or disable the background watcher |
| POST | `/blocker/add` | `{ "exe": "chrome.exe" }` | Add a process to the blocklist |
| POST | `/blocker/remove` | `{ "exe": "chrome.exe" }` | Remove a process from the blocklist |
| POST | `/blocker/kill-now` | — | Immediately kill all currently running blocked processes |
| GET | `/processes` | — | List all running process names |

---

## Troubleshooting

**"Cannot reach server" in the web app**
- Make sure `launch.bat` is running and both terminal windows are open.
- Check Windows Firewall: allow inbound TCP on ports 5000 and 5001 for `python.exe`.
- Verify the IP address — run `ipconfig` and use the IPv4 address under your active adapter.

**Admin pill stays orange / offline**
- The UAC prompt was declined. Re-run `launch.bat` and click *Yes* when prompted.
- Alternatively, open an elevated Command Prompt manually and run `python pc_control_server.py --port 5001`.

**Volume control errors**
- Ensure `comtypes` is installed: `pip install comtypes`.
- The volume API communicates through COM. If you see COM-related errors, make sure no other audio management software is exclusively locking the audio endpoint.

**Blocker doesn't kill a process**
- If the target process runs as Administrator, only the admin instance (port 5001) can kill it. Check that the admin server is running and the Admin pill is green.
- Some system-protected processes (`csrss.exe`, `lsass.exe`, etc.) cannot be terminated even by an administrator — this is by Windows design.

---

## License

MIT — see [LICENSE](LICENSE).
