"""Clip & Save download engine: wraps yt-dlp. No Tk code here, so it can be tested on its own.

fetch_info(url)            -> VideoInfo (title, channel, thumbnail, quality options)
download(info, option, …)  -> Path of the finished file; progress reported through a callback
"""
from __future__ import annotations

import os
import re
import shutil
import ssl
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import certifi
import yt_dlp

APP_NAME = "Clip & Save"
APP_VERSION = "1.0.0"
USER_AGENT = f"ClipAndSave/{APP_VERSION} (personal desktop video downloader)"

YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
CODEC_RANK = {"avc1": 0, "vp9": 1, "vp09": 1, "av01": 2}  # most compatible first
CODEC_LABEL = {"avc1": "H.264", "vp9": "VP9", "vp09": "VP9", "av01": "AV1"}


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- tools
def ffmpeg_path() -> str | None:
    """System ffmpeg if installed, else the copy bundled with imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - missing/corrupt bundle: run without ffmpeg
        return None


def js_runtimes() -> dict:
    """YouTube needs a JavaScript runtime for full format access; use whichever is installed."""
    found = {}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            found[name] = {"path": path}
    return found


def https_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^\s*(https?://)?([\w-]+\.)+[a-z]{2,}(/\S*)?\s*$", text or "", re.I))


def is_youtube(url: str) -> bool:
    host = re.sub(r"^\s*(https?://)?", "", url or "", flags=re.I).split("/")[0].lower()
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


def normalise_url(url: str) -> str:
    url = (url or "").strip()
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


# --------------------------------------------------------------------------- data
@dataclass
class Option:
    """One row in the quality list."""
    key: str                 # stable id, e.g. "v1080" or "mp3"
    label: str               # "1080p" / "Audio only"
    detail: str              # "MP4 · H.264 · 60 fps"
    size: int | None         # bytes (estimate) or None
    kind: str                # "video" | "audio"
    format_spec: str         # yt-dlp format selector
    height: int = 0
    audio_codec: str = ""    # for audio rows: "mp3" or "m4a"


@dataclass
class VideoInfo:
    url: str
    id: str
    title: str
    channel: str
    duration: int | None
    views: int | None
    upload_date: str
    thumbnail_url: str | None
    options: list[Option] = field(default_factory=list)


def human_size(n: int | None) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def human_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def human_count(n) -> str:
    if n is None:
        return ""
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            v = n / div
            return f"{v:.1f}".rstrip("0").rstrip(".") + suf
    return str(n)


def quality_name(height: int) -> str:
    names = {4320: "4320p (8K)", 2160: "2160p (4K)", 1440: "1440p (2K)", 1080: "1080p (Full HD)", 720: "720p (HD)"}
    return names.get(height, f"{height}p")


# --------------------------------------------------------------------------- yt-dlp
def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "http_headers": {},
        "windowsfilenames": True,
        "logger": _QuietLogger(),
    }
    ff = ffmpeg_path()
    if ff:
        opts["ffmpeg_location"] = ff
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts


def _size(f: dict, duration) -> int | None:
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = int(f["tbr"] * 1000 / 8 * duration)
    return int(size) if size else None


def _direct(f: dict) -> bool:
    """Plain HTTPS stream (faster, exact size) rather than HLS/DASH fragments."""
    return (f.get("protocol") or "") in ("https", "http")


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _codec(f: dict) -> str:
    return (f.get("vcodec") or "").split(".")[0].lower()


def build_options(info: dict) -> list[Option]:
    formats = info.get("formats") or []
    duration = info.get("duration")
    has_ffmpeg = ffmpeg_path() is not None

    audio = [f for f in formats if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
             and f.get("url") and not (f.get("format_note") or "").lower().startswith("storyboard")]
    # Prefer original-language track (no 'dubbed'/'descriptive' flags) and AAC (plays everywhere).
    def audio_key(f):
        lang_pref = f.get("language_preference") or 0
        stereo = (f.get("audio_channels") or 2) <= 2  # 5.1 tracks play badly on many devices
        plain = "drc" not in str(f.get("format_id", ""))  # skip YouTube's dynamic-range-compressed copy
        return (lang_pref, stereo, f.get("ext") == "m4a", plain, _direct(f), f.get("abr") or f.get("tbr") or 0)
    best_audio = max(audio, key=audio_key) if audio else None
    best_m4a = max((f for f in audio if f.get("ext") == "m4a"), key=audio_key, default=None)

    video_only = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("acodec") in (None, "none")
                  and f.get("height") and f.get("url")]
    muxed = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")
             and f.get("height") and f.get("url")]

    options: list[Option] = []
    heights = sorted({f["height"] for f in (video_only if has_ffmpeg else []) + muxed}, reverse=True)
    for h in heights:
        if h < 144:
            continue
        pick = None
        if has_ffmpeg:
            cands = [f for f in video_only if f["height"] == h]
            sdr = [f for f in cands if (f.get("dynamic_range") or "SDR") == "SDR"] or cands
            if sdr:
                # Most compatible codec first (H.264 > VP9 > AV1), then highest frame rate and bitrate.
                rank = min(CODEC_RANK.get(_codec(f), 9) for f in sdr)
                same_codec = [f for f in sdr if CODEC_RANK.get(_codec(f), 9) == rank]
                pick = max(same_codec, key=lambda f: ((f.get("fps") or 0), _direct(f), f.get("tbr") or 0))
        if pick is not None:
            aud = best_m4a or best_audio
            spec = f"{pick['format_id']}+{aud['format_id']}" if aud else pick["format_id"]
            size = (_size(pick, duration) or 0) + (_size(aud, duration) or 0) if aud else _size(pick, duration)
            codec = CODEC_LABEL.get(_codec(pick), _codec(pick).upper() or "video")
        else:
            m = [f for f in muxed if f["height"] == h]
            if not m:
                continue
            pick = max(m, key=lambda f: f.get("tbr") or 0)
            spec, size = pick["format_id"], _size(pick, duration)
            codec = CODEC_LABEL.get(_codec(pick), _codec(pick).upper() or "video")
        fps = round(pick.get("fps") or 0)
        detail = f"MP4 · {codec}" + (f" · {fps} fps" if fps > 30 else "")
        hdr = pick.get("dynamic_range") not in (None, "SDR")
        options.append(Option(key=f"v{h}", label=quality_name(h) + (" HDR" if hdr else ""), detail=detail,
                              size=size or None, kind="video", format_spec=spec, height=h))

    if best_audio is not None:
        abr = round(best_audio.get("abr") or best_audio.get("tbr") or 0)
        if has_ffmpeg:
            options.append(Option(key="mp3", label="Audio only", detail="MP3 · best quality (VBR)",
                                  size=_size(best_audio, duration), kind="audio",
                                  format_spec=best_audio["format_id"], audio_codec="mp3"))
        if best_m4a is not None:
            m4a_abr = round(best_m4a.get("abr") or best_m4a.get("tbr") or 0)
            options.append(Option(key="m4a", label="Audio only", detail=f"M4A · original AAC" +
                                  (f" · {m4a_abr} kbps" if m4a_abr else ""), size=_size(best_m4a, duration),
                                  kind="audio", format_spec=best_m4a["format_id"], audio_codec="m4a"))
        elif not has_ffmpeg:
            options.append(Option(key="aud", label="Audio only", detail=f"{best_audio.get('ext', '').upper()} · original"
                                  + (f" · {abr} kbps" if abr else ""), size=_size(best_audio, duration), kind="audio",
                                  format_spec=best_audio["format_id"]))
    return options


def best_thumbnail(info: dict) -> str | None:
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    jpgs = [t for t in thumbs if ".jpg" in t["url"].split("?")[0]]
    pool = jpgs or thumbs
    if pool:
        return max(pool, key=lambda t: ((t.get("width") or 0) * (t.get("height") or 0), t.get("preference") or 0))["url"]
    return info.get("thumbnail")


def fetch_info(url: str) -> VideoInfo:
    url = normalise_url(url)
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise ValueError("That link is a playlist with no playable videos.")
        info = entries[0]
    date = info.get("upload_date") or ""
    if len(date) == 8:
        date = f"{date[6:8]}/{date[4:6]}/{date[:4]}"
    return VideoInfo(url=info.get("webpage_url") or url, id=info.get("id", ""), title=info.get("title") or "Untitled",
                     channel=info.get("channel") or info.get("uploader") or "", duration=info.get("duration"),
                     views=info.get("view_count"), upload_date=date, thumbnail_url=best_thumbnail(info),
                     options=build_options(info))


def fetch_thumbnail(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20, context=https_context()) as r:
        return r.read()


def download(video: VideoInfo, option: Option, folder: Path, on_progress, cancel: threading.Event) -> Path:
    """Download ``option`` of ``video`` into ``folder``. on_progress(dict) receives:
    {"phase": "download"|"process", "frac": 0..1|None, "speed": B/s|None, "eta": s|None,
     "done": bytes, "total": bytes|None, "part": n, "parts": n}"""
    folder.mkdir(parents=True, exist_ok=True)
    parts = option.format_spec.count("+") + 1
    state = {"part": 0, "last_file": None, "temp": set(), "final": None}

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("tmpfilename"):
            state["temp"].add(d["tmpfilename"])
        if d.get("filename") != state["last_file"]:
            state["last_file"] = d.get("filename")
            state["part"] += 1
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            part_frac = (done / total) if total else None
            frac = None if part_frac is None else (min(state["part"], parts) - 1 + part_frac) / parts
            on_progress({"phase": "download", "frac": frac, "speed": d.get("speed"), "eta": d.get("eta"),
                         "done": done, "total": total, "part": min(state["part"], parts), "parts": parts})
        elif status == "finished" and state["part"] >= parts:
            on_progress({"phase": "process", "frac": 1.0, "speed": None, "eta": None, "done": 0, "total": None,
                         "part": parts, "parts": parts})

    def pp_hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                state["final"] = path

    opts = _base_opts()
    suffix = f" [{option.height}p]" if option.kind == "video" else ""
    opts.update({
        "format": option.format_spec,
        "outtmpl": {"default": str(folder / f"%(title).150B{suffix}.%(ext)s")},
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "overwrites": False,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
    })
    pps = []
    if option.kind == "video" and "ffmpeg_location" in opts:
        opts["merge_output_format"] = "mp4"
    if option.audio_codec == "mp3":
        pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"})
    if "ffmpeg_location" in opts:
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
    if pps:
        opts["postprocessors"] = pps

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video.url, download=True)
    except Cancelled:
        _cleanup(state["temp"])
        raise
    except yt_dlp.utils.DownloadError as exc:
        if cancel.is_set() or isinstance(getattr(exc, "exc_info", (None, None))[1], Cancelled):
            _cleanup(state["temp"])
            raise Cancelled() from None
        raise
    final = state["final"]
    if not final:
        reqs = info.get("requested_downloads") or []
        final = reqs[0].get("filepath") if reqs else info.get("filepath")
    if not final:
        final = yt_dlp.YoutubeDL(opts).prepare_filename(info)
    return Path(final)


def _cleanup(paths) -> None:
    for p in paths:
        for candidate in (p, p + ".part", p + ".ytdl"):
            try:
                if candidate.endswith((".part", ".ytdl")) and os.path.exists(candidate):
                    os.remove(candidate)
            except OSError:
                pass


def friendly_error(exc: BaseException) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    text = re.sub(r"^ERROR:\s*", "", text).strip()
    low = text.lower()
    if "private video" in low:
        return "This video is private."
    if "sign in to confirm your age" in low or "age-restricted" in low:
        return "This video is age-restricted and needs a signed-in account, which this app doesn't use."
    if "members-only" in low or "join this channel" in low:
        return "This video is for channel members only."
    if "video unavailable" in low or "not available" in low:
        return "This video is unavailable (removed, blocked in your region, or not public)."
    if "unsupported url" in low:
        return "That link isn't a video page this app can read."
    if "live event will begin" in low or "is_live" in low or "premieres in" in low:
        return "This is a live stream or premiere that hasn't finished yet."
    if "urlopen error" in low or "getaddrinfo" in low or "timed out" in low:
        return "Couldn't reach YouTube. Check your internet connection and try again."
    if "sign in to confirm you" in low and "bot" in low:
        return "YouTube asked to confirm you're not a bot. Wait a while, then try again."
    first = text.splitlines()[0] if text else exc.__class__.__name__
    return first[:220]
