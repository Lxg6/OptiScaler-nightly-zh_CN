#!/usr/bin/env python3
"""翻译 OptiScaler.ini 的 ; 注释与 setup_windows.bat 的说明文本（行级字典 dict_files.json）。

ini 只替换注释行，键值行不动，保持 UTF-8。bat 只替换 echo 显示文本，并以 GBK
（中文 Windows 控制台原生编码）写出——cmd 对含大量中文的长 UTF-8 批处理存在
位置漂移类解析 bug，GBK 是可靠选择；因此也不需要 chcp。bat 附带两处功能修正：
  PowerShell 读写 ini 的两处调用补 -Encoding UTF8（防止 UTF-8 中文注释被转码成乱码）
  生成的卸载器输出改名为 卸载_OptiScaler.bat
菜单选项（[1] Yes 等）、set /p 提示词、代码行、URL、文件名一律不翻译。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cstr

INI_LINE = re.compile(r'^(\s*;\s?)(.*?)(\s*)$')
# 取行内最后一个 echo 作为显示文本的起点（兼容 "echo echo xxx" 嵌套生成与 "if exist x echo y"）
ECHO_LINE = re.compile(r'^(\s*(?:.*\s)?echo\s+)(.+?)\s*$')
# 纯文件名/代码/版本号等无需翻译的 bat 文本
BAT_SKIP = re.compile(
    r'^(?:@[\w ]+$|cls$|pause$|echo\.$|REM .*$|set .*$|setlocal .*$|for .*$|if .*$|del .*$|rd .*$|'
    r'v\d[\w.+-]*$|chcp .*$|[-\s]*[\w.]+\.(?:dll|asi|bat|exe|txt)$|^-\s[\w ]+\.(?:bat|asi)$|'
    r'\^\) else \^\(|\^)$'
)


def load_dict() -> dict:
    p = cstr.TOOLS_DIR / 'dict_files.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    empty = [k for k, v in data.items() if not v]
    if empty:
        raise SystemExit(f'错误：dict_files.json 有空翻译，例如 {empty[:3]!r}')
    bad = [k for k, v in data.items() if not v.isascii() and not _gbk_ok(v)]
    if bad:
        raise SystemExit(f'错误：{len(bad)} 条译文无法用 GBK 编码（bat 需要），例如 {bad[0]!r}')
    return data


def _gbk_ok(s: str) -> bool:
    try:
        s.encode('gbk')
        return True
    except UnicodeEncodeError:
        return False


def ini_translatable(body: str) -> bool:
    """ini 注释内容是否属于应翻译的说明文本（供体检复用）。"""
    if not re.search(r'[A-Za-z]{3}', body):
        return False
    if body.startswith('http') or body.startswith('D3D12_RESOURCE_STATE'):
        return False
    if re.match(r'^[\w.+-]+$', body):                       # 单个标识符/文件名
        return False
    if re.match(r'^[\w\s]+:\s*[\d.]+$', body):              # DLAA : 1.0 之类取值表
        return False
    if re.search(r'\| (?:0x)?\d+ = ', body):                # 0 = A | 1 = B 之类取值枚举
        return False
    return True


def bat_translatable(text: str) -> bool:
    """bat echo 文本是否属于应翻译的说明文本（供体检复用）。"""
    if not re.search(r'[A-Za-z]{3}', text):
        return False
    if re.match(r'^\[\d+\]', text) or text in ('Yes', 'No'):
        return False
    if BAT_SKIP.match(text):
        return False
    return True


def read_bat(path: Path) -> str:
    """读取 bat 文本：原文件为 ASCII，翻译重跑时已是 GBK。"""
    raw = path.read_bytes()
    try:
        return raw.decode('gbk')
    except UnicodeDecodeError:
        return raw.decode('utf-8-sig')


def translate_ini(text: str, mapping: dict) -> tuple[str, int, int]:
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = [l.rstrip('\r') for l in text.split('\n')]
    hit = total = 0
    for i, line in enumerate(lines):
        m = INI_LINE.match(line)
        if not m:
            continue
        body = m.group(2).strip()
        if not ini_translatable(body):
            continue
        total += 1
        zh = mapping.get(body)
        if zh:
            lines[i] = f'{m.group(1)}{zh}'
            hit += 1
    return eol.join(lines), hit, total


def translate_bat(text: str, mapping: dict) -> tuple[str, int, int]:
    lines = [l.rstrip('\r') for l in text.split('\n')]
    out = []
    hit = total = 0
    for line in lines:
        bare = line.strip()

        # PowerShell 读写 ini 补 UTF-8 编码参数（幂等）
        if 'powershell' in line and '(Get-Content' in line and '-Encoding' not in line:
            line = line.replace("(Get-Content '%configFile%')",
                                "(Get-Content '%configFile%' -Encoding UTF8)")
            line = line.replace("Set-Content '%configFile%'",
                                "Set-Content '%configFile%' -Encoding UTF8")

        # 卸载器输出改名（幂等）
        if bare == ') > "Remove_OptiScaler.bat"':
            line = line.replace('"Remove_OptiScaler.bat"', '"卸载_OptiScaler.bat"')

        # echo 显示文本翻译（取最后一个 echo 后的部分）
        m = ECHO_LINE.match(line)
        if m:
            text_part = m.group(2)
            if bat_translatable(text_part):
                total += 1
                zh = mapping.get(text_part)
                if zh:
                    line = m.group(1) + zh
                    hit += 1

        out.append(line)

    return '\r\n'.join(out), hit, total


def main() -> None:
    ap = argparse.ArgumentParser(description='翻译 ini 注释与 bat 说明文本')
    ap.add_argument('--src', required=True, help='上游源码仓库根目录')
    args = ap.parse_args()

    root = Path(args.src)
    mapping = load_dict()

    ini_path = root / 'OptiScaler.ini'
    new, hit, total = translate_ini(ini_path.read_bytes().decode('utf-8-sig'), mapping)
    ini_path.write_bytes(new.encode('utf-8'))
    print(f'OptiScaler.ini   : 说明 {total} 条，翻译 {hit} 条（UTF-8）')

    bat_path = root / 'setup_windows.bat'
    new, hit, total = translate_bat(read_bat(bat_path), mapping)
    bat_path.write_bytes(new.encode('gbk'))
    print(f'setup_windows.bat: 说明 {total} 条，翻译 {hit} 条（GBK + CRLF）')


if __name__ == '__main__':
    main()
