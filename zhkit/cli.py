from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ASSETS, FONT_ASSET, FONT_SOURCE, INI_OVERRIDES, KINDS, system_font
from . import audit as auditmod
from . import font as fontmod
from . import patch
from . import targets
from .catalog import Catalog, read_text, resolve_menu


def cmd_font(args) -> int:
    menu_dir = resolve_menu(args.src)
    asset = Path(args.asset).expanduser()
    blob = fontmod.load(asset)
    if not blob:
        print(f"[失败] 找不到可用的字体资源：{asset}")
        return 1

    header = fontmod.pack(blob)
    fontmod.verify(header, blob)
    print(f"源码目录: {menu_dir}")
    print(f"字体资源: {asset}")
    print(f"模式    : {'check' if args.check else 'apply'}")
    print(f"[=] {len(blob) // 1024} KB TTF / {len(fontmod.cmap(blob))} 码点 → 数组 "
          f"{len(header.encode('ascii')) // 1024} KB")

    missing = fontmod.missing_glyphs(blob, Catalog.load("menu"))
    if missing:
        chars = "".join(sorted({char for _, char, _ in missing}))
        kinds = "、".join(sorted({reason for _, _, reason in missing}))
        print(f"[失败] 菜单字典有 {len(missing)} 个字渲染不出来（{kinds}）：{chars}")
        print("       本地重跑一次即可：python -m zhkit build-font（默认用系统微软雅黑）")
        return 1
    print()

    ok, notes = patch.install(menu_dir, header, args.check)
    for note in notes:
        print(note)
    print()
    print("结论：补丁已就位" if ok and not args.check else ("结论：检查通过" if ok else "结论：有未完成的步骤"))
    return 0 if ok else 1


def cmd_audit(args) -> int:
    summary, catalogs = auditmod.inspect(args.src, args.headers)
    summary.report = auditmod.write_report(summary, Path(args.out), catalogs)

    print(f"上游源码: {summary.menu_dir}")
    print(f"字典    : 菜单 {len(catalogs['menu'])} / ini {len(catalogs['ini'])} / bat {len(catalogs['bat'])} 条")
    print(f"界面文本: {summary.total} 条，已翻译 {summary.inplace + summary.unapplied}"
          f"（{summary.percent:.1f}%），未翻译 {summary.pending} 条")
    print(f"  已就位 {summary.inplace}（含有意保留英文），已译未应用 {summary.unapplied}，"
          f"字典暂无译文 {summary.pending}")
    if summary.root is None:
        print("ini/bat  : 跳过（找不到 OptiScaler.ini / setup_windows.bat）")
    else:
        print(f"ini/bat 未翻译: {len(summary.gaps)} 行")
    if summary.font is None:
        print("字体覆盖  : 未检查（找不到字体资源）")
    elif summary.font:
        print(f"字体覆盖  : 缺字 {len(summary.font)} 处，详见清单")
    else:
        print("字体覆盖  : 全部覆盖")
    print(f"过期键    : 菜单 {len(summary.stale['menu'])} / ini {len(summary.stale['ini'])}"
          f" / bat {len(summary.stale['bat'])}")
    if summary.total and summary.unapplied == 0 and summary.inplace > summary.total * 0.5:
        print("提示      : 源码看起来已经汉化，本体检应以 apply 之前的英文原树为准")
    print(f"清单已写入: {summary.report}")

    if summary.missing and not args.quiet:
        for item in sorted(summary.missing, key=lambda row: -row["count"])[:args.top]:
            hint = f"  ← 可复用 {item['suggest_from']!r}" if item["suggest_from"] else ""
            joined = "  ⇢ 与相邻字面量相连" if item.get("joined") else ""
            print(f"  ? [{item['count']}] {item['value']!r} @ {item['file']}:{item['line']}{hint}{joined}")
        if len(summary.missing) > args.top:
            print(f"  ... 其余 {len(summary.missing) - args.top} 条见清单")

    if args.all:
        others = [(entry, entry.kind()) for entry in summary.rows if entry.kind() != "ui"]
        for entry, kind in sorted(others, key=lambda pair: -pair[0].count)[:args.top]:
            name, line, _, _ = entry.first
            print(f"  {kind:<7} [{entry.count}] {entry.value!r} @ {name}:{line}")

    if args.strict and (summary.pending or summary.font or summary.gaps):
        return 1
    return 0


def cmd_apply(args) -> int:
    root = Path(args.src).expanduser().resolve()
    menu_dir = resolve_menu(str(root))
    parts = args.only or list(KINDS)

    print(f"源码目录: {menu_dir}")
    if args.dry_run:
        print("模式    : dry-run（不写文件）")
    print()

    if "menu" in parts:
        catalog = Catalog.load("menu")
        extra = targets.extra_source_files(root)
        seen = targets.values_in(menu_dir, args.headers, extra)
        total, touched = targets.apply_menu(menu_dir, catalog, args.headers,
                                            not args.comments, args.dry_run, extra)
        if not args.quiet:
            for name in touched:
                print(f"  {name}")
        print(f"菜单译文: {len(catalog)} 条字典，替换 {total} 处"
              + ("（dry-run 未落盘）" if args.dry_run else ""))
        stale = catalog.unused(seen)
        print(f"过期键  : {len(stale)} 条（源码里已找不到对应英文）")
        for key in stale[:10]:
            print(f"  STALE {key!r} -> {catalog[key]!r}")
        if len(stale) > 10:
            print(f"  ... 其余 {len(stale) - 10} 条略")
        if stale and total == 0:
            print("  提示：本次 0 处替换，源码可能已是汉化版，过期键应以英文原树为准")
        print()

    if "ini" in parts:
        path = root / "OptiScaler.ini"
        catalog = Catalog.load("ini")
        if not path.is_file():
            print(f"[!] 跳过：找不到 {path.name}")
        else:
            updated, hit, total = targets.translate_ini(read_text(path), catalog)
            print(f"ini 注释: 可译 {total} 条，命中 {hit} 条（UTF-8）")
            updated, forced, missing = targets.apply_ini_values(updated, INI_OVERRIDES)
            print("ini 取值: " + "，".join(f"{key}={value}" for key, value in INI_OVERRIDES.items())
                  + f"（改写 {forced} 处）")
            if missing:
                print(f"[!] ini 里找不到这些键，覆盖未生效：{', '.join(missing)}")
            if not args.dry_run:
                path.write_bytes(updated.encode("utf-8"))
            print()

    if "bat" in parts:
        path = root / "setup_windows.bat"
        catalog = Catalog.load("bat")
        if not path.is_file():
            print(f"[!] 跳过：找不到 {path.name}")
        else:
            updated, hit, total = targets.translate_bat(targets.read_bat(path), catalog)
            if not args.dry_run:
                path.write_bytes(targets.encode_bat(updated))
            print(f"bat 说明: 可译 {total} 条，命中 {hit} 条（GBK + CRLF）")
    return 0


def cmd_build_font(args) -> int:
    print(f"源字体  : {args.ttf}")
    fontmod.build_from(args.ttf, Path(args.out))
    return 0


def cmd_selftest(args) -> int:
    from . import selftest

    return selftest.main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhkit", description="OptiScaler 汉化工具链")
    sub = parser.add_subparsers(dest="command", required=True)

    font = sub.add_parser("font", help="注入内嵌字体补丁（打包 TTF → C 头文件）")
    font.add_argument("--src", required=True, help="上游源码仓库根或 OptiScaler/menu")
    font.add_argument("--check", action="store_true", help="只检查，不修改文件")
    font.add_argument("--asset", default=str(ASSETS / FONT_ASSET),
                      help="字体资源路径（字典用字不在其中时报错，需先跑 build-font）")
    font.set_defaults(func=cmd_font)

    audit = sub.add_parser("audit", help="上游同步体检（覆盖率、待翻译、缺字）")
    audit.add_argument("--src", required=True, help="上游源码仓库根或 OptiScaler/menu")
    audit.add_argument("--out", default="review", help="清单输出目录，默认 review")
    audit.add_argument("--headers", action="store_true", help="同时扫描 *.h / *.hpp")
    audit.add_argument("--top", type=int, default=10, help="终端最多打印条数，默认 10")
    audit.add_argument("--all", action="store_true", help="连日志/其他类也一起列出")
    audit.add_argument("--strict", action="store_true", help="有欠账时退出码 1")
    audit.add_argument("--quiet", action="store_true", help="少打印")
    audit.set_defaults(func=cmd_audit)

    apply = sub.add_parser("apply", help="把三份字典写进源码 / ini / bat（含 ini 取值覆盖）")
    apply.add_argument("--src", required=True, help="上游源码仓库根目录")
    apply.add_argument("--only", choices=list(KINDS), action="append", help="只处理指定部分，可重复")
    apply.add_argument("--headers", action="store_true", help="同时处理 *.h / *.hpp")
    apply.add_argument("--comments", action="store_true", help="连注释里的字面量也替换")
    apply.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    apply.add_argument("--quiet", action="store_true", help="不逐个文件打印")
    apply.set_defaults(func=cmd_apply)

    build = sub.add_parser("build-font", help="用系统字体裁剪出新的字体子集")
    build.add_argument("ttf", nargs="?", default=str(system_font()),
                       help=f"源字体路径，默认系统字体 {FONT_SOURCE}")
    build.add_argument("--out", default=str(ASSETS / FONT_ASSET), help="输出路径")
    build.set_defaults(func=cmd_build_font)

    selftest = sub.add_parser("selftest", help="回归自测（内置假源码树，约 5 秒）")
    selftest.set_defaults(func=cmd_selftest)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
