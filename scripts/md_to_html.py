"""将 docs/combined/ 下的 1 个 MD 文档转换为美观的 HTML"""
import markdown
from pathlib import Path

BASE_DIR = Path(r"/home/huajuanx/Agent_feishu")
SRC_DIR = BASE_DIR / "docs" / "combined"
OUT_DIR = SRC_DIR / "html"
OUT_DIR.mkdir(exist_ok=True)

FILES = [
    "01-项目全景与价值评估.md",
    "02-面试问答·技术原理与代码佐证.md",
    "03-面试话术·讲稿与临场应对.md",
    "04-求职策略与投递行动.md",
]

CSS = """
:root {
  --bg: #f8f9fa;
  --card: #ffffff;
  --text: #1a1a2e;
  --muted: #6c757d;
  --accent: #2563eb;
  --accent-light: #dbeafe;
  --border: #e2e8f0;
  --code-bg: #1e293b;
  --code-text: #e2e8f0;
  --blockquote-bg: #f0f7ff;
  --blockquote-border: #2563eb;
  --table-stripe: #f8fafc;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.75;
  font-size: 15px;
  padding: 0;
}

.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

/* 导航栏 */
.nav {
  background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
  padding: 20px 24px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.nav-inner {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.nav a {
  color: rgba(255,255,255,0.85);
  text-decoration: none;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 20px;
  transition: all 0.2s;
  white-space: nowrap;
}
.nav a:hover, .nav a.active {
  background: rgba(255,255,255,0.2);
  color: #fff;
}

/* 标题 */
h1 {
  font-size: 2em;
  font-weight: 700;
  margin: 0 0 24px;
  padding-bottom: 16px;
  border-bottom: 3px solid var(--accent);
  color: var(--text);
}
h2 {
  font-size: 1.5em;
  font-weight: 600;
  margin: 48px 0 16px;
  padding: 8px 0 8px 16px;
  border-left: 4px solid var(--accent);
  background: var(--accent-light);
  border-radius: 0 8px 8px 0;
  color: var(--text);
}
h3 {
  font-size: 1.2em;
  font-weight: 600;
  margin: 32px 0 12px;
  color: var(--text);
}
h4 {
  font-size: 1.05em;
  font-weight: 600;
  margin: 24px 0 8px;
  color: var(--muted);
}

/* 段落与列表 */
p { margin: 12px 0; }
ul, ol { margin: 12px 0 12px 24px; }
li { margin: 4px 0; }
li > ul, li > ol { margin: 2px 0 2px 16px; }

/* 引用块 */
blockquote {
  background: var(--blockquote-bg);
  border-left: 4px solid var(--blockquote-border);
  margin: 16px 0;
  padding: 16px 20px;
  border-radius: 0 8px 8px 0;
  font-size: 0.95em;
  color: #334155;
}
blockquote p { margin: 6px 0; }

/* 代码 */
code {
  background: #f1f5f9;
  color: #be185d;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
  font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
}
pre {
  background: var(--code-bg);
  color: var(--code-text);
  padding: 20px;
  border-radius: 10px;
  overflow-x: auto;
  margin: 16px 0;
  box-shadow: var(--shadow);
  line-height: 1.5;
}
pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: 0.85em;
}

/* 表格 */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 0.9em;
  box-shadow: var(--shadow);
  border-radius: 8px;
  overflow: hidden;
}
thead {
  background: linear-gradient(135deg, #1e3a5f, #2563eb);
  color: #fff;
}
th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
}
td {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
tbody tr:nth-child(even) { background: var(--table-stripe); }
tbody tr:hover { background: var(--accent-light); }

/* 分割线 */
hr {
  border: none;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--border), transparent);
  margin: 40px 0;
}

/* 复选框 */
input[type="checkbox"] {
  margin-right: 6px;
  accent-color: var(--accent);
}

/* 加粗 */
strong { color: var(--text); }

/* 链接 */
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* 页脚 */
.footer {
  text-align: center;
  margin-top: 60px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 13px;
}

/* 打印优化 */
@media print {
  .nav { display: none; }
  body { background: #fff; font-size: 12pt; }
  .container { max-width: 100%; padding: 0; }
  pre { white-space: pre-wrap; word-break: break-all; }
}

/* 移动端适配 */
@media (max-width: 640px) {
  .container { padding: 20px 16px 60px; }
  h1 { font-size: 1.6em; }
  h2 { font-size: 1.3em; }
  table { font-size: 0.8em; }
  th, td { padding: 8px 10px; }
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<nav class="nav">
  <div class="nav-inner">
    <a href="01-项目全景与价值评估.html" {active_1}>01 项目全景</a>
    <a href="02-面试问答·技术原理与代码佐证.html" {active_2}>02 技术原理</a>
    <a href="03-面试话术·讲稿与临场应对.html" {active_3}>03 面试话术</a>
    <a href="04-求职策略与投递行动.html" {active_4}>04 求职策略</a>
  </div>
</nav>
<div class="container">
{content}
<div class="footer">
  由 Markdown 转换生成 &middot; 电商运营智能 Agent 平台面试备战资料
</div>
</div>
</body>
</html>"""

EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "nl2br",
]


def convert(md_file: str):
    md_text = (SRC_DIR / md_file).read_text(encoding="utf-8")
    html_body = markdown.markdown(md_text, extensions=EXTENSIONS)
    title = md_text.split("\n")[0].lstrip("# ").strip()

    idx = FILES.index(md_file)
    actives = [""] * 4
    actives[idx] = 'class="active"'

    html = HTML_TEMPLATE.format(
        title=title,
        css=CSS,
        content=html_body,
        active_1=actives[0],
        active_2=actives[1],
        active_3=actives[2],
        active_4=actives[3],
    )

    out_name = md_file.replace(".md", ".html")
    (OUT_DIR / out_name).write_text(html, encoding="utf-8")
    print(f"  ✓ {out_name}")


if __name__ == "__main__":
    print("开始转换 Markdown → HTML ...")
    for f in FILES:
        convert(f)
    print(f"\n完成！HTML 文件已保存到: {OUT_DIR}")
