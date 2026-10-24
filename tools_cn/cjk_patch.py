#!/usr/bin/env python3
"""把"内嵌 CJK 字体"补丁注入 OptiScaler 源码树（升级上游源码后必跑一次，幂等）。

补丁包含三部分：
  1) menu_common.cpp 顶部 `#include "font/CJK_Font.h"`
  2) Init() 里字体图集初始化之后，合并内嵌的 CJK 子集字体（[CN] 块，未压缩 TTF）
  3) menu/font/CJK_Font.h 资源与 vcxproj 引用
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import cstr

FONT_HEADER_NAME = "CJK_Font.h"

INCLUDE_ANCHOR = '#include "font/Hack_Compressed.h"'
INCLUDE_LINE = f'#include "font/{FONT_HEADER_NAME}"'

BLOCK_MARK = "// [CN] Merge the embedded CJK subset font"

FONT_ANCHOR = """            io.FontDefault = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,
                                                                         fontSize, &fontConfig);
        }
    }

    if (!Config::Instance()->OverlayMenu.value_or_default())"""

# [CN] 块本体（不含前面那段锚点代码）
BLOCK_BODY = """    // [CN] Merge the embedded CJK subset font so the Chinese UI renders correctly.
    {
        ImFontAtlas* atlas = io.Fonts;

        // Ensure a base font exists even when the HQ font is disabled.
        if (atlas->Fonts.empty())
            io.FontDefault = atlas->AddFontDefault();

        ImFontConfig cjkConfig;
        cjkConfig.MergeMode = true;
        cjkConfig.FontNo = 0;
        // 保持 1/1 过采样且不启用 PixelSnapH：避免改变字宽/字距（曾出现中英间隔差 1px）
        cjkConfig.OversampleH = 1;
        cjkConfig.OversampleV = 1;
        // 字体数据是静态数组，不能让 ImGui 去 free 它
        cjkConfig.FontDataOwnedByAtlas = false;

        static const ImWchar cjkGlyphRanges[] = {
            0x0020, 0x00FF, // Basic Latin + Latin-1 Supplement
            0x2000, 0x2BFF, // Punctuation, symbols, arrows, math
            0x3000, 0x303F, // CJK Symbols and Punctuation
            0xFF00, 0xFFEF, // Halfwidth and Fullwidth Forms
            0x4E00, 0x9FAF, // CJK Unified Ideographs
            0,
        };

        atlas->AddFontFromMemoryTTF((void*) cjk_font_data, (int) cjk_font_size, fontSize, &cjkConfig,
                                    cjkGlyphRanges);
    }
"""

FONT_PATCH = FONT_ANCHOR.replace(
    "\n\n    if (!Config::Instance()->OverlayMenu.value_or_default())",
    "\n\n" + BLOCK_BODY + "\n    if (!Config::Instance()->OverlayMenu.value_or_default())")

# 匹配源码里已有的 [CN] 块（旧版压缩数组 / 旧参数都能命中）
BLOCK_RE = re.compile(r"\n( *" + re.escape(BLOCK_MARK) + r".*?\n    \}\n)", re.S)


def patch_cpp(path: Path, check_only: bool) -> tuple[bool, list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    original = text
    notes = []

    # 1) include 行
    if INCLUDE_LINE not in text:
        if INCLUDE_ANCHOR not in text:
            notes.append(f"[失败] 找不到 include 锚点：{INCLUDE_ANCHOR}")
            return False, notes
        text = text.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + "\n" + INCLUDE_LINE, 1)
        notes.append(f'[+] 已添加 #include "font/{FONT_HEADER_NAME}"')
    else:
        notes.append("[=] include 已存在")

    # 2) 字体块：已有块规范成最新版；没有则插入
    m = BLOCK_RE.search(text)
    if m:
        existing = m.group(1)
        if existing.strip() == BLOCK_BODY.strip():
            notes.append("[=] 字体合并块已是最新版本")
        else:
            text = text[:m.start()] + "\n" + BLOCK_BODY + text[m.end():]
            notes.append("[~] 已有字体块已更新为最新参数（1/1 过采样、无 PixelSnapH）")
    elif FONT_ANCHOR in text:
        text = text.replace(FONT_ANCHOR, FONT_PATCH, 1)
        notes.append("[+] 已插入 [CN] 字体合并块（AddFontFromMemoryTTF + 未压缩数据）")
    else:
        notes.append("[失败] 找不到字体初始化锚点（上游代码结构可能变了，请手工确认）")
        return False, notes

    if check_only:
        return True, notes
    if text != original:
        cstr.write_source(path, text, bom="auto")
    return True, notes


def patch_project(project_dir: Path, check_only: bool) -> list[str]:
    notes = []
    for name in ("OptiScaler.vcxproj", "OptiScaler.vcxproj.filters"):
        p = project_dir / name
        if not p.is_file():
            continue
        t = p.read_text(encoding="utf-8-sig")
        changed = False

        if FONT_HEADER_NAME in t:
            notes.append(f"[=] {name}: 已包含 {FONT_HEADER_NAME}")
        elif name.endswith(".vcxproj"):
            old = '    <ClInclude Include="menu\\font\\Hack_Compressed.h" />'
            if old not in t:
                notes.append(f"[!] {name}: 找不到 Hack_Compressed.h 条目，跳过")
                continue
            t = t.replace(old, old + f'\n    <ClInclude Include="menu\\font\\{FONT_HEADER_NAME}" />', 1)
            changed = True
            notes.append(f"[+] {name}: 已加入 {FONT_HEADER_NAME}")
        else:
            key = '<ClInclude Include="menu\\font\\Hack_Compressed.h">'
            if key not in t:
                notes.append(f"[!] {name}: 找不到 Hack_Compressed.h 条目，跳过")
                continue
            i = t.index(key)
            j = t.index("</ClInclude>", i) + len("</ClInclude>")
            t = t[:j] + "\n" + t[i:j].replace("Hack_Compressed.h", FONT_HEADER_NAME) + t[j:]
            changed = True
            notes.append(f"[+] {name}: 已加入 {FONT_HEADER_NAME}")

        if changed and not check_only:
            p.write_text(t, encoding="utf-8-sig")
    return notes


def main() -> None:
    ap = argparse.ArgumentParser(description="注入内嵌 CJK 字体补丁")
    ap.add_argument("--src", help="源码仓库根或 OptiScaler/menu 目录")
    ap.add_argument("--check", action="store_true", help="只检查，不修改文件")
    ap.add_argument("--font-asset",
                    default=str(cstr.TOOLS_DIR / "assets" / FONT_HEADER_NAME),
                    help=f"字体资源来源（默认 tools_cn/assets/{FONT_HEADER_NAME}）")
    ap.add_argument("--force-font", action="store_true",
                    help="用字体资源覆盖目标树里已有的字体头文件")
    args = ap.parse_args()

    menu_dir = cstr.resolve_menu_dir(args.src)
    project_dir = menu_dir.parent
    cpp = menu_dir / "menu_common.cpp"
    font_header = menu_dir / "font" / FONT_HEADER_NAME

    print(f"源码目录: {menu_dir}")
    print(f"模式    : {'check' if args.check else 'apply'}")
    print()

    ok = True
    asset = Path(args.font_asset)
    if not asset.is_absolute():
        asset = (cstr.TOOLS_DIR / asset).resolve()

    if font_header.is_file() and not args.force_font:
        print(f"[=] 字体资源存在: font/{FONT_HEADER_NAME}（{font_header.stat().st_size // 1024} KB）")
    elif asset.is_file():
        if args.check:
            ok = False
            print(f"[!] 目标树缺少 font/{FONT_HEADER_NAME}，apply 时会从 assets 复制过去")
        else:
            font_header.parent.mkdir(parents=True, exist_ok=True)
            font_header.write_bytes(asset.read_bytes())
            print(f"[+] 已从 assets 复制 font/{FONT_HEADER_NAME}（{font_header.stat().st_size // 1024} KB）")
    else:
        ok = False
        print(f"[失败] 目标树和 assets 都没有 {FONT_HEADER_NAME}（找过：{asset}）")

    if not cpp.is_file():
        print(f"[失败] 找不到 {cpp.name}")
        sys.exit(1)

    patched, notes = patch_cpp(cpp, args.check)
    ok = ok and patched
    for n in notes:
        print(n)
    for n in patch_project(project_dir, args.check):
        print(n)

    print()
    print("结论：补丁已就位" if ok and not args.check else
          ("结论：检查通过" if ok else "结论：有未完成的步骤，见上面的 [失败]"))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
