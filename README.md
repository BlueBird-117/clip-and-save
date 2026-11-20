# Clip & Save

A small Windows desktop app: paste a YouTube link, see the video's details, choose a quality,
and download it as MP4 (or just the audio as MP3 / M4A). It's the red sibling of
Track & Cover and uses the same glass-and-bubbles look ("Ruby Night" theme).

The application source is licensed under GPL-2.0-or-later. Third-party notices are in
`licenses/THIRD-PARTY-NOTICES.md` and are bundled into the built executable.

## Download

Get `ClipAndSave.exe` from the [latest release](https://github.com/BlueBird-117/clip-and-save/releases/latest).
It runs without installing anything. Windows SmartScreen may warn on first launch, because the
app isn't code-signed: choose **More info → Run anyway**.

## Start the app from source

1. Install Python 3.11 or newer from python.org (tick "Add Python to PATH").
2. Open PowerShell in this folder.
3. `py -3 -m venv .venv`
4. `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
5. `.\.venv\Scripts\python.exe app.py`

## Build a standalone Windows app

Run `build_windows.ps1`. The finished app is `dist\ClipAndSave.exe` (about 100 MB, because
FFmpeg is bundled inside). It doesn't need Python.

## How it works

- Paste a link (or press **Paste**; a YouTube link already on the clipboard is filled in when
  the app opens) and press **Fetch video**. youtube.com, youtu.be, Shorts and
  music.youtube.com links work. For a playlist link the first video is used.
- The quality list shows every resolution YouTube offers for that video (144p up to 4K/8K),
  each with its codec, frame rate and approximate file size, plus **Audio only** as MP3 or as
  the original M4A (AAC). The best quality up to 1080p is pre-selected.
- Pick a row and press **Download** (or double-click the row). Video and audio are fetched
  separately and joined into one MP4 with FFmpeg. Progress, speed and time left are shown
  under the folder field; **Cancel** stops the download and removes the partial files.
- Codec choice per resolution: H.264 where YouTube offers it (plays everywhere), otherwise VP9,
  then AV1. 1440p and 4K are usually VP9 only. They play in VLC and in the Windows Media Player
  app (which uses the VP9 extension from the Microsoft Store).
- Files are saved as `Title [1080p].mp4`, `Title.mp3` or `Title.m4a` in the chosen folder
  (default: `Videos\Clip & Save`). Existing files are never overwritten.
- Settings (folder, "open folder when finished", background animation) are remembered in
  `%LOCALAPPDATA%\Clip & Save\settings.json`.

## Requirements and limits

- **FFmpeg** is bundled through `imageio-ffmpeg`. A system-wide `ffmpeg` on PATH is used instead
  if one is installed.
- **JavaScript runtime.** YouTube needs a JavaScript runtime before yt-dlp can list every format.
  The app uses Deno, Node.js or Bun if one is installed (this PC has Node.js). Without one, some
  or all higher qualities may be missing. The fix is to install Deno (`winget install DenoLand.Deno`)
  or Node.js.
- **Keeping it working.** YouTube changes often. When fetching starts failing, update yt-dlp:
  `.\.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"`, then rebuild the exe.
- Private, members-only and age-restricted videos aren't supported (the app doesn't sign in).
  Live streams can be downloaded only after they've finished.

## Code layout

- `app.py` wires the window to the engine (background threads, event queue, settings).
- `downloader.py` is the yt-dlp wrapper: it reads video info, builds the quality options,
  downloads with progress and cancel, and turns errors into readable messages. It has no UI code.
- `ui/theme.py` holds the colour tokens and Pillow renderers. `ui/aero_widgets.py` has the glossy
  buttons, toggles, table and bubble background. `ui/main_view.py` lays out the window.
- `tools/make_icon.py` regenerates `assets/app.ico` and `assets/logo.png` from the drawn logo.

## Fair use

Only download videos you own, that are licensed for download (for example Creative Commons),
or that you otherwise have permission to save. YouTube's Terms of Service restrict downloading
other content. Clip & Save isn't affiliated with YouTube or Google.
