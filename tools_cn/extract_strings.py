#!/usr/bin/env python3
"""从 OptiScaler 源码抽取字符串字面量清单（供 scan_remaining / update_upstream 复用）。"""
from __future__ import annotations

from pathlib import Path

import cstr


def build(src_dir: Path, include_headers: bool, min_len: int, ctx_chars: int,
          max_locations: int, comments: str, sort_key: str) -> tuple[list, dict]:
    files = cstr.list_sources(src_dir, include_headers=include_headers)
    if not files:
        raise SystemExit(f"错误：{src_dir} 下没有找到可扫描的源文件")

    entries = {}
    per_file = {}

    for f in files:
        literals = cstr.scan_file(f, min_len=min_len, ctx_chars=ctx_chars)
        per_file[f.name] = len(literals)
        for lit in literals:
            if comments == "skip" and lit.in_comment:
                continue
            entry = entries.get(lit.value)
            if entry is None:
                entry = {"value": lit.value, "count": 0, "files": []}
                entries[lit.value] = entry
            entry["count"] += 1
            if len(entry["files"]) < max_locations:
                entry["files"].append(
                    {"file": f.name, "line": lit.line, "ctx": lit.ctx, "comment": lit.in_comment}
                )

    items = list(entries.values())

    for it in items:
        # 若所有记录位置都是注释，则保留 comment 标记供下游判断
        it["comment_only"] = all(loc["comment"] for loc in it["files"])

    if sort_key == "value":
        items.sort(key=lambda x: (-x["count"], x["value"]))
    elif sort_key == "file":
        items.sort(key=lambda x: (x["files"][0]["file"], x["files"][0]["line"]))
    else:
        items.sort(key=lambda x: -x["count"])

    return items, per_file
