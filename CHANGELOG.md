# Changelog

All notable changes to this project are documented here.

---

## [1.0.0] — Initial Release

### Added
- Flask API server (`pc_control_server.py`) with token-based authentication
- Standalone web UI (`pc_remote.html`) — no build step, no framework
- One-click dual-instance launcher (`launch.bat`)
  - Normal instance on port 5000 (no UAC)
  - Admin instance on port 5001 (single UAC prompt via PowerShell `Start-Process -Verb RunAs`)

### Power controls
- Lock session (`LockWorkStation`)
- Sleep (`SetSuspendState` via `powrprof.dll`)
- Hibernate (`shutdown /h`)
- Log off (`shutdown /l /f`)
- Restart (`shutdown /r /f /t`)
- Shutdown (`shutdown /s /f /t`)
- Cancel pending shutdown (`shutdown /a`)
- Confirmation dialog for destructive actions (log off, restart, shutdown)

### Volume controls
- Set master volume level (0–100) via slider and quick presets
- Toggle mute
- Read and sync current volume level
- Implemented with pure `comtypes` via `IMMDeviceEnumerator` → `IMMDevice` → `IAudioEndpointVolume`
  — no `pycaw` dependency, no `ctypes.cast` issues
- COM calls executed in a fresh thread with explicit `CoInitialize` / `CoUninitialize`
  to avoid Flask worker-thread COM apartment errors

### Program Blocker
- Add / remove process names (`.exe`) to a persistent blocklist (`blocklist.json`)
- Background watcher thread scans and kills blocked processes every 3 seconds
- Immediate kill-now action
- Running process browser with search filter — click to block
- Kill log (last 50 entries in memory, last 10 shown in UI)
- Admin-capable termination via `OpenProcess(PROCESS_TERMINATE)` + `TerminateProcess`
  — works on admin-elevated processes when the server itself runs as Administrator
- Admin status reported in `/status` and `/blocker/status` endpoints

### Web UI
- Dark theme, tab-based layout (Power / Volume / Blocker)
- Dual server status pills — shows online/offline and admin/normal state for each port
- Auto-refresh of blocker status and kill log every 5 seconds (when Blocker tab is active)
- Blocklist synced to both server instances simultaneously (add, remove, toggle, kill-now)
- Admin warning banner when port 5001 is unreachable
- Toast notifications for all actions
- Confirmation overlay for destructive power actions
