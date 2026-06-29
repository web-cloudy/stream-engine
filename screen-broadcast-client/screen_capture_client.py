"""
Screen Capture Broadcasting Client
Select a screen area, then Start/Stop Broadcasting it live to a server.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import os
import re
import time
import glob
import requests
from datetime import datetime
import tempfile
import sys
import shutil
import webbrowser


# Shared HTTP session that IGNORES system proxies. Many machines route traffic
# through a proxy/VPN (e.g. WARP) that can't reach the local/LAN streaming
# server, causing "Unable to connect to proxy" errors.
#
# trust_env=False stops requests from reading proxy settings from environment
# variables AND the Windows registry. We ALSO explicitly clear the session's
# proxies and force NO_PROXY for localhost/LAN so nothing routes traffic through
# a proxy/VPN that can't reach the local streaming server.
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.proxies = {'http': None, 'https': None}

# Pass this on EVERY request as well. Setting it at the call site guarantees no
# proxy is selected even if the session's proxy config is somehow overridden or
# a different requests version resolves session proxies unexpectedly.
NO_PROXIES = {'http': None, 'https': None}


# Belt-and-suspenders: make sure no proxy env vars interfere for this process.
for _var in ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy',
             'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_var, None)
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'



# ---------------------------------------------------------------------------
# Console / output helpers (safe in --windowed mode where stdout may be None)
# ---------------------------------------------------------------------------

def safe_print(*args, **kwargs):
    try:
        if sys.stdout is not None:
            print(*args, **kwargs)
    except Exception:
        pass


# On Windows, prevent child console windows from popping up for subprocess calls
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


# ---------------------------------------------------------------------------
# FFmpeg discovery
# ---------------------------------------------------------------------------
def _get_bundle_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg():
    """Locate the ffmpeg executable (bundled, local, C:\\ffmpeg, env, or PATH)."""
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    candidates = []

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, exe_name))
        candidates.append(os.path.join(meipass, 'ffmpeg', exe_name))
        candidates.append(os.path.join(meipass, 'ffmpeg', 'bin', exe_name))

    bundle = _get_bundle_dir()
    candidates.append(os.path.join(bundle, exe_name))
    candidates.append(os.path.join(bundle, 'ffmpeg', exe_name))
    candidates.append(os.path.join(bundle, 'ffmpeg', 'bin', exe_name))

    if sys.platform == 'win32':
        candidates.append(r'C:\ffmpeg\bin\ffmpeg.exe')

    env_path = os.environ.get('FFMPEG_PATH')
    if env_path:
        candidates.insert(0, env_path)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate

    found = shutil.which('ffmpeg')
    if found:
        return found
    return None


FFMPEG_PATH = find_ffmpeg()


# ---------------------------------------------------------------------------
# Audio capture device discovery (Windows DirectShow)
# ---------------------------------------------------------------------------
NO_AUDIO_LABEL = "No audio (silent)"

# Device-name fragments that indicate a system/desktop-audio loopback capture
# (preferred, so the broadcast includes what's playing on the PC, not just a mic).
LOOPBACK_HINTS = ('virtual-audio-capturer', 'stereo mix', 'stereomix',
                  'what u hear', 'what you hear', 'loopback')


def list_audio_devices():
    """Return DirectShow audio capture device names (Windows only)."""
    if sys.platform != 'win32' or not FFMPEG_PATH:
        return []
    try:
        proc = subprocess.run(
            [FFMPEG_PATH, '-hide_banner', '-list_devices', 'true',
             '-f', 'dshow', '-i', 'dummy'],
            capture_output=True, text=True, errors='ignore',
            creationflags=CREATE_NO_WINDOW,
        )
        output = (proc.stderr or '') + (proc.stdout or '')
    except Exception:
        return []
    devices = []
    for line in output.splitlines():
        if '(audio)' in line:
            m = re.search(r'"([^"]+)"', line)
            if m and m.group(1) not in devices:
                devices.append(m.group(1))
    return devices


def is_loopback_device(name):
    """True if `name` looks like a system-audio (desktop sound) loopback device."""
    low = (name or '').lower()
    return any(h in low for h in LOOPBACK_HINTS)


def find_loopback_device(devices):
    """Return the first system-audio loopback device, or None if there is none."""
    for d in devices:
        if is_loopback_device(d):
            return d
    return None


def pick_default_audio_device(devices):
    """Prefer a system-audio loopback device, else fall back to the first one."""
    return find_loopback_device(devices) or (devices[0] if devices else '')


# IMPORTANT: Do NOT make this process DPI-aware.
#
# The area-selector is a Tkinter overlay and ffmpeg's gdigrab is a SEPARATE
# process that we launch. gdigrab is *not* DPI-aware, so on a scaled display
# (125%/150%/etc.) Windows hands it a virtualized desktop measured in *logical*
# pixels, and it interprets our -offset_x/-offset_y/-video_size in logical
# pixels too. If we made THIS process DPI-aware, Tk would report *physical*
# pixels, and the two coordinate systems would disagree -> the broadcast would
# capture an offset/zoomed region instead of exactly what was selected.
#
# By staying DPI-UNAWARE, the selector reports logical pixels, matching gdigrab,
# so the captured frame matches the dragged selection at any scaling factor.

# Hide console window on Windows (only matters if a console exists)

if sys.platform == 'win32':
    import ctypes
    try:
        kernel32 = ctypes.WinDLL('kernel32')
        user32 = ctypes.WinDLL('user32')
        hWnd = kernel32.GetConsoleWindow()
        if hWnd:
            user32.ShowWindow(hWnd, 0)  # SW_HIDE
    except Exception:
        pass


# NOTE: pyautogui was previously imported here but never actually used (screen
# capture is done by FFmpeg's gdigrab and the selection overlay by tkinter).
# It was removed to drop a heavy, hard-to-bundle dependency from the .exe.


class ScreenSelector:
    """Transparent overlay for selecting a screen area."""

    def __init__(self, callback):
        self.callback = callback
        self.start_x = None
        self.start_y = None
        self.rect = None

        self.root = tk.Tk()
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-alpha', 0.3)
        self.root.attributes('-topmost', True)
        self.root.configure(background='gray')

        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        self.canvas.bind('<ButtonPress-1>', self.on_mouse_down)
        self.canvas.bind('<B1-Motion>', self.on_mouse_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_mouse_up)
        self.root.bind('<Escape>', lambda e: self.cancel())

        self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 50,
            text="Drag to select area. Press ESC to cancel.",
            fill='white', font=('Arial', 16, 'bold')
        )

    def on_mouse_down(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect:
            self.canvas.delete(self.rect)

    def on_mouse_drag(self, event):
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline='red', width=3, fill='red', stipple='gray50'
        )

    def on_mouse_up(self, event):
        if self.start_x is not None and self.start_y is not None:
            x1 = min(self.start_x, event.x)
            y1 = min(self.start_y, event.y)
            x2 = max(self.start_x, event.x)
            y2 = max(self.start_y, event.y)
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
                self.callback(x1, y1, x2, y2)
                self.root.destroy()
            else:
                messagebox.showwarning("Invalid Selection", "Please select a larger area")
                if self.rect:
                    self.canvas.delete(self.rect)

    def cancel(self):
        self.callback(None, None, None, None)
        self.root.destroy()

    def show(self):
        self.root.mainloop()


class BroadcastClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Screen Broadcast Client")
        self.root.geometry("520x640")
        self.root.resizable(False, False)

        self.server_ip = tk.StringVar(value="http://localhost:5000")
        self.audio_device = tk.StringVar()
        self.selected_area = None

        # Broadcast state
        self.is_broadcasting = False
        self.ffmpeg_process = None
        self.watch_thread = None
        self.stream_id = None
        self.work_dir = None
        self.uploaded = set()

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --------------------------------------------------------------- UI
    def setup_ui(self):
        ttk.Label(self.root, text="Screen Broadcast Client",
                  font=('Arial', 16, 'bold')).pack(pady=12)

        cfg = ttk.LabelFrame(self.root, text="Server Configuration", padding=10)
        cfg.pack(fill='x', padx=20, pady=8)
        ttk.Label(cfg, text="Server Address:").grid(row=0, column=0, sticky='w', pady=5)
        ttk.Entry(cfg, textvariable=self.server_ip, width=40).grid(row=0, column=1, pady=5, padx=10)

        area = ttk.LabelFrame(self.root, text="Screen Area", padding=10)
        area.pack(fill='x', padx=20, pady=8)
        self.area_label = ttk.Label(area, text="No area selected")
        self.area_label.pack(pady=5)
        ttk.Button(area, text="Select Area (Drag)", command=self.select_area, width=20).pack(pady=5)

        aud = ttk.LabelFrame(self.root, text="Audio Source", padding=10)
        aud.pack(fill='x', padx=20, pady=8)
        self.audio_devices = list_audio_devices()
        if not self.audio_device.get():
            self.audio_device.set(pick_default_audio_device(self.audio_devices) or NO_AUDIO_LABEL)
        ttk.Combobox(aud, textvariable=self.audio_device,
                     values=[NO_AUDIO_LABEL] + self.audio_devices,
                     state='readonly', width=45).pack(pady=5)

        # Live hint: tells the user exactly what the CURRENT selection will
        # record, and warns when only a microphone is available (so they don't
        # think a video's sound is being captured when it isn't).
        self.audio_hint = ttk.Label(aud, font=('Arial', 8), wraplength=450, justify='left')
        self.audio_hint.pack(fill='x', pady=(4, 0))
        self.audio_device.trace_add('write', lambda *_: self._update_audio_hint())
        self._update_audio_hint()

        bc = ttk.LabelFrame(self.root, text="Broadcast", padding=10)
        bc.pack(fill='x', padx=20, pady=8)
        btns = ttk.Frame(bc)
        btns.pack()
        self.start_btn = ttk.Button(btns, text="▶ Start Broadcasting",
                                    command=self.start_broadcasting, state='disabled', width=20)
        self.start_btn.pack(side='left', padx=5)
        self.stop_btn = ttk.Button(btns, text="■ Stop Broadcasting",
                                   command=self.stop_broadcasting, state='disabled', width=20)
        self.stop_btn.pack(side='left', padx=5)
        self.open_btn = ttk.Button(bc, text="Open Stream in Browser",
                                   command=self.open_in_browser, state='disabled', width=25)
        self.open_btn.pack(pady=(8, 0))

        st = ttk.LabelFrame(self.root, text="Status", padding=10)
        st.pack(fill='both', expand=True, padx=20, pady=8)
        self.status_text = tk.Text(st, height=8, width=58)
        self.status_text.pack(fill='both', expand=True, side='left')
        sb = ttk.Scrollbar(st, command=self.status_text.yview)
        sb.pack(side='right', fill='y')
        self.status_text.config(yscrollcommand=sb.set)

    def _update_audio_hint(self):
        """Reflect what the current audio selection will actually capture."""
        devices = getattr(self, 'audio_devices', [])
        selected = self.audio_device.get()

        if not devices:
            self.audio_hint.config(
                foreground='#a00',
                text="No audio devices detected - will broadcast VIDEO ONLY.")
        elif selected == NO_AUDIO_LABEL:
            self.audio_hint.config(
                foreground='#555',
                text="Video only - no audio will be broadcast.")
        elif is_loopback_device(selected):
            self.audio_hint.config(
                foreground='#0a7d00',
                text="OK: capturing SYSTEM/DESKTOP audio - exactly what plays on "
                     "the PC (e.g. a video's sound).")
        else:
            # A microphone is selected: the desktop/video sound is NOT captured.
            if find_loopback_device(devices) is None:
                tail = ("No system-audio (loopback) device found. To capture "
                        "desktop/video sound, enable 'Stereo Mix' or install "
                        "VB-Cable / virtual-audio-capturer.")
            else:
                tail = ("A loopback device is available - select it above to "
                        "capture desktop/video sound instead.")
            self.audio_hint.config(
                foreground='#c25e00',
                text="WARNING: MICROPHONE only - a video's sound is NOT captured "
                     "cleanly. " + tail)

    # --------------------------------------------------------------- utils
    def log_status(self, message):
        def _append():
            ts = datetime.now().strftime("%H:%M:%S")
            self.status_text.insert('end', f"[{ts}] {message}\n")
            self.status_text.see('end')
        try:
            self.root.after(0, _append)
        except Exception:
            _append()
        safe_print(message)

    def get_ffmpeg(self):
        return FFMPEG_PATH or 'ffmpeg'

    def viewer_url(self):
        if self.stream_id:
            return f"{self.server_ip.get().rstrip('/')}/viewer/{self.stream_id}"
        return None

    # --------------------------------------------------------------- area
    def select_area(self):
        self.root.withdraw()

        def on_selection(x1, y1, x2, y2):
            self.root.deiconify()
            if x1 is not None:
                w = (x2 - x1) // 2 * 2  # even dims for yuv420p
                h = (y2 - y1) // 2 * 2
                self.selected_area = {'x': x1, 'y': y1, 'width': w, 'height': h}
                self.area_label.config(text=f"Selected: {w}x{h} at ({x1}, {y1})")
                self.start_btn.config(state='normal')
                self.log_status(f"Area selected: {w}x{h}")
            else:
                self.log_status("Area selection cancelled")

        ScreenSelector(on_selection).show()

    # --------------------------------------------------------- broadcast
    def start_broadcasting(self):
        if not self.selected_area:
            messagebox.showerror("Error", "Please select a screen area first")
            return
        if not self.server_ip.get():
            messagebox.showerror("Error", "Please enter server address")
            return

        self.start_btn.config(state='disabled')

        def _begin():
            self.stream_id = self.initialize_stream(name="Screen Broadcast")
            if not self.stream_id:
                self.root.after(0, lambda: self.start_btn.config(state='normal'))
                return

            self.work_dir = tempfile.mkdtemp(prefix="broadcast_")
            self.uploaded = set()
            playlist_path = os.path.join(self.work_dir, "stream.m3u8")
            seg_pattern = os.path.join(self.work_dir, "segment_%03d.ts")

            ff = self.get_ffmpeg()
            base = [
                ff, '-f', 'gdigrab', '-framerate', '30',
                '-offset_x', str(self.selected_area['x']),
                '-offset_y', str(self.selected_area['y']),
                '-video_size', f"{self.selected_area['width']}x{self.selected_area['height']}",
                '-i', 'desktop',
            ]

            # Pick a quality-appropriate bitrate from the captured resolution
            # (~0.1 bits/pixel). Clamped so small areas still look crisp and huge
            # areas don't explode bandwidth.  720p30 ~ 2.8Mbps, 1080p30 ~ 6Mbps.
            cap_w = self.selected_area['width']
            cap_h = self.selected_area['height']
            target_kbps = int(max(3000, min(8000, cap_w * cap_h * 30 * 0.10 / 1000)))

            venc = [
                # 'fast' preset + 'high' profile = noticeably better picture than
                # veryfast. We drop '-tune zerolatency' (it disables B-frames and
                # look-ahead, hurting quality); our ~6s player buffer absorbs the
                # tiny extra latency.
                '-c:v', 'libx264', '-preset', 'fast', '-profile:v', 'high',
                '-pix_fmt', 'yuv420p',
                # Constant 30fps and a keyframe every 2s (= segment length) so each
                # segment starts on a keyframe -> no stutter at segment joins.
                '-r', '30',
                '-g', '60', '-keyint_min', '60', '-sc_threshold', '0',
                '-force_key_frames', 'expr:gte(t,n_forced*2)',
                # CRF 21 = visually high quality; maxrate/bufsize (VBV) caps the
                # peak bitrate so playback stays smooth on limited bandwidth.
                '-crf', '21',
                '-maxrate', f'{target_kbps}k', '-bufsize', f'{target_kbps * 2}k',
            ]

            hls = [
                '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6',
                '-hls_flags', 'delete_segments+append_list+omit_endlist+independent_segments',
                '-hls_segment_type', 'mpegts',
                '-hls_segment_filename', seg_pattern, playlist_path,
            ]

            cmd_video = base + venc + hls

            def _spawn(cmd):
                return subprocess.Popen(
                    cmd, stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW
                )

            chosen_audio = self.audio_device.get()
            use_audio = bool(chosen_audio) and chosen_audio != NO_AUDIO_LABEL

            if use_audio:
                audio_in = ['-f', 'dshow', '-i', f'audio={chosen_audio}']
                cmd_audio = base + audio_in + venc + ['-c:a', 'aac', '-b:a', '128k'] + hls
                self.log_status(f"Starting broadcast (audio: {chosen_audio})...")
                if not is_loopback_device(chosen_audio):
                    self.log_status("NOTE: microphone source - a video's sound is NOT "
                                    "captured cleanly (needs a Stereo Mix / VB-Cable "
                                    "loopback device for desktop audio).")
                self.ffmpeg_process = _spawn(cmd_audio)
                # Give ffmpeg a moment; if it died (audio device busy/unavailable),
                # retry video-only so the broadcast still goes out.
                time.sleep(2.0)
                if self.ffmpeg_process.poll() is not None:
                    self.log_status("Audio device unavailable; broadcasting VIDEO ONLY.")
                    self.ffmpeg_process = _spawn(cmd_video)
                else:
                    self.log_status("Audio IS being captured.")
            else:
                self.log_status("Broadcasting VIDEO ONLY (no audio selected).")
                self.ffmpeg_process = _spawn(cmd_video)

            self.is_broadcasting = True
            self.root.after(0, lambda: self.stop_btn.config(state='normal'))
            self.root.after(0, lambda: self.open_btn.config(state='normal'))
            self.log_status("Broadcasting LIVE!")
            self.log_status(f"Stream ID: {self.stream_id}")
            self.log_status(f"Watch at: {self.viewer_url()}")

            self.watch_thread = threading.Thread(target=self.upload_loop, daemon=True)
            self.watch_thread.start()

        threading.Thread(target=_begin, daemon=True).start()

    def upload_loop(self):
        """Continuously upload new HLS segments + the playlist to the server."""
        base_url = self.server_ip.get().rstrip('/')
        while self.is_broadcasting:
            try:
                segments = sorted(glob.glob(os.path.join(self.work_dir, "segment_*.ts")))
                for seg in segments:
                    name = os.path.basename(seg)
                    if name in self.uploaded:
                        continue
                    m = re.search(r'segment_(\d+)\.ts', name)
                    if not m:
                        continue
                    number = int(m.group(1))
                    # ffmpeg may still be writing the newest segment; ensure it's stable
                    try:
                        size1 = os.path.getsize(seg)
                        time.sleep(0.2)
                        size2 = os.path.getsize(seg)
                        if size1 != size2 or size2 == 0:
                            continue  # still being written; try next cycle
                    except OSError:
                        continue
                    try:
                        with open(seg, 'rb') as f:
                            SESSION.post(
                                f"{base_url}/api/stream-receiver/{self.stream_id}/segment",
                                files={'segment': f},
                                data={'segment_number': number},
                                timeout=30,
                                proxies=NO_PROXIES,
                            )

                        self.uploaded.add(name)
                        self.log_status(f"Uploaded {name}")
                    except Exception as e:
                        self.log_status(f"Segment upload error: {e}")

                # Upload the current playlist so viewers see the live window
                playlist_path = os.path.join(self.work_dir, "stream.m3u8")
                if os.path.exists(playlist_path):
                    try:
                        with open(playlist_path, 'r') as f:
                            content = f.read()
                        SESSION.post(
                            f"{base_url}/api/stream-receiver/{self.stream_id}/playlist",
                            json={'playlist': content}, timeout=15,
                            proxies=NO_PROXIES,
                        )


                    except Exception:
                        pass
            except Exception as e:
                self.log_status(f"Upload loop error: {e}")
            time.sleep(0.5)


    def stop_broadcasting(self):
        if not self.is_broadcasting:
            return
        self.is_broadcasting = False
        self.stop_btn.config(state='disabled')
        self.log_status("Stopping broadcast...")

        proc = self.ffmpeg_process
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(b'q')
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=6)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=4)
                except Exception:
                    pass
        self.ffmpeg_process = None

        # Final flush + end session on background thread
        def _finish():
            time.sleep(1.5)  # let the watcher push the last segments
            if self.stream_id:
                try:
                    SESSION.post(
                        f"{self.server_ip.get().rstrip('/')}/api/stream-receiver/{self.stream_id}/end",
                        timeout=10,
                        proxies=NO_PROXIES,
                    )


                except Exception:
                    pass
                self.log_status(f"Broadcast ended: {self.stream_id}")
            if self.work_dir:
                shutil.rmtree(self.work_dir, ignore_errors=True)
            self.root.after(0, lambda: self.start_btn.config(state='normal'))

        threading.Thread(target=_finish, daemon=True).start()

    def open_in_browser(self):
        url = self.viewer_url()
        if url:
            webbrowser.open(url)
            self.log_status(f"Opened: {url}")
        else:
            messagebox.showinfo("No Stream", "Start broadcasting first.")

    # --------------------------------------------------------------- server
    def initialize_stream(self, name="Screen Broadcast"):
        try:
            payload = {
                'name': name,
                'width': self.selected_area['width'],
                'height': self.selected_area['height'],
                'fps': 30,
            }
            r = SESSION.post(
                f"{self.server_ip.get().rstrip('/')}/api/stream-receiver/init",
                json=payload, timeout=10,
                proxies=NO_PROXIES,
            )


            if r.status_code in (200, 201):
                stream_id = r.json().get('stream_id')
                self.log_status(f"Stream session created: {stream_id}")
                return stream_id
            self.log_status(f"Failed to create stream session: HTTP {r.status_code}")
            return None
        except Exception as e:
            self.log_status(f"Connection error: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Connection Error", f"Failed to connect to server:\n{e}"))
            return None

    # --------------------------------------------------------------- lifecycle
    def on_closing(self):
        if self.is_broadcasting:
            self.is_broadcasting = False
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                try:
                    self.ffmpeg_process.terminate()
                except Exception:
                    pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def dependencies_message():
    missing = []
    ffmpeg_ok = False
    if FFMPEG_PATH:
        try:
            subprocess.run([FFMPEG_PATH, '-version'], capture_output=True,
                           check=True, creationflags=CREATE_NO_WINDOW)
            ffmpeg_ok = True
        except Exception:
            ffmpeg_ok = False
    if not ffmpeg_ok:
        missing.append("FFmpeg")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import requests as _r  # noqa: F401
    except ImportError:
        missing.append("requests")
    return missing


def show_missing_dependencies(missing):
    lines = ["The following dependencies are missing:", "",
             "  - " + ", ".join(missing), ""]
    if "FFmpeg" in missing:
        lines += ["FFmpeg should be bundled with this app. If you see this,",
                  "place 'ffmpeg.exe' in a 'ffmpeg' folder next to the program,",
                  "or install FFmpeg to C:\\ffmpeg\\bin, or add it to PATH."]
    msg = "\n".join(lines)
    safe_print(msg)
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing Dependencies", msg)
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    missing = dependencies_message()
    if missing:
        show_missing_dependencies(missing)
        sys.exit(1)
    safe_print(f"FFmpeg found at: {FFMPEG_PATH}")
    BroadcastClient().run()
