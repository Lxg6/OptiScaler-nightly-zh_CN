#!/usr/bin/env python3
"""OptiScaler 中文化工具链 - 公共模块。

提供 C/C++ 字符串字面量的解码、编码、精确扫描与批量替换，以及字典/路径约定；
所有脚本都从这里导入。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


def _configure_console() -> None:
    """把 stdout/stderr 切到 UTF-8，在模块导入时统一生效。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc in ("utf-8", "utf8"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_configure_console()

# ---------------------------------------------------------------- 常量约定

DEFAULT_MIN_LEN = 2          # 短于此长度的字面量不参与翻译
DEFAULT_MAX_LOCATIONS = 6    # 每条字符串最多记录的出现位置数（与现有 JSON 一致）
DEFAULT_CTX_CHARS = 160      # ctx 截断长度（与现有 JSON 一致）

MENU_SUBDIR = Path("OptiScaler") / "menu"
DICT_CANDIDATES = ("dict_v10.json",)   # v10 起只保留 dict_v10.json
TOOLS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 编解码

def decode_c(s: str) -> str:
    """把 C 字符串字面量的内容（不含首尾引号）解码为真实文本。"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            out.append("\\")
            break
        e = s[i]
        i += 1
        if e == "n":
            out.append("\n")
        elif e == "r":
            out.append("\r")
        elif e == "t":
            out.append("\t")
        elif e == "a":
            out.append("\a")
        elif e == "b":
            out.append("\b")
        elif e == "f":
            out.append("\f")
        elif e == "v":
            out.append("\v")
        elif e == "0":
            out.append("\0")
        elif e in "\\\"'?":
            out.append(e)
        elif e in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[e]
            h = s[i:i + width]
            if len(h) == width and all(c in "0123456789abcdefABCDEF" for c in h) \
                    and int(h, 16) <= 0x10FFFF:
                out.append(chr(int(h, 16)))
            else:
                out.append(e)
            i += len(h)
        else:
            out.append(e)
    return "".join(out)


def encode_c(value: str) -> str:
    """把真实文本编码回 C 字符串字面量的内容形式（不含首尾引号）。"""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------- 扫描

@dataclass
class StringLiteral:
    """源码中的一处字符串字面量。"""
    value: str           # 解码后的文本（翻译字典的键）
    raw: str             # 引号内的原始转义形式
    line: int            # 1 起始的行号
    col: int             # 0 起始的列号
    in_comment: bool     # 是否位于 // 或 /* */ 注释内
    ctx: str             # 所在行（strip 后截断）
    start: int = 0       # 左引号在全文中的偏移
    end: int = 0         # 右引号之后的偏移

    def location(self, file_name: str) -> str:
        return f"{file_name}:{self.line}"


def _is_digit_separator(text: str, idx: int) -> bool:
    """判断 idx 处的单引号是否为 C++14 数字分隔符（1'000 / 0x7F'FF）。"""
    return idx > 0 and idx + 1 < len(text) and text[idx - 1].isalnum() and text[idx + 1].isalnum()


def iter_literals(text: str, min_len: int = 0,
                  ctx_chars: int = DEFAULT_CTX_CHARS) -> Iterator[StringLiteral]:
    """按 C/C++ 词法逐字符扫描，产出所有字符串字面量（含注释内的）。"""
    line_starts = [0]
    for m in re.finditer("\n", text):
        line_starts.append(m.end())
    lines = text.split("\n")

    def pos_to_line_col(pos: int) -> Tuple[int, int]:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, pos - line_starts[lo]

    n = len(text)
    i = 0
    in_line_comment = False
    in_block_comment = False

    while i < n:
        c = text[i]

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                i += 1
                continue
        elif in_block_comment:
            if c == "*" and i + 1 < n and text[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
        else:
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                in_line_comment = True
                i += 2
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue
            if c == "'" and not _is_digit_separator(text, i):
                j = i + 1
                while j < n and text[j] != "'":
                    j += 2 if text[j] == "\\" else 1
                i = j + 1
                continue

        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"' or text[j] == "\n":
                    break
                j += 1
            raw = text[i + 1:j]
            value = decode_c(raw)
            if len(value) >= min_len:
                line, col = pos_to_line_col(i)
                ctx = lines[line - 1].strip()[:ctx_chars] if line - 1 < len(lines) else ""
                yield StringLiteral(value=value, raw=raw, line=line, col=col,
                                    in_comment=in_line_comment or in_block_comment,
                                    ctx=ctx, start=i, end=min(j + 1, n))
            i = j + 1
            continue

        i += 1


def scan_text(text: str, file_name: str = "", min_len: int = DEFAULT_MIN_LEN,
              ctx_chars: int = DEFAULT_CTX_CHARS) -> List[StringLiteral]:
    """扫描一段源码，返回长度 >= min_len 的全部字符串字面量。"""
    return list(iter_literals(text, min_len=min_len, ctx_chars=ctx_chars))


CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    """文本里是否含中文字符（用于判断是否需要 UTF-8 BOM）。"""
    return bool(CJK_RE.search(text))


def write_source(path: Path, text: str, bom: str = "keep") -> bool:
    """按 bom 策略（keep/auto/always/never）写回源码，返回是否实际带了 BOM。"""
    raw = path.read_bytes() if path.exists() else b""
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if bom == "always":
        want = True
    elif bom == "never":
        want = False
    elif bom == "auto":
        want = had_bom or has_cjk(text)
    else:
        want = had_bom

    data = text.encode("utf-8")
    if want:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return want


def read_source(path: Path) -> str:
    """读取源码文本，去掉 BOM，按原样保留行尾（\\r\\n 或 \\n）。"""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def scan_file(path: Path, min_len: int = DEFAULT_MIN_LEN,
              ctx_chars: int = DEFAULT_CTX_CHARS) -> List[StringLiteral]:
    return scan_text(read_source(path), path.name, min_len=min_len, ctx_chars=ctx_chars)


def rewrite_literals(text: str, mapping: Dict[str, str],
                     skip_comments: bool = True) -> Tuple[str, int]:
    """按字典替换源码中的字符串字面量（只做完整匹配，其余逐字节保持），返回 (新文本, 替换处数)。"""
    edits: List[Tuple[int, int, str]] = []
    for lit in iter_literals(text, min_len=1):
        if skip_comments and lit.in_comment:
            continue
        target = mapping.get(lit.value)
        if target is None or target == lit.value:
            continue
        edits.append((lit.start, lit.end, '"' + encode_c(target) + '"'))

    if not edits:
        return text, 0

    out = []
    cursor = 0
    for start, end, repl in edits:
        out.append(text[cursor:start])
        out.append(repl)
        cursor = end
    out.append(text[cursor:])
    return "".join(out), len(edits)


# ---------------------------------------------------------------- 路径与字典

def resolve_menu_dir(src: Optional[str] = None) -> Path:
    """解析源码 menu 目录（--src 可为上游仓库根目录或 menu 目录本身）。"""
    if not src:
        raise SystemExit("错误：请用 --src 指向上游源码仓库根目录或 OptiScaler/menu 目录。")
    p = Path(src).expanduser()
    if (p / MENU_SUBDIR).is_dir():
        p = p / MENU_SUBDIR
    if not p.is_dir():
        raise SystemExit(f"错误：源码目录不存在：{p}")
    return p.resolve()


def list_sources(menu_dir: Path, include_headers: bool = False) -> List[Path]:
    """列出要扫描的源文件（默认只 *.cpp，与现有 JSON 一致）。"""
    patterns = ["*.cpp"]
    if include_headers:
        patterns += ["*.h", "*.hpp"]
    files: List[Path] = []
    for pat in patterns:
        files.extend(sorted(menu_dir.glob(pat)))
    return sorted(set(files))


def resolve_dict(dict_path: Optional[str] = None) -> Path:
    """解析翻译字典：--dict 参数 > tools_cn/dict_v10.json。"""
    if dict_path:
        p = Path(dict_path).expanduser()
        if not p.is_absolute():
            p = (TOOLS_DIR / p).resolve()
        if not p.is_file():
            raise SystemExit(f"错误：字典文件不存在：{p}")
        return p

    for name in DICT_CANDIDATES:
        p = TOOLS_DIR / name
        if p.is_file():
            return p.resolve()
    raise SystemExit(
        f"错误：{TOOLS_DIR} 下找不到 {' / '.join(DICT_CANDIDATES)}，请用 --dict 指定字典。"
    )


def load_dict(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"错误：字典格式应为 JSON 对象：{path}")
    empty = [k for k, v in data.items() if not v]
    if empty:
        raise SystemExit(f"错误：字典中有 {len(empty)} 个空翻译，例如 {empty[:3]!r}")
    return data
