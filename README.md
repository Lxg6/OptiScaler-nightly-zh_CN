# OptiScaler 汉化版 nightly

GitHub Actions 每天检查 [optiscaler/OptiScaler](https://github.com/optiscaler/OptiScaler) 上游与本仓库翻译的更新，
有变化时自动拉取最新源码、注入中文字体补丁与全部译文后编译打包（上游无更新则不发布新包）。
产物目录结构与官方 nightly 完全一致，可与官方包互换。

多倍帧生成插件(asi)：https://github.com/dashdogy/MFG-Unlocker

## 下载与安装

- 到本仓库 [Releases](../../releases) 页下载最新的 `OptiScaler_zh-CN_*.7z`（上游或翻译有更新时自动构建，保留最近 14 个）。
- 解压后把全部文件放进游戏目录，运行 `setup_windows.bat`（已汉化）。卸载运行生成的 `卸载_OptiScaler.bat`。
- 与官方包的区别：未做代码签名（首次运行可能有 SmartScreen 提示）；菜单界面、ini 注释、setup 脚本说明均为中文。

## 上游更新时的维护

上游加了新菜单文字或新配置注释时，构建照常成功，新内容暂时显示英文。
到构建页下载 `translation-backlog` artifact（或本地运行下方体检命令）查看待翻译清单：

- 菜单新文本 → 补进 `dict_v10.json`
- ini 注释 / bat 说明新行 → 补进 `dict_files.json`
- 提交推送，第二天的自动构建即带上译文

本地体检命令（Python 3.10+，在仓库根目录运行）：

```
python tools_cn/update_upstream.py --src <上游源码目录> --out review
```

改动 tools_cn 下的脚本时，先跑 `python tools_cn/selftest.py`（约 5 秒）确认回归通过再提交。

脚本改自 https://github.com/CangShui/OptiScaler-zh_CN/

## 致谢

- [optiscaler/OptiScaler](https://github.com/optiscaler/OptiScaler) 及其上游依赖
- [CangShui/OptiScaler-zh_CN](https://github.com/CangShui/OptiScaler-zh_CN/)（脚本原作者）
