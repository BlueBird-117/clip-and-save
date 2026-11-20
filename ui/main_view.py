"""Ruby Night main window for Clip & Save: one full-window canvas plus a few real input widgets.

Same construction as Track & Cover's Aqua Night view (glass panels, glossy pills, drifting
bubbles), re-tinted red. The app talks to it through:
  url_entry, table, set_video(), set_thumbnail(), set_progress(), the GlossyButtons
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from . import theme as T
from .aero_widgets import (AeroTreeview, BubbleBackground, EmptyState, FocusManager, GlossyButton, ImageCache,
                           Placeholder, Toggle, truncate)

SUBTITLE = "Paste a YouTube link, choose the quality, and save the video or its audio to your PC."
RED_SPHERE = ("#ff5a5a", "#a80d14", (255, 60, 60, 204))
AMBER_SPHERE = ("#ffb35a", "#b8560d", (255, 160, 60, 204))


def _rr_points(x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    pts = []
    for cx, cy, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(9):
            a = math.radians(start + 90 * i / 8)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return pts


class RubyNightView:
    def __init__(self, root: tk.Tk, *, app_name: str, version: str, url: tk.StringVar, folder: tk.StringVar,
                 status: tk.StringVar, open_when_done: tk.BooleanVar, on_paste, on_fetch, on_change_folder,
                 on_download, on_cancel, on_open_folder, on_option_selected) -> None:
        self.root, self.app_name, self.version, self.status = root, app_name, version, status
        self.S = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.f = 1.0
        self.fonts = T.Fonts(root, self.S)
        self.cache = ImageCache()
        self._hits: list = []
        self._hovered = None
        self._pressed = None
        self._render_job = None
        self._bg_key = None
        self._option_count = 0
        self._video_title = ""
        self._video_meta = ""
        self._thumb_src = None
        self._thumb_key = 0
        self._progress = (None, "", "")  # frac, left text, right text
        self._busy = False
        settings = T.load_settings()
        self.animate = tk.BooleanVar(value=bool(settings.get("animate_background", T.system_animations_enabled())))
        self.animate.trace_add("write", lambda *_a: T.save_setting("animate_background", self.animate.get()))

        S = self.S
        root.configure(bg=T.BG_MID)
        try:
            root.iconbitmap(default=str(T.asset("app.ico")))
        except tk.TclError:
            pass
        ax, ay, aw, ah = T.work_area(root)
        title_bar = round(32 * S)
        w = min(round(1240 * S), int(aw * 0.94))
        h = min(round(860 * S), ah - title_bar - round(16 * S))
        x = ax + max(0, (aw - w) // 2)
        y = ay + max(0, (ah - h - title_bar) // 2)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(round(960 * S), round(640 * S))

        c = self.canvas = tk.Canvas(root, bg=T.BG_MID, highlightthickness=0, bd=0, takefocus=0)
        c.pack(fill="both", expand=True)
        c.bind("<Configure>", lambda _e: self.schedule_render())
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda _e: self._set_hover(None))
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<ButtonRelease-1>", self._on_release)

        self._style()

        # ---- real widgets -----------------------------------------------------
        body = self.fonts.body
        self.url_entry = self._entry(url)
        self.folder_entry = self._entry(folder)
        self.folder_entry.configure(state="readonly", readonlybackground=T.FIELD_SOLID, takefocus=0)
        self._placeholders = [Placeholder(self.url_entry, url, "Paste a YouTube link here…", body(15))]
        self.url_entry.bind("<Return>", lambda _e: on_fetch())

        cols = ("quality", "format", "size")
        self.table = AeroTreeview(c, on_rows_changed=self._rows_changed, columns=cols, show="headings",
                                  selectmode="browse", style="Ruby.Treeview")
        for col, title in zip(cols, ("QUALITY", "FORMAT", "SIZE (APPROX.)")):
            anchor = "e" if col == "size" else "w"
            self.table.heading(col, text=title, anchor=anchor)
            self.table.column(col, width=100, minwidth=60, stretch=col != "size", anchor=anchor)
        self.table.tag_configure("odd", background=T.TABLE_ODD)
        self.table.tag_configure("hover", background=T.TABLE_HOVER)
        self.table.bind("<<TreeviewSelect>>", on_option_selected, add="+")
        self.table.bind("<Double-1>", lambda e: self.table.identify_row(e.y) and on_download(), add="+")
        self.table.bind("<Return>", lambda _e: on_download(), add="+")
        self.table.bind("<Configure>", self._fit_columns, add="+")
        self.table_scroll = ttk.Scrollbar(c, orient="vertical", command=self.table.yview,
                                          style="Ruby.Vertical.TScrollbar")
        self.table.configure(yscrollcommand=self.table_scroll.set)
        self.table_empty = EmptyState(self, self.table, "No video loaded yet",
                                      "Paste a link above and press Fetch video. "
                                      "Every available quality will list here.", icon=True)

        self._windows = {}
        for name, widget in (("url", self.url_entry), ("folder", self.folder_entry), ("table", self.table),
                             ("scroll", self.table_scroll)):
            self._windows[name] = c.create_window(0, 0, window=widget, anchor="nw", tags=("win",))

        # ---- canvas-drawn controls -----------------------------------------------
        self.paste_button = GlossyButton(self, "Paste", on_paste, "secondary")
        self.fetch_button = GlossyButton(self, "Fetch video", on_fetch, "primary")
        self.folder_button = GlossyButton(self, "Change…", on_change_folder, "secondary")
        self.open_button = GlossyButton(self, "Open folder", on_open_folder, "secondary")
        self.cancel_button = GlossyButton(self, "Cancel", on_cancel, "secondary", state="disabled")
        self.download_button = GlossyButton(self, "Download", on_download, "primary", state="disabled")
        self.toggles = [Toggle(self, "Open the folder when a download finishes", open_when_done),
                        Toggle(self, "Animate background", self.animate)]

        self.focus = FocusManager(self)
        self.focus.order = [self.url_entry, self.paste_button, self.fetch_button, self.table, self.folder_button,
                            self.download_button, self.cancel_button, self.open_button, *self.toggles]

        self.bubbles = BubbleBackground(self, self.animate)
        self.bubbles.status_pulse = self._status_pulse
        status.trace_add("write", lambda *_a: self._draw_status_text())
        self.schedule_render(0)

    # ================================================================== public API
    def set_video(self, title: str, meta: str) -> None:
        self._video_title, self._video_meta = title, meta
        self._draw_video_text()

    def set_thumbnail(self, image) -> None:
        """PIL image or None (placeholder)."""
        self._thumb_src = image
        self._thumb_key += 1
        self._draw_thumb()

    def set_progress(self, frac, left: str = "", right: str = "") -> None:
        self._progress = (frac, left, right)
        self._draw_progress()

    def set_busy(self, busy: bool) -> None:
        """Pulse the status dot faster while working."""
        self._busy = busy

    # ================================================================== helpers
    def lerp(self, a: float, b: float) -> float:
        return a + (b - a) * self.f

    def register_hit(self, obj) -> None:
        self._hits.append(obj)

    def _entry(self, var: tk.StringVar) -> tk.Entry:
        return tk.Entry(self.canvas, textvariable=var, relief="flat", bd=0, highlightthickness=0,
                        bg=T.FIELD_SOLID, fg=T.TEXT_BODY, insertbackground=T.ACCENT, insertwidth=max(1, round(self.S)),
                        selectbackground=T.SELECT_BG, selectforeground="#ffffff", disabledbackground=T.FIELD_SOLID,
                        readonlybackground=T.FIELD_SOLID, font=self.fonts.body(15))

    def _style(self) -> None:
        S, body = self.S, self.fonts.body
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Ruby.Treeview", background=T.FIELD_SOLID, fieldbackground=T.FIELD_SOLID,
                        foreground=T.TEXT_BODY, rowheight=round(34 * S), font=body(14), borderwidth=0, relief="flat")
        style.layout("Ruby.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.map("Ruby.Treeview", background=[("selected", T.SELECT_BG)], foreground=[("selected", "#ffffff")])
        style.configure("Ruby.Treeview.Heading", background=T.TABLE_HEADING, foreground=T.TEXT_LABEL,
                        font=body(13, 700), relief="flat", borderwidth=0, padding=(round(14 * S), round(9 * S)))
        style.map("Ruby.Treeview.Heading", background=[("active", T.TABLE_HEADING_ACTIVE)])
        style.layout("Ruby.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Ruby.Vertical.TScrollbar", troughcolor=T.FIELD_SOLID, background=T.SCROLL_THUMB,
                        bordercolor=T.FIELD_SOLID, lightcolor=T.SCROLL_THUMB, darkcolor=T.SCROLL_THUMB,
                        gripcount=0, arrowsize=round(8 * S), relief="flat")
        style.map("Ruby.Vertical.TScrollbar", background=[("active", "#a3434a")])

    def focus_ring(self, tag, x, y, w, h, r) -> None:
        self.canvas.create_polygon(_rr_points(x, y, w, h, r), fill="", outline=T.FOCUS,
                                   width=max(2, round(2 * self.S)), tags=(tag, "chrome"))

    def _photo(self, key, factory):
        return self.cache.get(key, factory)

    def _rows_changed(self, n: int) -> None:
        self._option_count = n
        self.table_empty.set_visible(n == 0)
        self.canvas.itemconfigure("optcount", text=f"{n} option{'s' if n != 1 else ''}" if n else "")

    def _fit_columns(self, event) -> None:
        S = self.S
        size = round(140 * S)
        spare = max(2 * 60, event.width - size)
        self.table.column("quality", width=int(spare * 0.46))
        self.table.column("format", width=int(spare * 0.54))
        self.table.column("size", width=size)

    # ================================================================== pointer
    def _hit(self, x, y):
        for obj in reversed(self._hits):
            r = obj.hit_rect()
            if r and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]:
                return obj
        return None

    def _set_hover(self, obj) -> None:
        if obj is self._hovered:
            return
        if self._hovered is not None:
            self._hovered.on_leave()
        self._hovered = obj
        if obj is not None:
            obj.on_enter()

    def _on_motion(self, e) -> None:
        obj = self._hit(e.x, e.y)
        self._set_hover(obj)
        cursor = obj.cursor() if obj else ""
        if self.canvas.cget("cursor") != cursor:
            self.canvas.configure(cursor=cursor)

    def _on_press(self, e) -> None:
        obj = self._hit(e.x, e.y)
        self._pressed = obj
        if obj is not None:
            obj.on_press()
        else:
            self.canvas.focus_set()

    def _on_release(self, e) -> None:
        obj, self._pressed = self._pressed, None
        if obj is not None:
            obj.on_release(self._hit(e.x, e.y) is obj)

    # ================================================================== layout
    def schedule_render(self, delay: int = 150) -> None:
        if self._render_job is not None:
            self.canvas.after_cancel(self._render_job)
        self._render_job = self.canvas.after(delay, self.render)

    def _layout(self, W: int, H: int) -> dict:
        S = self.S
        self.f = max(0.0, min(1.0, (H / S - 640) / (860 - 640)))
        lp = self.lerp
        P, G = lp(16, 28) * S, lp(12, 20) * S
        L = {"P": P, "G": G}
        L["header"] = (P, P, W - 2 * P, lp(78, 118) * S)
        hy = P + L["header"][3] + G
        row_h = lp(42, 52) * S
        L["row"] = (P, hy, W - 2 * P, row_h)
        status_h = lp(40, 50) * S
        L["status"] = (P, H - P - status_h, W - 2 * P, status_h)
        opt_h = 30 * S
        oy = L["status"][1] - lp(10, 16) * S - opt_h
        L["options"] = (P, oy, W - 2 * P, opt_h)
        top = hy + row_h + G
        bottom = oy - lp(10, 16) * S
        avail_w = W - 2 * P - G
        lw = avail_w * 0.45
        L["left"] = (P, top, lw, bottom - top)
        L["right"] = (P + lw + G, top, avail_w - lw, bottom - top)
        return L

    # ================================================================== render
    def render(self) -> None:
        self._render_job = None
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        S = self.S
        L = self.L = self._layout(W, H)
        lp = self.lerp
        body, heading = self.fonts.body, self.fonts.heading

        if self._bg_key != (W, H):
            self._bg_img = T.render_background(W, H)
            self._bg_photo = ImageTk.PhotoImage(self._bg_img)
            self._bg_key = (W, H)
            self._glass_cache = {}
        c.delete("bg", "panel", "chrome", "static")
        c.create_image(0, 0, image=self._bg_photo, anchor="nw", tags=("bg",))
        c.tag_lower("bg")

        def glass(name, rect, gloss=False, pill=False, radius=26):
            key = (name, tuple(round(v) for v in rect), gloss, pill)
            if key not in self._glass_cache:
                img, m = T.render_glass(self._bg_img, rect, radius * S, S, gloss=gloss, pill=pill)
                self._glass_cache[key] = (ImageTk.PhotoImage(img), m)
            photo, m = self._glass_cache[key]
            c.create_image(rect[0] - m, rect[1] - m, image=photo, anchor="nw", tags=("panel",))

        def inset(rect, radius, **kw):
            x, y, w, h = (round(v) for v in rect)
            photo, _ = self._photo(("inset", w, h, radius, tuple(sorted(kw.items())), S),
                                   lambda: (T.render_inset(w, h, radius * S, S, **kw), 0))
            c.create_image(x, y, image=photo, anchor="nw", tags=("static",))

        def field(rect, radius):
            x, y, w, h = (round(v) for v in rect)
            photo, _ = self._photo(("field", w, h, round(radius), S), lambda: (T.render_field(w, h, radius, S), 0))
            c.create_image(x, y, image=photo, anchor="nw", tags=("static",))

        def icon(key, factory, x, y, anchor="nw"):
            photo, m = self._photo(key, factory)
            c.create_image(x - m, y - m, image=photo, anchor=anchor, tags=("static",))

        def place(name, x, y, w, h):
            c.coords(self._windows[name], round(x), round(y))
            c.itemconfigure(self._windows[name], width=max(1, round(w)), height=max(1, round(h)))

        glass("header", L["header"], gloss=True)
        glass("left", L["left"])
        glass("right", L["right"])
        glass("status", L["status"], gloss=True, pill=True)

        # ---- header -------------------------------------------------------------
        hx, hy, hw, hh = L["header"]
        logo_h = round(lp(54, 84) * S)
        lx = hx + lp(16, 24) * S
        icon(("logo", logo_h, S), lambda: T.render_logo(logo_h, logo_h, S), lx, hy + (hh - logo_h) / 2)
        title_px = lp(24, 34)
        tf, sf = heading(title_px, 700), body(lp(13, 15))
        tx = lx + logo_h + lp(14, 20) * S
        block = tf.metrics("linespace") + 4 * S + sf.metrics("linespace")
        ty = hy + (hh - block) / 2
        glow_px = round(title_px * S)
        icon(("titleglow", glow_px, S), lambda: T.render_text_glow(self.app_name, glow_px, S), tx, ty)
        c.create_text(tx, ty, text=self.app_name, font=tf, fill=T.TEXT_PRIMARY, anchor="nw", tags=("chrome",))
        badge_f = body(13, 700)
        badge = f"v{self.version}"
        bw = round(badge_f.measure(badge) + 46 * S)
        bh = round(30 * S)
        bx = hx + hw - lp(16, 24) * S - bw
        by = hy + (hh - bh) / 2
        ring = round(34 * S)
        rx = bx - 14 * S - ring
        c.create_text(tx + 1, ty + tf.metrics("linespace") + 4 * S, text=truncate(sf, SUBTITLE, rx - 20 * S - tx),
                      font=sf, fill=T.TEXT_SUB, anchor="nw", tags=("chrome",))
        icon(("ring", ring, S), lambda: T.render_ring(ring, S), rx, hy + (hh - ring) / 2)
        icon(("badge", bw, bh, S), lambda: T.render_pill(bw, bh, "badge", "normal", S), bx, by)
        dot = round(8 * S)
        icon(("okdot", dot, S), lambda: T.render_dot(dot, T.ACCENT_OK, S), bx + 14 * S, by + (bh - dot) / 2)
        c.create_text(bx + 14 * S + dot + 8 * S, by + bh / 2, text=badge, font=badge_f, fill=T.TEXT_BODY,
                      anchor="w", tags=("chrome",))

        # ---- link row -------------------------------------------------------------
        rx0, ry, rw, rh = L["row"]
        bgap = 12 * S
        fetch_w = self.fetch_button.natural_width(rh)
        paste_w = self.paste_button.natural_width(rh)
        self.fetch_button.place(rx0 + rw - fetch_w, ry, fetch_w, rh)
        self.paste_button.place(rx0 + rw - fetch_w - bgap - paste_w, ry, paste_w, rh)
        fw = rw - fetch_w - paste_w - 2 * bgap
        field((rx0, ry, fw, rh), rh / 2)
        isz = round(20 * S)
        icon(("link", isz, S), lambda: (T.render_link_icon(isz, S), 0), rx0 + 18 * S, ry + (rh - isz) / 2)
        eh = body(15).metrics("linespace") + 4
        place("url", rx0 + 18 * S + isz + 10 * S, ry + (rh - eh) / 2, fw - 18 * S - isz - 10 * S - 18 * S, eh)

        # ---- left panel: video preview ----------------------------------------------
        pp, ig = lp(14, 22) * S, lp(9, 16) * S
        hrow = lp(22, 26) * S
        x, y, w, h = L["left"]
        self._section(x + pp, y + pp, "Video", RED_SPHERE)
        tw = w - 2 * pp
        title_f, meta_f = heading(lp(16, 19), 600), body(lp(13, 14))
        text_h = 2 * title_f.metrics("linespace") + 6 * S + meta_f.metrics("linespace")
        room = h - 2 * pp - hrow - ig - ig - text_h
        th = min(tw * 9 / 16, room)
        tw_ = th * 16 / 9
        self._thumb_rect = (x + pp + (tw - tw_) / 2, y + pp + hrow + ig, tw_, th)
        self._text_rect = (x + pp, self._thumb_rect[1] + th + ig, tw, text_h)
        self._draw_thumb()
        self._draw_video_text()

        # ---- right panel: qualities, folder, progress, actions --------------------------
        x, y, w, h = L["right"]
        ix, iw = x + pp, w - 2 * pp
        self._section(ix, y + pp, "Choose quality", AMBER_SPHERE)
        c.create_text(x + w - pp, y + pp + hrow / 2, text=f"{self._option_count} options" if self._option_count else "",
                      font=body(13), fill=T.TEXT_MUTED, anchor="e", tags=("chrome", "optcount"))
        bottom = y + h - pp
        btn_h = lp(40, 46) * S
        lab_f = body(13, 700)
        field_h = lp(38, 44) * S
        prog_h = round(14 * S)
        ptext_h = body(lp(13, 14)).metrics("linespace")
        rg = lp(10, 16) * S
        # bottom-up: actions, progress text, progress bar, folder field, folder label
        actions_y = bottom - btn_h
        ptext_y = actions_y - rg - ptext_h
        pbar_y = ptext_y - 6 * S - prog_h
        fy = pbar_y - rg - field_h
        flab_y = fy - 6 * S - lab_f.metrics("linespace")
        k = 6 * S
        sbw = round(10 * S)
        heading_h = body(13, 700).metrics("linespace") + round(18 * S) + 2
        row_px = round(34 * S)
        box_top = y + pp + hrow + ig
        box_room = flab_y - rg - box_top
        rows = max(1, int((box_room - 2 * k - heading_h) // row_px))  # whole rows only, no half-cut last row
        box = (ix, box_top, iw, min(box_room, rows * row_px + heading_h + 2 * k + 2))
        inset(box, 18)
        place("table", box[0] + k, box[1] + k, box[2] - 2 * k - sbw - 2 * S, box[3] - 2 * k)
        place("scroll", box[0] + box[2] - k - sbw, box[1] + k, sbw, box[3] - 2 * k)

        c.create_text(ix + 2, flab_y, text="Save to", font=lab_f, fill=T.TEXT_LABEL, anchor="nw", tags=("chrome",))
        ch_w = self.folder_button.natural_width(field_h)
        self.folder_button.place(ix + iw - ch_w, fy, ch_w, field_h)
        ffw = iw - ch_w - 12 * S
        field((ix, fy, ffw, field_h), field_h / 2)
        fisz = round(18 * S)
        icon(("folder", fisz, S), lambda: (T.render_folder_icon(fisz, S), 0), ix + 16 * S, fy + (field_h - fisz) / 2)
        place("folder", ix + 16 * S + fisz + 10 * S, fy + (field_h - eh) / 2, ffw - 16 * S - fisz - 10 * S - 16 * S, eh)

        self._prog_rect = (ix, pbar_y, iw, prog_h, ptext_y)
        self._draw_progress()

        dl_w = self.download_button.natural_width(btn_h) + round(20 * S)
        cx_ = ix + iw - dl_w
        self.download_button.place(cx_, actions_y, dl_w, btn_h)
        for b in (self.cancel_button, self.open_button):
            bw_ = b.natural_width(btn_h)
            cx_ -= bw_ + 10 * S
            b.place(cx_, actions_y, bw_, btn_h)
        hint_room = cx_ - ix - 12 * S
        hint_f = body(lp(13, 14))
        for hint in ("Tip: double-click a quality to download it.", "Tip: double-click a quality."):
            if hint_f.measure(hint) <= hint_room:
                c.create_text(ix, actions_y + btn_h / 2, text=hint, font=hint_f, fill=T.TEXT_MUTED, anchor="w",
                              tags=("chrome",))
                break

        # ---- options row --------------------------------------------------------------
        ox, oy, ow, oh = L["options"]
        t1, t2 = self.toggles
        t1.place(ox + 6 * S, oy)
        t2.place(ox + ow - 6 * S - t2.width(), oy)

        # ---- status bar -----------------------------------------------------------------
        sx, sy, sw2, sh2 = L["status"]
        self._status_dot = (sx + 26 * S, sy + sh2 / 2)
        self._status_bg = T.mix("#57121a", "#2a0a0c", 0.4)
        self._draw_status_text()

        self.table_empty.set_visible(len(self.table.get_children()) == 0, top=heading_h)
        for p in self._placeholders:
            p.update()
        c.tag_raise("panel", "bg")
        c.tag_raise("static", "panel")
        c.tag_raise("chrome", "static")
        self.bubbles.reset()
        if self.animate.get():
            self.bubbles.resume()
        else:
            self.bubbles.pause(static=True)

    def _section(self, x, y, text, sphere) -> None:
        S, c = self.S, self.canvas
        d = round(14 * S)
        hrow = self.lerp(22, 26) * S
        inner, outer, glow = sphere
        photo, m = self._photo(("sphere", d, inner, S), lambda: T.render_sphere(d, inner, outer, glow, S))
        c.create_image(x - m, y + (hrow - d) / 2 - m, image=photo, anchor="nw", tags=("static",))
        c.create_text(x + d + 12 * S, y + hrow / 2, text=text, font=self.fonts.heading(self.lerp(17, 20), 600),
                      fill=T.TEXT_PRIMARY, anchor="w", tags=("chrome",))

    # ================================================================== dynamic parts
    def _draw_thumb(self) -> None:
        rect = getattr(self, "_thumb_rect", None)
        if not rect:
            return
        c, S = self.canvas, self.S
        c.delete("thumb")
        x, y, w, h = (round(v) for v in rect)
        if w < 16 or h < 16:
            return
        if self._thumb_src is None:
            photo, m = self._photo(("vph", w, h, S), lambda: T.render_video_placeholder(w, h, S))
            c.create_image(x - m, y - m, image=photo, anchor="nw", tags=("thumb", "chrome"))
            font = self.fonts.body(self.lerp(12, 13))
            c.create_text(x + w / 2, y + h * 0.5 + min(w, h) * 0.17 + 14 * S, text="Video preview appears here",
                          font=font, fill=T.TEXT_MUTED, anchor="n", tags=("thumb", "chrome"))
        else:
            if getattr(self, "_thumb_cached", None) != (self._thumb_key, w, h):
                self.cache.clear("thumb")  # only the current thumbnail stays in memory
                self._thumb_cached = (self._thumb_key, w, h)
            photo, m = self._photo(("thumb", self._thumb_key, w, h, S), lambda: T.render_thumb(self._thumb_src, w, h, S))
            c.create_image(x - m, y - m, image=photo, anchor="nw", tags=("thumb", "chrome"))

    def _draw_video_text(self) -> None:
        rect = getattr(self, "_text_rect", None)
        if not rect:
            return
        c, S = self.canvas, self.S
        c.delete("vtext")
        x, y, w, h = rect
        title_f, meta_f = self.fonts.heading(self.lerp(16, 19), 600), self.fonts.body(self.lerp(13, 14))
        if not self._video_title:
            c.create_text(x, y, text="Works with youtube.com, youtu.be and Shorts links.",
                          font=meta_f, fill=T.TEXT_MUTED, anchor="nw", width=w, tags=("vtext", "chrome"))
            return
        lines = self._wrap(title_f, self._video_title, w, 2)
        c.create_text(x, y, text="\n".join(lines), font=title_f, fill=T.TEXT_PRIMARY, anchor="nw",
                      tags=("vtext", "chrome"))
        my = y + len(lines) * title_f.metrics("linespace") + 6 * S
        c.create_text(x, my, text=truncate(meta_f, self._video_meta, w), font=meta_f, fill=T.TEXT_MUTED,
                      anchor="nw", tags=("vtext", "chrome"))

    @staticmethod
    def _wrap(font, text: str, width: float, max_lines: int) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for i, word in enumerate(words):
            trial = f"{cur} {word}".strip()
            if font.measure(trial) <= width or not cur:
                cur = trial
                continue
            lines.append(cur)
            cur = word
            if len(lines) == max_lines - 1:
                cur = " ".join(words[i:])
                break
        lines.append(truncate(font, cur, width))
        return lines[:max_lines]

    def _draw_progress(self) -> None:
        rect = getattr(self, "_prog_rect", None)
        if not rect:
            return
        c, S = self.canvas, self.S
        c.delete("progress")
        x, y, w, h, ty = rect
        frac, left, right = self._progress
        w, h = round(w), round(h)
        step = max(1, round(3 * S))
        q = 0 if frac is None else round(frac * w / step) * step / w
        photo, m = self._photo(("prog", w, h, round(q * w), S), lambda: T.render_progress(w, h, q, S))
        c.create_image(round(x) - m, round(y) - m, image=photo, anchor="nw", tags=("progress", "chrome"))
        font = self.fonts.body(self.lerp(13, 14))
        bold = self.fonts.body(self.lerp(13, 14), 700)
        rw = bold.measure(right) if right else 0
        if left:
            c.create_text(x, ty, text=truncate(font, left, w - rw - 16 * S), font=font, fill=T.TEXT_LABEL,
                          anchor="nw", tags=("progress", "chrome"))
        if right:
            c.create_text(x + w, ty, text=right, font=bold, fill=T.TEXT_PRIMARY, anchor="ne",
                          tags=("progress", "chrome"))

    # ================================================================== status
    def _draw_status_text(self) -> None:
        L = getattr(self, "L", None)
        if not L:
            return
        c, S = self.canvas, self.S
        c.delete("statustext")
        sx, sy, sw, sh = L["status"]
        font = self.fonts.body(self.lerp(14, 15))
        c.create_text(sx + 44 * S, sy + sh / 2, text=truncate(font, self.status.get(), sw - 70 * S), font=font,
                      fill=T.TEXT_LABEL, anchor="w", tags=("chrome", "statustext"))
        self._status_pulse(None)

    def _status_pulse(self, phase) -> None:
        if not getattr(self, "_status_dot", None):
            return
        c, S = self.canvas, self.S
        x, y = self._status_dot
        c.delete("pulse")
        r = 5 * S
        if phase is not None and self._busy:
            phase = (phase * 2) % 1.0
        if phase is not None and phase < 0.7:
            t = phase / 0.7
            rr = r + 10 * S * t
            col = T.mix("#ff6a6a", self._status_bg, 0.3 + 0.7 * t)
            c.create_oval(x - rr, y - rr, x + rr, y + rr, fill=col, outline="", tags=("chrome", "pulse"))
        c.create_oval(x - r, y - r, x + r, y + r, fill=T.ACCENT, outline="", tags=("chrome", "pulse"))
