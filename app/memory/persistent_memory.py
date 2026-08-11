"""
持久记忆模块 (s09)

设计:
- 记忆存储为 .memory/ 目录下的 Markdown 文件 (带 frontmatter)
- MEMORY.md 作为索引常驻 system prompt (仅名称+描述)
- 按需匹配注入: 用户提问时按关键词匹配相关记忆
- "记住"提取器: 检测用户表达稳定偏好时自动保存
- 分类: user (用户画像) / feedback (反馈偏好) / project (项目上下文) / reference (参考资料)

解耦设计:
- 独立于 local_memory (对话历史), 互不依赖
- workflow 通过 get_memory_index() 获取索引, get_relevant_memories() 获取匹配记忆
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger("persistent_memory")

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".memory")
MEMORY_INDEX = os.path.join(MEMORY_DIR, "MEMORY.md")

CATEGORIES = {"user", "feedback", "project", "reference"}

# "记住" 触发关键词
REMEMBER_TRIGGERS = ["记住", "以后都", "每次都", "我的偏好", "默认用", "习惯是", "记得"]


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _parse_frontmatter(content: str) -> tuple:
    """解析 Markdown frontmatter, 返回 (meta, body)"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return {}, content
    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2].strip()


def _format_frontmatter(meta: dict, body: str) -> str:
    """格式化为带 frontmatter 的 Markdown"""
    lines = ["---"]
    for k, v in meta.items():
        lines.append("%s: %s" % (k, v))
    lines.append("---\n")
    lines.append(body)
    return "\n".join(lines)


def save_memory(name: str, content: str, category: str = "user",
                tags: str = "", description: str = "") -> bool:
    """保存一条记忆到文件"""
    if category not in CATEGORIES:
        category = "user"
    _ensure_dir()
    meta = {
        "name": name,
        "category": category,
        "tags": tags,
        "description": description or content[:80],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # 文件名: category_name.md (替换空格和特殊字符)
    safe_name = re.sub(r'[^\w]', '_', name)[:50]
    filename = "%s_%s.md" % (category, safe_name)
    filepath = os.path.join(MEMORY_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(_format_frontmatter(meta, content))
    logger.info("[memory] saved: %s -> %s", name, filename)
    _update_index()
    return True


def _update_index():
    """重建 MEMORY.md 索引 (仅名称+描述)"""
    _ensure_dir()
    entries = list_memories()
    lines = ["# Memory Index\n"]
    if not entries:
        lines.append("(no memories yet)\n")
    else:
        for e in entries:
            lines.append("- [%s] %s (%s)" % (
                e.get("category", "?"),
                e.get("name", "?"),
                e.get("description", "")[:60],
            ))
    with open(MEMORY_INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def list_memories() -> List[Dict]:
    """列出所有记忆的元数据"""
    if not os.path.exists(MEMORY_DIR):
        return []
    entries = []
    for fname in sorted(os.listdir(MEMORY_DIR)):
        if not fname.endswith(".md") or fname == "MEMORY.md":
            continue
        filepath = os.path.join(MEMORY_DIR, fname)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                meta, _ = _parse_frontmatter(f.read())
            if meta:
                entries.append(meta)
        except Exception:
            pass
    return entries


def get_memory_index() -> str:
    """获取 MEMORY.md 索引内容 (注入 system prompt)"""
    if not os.path.exists(MEMORY_INDEX):
        _update_index()
    try:
        with open(MEMORY_INDEX, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def get_relevant_memories(user_input: str, limit: int = 3) -> List[Dict]:
    """按关键词匹配返回相关记忆 (简单子串匹配)"""
    entries = list_memories()
    if not entries:
        return []
    scored = []
    input_lower = user_input.lower()
    for e in entries:
        score = 0
        # 匹配 name
        if e.get("name", "").lower() in input_lower:
            score += 3
        # 匹配 tags
        for tag in e.get("tags", "").split(","):
            tag = tag.strip().lower()
            if tag and tag in input_lower:
                score += 2
        # 匹配 description 关键词
        for word in e.get("description", "").split():
            if len(word) > 1 and word.lower() in input_lower:
                score += 1
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


def extract_memory_from_input(user_input: str) -> Optional[Dict]:
    """
    "记住"提取器: 检测用户是否表达稳定偏好, 返回提取结果或 None

    示例:
    - "记住我的店铺主营女装" -> {name: "主营类目", content: "店铺主营女装", category: "user"}
    - "以后都默认看最近7天的数据" -> {name: "默认时间范围", content: "默认看最近7天", category: "feedback"}
    """
    if not user_input:
        return None
    for trigger in REMEMBER_TRIGGERS:
        if trigger in user_input:
            # 简单提取: trigger 后面的内容作为记忆
            idx = user_input.index(trigger)
            content = user_input[idx + len(trigger):].strip()
            if not content or len(content) < 3:
                continue
            # 截断过长的内容
            content = content[:200]
            # 简单分类: 含"喜欢/偏好/习惯" -> user, 含"默认/以后/每次" -> feedback
            if any(k in content for k in ("默认", "以后", "每次")):
                category = "feedback"
            elif any(k in content for k in ("店铺", "类目", "主营")):
                category = "project"
            else:
                category = "user"
            # 生成名称: 取前 10 个字
            name = content[:10].replace(" ", "_")
            return {
                "name": name,
                "content": content,
                "category": category,
                "trigger": trigger,
            }
    return None


def try_save_from_input(user_input: str) -> Optional[Dict]:
    """尝试从用户输入提取并保存记忆, 返回保存结果或 None"""
    result = extract_memory_from_input(user_input)
    if result:
        save_memory(
            name=result["name"],
            content=result["content"],
            category=result["category"],
            description=result["content"][:80],
        )
        return result
    return None


def deduplicate():
    """定期整理去重: 按名称合并重复记忆"""
    entries = list_memories()
    seen = {}
    duplicates = []
    for e in entries:
        key = "%s_%s" % (e.get("category", ""), e.get("name", ""))
        if key in seen:
            duplicates.append(e)
        else:
            seen[key] = e
    # 删除重复文件
    for d in duplicates:
        safe_name = re.sub(r'[^\w]', '_', d.get("name", ""))[:50]
        filename = "%s_%s.md" % (d.get("category", "user"), safe_name)
        filepath = os.path.join(MEMORY_DIR, filename)
        try:
            os.remove(filepath)
            logger.info("[memory] deduplicated: %s", filename)
        except Exception:
            pass
    _update_index()
    return len(duplicates)
