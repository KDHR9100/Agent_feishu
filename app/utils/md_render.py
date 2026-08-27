"""Markdown -> 飞书卡片渲染工具。

飞书普通文本消息不渲染 Markdown, 技能输出的 # 标题、* 列表等符号会原样显示。
本模块把 Markdown 转成飞书交互卡片支持的 lark_md 子集:
- 标题 (#/##/###)   -> 加粗文本
- 无序列表 (-/*/+)  -> "• " 项目符号
- 有序列表 (1.)     -> 保留编号
- 表格 (| a | b |)  -> 按行拼接为文本, 跳过分隔行
- 代码块/行内代码    -> 纯文本 (lark_md 不支持代码样式)
- 引用 (>)          -> ❝ 前缀
- 加粗/斜体/链接     -> 保留 (lark_md 原生支持)
"""
import re
import json
from typing import List, Tuple


def _convert_inline(text: str) -> str:
    """行内元素转换: 保留加粗/斜体/链接, 去掉反引号"""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def md_to_lark_md(md: str) -> str:
    """把完整 Markdown 文本转成 lark_md 兼容文本"""
    out_lines: List[str] = []
    in_code = False

    for line in md.split("\n"):
        stripped = line.strip()

        # 代码块围栏: 内部内容按纯文本处理
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out_lines.append(line)
            continue

        # 标题 -> 加粗
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            out_lines.append("**%s**" % _convert_inline(m.group(2).strip()))
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            out_lines.append("────────────────")
            continue

        # 表格: 跳过分隔行(|---|---|), 其余行按 " | " 拼接
        if stripped.startswith("|"):
            if re.match(r"^\|?[\s:\-|]+\|?$", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            out_lines.append(" | ".join(_convert_inline(c) for c in cells if c))
            continue

        # 无序列表 -> 项目符号 (保留两级缩进)
        m = re.match(r"^[-*+]\s+(.*)$", stripped)
        if m:
            indent = len(line) - len(line.lstrip())
            prefix = "　" * min(indent // 2, 2) + "• "
            out_lines.append(prefix + _convert_inline(m.group(1)))
            continue

        # 有序列表 -> 保留编号
        m = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if m:
            out_lines.append("%s. %s" % (m.group(1), _convert_inline(m.group(2))))
            continue

        # 块引用
        if stripped.startswith(">"):
            out_lines.append("❝ " + _convert_inline(stripped.lstrip("> ").strip()))
            continue

        out_lines.append(_convert_inline(stripped))

    # 折叠连续空行为单个空行
    result: List[str] = []
    for ln in out_lines:
        if ln == "" and result and result[-1] == "":
            continue
        result.append(ln)
    return "\n".join(result).strip()


def extract_title(md: str, default: str = "分析结果") -> Tuple[str, str]:
    """提取首个标题作为卡片标题, 返回 (标题, 去掉首个标题后的正文)"""
    lines = md.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            body = "\n".join(lines[:i] + lines[i + 1:])
            return title[:40], body
    return default, md


def has_markdown(text: str) -> bool:
    """判断文本是否包含需要渲染的 Markdown 结构"""
    if not isinstance(text, str):
        return False
    return bool(
        re.search(r"^#{1,6}\s", text, re.M)
        or re.search(r"^\s*[-*+]\s", text, re.M)
        or re.search(r"^\s*\d+[.)]\s", text, re.M)
        or "**" in text
        or "```" in text
        or re.search(r"^\|.*\|\s*$", text, re.M)
    )


def build_answer_card(md: str, template: str = "blue") -> str:
    """把 Markdown 答案构建成飞书交互卡片 JSON 字符串"""
    title, body = extract_title(md)
    content = md_to_lark_md(body)
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            }
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def strip_markdown(text: str) -> str:
    """兜底用: 剥掉常见 Markdown 符号, 输出纯文本"""
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)          # 标题符
    text = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", text, flags=re.M)  # 列表符 -> 项目符号
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)                   # 代码围栏
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)                # 加粗
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)     # 斜体
    text = re.sub(r"`([^`]+)`", r"\1", text)                      # 行内代码
    return text
