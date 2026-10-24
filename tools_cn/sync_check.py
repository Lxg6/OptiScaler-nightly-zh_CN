#!/usr/bin/env python3
"""字符串分类器：把抽取出的字符串字面量归类为 comment / log / ui / other。

被 scan_remaining.py 与 update_upstream.py 复用，用来判断"是不是界面文本"。
"""
from __future__ import annotations

import re

# 明显的日志/调试/非界面文本特征
LOG_PATTERNS = re.compile(
    r"\{[0-9A-Za-z_]*:?X?\}|"
    r"\berror\b|\bfailed\b|\bresult:|\bcaptured\b|\bcount\b|"
    r"%[0-9\.]*[dflus]|"
    r"LOG_|::|Handle|SwapChain|swapchain|pSwap|vk[A-Z]|ImGui_Impl|"
    r"PWSTR|HWND|CommandQueue|CommandList|allocator|Fence|Semaphore|Descriptor|"
    r"Backbuffer|_vulkanObjects|\{ADEC",
    re.IGNORECASE,
)

# 界面文本判定：出现在 ImGui 调用、选项表或状态标记里
UI_PATTERNS = re.compile(
    r"ImGui::(Text|TextWrapped|TextDisabled|TextColored|Button|Checkbox|SliderFloat|"
    r"SliderInt|Combo|BeginCombo|MenuItem|BeginMenu|Selectable|InputInt|InputText|"
    r"CollapsingHeader|BeginTabItem|TreeNodeEx|SetTooltip|ProgressBar|RadioButton|"
    r"BeginTable|TableSetupColumn|BulletText|LabelText|SeparatorText)|"
    r"ScopedCollapsingHeader|ShowTooltip|ShowHelpMarker|AddOption|StatusFlag|"
    r"PopulateCombo|OpenWiki|TextLink"
)

IDENT_LIKE = re.compile(r"^[\w\./\\\-+%#]+$")
CAMEL_ID = re.compile(r"^[a-z][A-Za-z0-9_]*$")


def classify(entry: dict) -> str:
    """把一条字符串归类：comment / log / ui / other。

    ui    = 真正的界面文本（ImGui 标签、选项表文字、状态标记）
    log   = 日志、调试输出、错误码格式串
    other = 文件名、内部标识符、ImGui ID、纯符号等非界面文本
    """
    value = entry["value"]
    ctx = entry["files"][0]["ctx"] if entry.get("files") else ""
    stripped = value.strip()

    if entry.get("comment_only") or ctx.lstrip().startswith("//"):
        return "comment"
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", stripped):
        return "other"                      # 纯符号/分隔符/占位符
    if stripped.startswith("##"):
        return "other"                      # ImGui 内部 ID，不出现在界面上
    if LOG_PATTERNS.search(value) or "LOG_" in ctx:
        return "log"
    if stripped.startswith(("http://", "https://")):
        return "other"                      # 链接，不翻译
    if re.search(r"\.(dll|exe|ini|json|log|txt|h|cpp)$", stripped, re.IGNORECASE):
        return "other"                      # 文件名，不翻译
    if " " not in stripped and CAMEL_ID.match(stripped):
        return "other"                      # lowerCamelCase 内部 ID
    if UI_PATTERNS.search(ctx):
        return "ui"
    if " " not in stripped and re.match(r"^[A-Z][A-Za-z]+$", stripped):
        return "ui"                         # 首字母大写的单个单词（如 Latency/Status 标签）
    if " " not in stripped and IDENT_LIKE.match(stripped):
        return "other"
    return "ui"
