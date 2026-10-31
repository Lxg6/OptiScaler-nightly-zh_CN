from __future__ import annotations

import os
from pathlib import Path

__version__ = "1.3.0"

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().parent / "assets"
DICT_DIR = ROOT / "dict"
FONT_NAME = "UI_Font.h"
FONT_ASSET = "font_subset.ttf"
FONT_SOURCE = "msyh.ttc"
FONT_FACE = 0
MENU_PATH = Path("OptiScaler") / "menu"
KINDS = ("menu", "ini", "bat")

EXTRA_SOURCES = ("OptiScaler/dllmain.cpp",)

INI_OVERRIDES = {"LoadAsiPlugins": "true"}

BASE_RANGES = (
    (0x0020, 0x00FF),
    (0x2000, 0x206F),
    (0x3000, 0x303F),
    (0xFF00, 0xFFEF),
)

CJK_RANGE = (0x4E00, 0x9FFF)

GLYPH_RANGES = tuple(sorted(BASE_RANGES + (CJK_RANGE,)))


def system_font() -> Path:
    return Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / FONT_SOURCE
