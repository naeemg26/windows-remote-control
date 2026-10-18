"""
PC Control Server v3 - Flask backend for remote Windows control
Run AS ADMINISTRATOR: python pc_control_server.py

Fixes in v3:
  - Volume: uses IMMDeviceEnumerator via raw comtypes — avoids pycaw .Activate() bug
  - Blocker: uses OpenProcess(PROCESS_TERMINATE) via ctypes — kills admin-level processes
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import ctypes
import ctypes.wintypes as wintypes
import os, sys, threading, time, json

app = Flask(__name__)
CORS(app)

# ── Config ─────────────────────────────────────────────────────────────────────

SECRET_TOKEN   = "change-me-please"   # ← Change this!
BLOCKLIST_FILE = "blocklist.json"
BLOCK_INTERVAL = 3                    # seconds between scans

# ── Elevation check ────────────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

# ── Blocklist state ────────────────────────────────────────────────────────────

_lock = threading.Lock()

def load_blocklist() -> list:
    if os.path.exists(BLOCKLIST_FILE):
        try:
            with open(BLOCKLIST_FILE) as f:
                return [x.lower().strip() for x in json.load(f) if x.strip()]
        except Exception:
            pass
    return []

def save_blocklist(lst: list):
    with open(BLOCKLIST_FILE, "w") as f:
        json.dump(lst, f)

blocked_programs: list = load_blocklist()
blocking_enabled: bool = False
kill_log:         list = []   # last 50 entries

# ── Admin-capable process killer ───────────────────────────────────────────────
# Uses CreateToolhelp32Snapshot + OpenProcess(PROCESS_TERMINATE) directly.
# Works on elevated processes when this server itself runs as Administrator.

PROCESS_TERMINATE  = 0x0001
TH32CS_SNAPPROCESS = 0x00000002

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]

def _enum_processes() -> list:
    """Return list of (exe_name_lower, pid) for all running processes."""
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    results = []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode(errors="ignore").lower()
                results.append((name, entry.th32ProcessID))
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return results

def _kill_pid(pid: int) -> bool:
    """Terminate process via OpenProcess+TerminateProcess (works on admin procs)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)

# ── Background watcher ─────────────────────────────────────────────────────────

def _watcher():
    while True:
        time.sleep(BLOCK_INTERVAL)
        if not blocking_enabled:
            continue
        with _lock:
            targets = set(blocked_programs)
        if not targets:
            continue
        for exe_name, pid in _enum_processes():
            if exe_name in targets:
                if _kill_pid(pid):
                    entry = {"exe": exe_name, "pid": str(pid), "time": time.strftime("%H:%M:%S")}
                    with _lock:
                        kill_log.append(entry)
                        if len(kill_log) > 50:
                            kill_log.pop(0)

threading.Thread(target=_watcher, daemon=True).start()

# ── Auth ───────────────────────────────────────────────────────────────────────

def check_auth(req):
    return req.headers.get("X-Auth-Token", "") == SECRET_TOKEN

@app.before_request
def auth_middleware():
    if request.method == "OPTIONS":
        return
    if not check_auth(request):
        return jsonify({"success": False, "message": "Unauthorized"}), 401

# ══════════════════════════════════════════════════════════════════════════════
# VOLUME  — 100% pure comtypes, zero pycaw dependency
#
# We define IAudioEndpointVolume ourselves as a comtypes COM interface so we
# get a properly-typed pointer back from Activate() with no ctypes.cast needed.
# ══════════════════════════════════════════════════════════════════════════════

import comtypes
import comtypes.client

# ── COM interface definitions ──────────────────────────────────────────────────

class IAudioEndpointVolume(comtypes.IUnknown):
    _iid_  = comtypes.GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [
        # RegisterControlChangeNotify / Unregister (we skip, use None vtable slots)
        comtypes.COMMETHOD([], comtypes.HRESULT, "RegisterControlChangeNotify",
            (["in"], comtypes.POINTER(comtypes.IUnknown), "pNotify")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "UnregisterControlChangeNotify",
            (["in"], comtypes.POINTER(comtypes.IUnknown), "pNotify")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetChannelCount",
            (["out"], comtypes.POINTER(ctypes.c_uint), "pnChannelCount")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "SetMasterVolumeLevel",
            (["in"], ctypes.c_float, "fLevelDB"),
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "SetMasterVolumeLevelScalar",
            (["in"], ctypes.c_float, "fLevel"),
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetMasterVolumeLevel",
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevelDB")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetMasterVolumeLevelScalar",
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevel")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "SetChannelVolumeLevel",
            (["in"], ctypes.c_uint, "nChannel"),
            (["in"], ctypes.c_float, "fLevelDB"),
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "SetChannelVolumeLevelScalar",
            (["in"], ctypes.c_uint, "nChannel"),
            (["in"], ctypes.c_float, "fLevel"),
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetChannelVolumeLevel",
            (["in"],  ctypes.c_uint, "nChannel"),
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevelDB")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetChannelVolumeLevelScalar",
            (["in"],  ctypes.c_uint, "nChannel"),
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevel")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "SetMute",
            (["in"], ctypes.c_bool, "bMute"),
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetMute",
            (["out"], comtypes.POINTER(ctypes.c_bool), "pbMute")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetVolumeStepInfo",
            (["out"], comtypes.POINTER(ctypes.c_uint), "pnStep"),
            (["out"], comtypes.POINTER(ctypes.c_uint), "pnStepCount")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "VolumeStepUp",
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "VolumeStepDown",
            (["in"], comtypes.POINTER(comtypes.GUID), "pguidEventContext")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "QueryHardwareSupport",
            (["out"], comtypes.POINTER(ctypes.c_uint), "pdwHardwareSupportMask")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetVolumeRange",
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevelMinDB"),
            (["out"], comtypes.POINTER(ctypes.c_float), "pfLevelMaxDB"),
            (["out"], comtypes.POINTER(ctypes.c_float), "pfVolumeIncrementDB")),
    ]

class IMMDevice(comtypes.IUnknown):
    _iid_ = comtypes.GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        comtypes.COMMETHOD([], comtypes.HRESULT, "Activate",
            (["in"],  comtypes.POINTER(comtypes.GUID), "iid"),
            (["in"],  ctypes.c_uint,  "dwClsCtx"),
            (["in"],  ctypes.c_void_p, "pActivationParams"),
            (["out"], comtypes.POINTER(comtypes.POINTER(IAudioEndpointVolume)), "ppInterface")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "OpenPropertyStore",
            (["in"],  ctypes.c_uint, "stgmAccess"),
            (["out"], comtypes.POINTER(comtypes.IUnknown), "ppProperties")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetId",
            (["out"], comtypes.POINTER(ctypes.c_wchar_p), "ppstrId")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetState",
            (["out"], comtypes.POINTER(ctypes.c_uint), "pdwState")),
    ]

class IMMDeviceEnumerator(comtypes.IUnknown):
    _iid_ = comtypes.GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        comtypes.COMMETHOD([], comtypes.HRESULT, "EnumAudioEndpoints",
            (["in"],  ctypes.c_uint, "dataFlow"),
            (["in"],  ctypes.c_uint, "dwStateMask"),
            (["out"], comtypes.POINTER(comtypes.IUnknown), "ppDevices")),
        comtypes.COMMETHOD([], comtypes.HRESULT, "GetDefaultAudioEndpoint",
            (["in"],  ctypes.c_uint, "dataFlow"),
            (["in"],  ctypes.c_uint, "role"),
            (["out"], comtypes.POINTER(comtypes.POINTER(IMMDevice)), "ppEndpoint")),
    ]

CLSID_MMDeviceEnumerator = comtypes.GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
CLSCTX_ALL = 23

def _run_com(fn):
    """
    Run fn() in a brand-new thread.
    New threads on Windows always start without a COM apartment, so comtypes
    will call CoInitialize automatically before any COM work happens.
    Blocks until fn() finishes and returns (result, error_string_or_None).
    """
    result, error = [None], [None]
    def _worker():
        try:
            # Explicitly initialize COM for this thread (STA)
            ctypes.windll.ole32.CoInitialize(None)
            try:
                result[0] = fn()
            finally:
                ctypes.windll.ole32.CoUninitialize()
        except Exception as e:
            error[0] = str(e)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=8)
    if t.is_alive():
        error[0] = "COM call timed out after 8s"
    return result[0], error[0]

def _build_volume_ctrl():
    """Must be called from a COM-initialized thread (inside _run_com)."""
    enumerator = comtypes.client.CreateObject(
        CLSID_MMDeviceEnumerator,
        interface=IMMDeviceEnumerator,
        clsctx=CLSCTX_ALL,
    )
    device = enumerator.GetDefaultAudioEndpoint(0, 0)  # eRender=0, eConsole=0
    return device.Activate(
        comtypes.GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}"),
        CLSCTX_ALL,
        None,
    )

@app.route("/volume", methods=["POST"])
def set_volume():
    try:
        level = max(0, min(100, int((request.json or {}).get("level", 50))))
        def _do():
            _build_volume_ctrl().SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Volume set to {level}%"
        msg, err = _run_com(_do)
        if err:
            return jsonify({"success": False, "message": err}), 500
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/mute", methods=["POST"])
def toggle_mute():
    try:
        def _do():
            ctrl = _build_volume_ctrl()
            muted = ctrl.GetMute()
            ctrl.SetMute(not muted, None)
            return "muted" if not muted else "unmuted"
        state, err = _run_com(_do)
        if err:
            return jsonify({"success": False, "message": err}), 500
        return jsonify({"success": True, "message": f"Audio {state}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/volume/get", methods=["GET"])
def get_volume():
    try:
        def _do():
            ctrl = _build_volume_ctrl()
            return {
                "level": round(ctrl.GetMasterVolumeLevelScalar() * 100),
                "muted": bool(ctrl.GetMute()),
            }
        data, err = _run_com(_do)
        if err:
            return jsonify({"success": False, "message": err}), 500
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POWER / SESSION
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/lock", methods=["POST"])
def lock():
    ctypes.windll.user32.LockWorkStation()
    return jsonify({"success": True, "message": "Session locked"})

@app.route("/logout", methods=["POST"])
def logout():
    subprocess.run(["shutdown", "/l", "/f"])
    return jsonify({"success": True, "message": "Logging off..."})

@app.route("/shutdown", methods=["POST"])
def shutdown():
    delay = (request.json or {}).get("delay", 0)
    subprocess.run(["shutdown", "/s", "/f", f"/t {delay}"])
    return jsonify({"success": True, "message": f"Shutting down in {delay}s..."})

@app.route("/restart", methods=["POST"])
def restart():
    delay = (request.json or {}).get("delay", 0)
    subprocess.run(["shutdown", "/r", "/f", f"/t {delay}"])
    return jsonify({"success": True, "message": f"Restarting in {delay}s..."})

@app.route("/sleep", methods=["POST"])
def sleep():
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return jsonify({"success": True, "message": "Going to sleep..."})

@app.route("/hibernate", methods=["POST"])
def hibernate():
    subprocess.run(["shutdown", "/h"])
    return jsonify({"success": True, "message": "Hibernating..."})

@app.route("/cancel-shutdown", methods=["POST"])
def cancel_shutdown():
    subprocess.run(["shutdown", "/a"])
    return jsonify({"success": True, "message": "Shutdown cancelled"})

# ══════════════════════════════════════════════════════════════════════════════
# BLOCKER
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/blocker/status", methods=["GET"])
def blocker_status():
    with _lock:
        return jsonify({
            "success":  True,
            "enabled":  blocking_enabled,
            "blocked":  list(blocked_programs),
            "log":      list(reversed(kill_log[-10:])),
            "is_admin": is_admin(),
        })

@app.route("/blocker/toggle", methods=["POST"])
def blocker_toggle():
    global blocking_enabled
    blocking_enabled = not blocking_enabled
    state = "enabled" if blocking_enabled else "disabled"
    return jsonify({"success": True, "enabled": blocking_enabled, "message": f"Blocker {state}"})

@app.route("/blocker/add", methods=["POST"])
def blocker_add():
    exe = (request.json or {}).get("exe", "").strip().lower()
    if not exe:
        return jsonify({"success": False, "message": "No exe provided"}), 400
    if not exe.endswith(".exe"):
        exe += ".exe"
    with _lock:
        if exe not in blocked_programs:
            blocked_programs.append(exe)
            save_blocklist(blocked_programs)
        current = list(blocked_programs)
    return jsonify({"success": True, "message": f"Added {exe}", "blocked": current})

@app.route("/blocker/remove", methods=["POST"])
def blocker_remove():
    global blocked_programs
    exe = (request.json or {}).get("exe", "").strip().lower()
    if not exe.endswith(".exe"):
        exe += ".exe"
    with _lock:
        blocked_programs = [x for x in blocked_programs if x != exe]
        save_blocklist(blocked_programs)
        current = list(blocked_programs)
    return jsonify({"success": True, "message": f"Removed {exe}", "blocked": current})

@app.route("/blocker/kill-now", methods=["POST"])
def blocker_kill_now():
    with _lock:
        targets = set(blocked_programs)
    killed, failed = [], []
    for exe_name, pid in _enum_processes():
        if exe_name in targets:
            if _kill_pid(pid):
                killed.append(exe_name)
                with _lock:
                    kill_log.append({"exe": exe_name, "pid": str(pid), "time": time.strftime("%H:%M:%S")})
            else:
                failed.append(f"{exe_name}(pid={pid})")
    parts = []
    if killed: parts.append(f"Killed: {', '.join(set(killed))}")
    if failed: parts.append(f"Failed: {', '.join(failed)} — is server running as Admin?")
    msg = " | ".join(parts) if parts else "No blocked programs were running"
    return jsonify({"success": True, "message": msg})

@app.route("/processes", methods=["GET"])
def list_processes():
    try:
        names = sorted(set(name for name, _ in _enum_processes()))
        return jsonify({"success": True, "processes": names})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "success":  True,
        "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
        "is_admin": is_admin(),
    })

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.platform != "win32":
        print("WARNING: Designed for Windows only.")

    admin = is_admin()
    print("=" * 60)
    print("  PC Control Server v3  —  http://0.0.0.0:5000")
    print(f"  Token    : {SECRET_TOKEN}")
    print(f"  Admin    : {'YES ✓' if admin else 'NO — restart as Administrator!'}")
    print(f"  Blocklist: {blocked_programs or '(empty)'}")
    print("  Change SECRET_TOKEN before using on a network!")
    print("=" * 60)
    if not admin:
        print("\n  ⚠  Right-click the script → Run as administrator")
        print("     Required to kill admin-level processes.\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
