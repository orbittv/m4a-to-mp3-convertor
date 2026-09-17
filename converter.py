import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import subprocess
import os
import sys
import zipfile
import urllib.request
import shutil
import json

APP_DIR    = os.path.dirname(os.path.abspath(__file__))
FFMPEG_DIR = os.path.join(APP_DIR, "ffmpeg")
FFMPEG_EXE = os.path.join(FFMPEG_DIR, "ffmpeg.exe")

FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

BG       = "#1e1e2e"
BG2      = "#2a2a3e"
ACCENT   = "#7c6af7"
ACCENT2  = "#5a4fcf"
FG       = "#cdd6f4"
FG_DIM   = "#6c7086"
GREEN    = "#a6e3a1"
YELLOW   = "#f9e2af"
RED      = "#f38ba8"
ROW_ODD  = "#252535"
ROW_EVEN = "#1e1e2e"


def find_ffmpeg():
    if os.path.isfile(FFMPEG_EXE):
        return FFMPEG_EXE
    found = shutil.which("ffmpeg")
    if found:
        return found
    return None


def download_ffmpeg(progress_cb=None):
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    zip_path = os.path.join(FFMPEG_DIR, "ffmpeg.zip")

    def _report(block, block_size, total):
        if progress_cb and total > 0:
            pct = min(100, int(block * block_size * 100 / total))
            progress_cb(pct)

    if progress_cb:
        progress_cb(0)
    urllib.request.urlretrieve(FFMPEG_URL, zip_path, reporthook=_report)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.lower().endswith("bin/ffmpeg.exe"):
                with zf.open(member) as src, open(FFMPEG_EXE, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                break

    os.remove(zip_path)
    if progress_cb:
        progress_cb(100)


def find_ffprobe():
    """Return path to ffprobe binary (same folder as ffmpeg or PATH)."""
    local = os.path.join(FFMPEG_DIR, "ffprobe.exe")
    if os.path.isfile(local):
        return local
    found = shutil.which("ffprobe")
    if found:
        return found
    return None


def probe_file(path):
    """Return (bitrate_str, samplerate_str) of the audio stream, or ('?', '?')."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return ("?", "?")
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-select_streams", "a:0",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return ("?", "?")
        s = streams[0]
        # sample rate
        sr = s.get("sample_rate", "?")
        sr_str = "{} Hz".format(sr) if sr != "?" else "?"
        # bitrate: prefer stream bit_rate, fall back to format bit_rate
        br = s.get("bit_rate")
        if not br:
            fmt = data.get("format", {})
            br = fmt.get("bit_rate")
        if br:
            br_str = "{} kbps".format(int(br) // 1000)
        else:
            br_str = "?"
        return (br_str, sr_str)
    except Exception:
        return ("?", "?")



class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("M4A to MP3 Converter")
        self.geometry("1280x1024")
        self.minsize(1024, 800)
        self.configure(bg=BG)

        self.source_dir = tk.StringVar(value="")
        self.output_dir = tk.StringVar(value="")
        self._files = []
        self._file_meta = {}   # idx -> (bitrate_str, samplerate_str)
        self._converting = False
        self._ffmpeg_exe = None

        self._build_styles()
        self._build_ui()
        self.after(200, self._init_ffmpeg)

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Treeview", background=BG2, foreground=FG,
                        fieldbackground=BG2, rowheight=32, borderwidth=0,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=BG2, foreground=ACCENT,
                        relief="flat", font=("Segoe UI", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", ACCENT2)],
                  foreground=[("selected", FG)])
        style.configure("App.TButton", background=BG2, foreground=FG,
                        borderwidth=1, relief="flat", padding=(12, 6),
                        font=("Segoe UI", 10))
        style.map("App.TButton",
                  background=[("active", ACCENT2)],
                  foreground=[("active", FG)])
        style.configure("Convert.TButton", background=ACCENT, foreground="#ffffff",
                        borderwidth=0, relief="flat", padding=(20, 8),
                        font=("Segoe UI", 10, "bold"))
        style.map("Convert.TButton",
                  background=[("active", ACCENT2), ("disabled", BG2)],
                  foreground=[("active", "#ffffff"), ("disabled", FG_DIM)])
        style.configure("Green.Horizontal.TProgressbar",
                        troughcolor=BG2,
                        background=GREEN,
                        bordercolor=BG,
                        lightcolor=GREEN,
                        darkcolor=GREEN)

    def _build_ui(self):
        top = tk.Frame(self, bg=BG, pady=12, padx=16)
        top.pack(fill="x")

        src_frame = tk.Frame(top, bg=BG)
        src_frame.pack(side="left")
        ttk.Button(src_frame, text="Source", style="App.TButton",
                   command=self._pick_source).pack(side="left")
        tk.Label(src_frame, textvariable=self.source_dir, bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9), width=60, anchor="w", padx=8).pack(side="left")

        out_frame = tk.Frame(top, bg=BG, padx=16)
        out_frame.pack(side="left")
        ttk.Button(out_frame, text="Output", style="App.TButton",
                   command=self._pick_output).pack(side="left")
        tk.Label(out_frame, textvariable=self.output_dir, bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9), width=60, anchor="w", padx=8).pack(side="left")

        self._convert_btn = ttk.Button(top, text="  Convert", style="Convert.TButton",
                                       command=self._start_conversion)
        self._convert_btn.pack(side="right")

        tk.Frame(self, bg=ACCENT, height=1).pack(fill="x")

        info_frame = tk.Frame(self, bg=BG2, pady=6, padx=16)
        info_frame.pack(fill="x")

        self._status_var = tk.StringVar(value="No folder selected")
        tk.Label(info_frame, textvariable=self._status_var, bg=BG2, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(side="left")

        self._count_var = tk.StringVar(value="")
        tk.Label(info_frame, textvariable=self._count_var, bg=BG2, fg=FG,
                 font=("Segoe UI", 9, "bold")).pack(side="right")

        self._prog_var = tk.DoubleVar(value=0)
        ttk.Progressbar(self, variable=self._prog_var, maximum=100,
                        mode="determinate",
                        style="Green.Horizontal.TProgressbar").pack(fill="x")

        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=16, pady=12)

        cols = ("name", "format", "bitrate", "samplerate", "status")
        self._tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("name",       text="File name")
        self._tree.heading("format",     text="Format")
        self._tree.heading("bitrate",    text="Bitrate")
        self._tree.heading("samplerate", text="Sample Rate")
        self._tree.heading("status",     text="Status")
        self._tree.column("name",       width=480, stretch=True,  anchor="w")
        self._tree.column("format",     width=110, stretch=False, anchor="center")
        self._tree.column("bitrate",    width=110, stretch=False, anchor="center")
        self._tree.column("samplerate", width=110, stretch=False, anchor="center")
        self._tree.column("status",     width=110, stretch=False, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._tree.tag_configure("odd",      background=ROW_ODD)
        self._tree.tag_configure("even",     background=ROW_EVEN)
        self._tree.tag_configure("progress", foreground=YELLOW)
        self._tree.tag_configure("done",     foreground=GREEN)
        self._tree.tag_configure("error",    foreground=RED)

        bottom_bar = tk.Frame(self, bg=BG)
        bottom_bar.pack(side="bottom", fill="x", pady=4, padx=16)

        self._ffmpeg_var = tk.StringVar(value="Checking ffmpeg...")
        tk.Label(bottom_bar, textvariable=self._ffmpeg_var, bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side="left")

        tk.Label(bottom_bar, text="version 0.1", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side="right")

    def _init_ffmpeg(self):
        exe = find_ffmpeg()
        if exe:
            self._ffmpeg_exe = exe
            self._ffmpeg_var.set("ffmpeg: " + exe)
        else:
            self._ffmpeg_var.set("ffmpeg not found - downloading...")
            threading.Thread(target=self._download_ffmpeg_thread, daemon=True).start()

    def _download_ffmpeg_thread(self):
        try:
            def cb(pct):
                self._ffmpeg_var.set("Downloading ffmpeg... {}%".format(pct))
                self._prog_var.set(pct)
            download_ffmpeg(progress_cb=cb)
            self._ffmpeg_exe = FFMPEG_EXE
            self.after(0, lambda: self._ffmpeg_var.set("ffmpeg: " + FFMPEG_EXE))
            self.after(0, lambda: self._prog_var.set(0))
        except Exception as e:
            self.after(0, lambda: self._ffmpeg_var.set("ffmpeg download failed: {}".format(e)))
            self.after(0, lambda: messagebox.showerror(
                "FFmpeg missing",
                "Could not download ffmpeg.\n\nInstall manually:\n  winget install ffmpeg\n\nError: {}".format(e)
            ))

    def _pick_source(self):
        d = filedialog.askdirectory(title="Select source folder (M4A files)")
        if not d:
            return
        self.source_dir.set(d)
        self._load_files(d)

    def _pick_output(self):
        d = filedialog.askdirectory(title="Select output folder (MP3 files)")
        if not d:
            return
        self.output_dir.set(d)

    def _load_files(self, folder):
        self._files = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".m4a")
        ])
        self._file_meta = {}
        for row in self._tree.get_children():
            self._tree.delete(row)
        for i, path in enumerate(self._files):
            fname = os.path.basename(path)
            tag = "odd" if i % 2 else "even"
            self._tree.insert("", "end", iid=str(i),
                              values=(fname, "M4A -> MP3", "...", "...", "Ready"),
                              tags=(tag,))
        n = len(self._files)
        self._count_var.set("{} file{} found".format(n, "s" if n != 1 else ""))
        self._status_var.set("Reading file info..." if n else "No .m4a files found")
        self._prog_var.set(0)
        if n:
            threading.Thread(target=self._probe_all, daemon=True).start()

    def _probe_all(self):
        """Probe each file in background and update bitrate/samplerate columns."""
        for i, path in enumerate(self._files):
            br, sr = probe_file(path)
            self._file_meta[i] = (br, sr)
            self.after(0, self._update_meta_row, i, br, sr)
        self.after(0, lambda: self._status_var.set("Ready to convert"))

    def _update_meta_row(self, idx, br, sr):
        iid = str(idx)
        if not self._tree.exists(iid):
            return
        old = self._tree.item(iid, "values")
        self._tree.item(iid, values=(old[0], old[1], br, sr, old[4]))

    def _start_conversion(self):
        if self._converting:
            return
        if not self._files:
            messagebox.showwarning("No files",
                                   "Please select a source folder with .m4a files.")
            return
        if not self.output_dir.get():
            messagebox.showwarning("No output", "Please select an output folder.")
            return
        if not self._ffmpeg_exe or not os.path.isfile(self._ffmpeg_exe):
            exe = find_ffmpeg()
            if not exe:
                messagebox.showerror("FFmpeg missing",
                                     "ffmpeg is not available yet.")
                return
            self._ffmpeg_exe = exe
        self._converting = True
        self._convert_btn.state(["disabled"])
        threading.Thread(target=self._convert_thread, daemon=True).start()

    def _convert_thread(self):
        total = len(self._files)
        done  = 0
        for i, path in enumerate(self._files):
            fname    = os.path.basename(path)
            stem     = os.path.splitext(fname)[0]
            out_file = os.path.join(self.output_dir.get(), stem + ".mp3")
            self.after(0, self._set_status, i, "Progress")
            # use probed meta if available
            br_str, sr_str = self._file_meta.get(i, ("?", "?"))
            success = self._run_ffmpeg(path, out_file, br_str, sr_str)
            status  = "Done" if success else "Error"
            done   += 1
            pct     = done * 100 / total
            self.after(0, self._set_status, i, status)
            self.after(0, lambda p=pct: self._prog_var.set(p))
            self.after(0, lambda d=done, t=total:
                       self._status_var.set("Converting... {}/{}".format(d, t)))
        self.after(0, self._conversion_done)

    def _run_ffmpeg(self, src, dst, br_str="?", sr_str="?"):
        # parse bitrate: "256 kbps" -> "256k", fallback 192k
        try:
            ab = str(int(br_str.split()[0])) + "k" if br_str != "?" else "192k"
        except Exception:
            ab = "192k"
        # parse sample rate: "44100 Hz" -> "44100", fallback 44100
        try:
            ar = sr_str.split()[0] if sr_str != "?" else "44100"
        except Exception:
            ar = "44100"
        cmd = [self._ffmpeg_exe, "-y", "-i", src,
               "-vn", "-ab", ab, "-ar", ar, "-f", "mp3", dst]
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=300)
            return r.returncode == 0
        except Exception:
            return False

    def _set_status(self, idx, status):
        iid = str(idx)
        if not self._tree.exists(iid):
            return
        tags = [t for t in self._tree.item(iid, "tags")
                if t not in ("progress", "done", "error")]
        tags.append(status.lower())
        old = self._tree.item(iid, "values")
        self._tree.item(iid, values=(old[0], old[1], old[2], old[3], status), tags=tags)
        self._tree.see(iid)

    def _conversion_done(self):
        self._converting = False
        self._convert_btn.state(["!disabled"])
        self._status_var.set("All done!")
        self._prog_var.set(100)
        messagebox.showinfo("Done!", "Conversion complete!")


if __name__ == "__main__":
    app = ConverterApp()
    app.mainloop()
