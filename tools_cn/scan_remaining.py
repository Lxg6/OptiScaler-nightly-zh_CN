#!/usr/bin/env python3
"""扫描源码里"还没处理"的界面文本：待翻译、已译未应用，并输出覆盖率摘要。

需在 apply_dict_v10.py 注入前对英文源码运行，对已汉化的树统计会失真。
"""
from __future__ import annotations

import argparse

import cstr
import extract_strings
import sync_check


def main() -> None:
    ap = argparse.ArgumentParser(description="扫描仍是英文的界面文本")
    ap.add_argument("--src", help="源码目录（仓库根或 OptiScaler/menu）")
    ap.add_argument("--dict", dest="dict_path", help="翻译字典，默认 dict_v10.json")
    ap.add_argument("--include-headers", action="store_true", help="同时扫描 *.h / *.hpp")
    ap.add_argument("--top", type=int, default=30, help="每类最多打印条数，默认 30")
    ap.add_argument("--all", action="store_true", help="连日志/其他类也一起列出")
    args = ap.parse_args()

    menu_dir = cstr.resolve_menu_dir(args.src)
    dict_path = cstr.resolve_dict(args.dict_path)
    mapping = cstr.load_dict(dict_path)

    items, _ = extract_strings.build(
        menu_dir,
        include_headers=args.include_headers,
        min_len=cstr.DEFAULT_MIN_LEN,
        ctx_chars=cstr.DEFAULT_CTX_CHARS,
        max_locations=cstr.DEFAULT_MAX_LOCATIONS,
        comments="include",
        sort_key="count",
    )

    def has_cjk(s: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in s)

    pending, unapplied, done, other = [], [], 0, []
    for it in items:
        value = it["value"]
        kind = sync_check.classify(it)
        if kind != "ui":
            other.append((it, kind))
            continue
        if has_cjk(value):
            done += 1                       # 源码里已经是中文
            continue
        translated = mapping.get(value)
        if translated is None:
            pending.append(it)              # 字典里没有
        elif translated == value:
            done += 1                       # 恒等映射，保留原文
        elif has_cjk(translated):
            unapplied.append(it)            # 有译文但还没写进源码
        else:
            done += 1                       # 有意保留英文写法

    total_ui = len(pending) + len(unapplied) + done
    translated_total = done + len(unapplied)    # 已有中文译文的条数（含已写入/待写入）
    pct = translated_total * 100 / total_ui if total_ui else 0.0
    print(f"源码目录: {menu_dir}")
    print(f"翻译字典: {dict_path}（{len(mapping)} 条）")
    print(f"界面文本: {total_ui} 条，已翻译 {translated_total}（{pct:.1f}%），"
          f"未翻译 {len(pending)} 条（仅供参考，部分为有意保留的技术名词）")
    print(f"  其中已写入源码 {done}，已译未应用 {len(unapplied)}，字典暂无译文 {len(pending)}")
    print()

    if unapplied:
        print(f"已译未应用（{len(unapplied)} 条，运行 apply_dict_v10.py 即可写入）：")
        for it in sorted(unapplied, key=lambda x: -x["count"])[: args.top]:
            f0 = it["files"][0]
            print(f'  A [{it["count"]}] {it["value"]!r} @ {f0["file"]}:{f0["line"]}')
        print()

    if pending:
        print(f"待翻译（{len(pending)} 条）：")
        for it in sorted(pending, key=lambda x: -x["count"])[: args.top]:
            f0 = it["files"][0]
            print(f'  ? [{it["count"]}] {it["value"]!r} @ {f0["file"]}:{f0["line"]}')
        print()

    if args.all and other:
        print(f"非界面文本（{len(other)} 条，通常无需翻译）：")
        for it, kind in sorted(other, key=lambda x: -x[0]["count"])[: args.top]:
            f0 = it["files"][0]
            print(f'  {kind:<7} [{it["count"]}] {it["value"]!r} @ {f0["file"]}:{f0["line"]}')


if __name__ == "__main__":
    main()
