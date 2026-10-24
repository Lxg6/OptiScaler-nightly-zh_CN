#!/usr/bin/env python3
"""用指定 TTF 重建内嵌 CJK 字体子集 assets/CJK_Font.h。

数组保持未压缩 TTF 输出。不要改成压缩格式：ImGui 的
AddFontFromMemoryCompressedTTF 解的是 stb/ryg 私有压缩格式（数据头 03 00 00 00），
不是标准 zlib（78 9C 开头）——用 Python zlib 压的数据它解不开，
会让整个字体图集作废、菜单文字全变问号（2026-10 实测踩坑）。
字符集 = 现有 CJK_Font.h 的全部码点 ∪ dict_v10.json 译文用字，
保证重建后覆盖只增不减。源字体必须是 TrueType glyf 轮廓（stb_truetype 不支持 CFF）。
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

import cstr
import update_upstream


def main() -> None:
    ap = argparse.ArgumentParser(description="重建内嵌 CJK 字体头文件")
    ap.add_argument("--font", required=True, help="源 TTF 路径（如 msyh.ttf）")
    ap.add_argument("--out", default=str(cstr.TOOLS_DIR / "assets" / "CJK_Font.h"),
                    help="输出头文件路径，默认 assets/CJK_Font.h")
    args = ap.parse_args()

    out = Path(args.out)
    dictionary = cstr.load_dict(cstr.resolve_dict(None))

    # 字符集：旧头文件的全部码点 ∪ 字典用字
    dict_cps = {ord(ch) for v in dictionary.values() for ch in v if ord(ch) >= 0x20}
    old_cps: set = set()
    if out.is_file():
        old_data = update_upstream.font_bytes_from_header(out)
        if old_data:
            old_cps = update_upstream.parse_cmap(old_data)
            print(f"旧字体: {len(old_cps)} 码点 / {len(old_data)} 字节")
    charset = old_cps | dict_cps
    print(f"目标字符集: {len(charset)} 码点（其中字典用字 {len(dict_cps)}）")

    font = TTFont(args.font)
    if "glyf" not in font:
        sys.exit("错误：源字体不是 TrueType glyf 轮廓（CFF/OTF 不被 stb_truetype 支持）")
    src_cmap = set(font.getBestCmap().keys())
    version = font["name"].getDebugName(5) or "unknown"

    missing_dict = {cp for cp in dict_cps if cp not in src_cmap}
    if missing_dict:
        sample = ", ".join(f"U+{c:04X}" for c in sorted(missing_dict)[:10])
        sys.exit(f"错误：源字体缺 {len(missing_dict)} 个字典用字（{sample}），不能生成")
    missing_old = {cp for cp in old_cps if cp not in src_cmap}
    if missing_old:
        print(f"[!] 旧字体有而源字体没有的码点 {len(missing_old)} 个将被舍弃"
              f"（均不在字典译文里，不影响现有界面）")

    opts = Options()
    opts.layout_features = []       # stb_truetype 不用 GSUB/GPOS
    opts.hinting = False
    opts.name_IDs = [1, 2, 4, 6]
    opts.name_languages = [0x409]
    opts.glyph_names = False
    opts.notdef_outline = True
    opts.recalc_timestamp = False

    keep = sorted(charset - missing_old)
    sub = Subsetter(options=opts)
    sub.populate(unicodes=keep)
    sub.subset(font)

    buf = io.BytesIO()
    font.save(buf)
    data = buf.getvalue()

    rows = [data[i:i + 24] for i in range(0, len(data), 24)]
    body = "\r\n".join("    " + ",".join(str(b) for b in row) + "," for row in rows)
    header = (
        "// Embedded CJK font subset for the Chinese UI.\r\n"
        f"// Source: {Path(args.font).stem} ({version})  |  {len(keep)} chars  |  "
        f"{len(data)} bytes  |  uncompressed TTF\r\n"
        "// Loaded with ImFontAtlas::AddFontFromMemoryTTF() (font_cfg->FontDataOwnedByAtlas = false).\r\n"
        "// Regenerate with tools_cn/build_font.py\r\n"
        f"static const unsigned int cjk_font_size = {len(data)};\r\n"
        f"static const unsigned char cjk_font_data[{len(data)}] =\r\n"
        "{\r\n"
        f"{body}\r\n"
        "};\r\n"
    )
    out.write_bytes(header.encode("ascii"))
    print(f"已写入: {out}")
    print(f"字符 {len(keep)} / 字节 {len(data)}（未压缩）")

    # 自检：数组格式、字体字节回读、码点覆盖
    text = out.read_text(encoding="utf-8")
    if ",," in text:
        sys.exit("错误：生成的数组里出现连续逗号，无法通过 C 语法")
    bad_lines = [l for l in text.splitlines()
                 if l.startswith("    ") and not re.match(r"^ {4}\d+(,\d+)*,$", l)]
    if bad_lines:
        sys.exit(f"错误：{len(bad_lines)} 行数据行不符合 \"值,值,...,\" 格式，如 {bad_lines[0][:60]!r}")

    check = update_upstream.font_bytes_from_header(out)
    if check != data:
        sys.exit("错误：从头文件回读的字节与生成的 TTF 不一致")
    cmap = update_upstream.parse_cmap(check)
    uncovered = {cp for cp in dict_cps if cp not in cmap}
    print(f"自检: 格式与回读通过；cmap {len(cmap)} 码点，字典用字未覆盖 {len(uncovered)} 个"
          f"{'（通过）' if not uncovered else '（失败！）'}")
    if uncovered:
        sys.exit(1)


if __name__ == "__main__":
    main()
