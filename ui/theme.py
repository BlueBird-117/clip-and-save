"""Ruby Night theme (red twin of Track & Cover's Aqua Night): colour tokens, font registration and Pillow renderers.

Everything here is pure presentation. All sizes passed to the render functions are
device pixels (already multiplied by the UI scale factor).
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# --------------------------------------------------------------------------- paths
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def asset(name: str) -> Path:
    return APP_DIR / "assets" / name


FONT_FILES = {
    ("Exo 2", 600): "Exo2-600.ttf",
    ("Exo 2", 700): "Exo2-700.ttf",
    ("Nunito Sans", 400): "NunitoSans-400.ttf",
    ("Nunito Sans", 600): "NunitoSans-600.ttf",
    ("Nunito Sans", 700): "NunitoSans-700.ttf",
}

# --------------------------------------------------------------------------- tokens
BG_TOP, BG_MID, BG_BOTTOM = "#2b0709", "#170405", "#24060a"
GLOWS = (  # colour, alpha, centre (fx, fy), radius as fraction of farthest corner
    ((255, 40, 40), 0.36, (0.12, 0.18), 0.38),
    ((220, 30, 90), 0.30, (0.88, 0.08), 0.36),
    ((255, 120, 50), 0.18, (0.72, 0.92), 0.40),
    ((200, 20, 30), 0.24, (0.30, 0.85), 0.35),
)
TEXT_PRIMARY = "#ffffff"
TEXT_BODY = "#ffeeee"
TEXT_MUTED = "#e6b3b3"
TEXT_LABEL = "#ffd9d9"
TEXT_SUB = "#f2c2c2"
PLACEHOLDER = "#c69292"
ACCENT = "#ff4d4d"
ACCENT_OK = "#45f0c8"
FIELD_SOLID = "#300a0d"
FOCUS = "#ff8c8c"
TABLE_HEADING = "#4d181c"
TABLE_HEADING_ACTIVE = "#682026"
TABLE_ODD = "#3a0d11"
TABLE_HOVER = "#541419"
SELECT_BG = "#c8141c"
SCROLL_THUMB = "#7a2e34"

GLASS_BORDER = (255, 175, 175, 0.28)
GLASS_HIGHLIGHT = (255, 255, 255, 0.35)
PRIMARY_GLOSS = ((0.0, "#ff6a6a"), (0.49, "#e3161e"), (0.51, "#b80f17"), (1.0, "#d4141c"))
PRIMARY_BORDER = (255, 215, 215, 0.65)
SECONDARY_GLOSS = ((0.0, 0.28), (0.50, 0.10), (0.51, 0.04), (1.0, 0.12))
SECONDARY_BORDER = (255, 205, 205, 0.45)

SS = 3  # supersampling factor for anti-aliased shapes


# --------------------------------------------------------------------------- platform
def enable_dpi_awareness() -> None:
    """Render at real pixel size on 125-150% displays instead of being bitmap-stretched."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def register_fonts() -> bool:
    """Privately register the bundled TTFs for this process (Windows). Returns True if all loaded."""
    if sys.platform != "win32":
        return False
    ok = True
    for name in FONT_FILES.values():
        path = asset("fonts/" + name)
        try:
            ok &= bool(path.exists() and ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0))
        except (AttributeError, OSError):
            ok = False
    return ok


def work_area(root) -> tuple[int, int, int, int]:
    """Usable screen area (x, y, w, h) excluding the taskbar; falls back to the full screen."""
    if sys.platform == "win32":
        rect = (ctypes.c_long * 4)()
        try:
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def system_animations_enabled() -> bool:
    """Honour Windows 'Animation effects' (Settings > Accessibility > Visual effects)."""
    if sys.platform != "win32":
        return True
    value = ctypes.c_int(1)
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)  # SPI_GETCLIENTAREAANIMATION
    except (AttributeError, OSError):
        return True
    return bool(value.value)


SETTINGS_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clip & Save" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key: str, value) -> None:
    data = load_settings()
    data[key] = value
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- fonts
class Fonts:
    """Tk fonts in pixel sizes (scaled), using bundled families with Segoe UI fallback."""

    def __init__(self, root, scale: float) -> None:
        import tkinter.font as tkfont
        self._tkfont, self._root, self.scale = tkfont, root, scale
        families = set(tkfont.families(root))
        self.has_exo = "Exo 2" in families
        self.has_nunito = "Nunito Sans" in families
        self.has_exo_semi = "Exo 2 SemiBold" in families
        self.has_nunito_semi = "Nunito Sans SemiBold" in families
        self._cache: dict = {}

    def _font(self, family: str, px: float, weight: str):
        key = (family, round(px), weight)
        if key not in self._cache:
            self._cache[key] = self._tkfont.Font(root=self._root, family=family,
                                                 size=-max(6, round(px * self.scale)), weight=weight)
        return self._cache[key]

    def heading(self, px: float, weight: int = 600):
        if weight >= 700:
            return self._font("Exo 2" if self.has_exo else "Segoe UI", px, "bold")
        if self.has_exo_semi:
            return self._font("Exo 2 SemiBold", px, "normal")
        return self._font("Segoe UI Semibold", px, "normal")

    def body(self, px: float, weight: int = 400):
        if weight >= 700:
            return self._font("Nunito Sans" if self.has_nunito else "Segoe UI", px, "bold")
        if weight >= 600:
            return self._font("Nunito Sans SemiBold" if self.has_nunito_semi else "Segoe UI Semibold", px, "normal")
        return self._font("Nunito Sans" if self.has_nunito else "Segoe UI", px, "normal")


@lru_cache(maxsize=32)
def pil_font(family: str, weight: int, px: int):
    path = asset("fonts/" + FONT_FILES.get((family, weight), ""))
    try:
        return ImageFont.truetype(str(path), px)
    except OSError:
        try:
            return ImageFont.truetype("segoeuib.ttf" if weight >= 600 else "segoeui.ttf", px)
        except OSError:
            return ImageFont.load_default()


# --------------------------------------------------------------------------- colour helpers
def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgba(color, alpha: float = 1.0) -> tuple[int, int, int, int]:
    if isinstance(color, str):
        color = hex_rgb(color)
    return (*color[:3], round(255 * alpha))


def mix(c1: str, c2: str, t: float) -> str:
    a, b = hex_rgb(c1), hex_rgb(c2)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _stop_color(stops, t):
    """stops: list of (pos, rgba tuple). Linear interpolation."""
    if t <= stops[0][0]:
        return stops[0][1]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            return _lerp(c0, c1, 0 if p1 == p0 else (t - p0) / (p1 - p0))
    return stops[-1][1]


# --------------------------------------------------------------------------- primitives
def vgradient(w: int, h: int, stops) -> Image.Image:
    """Vertical RGBA gradient. stops: [(pos, (r,g,b,a)), ...]"""
    column = Image.new("RGBA", (1, max(1, h)))
    px = column.load()
    for y in range(h):
        px[0, y] = _stop_color(stops, y / max(1, h - 1))
    return column.resize((max(1, w), max(1, h)), Image.NEAREST)


def round_mask(w: int, h: int, r: float) -> Image.Image:
    """Anti-aliased rounded-rectangle mask."""
    big = Image.new("L", (max(1, w * SS), max(1, h * SS)), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=max(0, r * SS), fill=255)
    return big.resize((max(1, w), max(1, h)), Image.LANCZOS)


def outline_layer(w: int, h: int, r: float, color, width: float = 1.0, inset: float = 0.0) -> Image.Image:
    big = Image.new("RGBA", (max(1, w * SS), max(1, h * SS)), (0, 0, 0, 0))
    i = inset * SS
    ImageDraw.Draw(big).rounded_rectangle((i, i, w * SS - 1 - i, h * SS - 1 - i), radius=max(0, (r - inset) * SS),
                                          outline=color, width=max(1, round(width * SS)))
    return big.resize((max(1, w), max(1, h)), Image.LANCZOS)


def multiply_alpha(img: Image.Image, factor: float) -> Image.Image:
    img = img.copy()
    alpha = img.getchannel("A").point(lambda a: round(a * factor))
    img.putalpha(alpha)
    return img


def brighten(img: Image.Image, factor: float) -> Image.Image:
    alpha = img.getchannel("A")
    out = ImageEnhance.Brightness(img.convert("RGB")).enhance(factor).convert("RGBA")
    out.putalpha(alpha)
    return out


def soft_shadow(mask: Image.Image, color, sigma: float, offset=(0, 0), margin: int = 0) -> Image.Image:
    """Blurred coloured shadow of ``mask`` (L), returned at mask size + 2*margin. Blur runs at 1/4 size."""
    w, h = mask.size
    canvas = Image.new("L", (w + 2 * margin, h + 2 * margin), 0)
    canvas.paste(mask, (margin + round(offset[0]), margin + round(offset[1])))
    k = 4 if sigma >= 6 else 1
    small = canvas.resize((max(1, canvas.width // k), max(1, canvas.height // k)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(0.5, sigma / k)))
    blurred = small.resize(canvas.size, Image.BILINEAR)
    color = rgba(color[:3], color[3]) if len(color) == 4 and isinstance(color[3], float) else color
    layer = Image.new("RGBA", canvas.size, color[:3] + (0,))
    layer.putalpha(blurred.point(lambda a: round(a * color[3] / 255)))
    return layer


def _distance_image(size: int, cx: float, cy: float, radius: float) -> Image.Image:
    """L image where value ~= 180 * distance/radius (Pillow's radial_gradient scale)."""
    side = max(2, round(2 * radius * 1.0))
    grad = Image.radial_gradient("L").resize((side, side), Image.BILINEAR)
    # grad centre is at side/2; distance 'radius' maps to ~180.
    full = Image.new("L", (size, size), 255)
    full.paste(grad, (round(cx - side / 2), round(cy - side / 2)))
    return full


def radial_rgba(size: int, center=(0.5, 0.5), stops=None, radius: float | None = None,
                circle_clip: bool = True) -> Image.Image:
    """Radial gradient sprite. stops: [(pos 0..1 of radius, (r,g,b,a))]."""
    cx, cy = center[0] * size, center[1] * size
    if radius is None:  # CSS 'circle farthest-corner'
        radius = max(math.hypot(cx - x, cy - y) for x in (0, size) for y in (0, size))
    dist = _distance_image(size, cx, cy, radius)
    lut = [_stop_color(stops, min(1.0, v / 180.3)) for v in range(256)]
    channels = [dist.point([c[i] for c in lut]) for i in range(4)]
    img = Image.merge("RGBA", channels)
    if circle_clip:
        mask = Image.new("L", (size * SS, size * SS), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * SS - 1, size * SS - 1), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mask))
    return img


# --------------------------------------------------------------------------- background
def render_background(w: int, h: int) -> Image.Image:
    stops = [(0.0, rgba(BG_TOP)), (0.55, rgba(BG_MID)), (1.0, rgba(BG_BOTTOM))]
    # 160deg CSS gradient ~ mostly vertical with a slight horizontal lean.
    big = vgradient(1, 64, stops).resize((64, 64), Image.NEAREST)
    big = big.rotate(-20, resample=Image.BICUBIC, expand=False, fillcolor=rgba(BG_MID))
    img = vgradient(1, max(1, h), stops).resize((max(1, w), max(1, h)), Image.NEAREST)
    img = Image.blend(img, big.resize(img.size, Image.BILINEAR), 0.35)
    far = math.hypot(w, h)
    for color, alpha, (fx, fy), rad in GLOWS:
        r = rad * far
        cx, cy = fx * w, fy * h
        side = max(2, round(2 * r))
        grad = Image.radial_gradient("L").resize((side, side), Image.BILINEAR)
        mask_full = Image.new("L", (w, h), 255)
        mask_full.paste(grad, (round(cx - side / 2), round(cy - side / 2)))
        a255 = alpha * 255
        mask = mask_full.point(lambda v: round(max(0.0, 1 - v / 180.3) * a255))
        layer = Image.new("RGBA", (w, h), color + (0,))
        layer.putalpha(mask)
        img.alpha_composite(layer)
    return img


# --------------------------------------------------------------------------- glass panels
def render_glass(bg: Image.Image, rect, radius: float, scale: float, gloss: bool = False,
                 shadow: bool = True, pill: bool = False) -> tuple[Image.Image, int]:
    """Frosted glass panel for ``rect`` (x, y, w, h) over ``bg``. Returns (image, margin)."""
    x, y, w, h = (round(v) for v in rect)
    w, h = max(4, w), max(4, h)
    r = h / 2 if pill else radius
    m = round(42 * scale) if shadow else 0
    crop = bg.crop((x, y, x + w, y + h)).convert("RGB")
    k = 3  # blur at 1/3 size for speed (visually identical on smooth gradients)
    small = crop.resize((max(1, w // k), max(1, h // k)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(18 * scale / k))
    glass = ImageEnhance.Color(small.resize((w, h), Image.BILINEAR)).enhance(1.4).convert("RGBA")
    if gloss:
        ramp = [(0.0, (255, 255, 255, 46)), (0.48, (255, 255, 255, 15)),
                (0.52, (255, 255, 255, 5)), (1.0, (255, 255, 255, 13))]
    else:
        ramp = [(0.0, (255, 255, 255, 31)), (0.30, (255, 255, 255, 10)), (1.0, (255, 255, 255, 8))]
    glass.alpha_composite(vgradient(w, h, ramp))
    glass.alpha_composite(outline_layer(w, h, r, rgba(*_split(GLASS_BORDER)), 1 * scale))
    # 1px highlight just inside the top edge, fading out down the sides.
    hl = outline_layer(w, h, r, rgba(*_split(GLASS_HIGHLIGHT)), 1 * scale, inset=1 * scale)
    fade = vgradient(1, h, [(0.0, (0, 0, 0, 255)), (min(0.5, (r + 4) / h), (0, 0, 0, 0)), (1.0, (0, 0, 0, 0))])
    hl.putalpha(Image.composite(hl.getchannel("A"), Image.new("L", (w, h), 0),
                                fade.resize((w, h)).getchannel("A")))
    glass.alpha_composite(hl)
    mask = round_mask(w, h, r)
    glass.putalpha(mask)
    if not shadow:
        return glass, 0
    out = soft_shadow(mask, (0, 0, 0, 89), 18 * scale, (0, 14 * scale), m)
    out.alpha_composite(glass, (m, m))
    return out, m


def _split(token):
    return token[:3], token[3]


def render_inset(w: int, h: int, radius: float, scale: float, fill=(48, 10, 13, 255),
                 border=(255, 175, 175, 56), dashed: bool = False, inner_shadow: bool = True,
                 radial: bool = False) -> Image.Image:
    w, h = max(4, round(w)), max(4, round(h))
    img = Image.new("RGBA", (w, h), fill)
    if radial:  # cover box: soft cyan light at (50%, 40%)
        glow = radial_rgba(max(w, h), (0.5, 0.4), [(0.0, (255, 70, 70, 46)), (0.7, (30, 4, 6, 0)),
                                                    (1.0, (30, 4, 6, 0))], circle_clip=False)
        img.alpha_composite(glow.crop((0, 0, w, h)))
    if inner_shadow:
        img.alpha_composite(vgradient(w, round(10 * scale), [(0.0, (0, 0, 0, 115)), (1.0, (0, 0, 0, 0))]))
    if dashed:
        img.alpha_composite(_dashed_outline(w, h, radius, (255, 175, 175, 90), scale))
    else:
        img.alpha_composite(outline_layer(w, h, radius, border, 1 * scale))
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), round_mask(w, h, radius)))
    return img


def _dashed_outline(w, h, r, color, scale):
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    pts = []
    R = r * SS
    W, H = w * SS - 1, h * SS - 1
    for cx, cy, start in ((W - R, R, -90), (W - R, H - R, 0), (R, H - R, 90), (R, R, 180)):
        for i in range(13):
            a = math.radians(start + 90 * i / 12)
            pts.append((cx + R * math.cos(a), cy + R * math.sin(a)))
    pts.append(pts[0])
    dash, gap = 6 * scale * SS, 4 * scale * SS
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            if on:
                t0, t1 = pos / seg, (pos + step) / seg
                d.line((x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0, x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1),
                       fill=color, width=max(1, round(scale * SS)))
            pos += step
            left -= step
            if left <= 0:
                on, left = not on, (gap if on else dash)
    return big.resize((w, h), Image.LANCZOS)


def render_field(w: int, h: int, radius: float, scale: float) -> Image.Image:
    """Opaque inset entry field (solid fill so the real Entry blends in exactly)."""
    return render_inset(w, h, radius, scale, fill=rgba(FIELD_SOLID), border=rgba((255, 175, 175), 0.28),
                        inner_shadow=True)


# --------------------------------------------------------------------------- pills (buttons, toggles)
def _primary_body(w, h):
    return vgradient(w, h, [(p, rgba(c)) for p, c in PRIMARY_GLOSS])


def _secondary_body(w, h):
    return vgradient(w, h, [(p, (255, 255, 255, round(a * 255))) for p, a in SECONDARY_GLOSS])


def render_pill(w: int, h: int, kind: str, state: str, scale: float) -> tuple[Image.Image, int]:
    """Glossy pill button. kind: primary|secondary|badge. state: normal|hover|pressed|disabled."""
    w, h = max(8, round(w)), max(8, round(h))
    r = h / 2
    m = round(30 * scale)
    mask = round_mask(w, h, r)
    if kind == "primary":
        body = _primary_body(w, h)
        border, highlight = PRIMARY_BORDER, (255, 255, 255, 0.75)
        out = soft_shadow(mask, (230, 20, 30, 128), 12 * scale, (0, 8 * scale), m)
    elif kind == "badge":
        body = vgradient(w, h, [(0.0, (255, 255, 255, 51)), (1.0, (255, 255, 255, 10))])
        border, highlight = (255, 175, 175, 0.35), (255, 255, 255, 0.0)
        out = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    else:
        body = _secondary_body(w, h)
        border, highlight = SECONDARY_BORDER, (255, 255, 255, 0.6)
        out = soft_shadow(mask, (0, 0, 0, 77), 9 * scale, (0, 6 * scale), m) if kind == "secondary" \
            else Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    if state == "hover":
        body = brighten(body, 1.08) if kind == "primary" else multiply_alpha(body, 1.45)
    elif state == "pressed":
        body = brighten(body, 0.90) if kind == "primary" else multiply_alpha(body, 0.7)
    body.alpha_composite(outline_layer(w, h, r, rgba(*_split(border)), 1 * scale))
    if highlight[3]:
        hl = outline_layer(w, h, r, rgba(*_split(highlight)), 1 * scale, inset=1 * scale)
        fade = vgradient(w, h, [(0.0, (0, 0, 0, 255)), (0.35, (0, 0, 0, 0)), (1.0, (0, 0, 0, 0))])
        hl.putalpha(Image.composite(hl.getchannel("A"), Image.new("L", (w, h), 0), fade.getchannel("A")))
        body.alpha_composite(hl)
    body.putalpha(Image.composite(body.getchannel("A"), Image.new("L", (w, h), 0), mask))
    out.alpha_composite(body, (m, m))
    if state == "disabled":
        out = multiply_alpha(out, 0.45)
    return out, m


def render_toggle_track(w: int, h: int, on: bool, scale: float) -> tuple[Image.Image, int]:
    w, h = round(w), round(h)
    r = h / 2
    m = round(16 * scale)
    mask = round_mask(w, h, r)
    if on:
        out = soft_shadow(mask, (255, 30, 40, 128), 7 * scale, (0, 0), m)
        body = _primary_body(w, h)
        body.alpha_composite(outline_layer(w, h, r, (255, 215, 215, 153), 1 * scale))
        hl = outline_layer(w, h, r, (255, 255, 255, 153), 1 * scale, inset=1 * scale)
        fade = vgradient(w, h, [(0.0, (0, 0, 0, 255)), (0.4, (0, 0, 0, 0)), (1.0, (0, 0, 0, 0))])
        hl.putalpha(Image.composite(hl.getchannel("A"), Image.new("L", (w, h), 0), fade.getchannel("A")))
        body.alpha_composite(hl)
    else:
        out = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
        body = Image.new("RGBA", (w, h), (255, 255, 255, 26))
        body.alpha_composite(outline_layer(w, h, r, rgba(*_split(GLASS_BORDER)), 1 * scale))
    body.putalpha(Image.composite(body.getchannel("A"), Image.new("L", (w, h), 0), mask))
    out.alpha_composite(body, (m, m))
    return out, m


def render_knob(d: int, scale: float) -> tuple[Image.Image, int]:
    d = round(d)
    m = round(6 * scale)
    sphere = radial_rgba(d, (0.35, 0.30), [(0.0, rgba("#ffffff")), (0.5, rgba("#ffe9e9")), (1.0, rgba("#eeb2b2"))])
    out = soft_shadow(sphere.getchannel("A"), (0, 0, 0, 102), 3 * scale, (0, 2 * scale), m)
    out.alpha_composite(sphere, (m, m))
    return out, m


def render_sphere(d: int, inner: str, outer: str, glow, scale: float) -> tuple[Image.Image, int]:
    """Small glossy section marker sphere with a coloured glow."""
    d = round(d)
    m = round(8 * scale)
    sphere = radial_rgba(d, (0.35, 0.30), [(0.0, rgba("#ffffff")), (0.4, rgba(inner)), (1.0, rgba(outer))])
    out = soft_shadow(sphere.getchannel("A"), glow, 5 * scale, (0, 0), m)
    out.alpha_composite(sphere, (m, m))
    return out, m


def render_ring(d: int, scale: float) -> tuple[Image.Image, int]:
    """Header accent ring: 3px stroke, glowing, with a solid centre dot."""
    d = round(d)
    m = round(14 * scale)
    big = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    sw = round(3 * scale * SS)
    dr.ellipse((sw / 2, sw / 2, d * SS - sw / 2, d * SS - sw / 2), outline=rgba(ACCENT), width=sw)
    dot = 12 * scale * SS
    c = d * SS / 2
    dr.ellipse((c - dot / 2, c - dot / 2, c + dot / 2, c + dot / 2), fill=rgba(ACCENT))
    ring = big.resize((d, d), Image.LANCZOS)
    out = soft_shadow(ring.getchannel("A"), (255, 70, 70, 153), 8 * scale, (0, 0), m)
    out.alpha_composite(ring, (m, m))
    return out, m


def render_dot(d: int, color: str, scale: float, glow: bool = True) -> tuple[Image.Image, int]:
    d = round(d)
    m = round(6 * scale) if glow else 0
    big = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, d * SS - 1, d * SS - 1), fill=rgba(color))
    dot = big.resize((d, d), Image.LANCZOS)
    if not glow:
        return dot, 0
    out = soft_shadow(dot.getchannel("A"), rgba(color, 0.9), 4 * scale, (0, 0), m)
    out.alpha_composite(dot, (m, m))
    return out, m


def render_disc(d: int, scale: float) -> tuple[Image.Image, int]:
    """Rainbow CD placeholder: conic gradient, dark hole with a pale ring, soft shadow."""
    d = round(d)
    m = round(20 * scale)
    colors = [hex_rgb(c) for c in ("#c9f2ff", "#8fb6ff", "#e2c8ff", "#9ff5e4", "#c9f2ff")]
    n = d * SS
    big = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    steps = 180
    for i in range(steps):
        t = i / steps
        k = min(3, int(t * 4))
        col = _lerp(colors[k], colors[k + 1], t * 4 - k)
        a0 = -90 + 30 + 360 * t  # conic 'from 30deg'
        dr.pieslice((0, 0, n - 1, n - 1), a0, a0 + 360 / steps + 0.6, fill=col + (255,))
    c = n / 2
    ring_r = n * 19 / 96  # proportions of the 96px reference disc: 26px hole + 6px pale ring
    dr.ellipse((c - ring_r, c - ring_r, c + ring_r, c + ring_r), fill=(255, 255, 255, 140))
    hole = n * 13 / 96
    dr.ellipse((c - hole, c - hole, c + hole, c + hole), fill=rgba("#0a1f35"))
    dr.ellipse((1, 1, n - 2, n - 2), outline=(255, 255, 255, 153), width=max(1, round(scale * SS)))
    disc = big.resize((d, d), Image.LANCZOS)
    out = soft_shadow(disc.getchannel("A"), (0, 0, 0, 102), 10 * scale, (0, 8 * scale), m)
    out.alpha_composite(disc, (m, m))
    return out, m


def _note_icon(size: int, color, stroke: float) -> Image.Image:
    """Feather-style music note (two heads)."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = n / 24
    w = max(1, round(stroke * SS))
    d.line([(9 * s, 18 * s), (9 * s, 5 * s), (21 * s, 3 * s), (21 * s, 16 * s)], fill=color, width=w, joint="curve")
    for cx, cy in ((6, 18), (18, 16)):
        d.ellipse(((cx - 3) * s, (cy - 3) * s, (cx + 3) * s, (cy + 3) * s), outline=color, width=w)
    return img.resize((size, size), Image.LANCZOS)


def render_empty_bubble(d: int, scale: float) -> tuple[Image.Image, int]:
    d = round(d)
    m = round(24 * scale)
    sphere = radial_rgba(d, (0.35, 0.28), [(0.0, (255, 255, 255, 140)), (0.35, (255, 120, 120, 64)),
                                           (1.0, (140, 15, 20, 64))])
    sphere.alpha_composite(outline_layer(d, d, d / 2, (255, 200, 200, 115), 1 * scale))
    inner = vgradient(d, d, [(0.0, (0, 0, 0, 0)), (0.75, (0, 0, 0, 0)), (1.0, (120, 10, 15, 102))])
    inner.putalpha(Image.composite(inner.getchannel("A"), Image.new("L", (d, d), 0), sphere.getchannel("A")))
    sphere.alpha_composite(inner)
    icon = _play_icon(round(40 * scale), rgba("#fff0f0"), 1.6 * scale * 40 / 24)
    sphere.alpha_composite(icon, ((d - icon.width) // 2, (d - icon.height) // 2))
    out = soft_shadow(sphere.getchannel("A"), (240, 30, 40, 89), 15 * scale, (0, 10 * scale), m)
    out.alpha_composite(sphere, (m, m))
    return out, m


def render_folder_icon(size: int, scale: float) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = n / 24
    w = max(1, round(1.8 * scale * SS * size / 20 / 1.2))
    pts = [(3, 7), (3, 17), (5, 19), (19, 19), (21, 17), (21, 9), (19, 7), (11, 7), (9, 5), (5, 5), (3, 7)]
    d.line([(x * s, y * s) for x, y in pts], fill=rgba("#ff8c8c"), width=w, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def render_shield_icon(size: int, scale: float) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = n / 24
    pts = [(12, 3), (20, 6), (20, 12), (18, 17), (12, 21), (6, 17), (4, 12), (4, 6), (12, 3)]
    d.line([(x * s, y * s) for x, y in pts], fill=rgba(ACCENT_OK), width=max(1, round(2 * scale * SS * size / 16 / 1.5)),
           joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def render_logo(w: int, h: int, scale: float) -> tuple[Image.Image, int]:
    """Procedural Clip & Save logo with a soft red drop shadow."""
    m = round(22 * scale)
    d = round(min(w, h))
    logo = Image.new("RGBA", (round(w), round(h)), (0, 0, 0, 0))
    mark = render_logo_mark(d)
    logo.alpha_composite(mark, ((logo.width - d) // 2, (logo.height - d) // 2))
    out = soft_shadow(logo.getchannel("A"), (255, 30, 40, 110), 8 * scale, (0, 6 * scale), m)
    out.alpha_composite(logo, (m, m))
    return out, m


def render_text_glow(text: str, px: int, scale: float) -> tuple[Image.Image, int]:
    """Soft cyan glow behind the app title (the crisp text itself is a Tk text item)."""
    font = pil_font("Exo 2", 700, round(px))
    m = round(20 * scale)
    bbox = font.getbbox(text)
    w, h = bbox[2] + 2 * m, bbox[3] + 2 * m
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((m, m), text, font=font, fill=255)
    small = mask.resize((max(1, w // 3), max(1, h // 3)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3 * scale))
    glow = Image.new("RGBA", (w, h), (255, 70, 70, 0))
    glow.putalpha(small.resize((w, h), Image.BILINEAR).point(lambda a: round(min(255, a * 1.6) * 0.55)))
    return glow, m


# --------------------------------------------------------------------------- animated sprites
def render_bubble_sprite(size: int, tint=(255, 150, 150), deep=(190, 20, 30), hi_alpha=0.75,
                         tint_alpha=0.28, deep_alpha=0.10, rim=True) -> Image.Image:
    size = max(4, round(size))
    img = radial_rgba(size, (0.32, 0.28), [
        (0.0, (255, 255, 255, round(255 * hi_alpha))),
        (0.28, tint + (round(255 * tint_alpha),)),
        (0.70, deep + (round(255 * deep_alpha),)),
        (1.0, deep + (0,)),
    ])
    if rim:
        img.alpha_composite(outline_layer(size, size, size / 2, (255, 200, 200, 64), 1))
    return img


def render_glow_sprite(size: int, color, alpha: float, blur: float) -> tuple[Image.Image, int]:
    size = max(4, round(size))
    m = round(blur * 2)
    img = Image.new("RGBA", (size + 2 * m, size + 2 * m), (0, 0, 0, 0))
    core = radial_rgba(size, (0.5, 0.5), [(0.0, color + (round(255 * alpha),)), (0.7, color + (0,)),
                                          (1.0, color + (0,))], radius=size / 2)
    img.alpha_composite(core, (m, m))
    small = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(blur / 2)).resize(img.size, Image.BILINEAR), m


# --------------------------------------------------------------------------- Clip & Save extras
def _play_icon(size: int, color, stroke: float) -> Image.Image:
    """Rounded play triangle outline (Feather-style), used in the empty-state bubble."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = n / 24
    w = max(1, round(stroke * SS))
    pts = [(8 * s, 5 * s), (19 * s, 12 * s), (8 * s, 19 * s), (8 * s, 5 * s)]
    d.line(pts, fill=color, width=w, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def render_logo_mark(d: int) -> Image.Image:
    """Glossy red sphere with a white play triangle and a small download badge."""
    d = max(8, round(d))
    sphere = radial_rgba(d, (0.35, 0.28), [(0.0, rgba("#ff9a9a")), (0.45, rgba("#e3161e")), (1.0, rgba("#7a070c"))])
    n = d * SS
    over = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    dr = ImageDraw.Draw(over)
    # gloss highlight across the top half
    gl = Image.new("L", (n, n), 0)
    ImageDraw.Draw(gl).ellipse((n * 0.16, n * 0.05, n * 0.84, n * 0.50), fill=70)
    over.paste((255, 255, 255, 255), (0, 0), gl)
    # play triangle (slightly right of centre for optical balance)
    c = n / 2
    tri = [(c - n * 0.13, c - n * 0.20), (c + n * 0.22, c), (c - n * 0.13, c + n * 0.20)]
    dr.polygon(tri, fill=(255, 255, 255, 255))
    # download badge, bottom-right
    br = n * 0.17
    bx, by = n * 0.78, n * 0.78
    dr.ellipse((bx - br, by - br, bx + br, by + br), fill=(255, 255, 255, 255))
    aw = max(1, round(n * 0.035))
    dr.line((bx, by - br * 0.55, bx, by + br * 0.35), fill=rgba("#c8141c"), width=aw)
    dr.line((bx - br * 0.42, by - br * 0.02, bx, by + br * 0.42, bx + br * 0.42, by - br * 0.02),
            fill=rgba("#c8141c"), width=aw, joint="curve")
    over = over.resize((d, d), Image.LANCZOS)
    # keep the badge visible even where it hangs over the sphere edge
    canvas = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    canvas.alpha_composite(sphere)
    canvas.alpha_composite(over)
    return canvas


def render_link_icon(size: int, scale: float) -> Image.Image:
    """Two chain links (Feather 'link')."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = n / 24
    w = max(1, round(1.9 * scale * SS * size / 20 / 1.2))
    col = rgba("#ff8c8c")
    for cx, cy in ((9.0, 15.0), (15.0, 9.0)):
        box = [(-4.2, -2.6), (4.2, 2.6)]
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(((cx + box[0][0]) * s, (cy + box[0][1]) * s,
                                                 (cx + box[1][0]) * s, (cy + box[1][1]) * s),
                                                radius=2.6 * s, outline=col, width=w)
        img.alpha_composite(layer.rotate(45, center=(cx * s, cy * s), resample=Image.BICUBIC))
    return img.resize((size, size), Image.LANCZOS)


def render_video_placeholder(w: int, h: int, scale: float) -> tuple[Image.Image, int]:
    """Empty 16:9 screen: dark glass with a glossy play bubble in the middle."""
    w, h = max(8, round(w)), max(8, round(h))
    img = render_inset(w, h, 16 * scale, scale, fill=(30, 4, 6, 255), radial=True)
    d = round(min(w, h) * 0.34)
    bubble, m = render_empty_bubble(d, scale)
    big = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    big.alpha_composite(img, (m, m))
    big.alpha_composite(bubble, ((w - d) // 2, (h - d) // 2))
    img = big.crop((m, m, m + w, m + h))
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), round_mask(w, h, 16 * scale)))
    return img, 0


def render_thumb(src: Image.Image, w: int, h: int, scale: float) -> tuple[Image.Image, int]:
    """Video thumbnail cover-fitted to w x h with rounded corners, a thin rim and a soft shadow."""
    w, h = max(8, round(w)), max(8, round(h))
    src = src.convert("RGBA")
    k = max(w / src.width, h / src.height)
    img = src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    r = 16 * scale
    img.alpha_composite(outline_layer(w, h, r, (255, 200, 200, 90), 1 * scale))
    img.putalpha(round_mask(w, h, r))
    m = round(26 * scale)
    out = soft_shadow(img.getchannel("A"), (0, 0, 0, 120), 14 * scale, (0, 10 * scale), m)
    out.alpha_composite(img, (m, m))
    return out, m


def render_progress(w: int, h: int, frac: float, scale: float) -> tuple[Image.Image, int]:
    """Glass track with a glossy red fill of ``frac`` (0..1)."""
    w, h = max(8, round(w)), max(6, round(h))
    m = round(10 * scale)
    out = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    track = render_inset(w, h, h / 2, scale, fill=(40, 8, 11, 255), inner_shadow=True)
    out.alpha_composite(track, (m, m))
    fw = round(w * max(0.0, min(1.0, frac)))
    if fw >= 2:
        fw = max(fw, h)
        mask = round_mask(fw, h, h / 2)
        fill = _primary_body(fw, h)
        hl = vgradient(fw, h, [(0.0, (255, 255, 255, 90)), (0.45, (255, 255, 255, 10)), (1.0, (255, 255, 255, 0))])
        fill.alpha_composite(hl)
        fill.putalpha(mask)
        glow = soft_shadow(mask, (255, 40, 40, 140), 5 * scale, (0, 0), m)
        out.alpha_composite(glow, (0, 0))
        out.alpha_composite(fill, (m, m))
    return out, m
