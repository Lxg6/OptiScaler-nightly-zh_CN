#!/usr/bin/env python3
"""把中文翻译字典应用到 OptiScaler 源码（v10 唯一入口，字典固定为 dict_v10.json）。"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import cstr


def apply_file(path: Path, mapping: Dict[str, str], skip_comments: bool,
               dry_run: bool, bom: str = "auto") -> Tuple[int, int]:
    """替换单个文件，返回 (替换处数, 原文件字符数变化)。"""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    new_text, count = cstr.rewrite_literals(text, mapping, skip_comments=skip_comments)

    had_bom = raw.startswith(b"\xef\xbb\xbf")
    need_bom = bom in ("auto", "always") and cstr.has_cjk(new_text) and not had_bom
    if not dry_run and (count or need_bom):
        cstr.write_source(path, new_text, bom=bom)

    return count, len(new_text) - len(text)


def collect_literals(menu_dir: Path, include_headers: bool, min_len: int = 1) -> list:
    for f in cstr.list_sources(menu_dir, include_headers=include_headers):
        for lit in cstr.scan_file(f, min_len=min_len):
            yield f, lit


def main() -> None:
    ap = argparse.ArgumentParser(description="把 dict_v10.json 的译文写入 OptiScaler 源码")
    ap.add_argument("--dict", dest="dict_path", help="翻译字典路径，默认 tools_cn/dict_v10.json")
    ap.add_argument("--src", help="源码目录（仓库根或 OptiScaler/menu）")
    ap.add_argument("--include-headers", action="store_true", help="同时处理 *.h / *.hpp")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--translate-comments", action="store_true",
                    help="连注释中的字面量也替换（默认跳过注释）")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    ap.add_argument("--bom", choices=["keep", "auto", "always", "never"], default="auto",
                    help="写回时的 BOM 策略，默认 auto（含中文则补 BOM，避免 MSVC 乱码）")
    args = ap.parse_args()

    dict_path = cstr.resolve_dict(args.dict_path)
    menu_dir = cstr.resolve_menu_dir(args.src)
    mapping = cstr.load_dict(dict_path)

    print(f"翻译字典: {dict_path}（{len(mapping)} 条）")
    print(f"源码目录: {menu_dir}")
    if args.dry_run:
        print("模式    : dry-run（不写文件）")
    print()

    # 应用前先记录源码里出现过的字面量，用于判断"过期键"
    values_before = {lit.value for _, lit in collect_literals(menu_dir, args.include_headers)}

    total = 0
    changed_files: List[str] = []
    for f in cstr.list_sources(menu_dir, include_headers=args.include_headers):
        count, delta = apply_file(f, mapping, skip_comments=not args.translate_comments,
                                  dry_run=args.dry_run, bom=args.bom)
        total += count
        if count:
            changed_files.append(f.name)
        if not args.quiet:
            flag = "" if count == 0 else f"  ({delta:+d} 字符)"
            print(f"  {f.name:<24} {count:4d} 处{flag}")

    # ---- 报告：仍是英文的键 / 已过期的键 ----
    present: Dict[str, List[str]] = {}
    for f, lit in collect_literals(menu_dir, args.include_headers):
        if lit.value in mapping and mapping[lit.value] != lit.value:
            present.setdefault(lit.value, []).append(f"{f.name}:{lit.line}")

    values_after = {lit.value for _, lit in collect_literals(menu_dir, args.include_headers)}
    in_use = values_before | values_after
    stale = [k for k in mapping if k not in in_use and mapping[k] not in in_use]

    print()
    print(f"替换合计      : {total} 处" + ("（dry-run 未落盘）" if args.dry_run else ""))
    if args.dry_run:
        print(f"预计覆盖键数  : {len(present)} 条（字典共 {len(mapping)} 条）")
    else:
        print(f"仍为英文的键  : {len(present)} 条（只出现在注释里，注入时有意跳过）")

    print(f"过期键        : {len(stale)} 条（源码中已无对应英文，可清理）")
    for k in stale[:10]:
        print(f"  STALE {k!r} -> {mapping[k]!r}")
    if len(stale) > 10:
        print(f"  ... 其余 {len(stale) - 10} 条略")


if __name__ == "__main__":
    main()
