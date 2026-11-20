"""Regenerate assets/app.ico and assets/logo.png from the procedural logo mark."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import theme as T  # noqa: E402

root = Path(__file__).resolve().parent.parent / "assets"
mark = T.render_logo_mark(256)
mark.save(root / "logo.png")
mark.save(root / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", root / "app.ico")
