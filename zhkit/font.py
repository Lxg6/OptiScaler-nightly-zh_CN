from __future__ import annotations

import io
import re
import struct
import sys
from pathlib import Path

from . import ASSETS, BASE_RANGES, FONT_ASSET, FONT_FACE, FONT_NAME, GLYPH_RANGES
from .catalog import Catalog

TRUETYPE_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"ttcf")
DATA_PATTERN = re.compile(r"ui_font_data\[\d+\]\s*=\s*\{(.*?)\};", re.S)
ROW_BYTES = 24


def base_points() -> set:
    return {point for low, high in BASE_RANGES for point in range(low, high + 1)}


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def cmap(blob: bytes) -> set:
    points = set()
    if len(blob) < 12 or blob[:4] not in TRUETYPE_MAGIC:
        return points

    table = None
    for index in range(_u16(blob, 4)):
        record = 12 + 16 * index
        if blob[record:record + 4] == b"cmap":
            table = _u32(blob, record + 8)
            break
    if table is None:
        return points

    for index in range(_u16(blob, table + 2)):
        sub = table + _u32(blob, table + 8 + 8 * index)
        version = _u16(blob, sub)
        if version == 4:
            segments = _u16(blob, sub + 6) // 2
            ends = sub + 14
            starts = ends + 2 * segments + 2
            offsets = starts + 4 * segments
            for seg in range(segments):
                first, last = _u16(blob, starts + 2 * seg), _u16(blob, ends + 2 * seg)
                if first == 0xFFFF:
                    continue
                slot = offsets + 2 * seg
                delta = _u16(blob, slot)
                if delta == 0:
                    points.update(range(first, last + 1))
                    continue
                base = slot + delta
                for point in range(first, last + 1):
                    if _u16(blob, base + 2 * (point - first)):
                        points.add(point)
        elif version == 12:
            groups = _u32(blob, sub + 12)
            for group in range(groups):
                begin = _u32(blob, sub + 16 + 12 * group)
                end = _u32(blob, sub + 20 + 12 * group)
                points.update(range(begin, end + 1))
    return points


def unpack(text: str) -> bytes | None:
    matched = DATA_PATTERN.search(text)
    if not matched:
        return None
    return bytes(int(value) for value in re.findall(r"\d+", matched.group(1)))


def pack(blob: bytes) -> str:
    rows = [blob[offset:offset + ROW_BYTES] for offset in range(0, len(blob), ROW_BYTES)]
    body = "\r\n".join("    " + ",".join(str(byte) for byte in row) + "," for row in rows)
    return (
        f"static const unsigned int ui_font_size = {len(blob)};\r\n"
        f"static const unsigned char ui_font_data[{len(blob)}] =\r\n"
        "{\r\n"
        f"{body}\r\n"
        "};\r\n"
    )


def verify(header: str, blob: bytes) -> None:
    if ",," in header:
        sys.exit("错误：生成的数组里出现连续逗号")
    broken = [line for line in header.splitlines()
              if line.startswith("    ") and not re.match(r"^ {4}\d+(,\d+)*,$", line)]
    if broken:
        sys.exit(f"错误：{len(broken)} 行数据格式非法，如 {broken[0][:60]!r}")
    if unpack(header) != blob:
        sys.exit("错误：从头文件回读的字节与字体资源不一致")


def missing_glyphs(blob: bytes, catalog) -> list:
    mapped = cmap(blob)
    problems = []
    for key, value in catalog.items():
        for char in value:
            point = ord(char)
            if point < 0x80:
                continue
            if not any(low <= point <= high for low, high in GLYPH_RANGES):
                problems.append((key, char, "字形范围外"))
            elif point not in mapped:
                problems.append((key, char, "字体缺字"))
    return problems


def load(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    if path.suffix.lower() == ".ttf":
        return path.read_bytes()
    return unpack(path.read_text(encoding="utf-8", errors="replace"))


def load_for(menu_dir: Path) -> bytes | None:
    font_header = menu_dir / "font" / FONT_NAME
    if font_header.is_file():
        blob = unpack(font_header.read_text(encoding="utf-8", errors="replace"))
        if blob:
            return blob
    return load(ASSETS / FONT_ASSET)


def build_from(src_ttf: str, out: Path) -> None:
    from fontTools.subset import Options, Subsetter
    from fontTools.ttLib import TTFont, TTLibFileIsCollectionError

    wanted = {ord(char) for value in Catalog.load("menu").entries.values()
              for char in value if ord(char) >= 0x20}
    existing = load(out)
    if existing:
        print(f"旧字体: {len(cmap(existing))} 码点 / {len(existing)} 字节（将按字典重算）")

    try:
        font = TTFont(src_ttf)
    except TTLibFileIsCollectionError:
        font = TTFont(src_ttf, fontNumber=FONT_FACE)
        print(f"[i] {Path(src_ttf).name} 是字体集合，使用第 {FONT_FACE} 个面")
    if "glyf" not in font:
        sys.exit("错误：源字体不是 TrueType glyf 轮廓（stb_truetype 不支持 CFF/OTF）")
    available = set(font.getBestCmap())
    version = font["name"].getDebugName(5) or "unknown"

    missing = {point for point in wanted if point not in available}
    if missing:
        sample = ", ".join(f"U+{point:04X}" for point in sorted(missing)[:10])
        sys.exit(f"错误：源字体缺 {len(missing)} 个字典用字（{sample}）")

    wanted |= base_points() & available

    options = Options()
    options.layout_features = []
    options.hinting = False
    options.name_IDs = [1, 2, 4, 6]
    options.name_languages = [0x409]
    options.glyph_names = False
    options.notdef_outline = True

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=sorted(wanted))
    subsetter.subset(font)

    font.recalcTimestamp = False

    buffer = io.BytesIO()
    font.save(buffer)
    blob = buffer.getvalue()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    print(f"已写入: {out}（{len(blob)} 字节 TTF，源 {Path(src_ttf).stem} {version}）")

    if load(out) != blob:
        sys.exit("错误：回读的字体字节与写入的不一致")
    verify(pack(blob), blob)
    uncovered = {point for point in wanted if point not in cmap(blob)}
    print(f"自检: TTF 回读与头文件打包通过；cmap {len(cmap(blob))} 码点，字典用字未覆盖 {len(uncovered)} 个")
    if uncovered:
        sys.exit(1)
