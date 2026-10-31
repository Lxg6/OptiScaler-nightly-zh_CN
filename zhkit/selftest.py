from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import ASSETS, DICT_DIR, FONT_ASSET, FONT_NAME, KINDS, ROOT
from . import audit as auditmod
from . import catalog as cat
from . import font as fontmod
from . import lexer, targets

RESULTS: list = []

MENU_COMMON = '''#include "font/Hack_Compressed.h"

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

MENU_OVERLAY = '''void Draw()
{
    ImGui::Text("Hooks");
    ImGui::TextWrapped("This might help filtering of wrong HUDless resources");
    ImGui::Text("Pos=4;Type=7;Horizontal=true;Rows=fps");
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
LoadAsiPlugins=auto
DlssOverrides=auto
'''

BAT = '''REM Setup OptiScaler for your game
@echo off
if exist "Remove_OptiScaler.bat" set "OLD_FILES_FOUND=1"
echo Coping is strong with this one...
echo.
echo [1] Yes
echo [2] No
set /p "USER_CHOICE=Waiting - "
echo Choose a filename for OptiScaler (default is dxgi.dll, most compatible):
set /p filenameChoice="Enter 1-8 (or press Enter for default): "
if "%filenameChoice%"=="" (
    powershell -Command "(Get-Content '%configFile%') -replace 'Dxgi=auto', 'Dxgi=false' | Set-Content '%configFile%'"
    echo Do you want to delete these files?
)
echo Deleted Remove_OptiScaler.bat
echo @echo off
echo echo Coping is strong with this one...
echo set "OLD_FILES_FOUND=0"
echo set /p removeChoice="Waiting - "
) > "Remove_OptiScaler.bat"
'''


def check(ok: bool, name: str) -> None:
    RESULTS.append((bool(ok), name))
    print(("  ok " if ok else "  FAIL ") + name)


def zhkit(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "zhkit", *args],
                          cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)


def build_fixture(root: Path) -> None:
    menu = root / "OptiScaler" / "menu"
    menu.mkdir(parents=True)
    (menu / "menu_common.cpp").write_text(MENU_COMMON, encoding="utf-8")
    (menu / "menu_overlay_dx.cpp").write_text(MENU_OVERLAY, encoding="utf-8")
    (root / "OptiScaler" / "OptiScaler.vcxproj").write_text(VCPROJ, encoding="utf-8")
    (root / "OptiScaler" / "OptiScaler.vcxproj.filters").write_text(FILTERS, encoding="utf-8")
    (root / "OptiScaler.ini").write_text(INI, encoding="utf-8")
    (root / "setup_windows.bat").write_text(BAT, encoding="utf-8")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="zhkit_test_"))
    build_fixture(work)
    cpp = work / "OptiScaler" / "menu" / "menu_common.cpp"
    overlay = work / "OptiScaler" / "menu" / "menu_overlay_dx.cpp"
    header = work / "OptiScaler" / "menu" / "font" / FONT_NAME
    ini = work / "OptiScaler.ini"
    bat = work / "setup_windows.bat"

    print("== 1. 字体补丁 ==")
    pre = zhkit("font", "--src", str(work), "--check")
    check(pre.returncode == 1 and not header.parent.exists(), "--check 对未打补丁的树报不一致且不落盘")
    result = zhkit("font", "--src", str(work))
    check(result.returncode == 0, "font 退出码 0")
    if result.returncode != 0:
        for line in (result.stdout + result.stderr).strip().splitlines()[:12]:
            print("   ", line)
        print("    -> 若提示缺字，先执行：python -m zhkit build-font（默认用系统微软雅黑）")
    else:
        text = cpp.read_text(encoding="utf-8-sig")
        check(f'#include "font/{FONT_NAME}"' in text, "include 行已注入")
        check("ui_font_data" in text, "字体块已注入")
        check("uiConfig.MergeMode = true" in text, "中文按 MergeMode 合入上游 Hack")
        check(text.count("atlas->Clear()") == MENU_COMMON.count("atlas->Clear()"),
              "不清空图集，英文仍用上游 Hack")
        check("OversampleH" not in text and "OversampleV" not in text, "不改上游超采样参数")
        check(text.index("hack_compressed_compressed_data_base85") < text.index("ui_font_data"),
              "字体块在上游 Hack 之后合入")
        check(header.is_file(), "字体头文件已生成")
        asset = fontmod.load(ASSETS / FONT_ASSET)
        check(fontmod.unpack(header.read_text(encoding="utf-8")) == asset, "头文件与 TTF 字节一致")
        project = (work / "OptiScaler" / "OptiScaler.vcxproj").read_text(encoding="utf-8-sig")
        check(FONT_NAME in project, "vcxproj 已加条目")
        snapshot = cpp.read_bytes()
        zhkit("font", "--src", str(work))
        check(cpp.read_bytes() == snapshot, "font 幂等")
        check(zhkit("font", "--src", str(work), "--check").returncode == 0, "font --check 通过")

    broken = Path(tempfile.mkdtemp(prefix="zhkit_bad_")) / "OptiScaler" / "menu"
    broken.mkdir(parents=True)
    (broken / "menu_common.cpp").write_text("int f() { return 0; }\n", encoding="utf-8")
    check(zhkit("font", "--src", str(broken)).returncode != 0, "锚点缺失时明确失败")

    print("== 2. 英文树体检 ==")
    result = zhkit("audit", "--src", str(work), "--out", str(work / "review"), "--strict")
    check(result.returncode == 0, "audit 零欠账退出码 0")
    check(bool(list((work / "review").glob("todo-*.md"))), "清单已生成")

    print("== 3. 写入译文 ==")
    result = zhkit("apply", "--src", str(work), "--quiet")
    check(result.returncode == 0, "apply 退出码 0")
    raw = cpp.read_bytes()
    text = raw.decode("utf-8-sig")
    check(raw.startswith(b"\xef\xbb\xbf"), "注入后补 UTF-8 BOM")
    check(cat.has_cjk(text) and cat.has_cjk(overlay.read_text(encoding="utf-8-sig")), "菜单源码已写入中文")
    check('"Latency"' not in text.split("// keep")[0], "代码区字面量已替换")
    check('keep "Latency" untouched' in text, "注释内字面量未动")
    check("1'000" in text, "数字分隔符 1'000 未被误判")
    check("Pos=4;Type=7" in overlay.read_text(encoding="utf-8-sig"), "配置串未被翻译")
    snapshot = cpp.read_bytes()
    zhkit("apply", "--src", str(work), "--quiet")
    check(cpp.read_bytes() == snapshot, "apply 幂等")
    result = zhkit("apply", "--src", str(work), "--only", "menu", "--dry-run", "--quiet")
    check(cpp.read_bytes() == snapshot and "未落盘" in result.stdout, "dry-run 不写文件")

    print("== 4. ini / bat ==")
    ini_text = ini.read_text(encoding="utf-8")
    check(cat.has_cjk(ini_text) and "Dx11Upscaler=auto" in ini_text, "ini 注释已翻译、键值行不动")
    check("LoadAsiPlugins=true" in ini_text, "LoadAsiPlugins 取值改写为 true")
    check("DlssOverrides=auto" in ini_text, "覆盖表以外的键保持上游默认")
    bat_raw = bat.read_bytes()
    check(not bat_raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in bat_raw, "bat 无 BOM 且 CRLF")
    try:
        bat_text, gbk_ok = bat_raw.decode("gbk"), True
    except UnicodeDecodeError:
        bat_text, gbk_ok = "", False
    check(gbk_ok, "bat 为合法 GBK")
    check(cat.has_cjk(bat_text) and "[1] Yes" in bat_text and "[2] No" in bat_text,
          "bat 说明已翻译、选项保留")
    check('set /p "USER_CHOICE=' in bat_text, "整段引号形态 set /p 前缀不动")
    check('set /p removeChoice="等待输入 - "' in bat_text, "写进卸载器的确认提示一起翻译")
    check(bat_text.count(targets.UNINSTALL_NEW) == BAT.count(targets.UNINSTALL_OLD),
          "旧卸载器名按出现次数全部改名")
    check(targets.UNINSTALL_OLD not in bat_text, "旧卸载器名已无残留")
    check(bat_text.count("-Encoding UTF8") == 2, "PS 读写 ini 补了 UTF-8 参数")
    probe_ini, forced, missing = targets.apply_ini_values("A=1\n", {"LoadAsiPlugins": "true"})
    check(forced == 0 and missing == ["LoadAsiPlugins"] and probe_ini == "A=1\n",
          "覆盖键在 ini 里不存在时报缺失且不改文件")
    ini_snapshot, bat_snapshot = ini.read_bytes(), bat_raw
    zhkit("apply", "--src", str(work), "--quiet")
    check(ini.read_bytes() == ini_snapshot and bat.read_bytes() == bat_snapshot, "ini/bat 幂等")

    print("== 5. 词法边界 ==")
    check(lexer.unescape(r"\xzz") == "x", "畸形 \\x 转义不崩溃")
    check(lexer.unescape(r"\u4e2d") == "中", "\\u 转义正确")
    check([token.text for token in lexer.Scanner("int n = 1'000; char c = '\"';").tokens(min_len=2)] == [],
          "单引号/数字分隔符不产生假字面量")
    check(lexer.escape('a"b\\c\nd') == 'a\\"b\\\\c\\nd', "escape 处理引号反斜杠换行")
    check([t.text for t in lexer.Scanner('R"(a "q" b)"').tokens(min_len=1)] == ['a "q" b'],
          "原始字符串按分隔符收尾")
    check([t.text for t in lexer.Scanner('auto a = L"x"; auto b = L\'中\'; auto c = "z";').tokens(min_len=1)]
          == ["x", "z"], "宽字符字面量不吞掉后面的字符串")
    check([(token.text, token.in_comment) for token
           in lexer.Scanner('// note "unpaired\nconst char* s = "Real";\n').tokens(min_len=1)]
          == [("unpaired", True), ("Real", False)], "行注释里的落单引号不吞掉下一行")
    check(lexer.rewrite('auto s = L"Latency";', {"Latency": "延迟"})[0] == 'auto s = L"延迟";',
          "带前缀字符串替换后保留 L")
    check(lexer.rewrite('auto s = R"(Latency)";', {"Latency": "延迟"})[0] == 'auto s = "延迟";',
          "原始字符串可整体替换")

    print("== 6. 分类器 ==")
    check(cat.classify("DLSSG", 'ImGui::TextDisabled("DLSSG")') == "ui", "缩写判 ui")
    check(cat.classify("Progress {0}", "LOG_DEBUG(...)") == "log", "日志格式串判 log")
    check(cat.classify("##tab1") == "other", "ImGui ID 判 other")
    check(cat.classify("Pos=4;Type=7;Horizontal=true;") == "other", "配置串判 other")
    check(cat.classify("Whatever the game uses") == "ui", "普通句子判 ui")

    print("== 7. 资产与字典 ==")
    blob = fontmod.load(ASSETS / FONT_ASSET)
    check(blob is not None and blob[:4] == b"\x00\x01\x00\x00", "字体资源是有效 TTF")
    check(len(blob) < 400_000, f"字体资源体积 {len(blob) // 1024} KB（瘦身后应 ≤ 400 KB）")
    check(fontmod.unpack(fontmod.pack(blob)) == blob, "头文件打包可往返")
    mapped = fontmod.cmap(blob)
    check(all(point in mapped for point in (0x2014, 0x2026, 0x3001, 0xFF0C, 0xFF1F)),
          "子集含中文标点与全角符号")
    menu_catalog = cat.Catalog.load("menu")
    needed = {ord(char) for value in menu_catalog.entries.values() for char in value if ord(char) >= 0x20}
    needed |= fontmod.base_points()
    gaps = fontmod.missing_glyphs(blob, menu_catalog)
    check(not gaps, f"字体与字典一致（含加载区间判定，缺 {len(gaps)} 处）")
    issues = cat.placeholder_issues(menu_catalog)
    for key, value, why in issues[:5]:
        print(f"    ! {why}: {key!r} -> {value!r}")
    check(not issues, f"占位符 / ##id / 换行与原文一致（异常 {len(issues)} 条）")
    check(len(mapped) <= len(needed) + 50,
          f"字体子集无历史残留（cmap {len(mapped)} / 字典用字 {len(needed)}）")
    ini_catalog, bat_catalog = cat.Catalog.load("ini"), cat.Catalog.load("bat")
    check(len(ini_catalog) > 500 and len(bat_catalog) > 50,
          f"ini/bat 字典可加载（{len(ini_catalog)}/{len(bat_catalog)}）")
    for kind in KINDS:
        path = DICT_DIR / f"{kind}.json"
        text = path.read_text(encoding="utf-8")
        entries = json.loads(text)
        check(text == json.dumps({key: entries[key] for key in sorted(entries)}, ensure_ascii=False, indent=2) + "\n",
              f"{path.name} 格式规范（排序 + 2 空格缩进）")

    print("== 8. 健壮性 ==")
    try:
        targets.encode_bat("ok\n😀")
    except SystemExit as exc:
        check("第 2 行" in str(exc), "bat 编码失败时报出行号")
    else:
        check(False, "bat 编码失败时报出行号")
    check(auditmod.find_root(work / "OptiScaler" / "menu") == work, "find_root 定位到仓库根")
    check(auditmod.find_root(broken) is None, "find_root 找不到时返回 None")
    try:
        cat.decode_strict(b"ok\n\xff\xfe", work / "menu_common.cpp")
    except SystemExit as exc:
        check("第 2 行" in str(exc), "非法 UTF-8 报出行号")
    else:
        check(False, "非法 UTF-8 报出行号")
    result = zhkit("audit", "--src", str(broken), "--out", str(broken / "review"))
    check(result.returncode == 0 and "跳过（找不到" in result.stdout, "缺 ini/bat 时降级不崩并提示")

    print("== 9. 过期键判定 ==")
    probe = Path(tempfile.mkdtemp(prefix="zhkit_probe_"))
    probe_menu = probe / "OptiScaler" / "menu"
    probe_menu.mkdir(parents=True)
    (probe_menu / "probe.cpp").write_text(
        '// "Latency"\n'
        "void f()\n"
        "{\n"
        '    ImGui::Text("Hooks");\n'
        '    ImGui::TextDisabled("Only In Comment");\n'
        "}\n", encoding="utf-8")
    rows, _seen, writable = targets.scan(probe_menu)
    menu_cat = cat.Catalog.load("menu")
    stale = menu_cat.unused(writable)
    check("Latency" not in writable, "注释内字面量不计入可写集合")
    check("Latency" in stale and "Hooks" not in stale, "只出现在注释里的词条判为过期键")
    probe_ini = probe / "OptiScaler.ini"
    probe_ini.write_text("; Select Upscaler for Dx11 games\n; Balanced              : 1.7\n",
                         encoding="utf-8")
    ini_seen = auditmod._ini_keys_seen(probe_ini)
    check("Select Upscaler for Dx11 games" in ini_seen
          and "Balanced              : 1.7" not in ini_seen, "ini 过期键只统计 apply 会替换的行")

    print("== 10. 相邻字面量 ==")
    (probe_menu / "join.cpp").write_text(
        "void g()\n"
        "{\n"
        '    ImGui::Text("Part one "\n'
        '                "part two");\n'
        '    ImGui::Text("Solo label");\n'
        "}\n", encoding="utf-8")
    joined = {row.value: row.joined for row in targets.scan(probe_menu)[0]}
    check(joined.get("Part one ") and joined.get("part two"), "拼接的两段都标记相连")
    check(joined.get("Solo label") is False, "独立字面量不标记相连")

    failed = [name for ok, name in RESULTS if not ok]
    print(f"\n共 {len(RESULTS)} 项，失败 {len(failed)}")
    for name in failed:
        print("  FAIL", name)
    if not failed:
        for temp in (work, broken.parent.parent, probe):
            shutil.rmtree(temp, ignore_errors=True)
    return 1 if failed else 0
