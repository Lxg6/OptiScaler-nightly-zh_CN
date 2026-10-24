#!/usr/bin/env python3
"""tools_cn 回归自测：构造迷你源码树跑完整注入链，把历史事故钉成断言。

覆盖：字体补丁结构与幂等、译文注入与 BOM 与注释跳过、ini/bat 翻译（GBK/CRLF/
卸载器改名/PS 编码参数/菜单项保留）与幂等、覆盖率统计、体检零欠账、
cstr 词法边界、分类器关键判定、真实字体资产有效性。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import cstr            # noqa: E402
import sync_check      # noqa: E402
import translate_files  # noqa: E402
import update_upstream  # noqa: E402

PY = sys.executable
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, name: str) -> None:
    RESULTS.append((ok, name))
    print(('  ok ' if ok else '  FAIL ') + name)


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    return subprocess.run([PY, '-X', 'utf8', str(TOOLS / args[0]), *args[1:]],
                          capture_output=True, text=True, encoding='utf-8', env=env)


MENU_COMMON = '''// Fixture for selftest
#include "font/Hack_Compressed.h"

static const char* g_test = "Latency";
static const char* g_keep = "DLSSG";
static const char* g_two = "Frame Gen";
// keep "Latency" untouched in comment

void Init()
{
    if (io.Fonts->Fonts.empty() && Config::Instance()->UseHQFont.value_or_default())
    {
        ImFontAtlas* atlas = io.Fonts;
        atlas->Clear();

        // This automatically becomes the next default font
        ImFontConfig fontConfig;

        if (Config::Instance()->TTFFontPath.has_value())
        {
            io.FontDefault =
                atlas->AddFontFromFileTTF(wstring_to_string(Config::Instance()->TTFFontPath.value()).c_str(), fontSize,
                                          &fontConfig, io.Fonts->GetGlyphRangesDefault());
        }
        else
        {
            io.FontDefault = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,
                                                                         fontSize, &fontConfig);
        }
    }

    if (!Config::Instance()->OverlayMenu.value_or_default())
    {
        _hdrTonemapApplied = false;
    }

    ImGui::TextDisabled("Whatever the game uses");
    int n = 1'000;
    (void) n;
}
'''

MENU_OVERLAY = '''// second fixture file
void Draw()
{
    ImGui::Text("Hooks");
    ImGui::TextWrapped("This might help filtering of wrong HUDless resources");
    LOG_DEBUG("log line {0}", 1);
}
'''

VCPROJ = '''<?xml version="1.0" encoding="utf-8"?>
<Project>
  <ItemGroup>
    <ClInclude Include="menu\\font\\Hack_Compressed.h" />
  </ItemGroup>
</Project>
'''

FILTERS = '''<?xml version="1.0" encoding="utf-8"?>
<Project>
  <ItemGroup>
    <ClInclude Include="menu\\font\\Hack_Compressed.h">
      <Filter>Font</Filter>
    </ClInclude>
  </ItemGroup>
</Project>
'''

INI = '''; Select Upscaler for Dx11 games
Dx11Upscaler=auto

; true or false - Default (auto) is false
Enabled=auto
'''

BAT = '''REM Setup OptiScaler for your game
@echo off
echo Coping is strong with this one...
echo.
echo [1] Yes
echo Choose a filename for OptiScaler (default is dxgi.dll, most compatible):
set /p filenameChoice="Enter 1-8 (or press Enter for default): "
if "%filenameChoice%"=="" (
    powershell -Command "(Get-Content '%configFile%') -replace 'Dxgi=auto', 'Dxgi=false' | Set-Content '%configFile%'"
    echo Do you want to delete these files?
)
echo @echo off
echo echo Coping is strong with this one...
echo set "OLD_FILES_FOUND=0"
) > "Remove_OptiScaler.bat"
'''


def build_fixture(root: Path) -> None:
    menu = root / 'OptiScaler' / 'menu'
    menu.mkdir(parents=True)
    (menu / 'menu_common.cpp').write_text(MENU_COMMON, encoding='utf-8')
    (menu / 'menu_overlay_dx.cpp').write_text(MENU_OVERLAY, encoding='utf-8')
    (root / 'OptiScaler' / 'OptiScaler.vcxproj').write_text(VCPROJ, encoding='utf-8')
    (root / 'OptiScaler' / 'OptiScaler.vcxproj.filters').write_text(FILTERS, encoding='utf-8')
    (root / 'OptiScaler.ini').write_text(INI, encoding='utf-8')
    (root / 'setup_windows.bat').write_text(BAT, encoding='utf-8')


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix='opti_selftest_'))
    build_fixture(tmp)
    cpp = tmp / 'OptiScaler' / 'menu' / 'menu_common.cpp'
    ini = tmp / 'OptiScaler.ini'
    bat = tmp / 'setup_windows.bat'

    print('== 1. 字体补丁 ==')
    r = run('cjk_patch.py', '--src', str(tmp))
    check(r.returncode == 0, 'cjk_patch apply 退出码 0')
    text = cpp.read_text(encoding='utf-8-sig')
    check('#include "font/CJK_Font.h"' in text, 'include 行已注入')
    check('cjk_font_data' in text, '[CN] 合并块已注入')
    check((tmp / 'OptiScaler' / 'menu' / 'font' / 'CJK_Font.h').is_file(), '字体资产已复制')
    proj = (tmp / 'OptiScaler' / 'OptiScaler.vcxproj').read_text(encoding='utf-8-sig')
    check('CJK_Font.h' in proj, 'vcxproj 已加条目')
    snap = cpp.read_bytes()
    run('cjk_patch.py', '--src', str(tmp))
    check(cpp.read_bytes() == snap, 'cjk_patch 幂等')
    check(run('cjk_patch.py', '--src', str(tmp), '--check').returncode == 0, 'cjk_patch --check 通过')

    print('== 2. 译文注入 ==')
    r = run('apply_dict_v10.py', '--src', str(tmp), '--quiet')
    check(r.returncode == 0, 'apply_dict 退出码 0')
    raw = cpp.read_bytes()
    text = raw.decode('utf-8-sig')
    check(raw.startswith(b'\xef\xbb\xbf'), '注入后补 UTF-8 BOM')
    check('"延迟"' in text, 'Latency 已替换（单词盲区回归）')
    check('"挂钩"' in (tmp / 'OptiScaler' / 'menu' / 'menu_overlay_dx.cpp').read_text(encoding='utf-8-sig'),
          'Hooks 已替换')
    check('keep "Latency" untouched' in text, '注释内字面量未动')
    check('"DLSSG"' in text, '保留英文的键未动')
    check('1\'000' in text, "数字分隔符 1'000 未被误判")
    snap = cpp.read_bytes()
    run('apply_dict_v10.py', '--src', str(tmp), '--quiet')
    check(cpp.read_bytes() == snap, 'apply_dict 幂等')

    print('== 3. 覆盖率与体检（英文树上应为 1 条保留/DLSSG，0 欠账）==')
    r = run('scan_remaining.py', '--src', str(tmp), '--top', '5')
    line = next((l for l in r.stdout.splitlines() if '界面文本' in l), '')
    check('未翻译 1 条' in line, f'覆盖统计符合预期（{line.strip()[:60]}）')
    r = run('update_upstream.py', '--src', str(tmp), '--out', str(tmp / 'review'), '--quiet')
    check(r.returncode == 0 and 'ini/bat 未翻译: 0 行' in r.stdout, '体检零欠账')

    print('== 4. ini / bat 翻译 ==')
    r = run('translate_files.py', '--src', str(tmp))
    check(r.returncode == 0, 'translate_files 退出码 0')
    it = ini.read_text(encoding='utf-8')
    check('为 Dx11 游戏选择超分器' in it and 'Dx11Upscaler=auto' in it, 'ini 注释翻译且键值行不动')
    braw = bat.read_bytes()
    check(not braw.startswith(b'\xef\xbb\xbf') and b'\r\n' in braw, 'bat 无 BOM 且 CRLF')
    try:
        bt = braw.decode('gbk')
        gbk_ok = True
    except UnicodeDecodeError:
        bt, gbk_ok = '', False
    check(gbk_ok, 'bat 为合法 GBK')
    check('原力与你同在' in bt, 'bat 说明已翻译')
    check('[1] Yes' in bt and 'Enter 1-8' in bt, '菜单项与提示词保留')
    check('卸载_OptiScaler.bat' in bt and '"Remove_OptiScaler.bat"' not in bt, '卸载器已改名')
    check(bt.count('-Encoding UTF8') == 2, 'PS 读写 ini 补了 UTF-8 参数')
    snap_i, snap_b = ini.read_bytes(), braw
    run('translate_files.py', '--src', str(tmp))
    check(ini.read_bytes() == snap_i and bat.read_bytes() == snap_b, 'translate_files 幂等')

    print('== 5. cstr 词法边界 ==')
    check(cstr.decode_c(r'\xzz') == 'x', '畸形 \\x 转义不崩溃（回退为 x 并跳过无效位）')
    check(cstr.decode_c(r'\u4e2d') == '中', '\\u 转义正确')
    lits = [l.value for l in cstr.scan_text("int n = 1'000; char c = '\"';", min_len=2)]
    check(lits == [], "单引号/数字分隔符不产生假字面量")

    print('== 6. 分类器关键判定 ==')
    def cls(v, ctx=''):
        return sync_check.classify({'value': v, 'files': [{'ctx': ctx}]})
    check(cls('Latency') == 'ui', '单个大写单词判 ui（Latency 回归）')
    check(cls('DLSSG', 'ImGui::TextDisabled("DLSSG")') == 'ui', '缩写判 ui')
    check(cls('Progress {0}', 'LOG_DEBUG(...)') == 'log', '日志格式串判 log')
    check(cls('##tab1') == 'other', 'ImGui ID 判 other')
    check(cls('Whatever the game uses') == 'ui', '普通句子判 ui')

    print('== 7. 真实资产与字典 ==')
    asset = (TOOLS / 'assets' / 'CJK_Font.h').read_text(encoding='utf-8', errors='replace')
    check(',,,' not in asset and ',,' not in asset, 'CJK_Font.h 无连续逗号')
    data = update_upstream.font_bytes_from_header(TOOLS / 'assets' / 'CJK_Font.h')
    cmap = update_upstream.parse_cmap(data)
    check(len(cmap) > 4000 and 0x4E2D in cmap, f'字体 cmap 有效（{len(cmap)} 码点）')
    d = cstr.load_dict(cstr.resolve_dict())
    need = {ord(ch) for v in d.values() for ch in v if ord(ch) >= 0x20}
    check(not (need - cmap), '字典用字全部有字形')
    tf = translate_files.load_dict()
    check(len(tf) > 600, f'dict_files.json 可加载且 GBK 合法（{len(tf)} 条）')
    json.loads((TOOLS / 'dict_v10.json').read_text(encoding='utf-8'))

    failed = [n for ok, n in RESULTS if not ok]
    print(f'\n共 {len(RESULTS)} 项，失败 {len(failed)}')
    for n in failed:
        print('  FAIL', n)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
