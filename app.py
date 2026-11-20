"""Clip & Save: paste a YouTube link, pick a quality, download it.

UI: ui/ (Ruby Night theme, the red twin of Track & Cover's Aqua Night).
Engine: downloader.py (yt-dlp + ffmpeg).
"""
from __future__ import annotations

import io
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image

import downloader as D
from ui.main_view import RubyNightView
from ui.theme import enable_dpi_awareness, load_settings, register_fonts, save_setting


def default_folder() -> Path:
    home = Path.home()
    for cand in (home / "Videos", home / "Downloads", home):
        if cand.is_dir():
            return cand / "Clip & Save" if cand.name == "Videos" else cand
    return home


class ClipAndSaveApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(D.APP_NAME)
        settings = load_settings()
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=settings.get("folder") or str(default_folder()))
        self.status = tk.StringVar(value="Ready. Paste a YouTube link to begin.")
        self.open_when_done = tk.BooleanVar(value=bool(settings.get("open_when_done", False)))
        self.open_when_done.trace_add("write", lambda *_a: save_setting("open_when_done", self.open_when_done.get()))

        self.events: queue.Queue = queue.Queue()
        self.video: D.VideoInfo | None = None
        self.options: dict[str, D.Option] = {}
        self.cancel_flag = threading.Event()
        self.fetching = False
        self.downloading = False
        self.last_file: Path | None = None
        self._fetch_token = 0
        self._last_progress = 0.0

        self.view = RubyNightView(
            root, app_name=D.APP_NAME, version=D.APP_VERSION, url=self.url, folder=self.folder, status=self.status,
            open_when_done=self.open_when_done, on_paste=self.paste, on_fetch=self.fetch,
            on_change_folder=self.change_folder, on_download=self.download, on_cancel=self.cancel,
            on_open_folder=self.open_folder, on_option_selected=self.option_selected)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.pump)
        root.after(200, self._prefill_from_clipboard)
        if D.ffmpeg_path() is None:
            self.status.set("ffmpeg not found: only qualities with built-in audio (usually 360p) and audio-only "
                            "downloads are available.")

    # ------------------------------------------------------------------ helpers
    def post(self, kind: str, *payload) -> None:
        self.events.put((kind, payload))

    def clipboard_text(self) -> str:
        try:
            return self.root.clipboard_get().strip()
        except tk.TclError:
            return ""

    def _prefill_from_clipboard(self) -> None:
        text = self.clipboard_text()
        if not self.url.get() and D.looks_like_url(text) and D.is_youtube(text):
            self.url.set(text)
            self.status.set("Found a YouTube link on your clipboard. Press Fetch video.")

    def refresh_buttons(self) -> None:
        busy = self.fetching or self.downloading
        v = self.view
        v.fetch_button.configure(state="disabled" if busy else "normal")
        v.paste_button.configure(state="disabled" if busy else "normal")
        v.folder_button.configure(state="disabled" if self.downloading else "normal")
        v.download_button.configure(state="normal" if (self.selected_option() and not busy) else "disabled")
        v.cancel_button.configure(state="normal" if self.downloading else "disabled")
        v.set_busy(busy)

    def selected_option(self) -> D.Option | None:
        sel = self.view.table.selection()
        return self.options.get(sel[0]) if sel else None

    # ------------------------------------------------------------------ actions
    def paste(self) -> None:
        text = self.clipboard_text()
        if not text:
            self.status.set("The clipboard is empty. Copy a video link first.")
            return
        self.url.set(text.splitlines()[0].strip())
        self.fetch()

    def fetch(self) -> None:
        if self.fetching or self.downloading:
            return
        url = self.url.get().strip()
        if not url:
            self.status.set("Paste a YouTube link first.")
            self.view.url_entry.focus_set()
            return
        if not D.looks_like_url(url):
            self.status.set("That doesn't look like a link. Copy the address of a YouTube video and paste it here.")
            return
        if not D.is_youtube(url):
            self.status.set("Not a YouTube link. Trying anyway…")
        else:
            self.status.set("Reading video details from YouTube…")
        self.fetching = True
        self._fetch_token += 1
        token = self._fetch_token
        self.view.table.delete(*self.view.table.get_children())
        self.options.clear()
        self.view.set_video("", "")
        self.view.set_thumbnail(None)
        self.view.set_progress(None)
        self.refresh_buttons()
        threading.Thread(target=self._fetch_worker, args=(url, token), daemon=True).start()

    def _fetch_worker(self, url: str, token: int) -> None:
        try:
            info = D.fetch_info(url)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.post("fetch_error", token, D.friendly_error(exc))
            return
        self.post("fetched", token, info)
        if info.thumbnail_url:
            try:
                img = Image.open(io.BytesIO(D.fetch_thumbnail(info.thumbnail_url)))
                img.load()
                self.post("thumb", token, img)
            except Exception:  # noqa: BLE001 - thumbnail is cosmetic
                pass

    def option_selected(self, _event=None) -> None:
        opt = self.selected_option()
        if opt and not self.downloading:
            self.view.set_progress(None, f"Ready to download {opt.label} · {opt.detail}",
                                   D.human_size(opt.size) if opt.size else "")
        self.refresh_buttons()

    def change_folder(self) -> None:
        start = self.folder.get() if Path(self.folder.get()).is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(parent=self.root, initialdir=start, title="Choose where to save downloads")
        if chosen:
            self.folder.set(str(Path(chosen)))
            save_setting("folder", self.folder.get())

    def download(self) -> None:
        opt = self.selected_option()
        if not opt or not self.video or self.downloading or self.fetching:
            return
        folder = Path(self.folder.get())
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(D.APP_NAME, f"Can't use that folder:\n{exc}", parent=self.root)
            return
        self.downloading = True
        self.cancel_flag.clear()
        self.status.set(f"Downloading {opt.label} ({opt.detail})…")
        self.view.set_progress(0.0, "Starting…", "0%")
        self.refresh_buttons()
        threading.Thread(target=self._download_worker, args=(self.video, opt, folder), daemon=True).start()

    def _download_worker(self, video: D.VideoInfo, opt: D.Option, folder: Path) -> None:
        try:
            path = D.download(video, opt, folder, lambda p: self.post("progress", p), self.cancel_flag)
        except D.Cancelled:
            self.post("cancelled")
            return
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.post("download_error", D.friendly_error(exc))
            return
        self.post("downloaded", path)

    def cancel(self) -> None:
        if self.downloading:
            self.cancel_flag.set()
            self.status.set("Cancelling…")

    def open_folder(self) -> None:
        target = self.last_file if self.last_file and self.last_file.exists() else None
        folder = Path(self.folder.get())
        try:
            if target:
                subprocess.Popen(["explorer", "/select,", str(target)])
            elif folder.is_dir():
                os.startfile(folder)  # noqa: S606 - opening the user's own folder
            else:
                self.status.set("That folder doesn't exist yet. It's created on your first download.")
        except OSError as exc:
            self.status.set(f"Couldn't open the folder: {exc}")

    def close(self) -> None:
        if self.downloading and not messagebox.askyesno(
                D.APP_NAME, "A download is still running. Stop it and quit?", parent=self.root):
            return
        self.cancel_flag.set()
        self.root.destroy()

    # ------------------------------------------------------------------ event pump
    def pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                getattr(self, "on_" + kind)(*payload)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def on_fetch_error(self, token: int, message: str) -> None:
        if token != self._fetch_token:
            return
        self.fetching = False
        self.status.set(message)
        self.refresh_buttons()

    def on_fetched(self, token: int, info: D.VideoInfo) -> None:
        if token != self._fetch_token:
            return
        self.fetching = False
        self.video = info
        meta = " · ".join(p for p in (info.channel, D.human_duration(info.duration),
                                      f"{D.human_count(info.views)} views" if info.views is not None else "",
                                      info.upload_date) if p)
        self.view.set_video(info.title, meta)
        table = self.view.table
        preferred = None
        for opt in info.options:
            iid = table.insert("", "end", values=(opt.label, opt.detail, D.human_size(opt.size)))
            self.options[iid] = opt
            if opt.kind == "video" and preferred is None and opt.height <= 1080:
                preferred = iid
        if not info.options:
            self.status.set("No downloadable formats were found for this video.")
        else:
            preferred = preferred or table.get_children()[0]
            table.selection_set(preferred)
            table.focus(preferred)
            table.see(preferred)
            self.status.set(f"Found {len(info.options)} options. Pick a quality and press Download.")
        self.refresh_buttons()

    def on_thumb(self, token: int, img) -> None:
        if token == self._fetch_token:
            self.view.set_thumbnail(img)

    def on_progress(self, p: dict) -> None:
        now = time.monotonic()
        if p["phase"] == "download" and now - self._last_progress < 0.12:
            return
        self._last_progress = now
        if p["phase"] == "process":
            self.view.set_progress(1.0, "Finishing up (joining video and audio / converting)…", "100%")
            self.status.set("Finishing up…")
            return
        frac = p["frac"]
        bits = []
        if p["parts"] > 1:
            bits.append("Video" if p["part"] == 1 else "Audio")
        if p["total"]:
            bits.append(f"{D.human_size(p['done'])} of {D.human_size(p['total'])}")
        if p["speed"]:
            bits.append(f"{D.human_size(p['speed'])}/s")
        if p["eta"] is not None:
            bits.append(f"{D.human_duration(p['eta']) or '0:00'} left")
        self.view.set_progress(frac, " · ".join(bits) or "Downloading…",
                               f"{frac * 100:.0f}%" if frac is not None else "")

    def on_downloaded(self, path: Path) -> None:
        self.downloading = False
        self.last_file = path
        self.view.set_progress(1.0, f"Saved: {path.name}", "Done")
        self.status.set(f"Saved to {path}")
        self.refresh_buttons()
        if self.open_when_done.get():
            self.open_folder()

    def on_cancelled(self) -> None:
        self.downloading = False
        self.view.set_progress(None, "Download cancelled.", "")
        self.status.set("Download cancelled. Partial files were removed.")
        self.refresh_buttons()

    def on_download_error(self, message: str) -> None:
        self.downloading = False
        self.view.set_progress(None, "Download failed.", "")
        self.status.set(message)
        self.refresh_buttons()


def main() -> None:
    # The windowed .exe has no console: give libraries that print somewhere harmless to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    enable_dpi_awareness()
    register_fonts()
    root = tk.Tk()
    ClipAndSaveApp(root)
    root.mainloop()


def selftest(url: str, out: str) -> None:
    """ClipAndSave.exe --selftest <url> <report.txt>: check the engine without the window."""
    lines = [f"ffmpeg: {D.ffmpeg_path()}", f"js runtimes: {list(D.js_runtimes())}"]
    try:
        info = D.fetch_info(url)
        lines.append(f"title: {info.title}")
        lines += [f"  {o.label} | {o.detail} | {D.human_size(o.size)}" for o in info.options]
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ERROR: {D.friendly_error(exc)}")
    Path(out).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClipAndSave.App")
        except (AttributeError, OSError):
            pass
    main()
