#!/usr/bin/env python3
"""上游更新后的一站式体检脚本。

做两件事：
  1) 体检：对比最新上游源码与 dict_v10.json，列出「新增待翻译 / 字典过期键 /
     OptiScaler.ini 注释与 setup_windows.bat 说明未翻译行」，并检查字典译文的
     用字是否被内嵌 CJK 字体与字形范围覆盖（防界面豆腐块）
  2) 出清单：把待翻译条目写成 review/todo-YYYYMMDD.md + .json（含上下文、位置、可复用的旧译文建议）

注意：需在 translate_files.py 之前运行（体检基于英文原文件）。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import cstr
import extract_strings
import sync_check
import translate_files

# cjk_patch.py 注入的 cjkGlyphRanges，改那边时同步改这里
GLYPH_RANGES = ((0x0020, 0x00FF), (0x2000, 0x2BFF), (0x3000, 0x303F),
                (0xFF00, 0xFFEF), (0x4E00, 0x9FAF))


def scan(menu_dir: Path, include_headers: bool) -> list:
    items, _ = extract_strings.build(
        menu_dir,
        include_headers=include_headers,
        min_len=cstr.DEFAULT_MIN_LEN,
        ctx_chars=cstr.DEFAULT_CTX_CHARS,
        max_locations=cstr.DEFAULT_MAX_LOCATIONS,
        comments="include",
        sort_key="count",
    )
    return items


def best_match(value: str, keys: list):
    """找最可能对应的旧条目（上游改名/微调原文时，可直接复用旧译文）。"""
    close = difflib.get_close_matches(value, keys, n=1, cutoff=0.7)
    return close[0] if close else None


def analyse(items: list, dictionary: dict) -> tuple:
    """返回 (待翻译界面文本, 缺失计数, 过期键)。"""
    missing_ui = []
    bucket = {"ui": 0, "log": 0, "comment": 0, "other": 0}

    keys = list(dictionary)
    for it in items:
        if it["value"] in dictionary:
            continue
        kind = sync_check.classify(it)
        bucket[kind] += 1
        if kind != "ui":
            continue
        suggestion = best_match(it["value"], keys)
        missing_ui.append({
            "value": it["value"],
            "count": it["count"],
            "file": it["files"][0]["file"],
            "line": it["files"][0]["line"],
            "ctx": it["files"][0]["ctx"],
            "suggest_from": suggestion,
            "suggest_text": dictionary[suggestion] if suggestion else None,
        })

    values = {it["value"] for it in items}
    stale = [k for k in dictionary
             if k not in values and dictionary[k] not in values]
    return missing_ui, bucket, stale


# ---------------------------------------------------------------- 字体覆盖检查

def _u16(data: bytes, o: int) -> int:
    return int.from_bytes(data[o:o + 2], "big")


def _u32(data: bytes, o: int) -> int:
    return int.from_bytes(data[o:o + 4], "big")


def parse_cmap(data: bytes) -> set:
    """解析 TTF 的 cmap 表，返回全部已映射码点（支持子表格式 4 / 12）。"""
    cps = set()
    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"ttcf"):
        return cps

    cmap_off = None
    for i in range(_u16(data, 4)):
        rec = 12 + 16 * i
        if data[rec:rec + 4] == b"cmap":
            cmap_off = _u32(data, rec + 8)
            break
    if cmap_off is None:
        return cps

    for i in range(_u16(data, cmap_off + 2)):
        sub = cmap_off + _u32(data, cmap_off + 8 + 8 * i)
        fmt = _u16(data, sub)

        if fmt == 4:
            seg = _u16(data, sub + 6) // 2
            seg_end = sub + 14
            seg_start = seg_end + 2 * seg + 2
            seg_delta = seg_start + 2 * seg
            seg_roff = seg_delta + 2 * seg
            for s in range(seg):
                start, end = _u16(data, seg_start + 2 * s), _u16(data, seg_end + 2 * s)
                if start == 0xFFFF:
                    continue
                roff_entry = seg_roff + 2 * s
                if _u16(data, roff_entry) == 0:
                    cps.update(range(start, end + 1))
                else:
                    base = roff_entry + _u16(data, roff_entry)
                    for c in range(start, end + 1):
                        if _u16(data, base + 2 * (c - start)):
                            cps.add(c)

        elif fmt == 12:
            for g in range(_u32(data, sub + 12)):
                cps.update(range(_u32(data, sub + 16 + 12 * g),
                                 _u32(data, sub + 20 + 12 * g) + 1))
    return cps


def files_untranslated(menu_dir: Path) -> List[dict]:
    """OptiScaler.ini 注释与 setup_windows.bat 说明文本中仍是英文且字典未收录的行。"""
    root = menu_dir.parent.parent
    mapping = translate_files.load_dict()

    def has_cjk(s: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in s)

    out = []
    ini = root / "OptiScaler.ini"
    if ini.is_file():
        for i, line in enumerate(ini.read_text(encoding="utf-8-sig").splitlines(), 1):
            m = translate_files.INI_LINE.match(line)
            body = m.group(2).strip() if m else ""
            if m and translate_files.ini_translatable(body) and not has_cjk(body) and body not in mapping:
                out.append({"file": "OptiScaler.ini", "line": i, "text": body})

    bat = root / "setup_windows.bat"
    if bat.is_file():
        for i, line in enumerate(translate_files.read_bat(bat).splitlines(), 1):
            m = translate_files.ECHO_LINE.match(line)
            t = m.group(2) if m else ""
            if m and translate_files.bat_translatable(t) and not has_cjk(t) and t not in mapping:
                out.append({"file": "setup_windows.bat", "line": i, "text": t})
    return out


def font_bytes_from_header(path: Path) -> Optional[bytes]:
    """从 CJK_Font.h 取回未压缩 TTF 字节。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"cjk_font_data\[\d+\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        return None
    return bytes(int(x) for x in re.findall(r"\d+", m.group(1)))


def font_problems(menu_dir: Path, dictionary: dict) -> Optional[List[Tuple[str, str, str]]]:
    """检查字典译文用字是否被内嵌 CJK 字体与字形范围覆盖。

    返回 [(英文原文, 字符, 原因)]，原因为 "字形范围外" / "字体缺字"；
    找不到 CJK_Font.h 时返回 None（表示未检查）。
    """
    header = menu_dir / "font" / "CJK_Font.h"
    if not header.is_file():
        header = cstr.TOOLS_DIR / "assets" / "CJK_Font.h"
    if not header.is_file():
        return None

    data = font_bytes_from_header(header)
    if not data:
        return None
    cmap = parse_cmap(data)

    problems = []
    for k, v in dictionary.items():
        for ch in v:
            cp = ord(ch)
            if cp < 0x80:
                continue
            if not any(lo <= cp <= hi for lo, hi in GLYPH_RANGES):
                problems.append((k, ch, "字形范围外"))
            elif cp not in cmap:
                problems.append((k, ch, "字体缺字"))
    return problems


def write_review(out_dir: Path, menu_dir: Path, items, missing_ui, bucket, stale,
                 dictionary, font, files_todo) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    md = out_dir / f"todo-{stamp}.md"
    js = out_dir / f"todo-{stamp}.json"

    ui_total = sum(1 for it in items if sync_check.classify(it) == "ui")
    lines = [
        f"# 上游同步检查 {stamp}",
        "",
        f"- 源码目录：`{menu_dir}`",
        f"- 上游字符串：{len(items)} 条（界面文本 {ui_total}）",
        f"- 字典条目：{len(dictionary)}",
        f"- **待翻译界面文本：{len(missing_ui)} 条**",
        f"- 无需翻译：日志/格式串 {bucket['log']}、注释 {bucket['comment']}、其他 {bucket['other']}",
        f"- 字典中已失效的键：{len(stale)} 条",
        "",
    ]

    if missing_ui:
        lines += ["## 待翻译", "", "| # | 英文原文 | 次数 | 位置 | 可复用旧译文 |", "|---|---|---|---|---|"]
        for i, m in enumerate(sorted(missing_ui, key=lambda x: -x["count"]), 1):
            reuse = ""
            if m["suggest_from"]:
                reuse = f"`{m['suggest_from']}` → {m['suggest_text']}"
            value = m["value"].replace("|", "\\|").replace("\n", "\\n")
            lines.append(f"| {i} | `{value}` | {m['count']} | {m['file']}:{m['line']} | {reuse} |")
        lines += ["", "> 每条的位置见上表；翻译时保留 `##id`、`%s`、`{0:X}`、`\\n` 等占位符。", ""]
    else:
        lines += ["## 待翻译", "", "没有新增界面文本，上游这次改动不涉及菜单文字。", ""]

    lines += ["## 字体覆盖", ""]
    if font is None:
        lines += ["未找到 CJK_Font.h，本次未检查。", ""]
    elif font:
        lines += [f"缺字 {len(font)} 处（这些字在界面会显示为方块）：", ""]
        for k, ch, why in font[:40]:
            lines.append(f"- `{k}` → {ch!r}（{why}，U+{ord(ch):04X}）")
        if len(font) > 40:
            lines.append(f"- ... 其余 {len(font) - 40} 处")
        lines.append("")
    else:
        lines += ["字典译文用字全部被内嵌字体与字形范围覆盖。", ""]

    lines += ["## ini / bat 未翻译行", ""]
    if files_todo:
        lines += [f"共 {len(files_todo)} 行（补进 dict_files.json 即可）：", ""]
        for f in files_todo[:30]:
            lines.append(f"- `{f['file']}:{f['line']}` {f['text'][:90]}")
        if len(files_todo) > 30:
            lines.append(f"- ... 其余 {len(files_todo) - 30} 行")
        lines.append("")
    else:
        lines += ["OptiScaler.ini 注释与 setup_windows.bat 说明全部有译文。", ""]

    if stale:
        lines += ["## 字典中已失效的键（上游删了或改了原文）", ""]
        for k in sorted(stale)[:80]:
            lines.append(f"- `{k}` → {dictionary[k]}")
        if len(stale) > 80:
            lines.append(f"- ... 其余 {len(stale) - 80} 条")

    md.write_text("\n".join(lines), encoding="utf-8")
    js.write_text(json.dumps({"generated": stamp, "source": str(menu_dir),
                              "missing_ui": missing_ui, "stale_keys": stale,
                              "font_problems": font, "files_untranslated": files_todo},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    return md


def main() -> None:
    ap = argparse.ArgumentParser(description="上游源码与字典的同步体检")
    ap.add_argument("--src", help="上游源码目录（仓库根或 OptiScaler/menu）", required=True)
    ap.add_argument("--dict", dest="dict_path", help="翻译字典，默认 dict_v10.json")
    ap.add_argument("--out", default=str(cstr.TOOLS_DIR / "review"), help="清单输出目录")
    ap.add_argument("--include-headers", action="store_true", help="同时扫描 *.h / *.hpp")
    ap.add_argument("--strict", action="store_true",
                    help="存在待翻译条目或字体缺字时返回退出码 1")
    ap.add_argument("--quiet", action="store_true", help="少打印")
    args = ap.parse_args()

    menu_dir = cstr.resolve_menu_dir(args.src)
    dict_path = cstr.resolve_dict(args.dict_path)
    dictionary = cstr.load_dict(dict_path)

    print(f"上游源码: {menu_dir}")
    print(f"翻译字典: {dict_path}（{len(dictionary)} 条）")

    items = scan(menu_dir, args.include_headers)
    missing_ui, bucket, stale = analyse(items, dictionary)
    font = font_problems(menu_dir, dictionary)
    files_todo = files_untranslated(menu_dir)
    md = write_review(Path(args.out), menu_dir, items, missing_ui, bucket, stale,
                      dictionary, font, files_todo)

    print(f"上游字符串: {len(items)} 条")
    print(f"待翻译界面文本: {len(missing_ui)} 条"
          f"（日志/格式串 {bucket['log']}、注释 {bucket['comment']}、其他 {bucket['other']} 不计）")
    print(f"ini/bat 未翻译: {len(files_todo)} 行")
    if font is None:
        print("字体覆盖  : 未检查（找不到 CJK_Font.h）")
    elif font:
        print(f"字体覆盖  : 缺字 {len(font)} 处，详见清单")
    else:
        print("字体覆盖  : 全部覆盖")
    print(f"清单已写入: {md}")
    if missing_ui and not args.quiet:
        for m in sorted(missing_ui, key=lambda x: -x["count"])[:10]:
            hint = f"  ⟵ 可复用 {m['suggest_from']!r}" if m["suggest_from"] else ""
            print(f"  ? [{m['count']}] {m['value']!r} @ {m['file']}:{m['line']}{hint}")
        if len(missing_ui) > 10:
            print(f"  ... 其余 {len(missing_ui) - 10} 条见清单")

    if args.strict and (missing_ui or font):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
