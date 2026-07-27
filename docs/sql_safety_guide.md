# 数据库 SQL 安全指南（面向转行开发者）

> 本文档以本项目 (`Agent_feishu`) 的真实代码为例，帮助你从零理解 SQL 注入风险和防御手段。
> 即使你没有计算机科学背景，也能看懂。

---

## 1. 什么是 SQL 注入？

### 一个生活中的比喻

想象你去银行办业务，你需要填一张表格：

```
姓名：__________
业务：取款 1000 元
```

正常的流程是：柜员读取你的姓名，然后执行"取款 1000 元"这个操作。

但如果有人这样填写：

```
姓名：张三
业务：取款 1000 元；然后把保险柜的钱全给我
```

如果柜员**真的按照字面意思执行了**——这就是"注入"攻击。用户在本该填写"数据"的地方，偷偷塞进了"指令"。

### SQL 注入的技术原理

SQL 是数据库的"语言"。当我们用 Python 查询数据库时，本质上是拼出一段 SQL 指令发给数据库执行。

**有漏洞的代码（字符串拼接）：**

```python
# 危险！千万不要这样写！
user_input = request.form["name"]
sql = f"SELECT * FROM users WHERE name = '{user_input}'"
result = conn.execute(sql)
```

正常用户输入 `张三`，SQL 变成：

```sql
SELECT * FROM users WHERE name = '张三'
```

看起来没问题。但如果恶意用户输入 `'; DROP TABLE users; --`，SQL 变成：

```sql
SELECT * FROM users WHERE name = ''; DROP TABLE users; --'
```

这条语句做了三件事：
1. `SELECT * FROM users WHERE name = ''` —— 查询一个空名字（无害）
2. `DROP TABLE users` —— **删除整个用户表！**
3. `--'` —— `--` 是 SQL 的注释符，把后面多余的 `'` 注释掉

### SQL 注入的危害

| 危害类型 | 说明 | 举例 |
|---------|------|------|
| 数据泄露 | 攻击者可以读取数据库中所有数据 | 窃取用户密码、手机号、订单信息 |
| 数据篡改 | 攻击者可以修改或删除数据 | 修改账户余额、删除订单记录 |
| 权限提升 | 攻击者可以绕过登录验证 | 输入 `' OR '1'='1` 跳过密码校验 |
| 系统破坏 | 攻击者可以删除整个数据库表 | `DROP TABLE` 导致服务瘫痪 |

---

## 2. 本项目如何防范 SQL 注入

本项目使用 **SQLAlchemy** 库（Python 最流行的数据库工具库之一），通过**参数化查询**来防止 SQL 注入。

### 核心机制：`text()` 函数 + 参数绑定

本项目的 `DatabaseTool` 类有两个核心方法 `query()` 和 `execute()`，它们是所有数据库操作的入口：

```python
# 来自 app/tools/database_tool.py

from sqlalchemy import create_engine, text

class DatabaseTool:
    def query(self, sql: str, params: Optional[Dict[str, Any]] = None):
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            columns = result.keys()
            return [dict(zip(columns, row)) for row in result.fetchall()]

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None):
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            conn.commit()
            return {"affected_rows": result.rowcount}
```

关键点：

1. **`text(sql)`**：SQLAlchemy 的 `text()` 函数将 SQL 字符串标记为"可执行 SQL"，同时启用参数绑定功能。
2. **`:param` 语法**：SQL 中的 `:sku`、`:ad_id` 等是**占位符**（placeholder），表示"这里将来会被填入一个值"。
3. **`params` 字典**：实际的参数值通过第二个参数传入，SQLAlchemy 会**自动转义**这些值。

### 实际例子：`get_product_sales` 方法

```python
# 来自 app/tools/database_tool.py

def get_product_sales(self, sku: Optional[str] = None, days: int = 7):
    if sku:
        date_threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()
        sql = """SELECT sku, product_name, category, sales_volume, revenue, cost, inventory, avg_price, date
                 FROM product_sales
                 WHERE sku = :sku AND date >= :date_threshold
                 ORDER BY date DESC"""
        return self.query(sql, {"sku": sku, "date_threshold": date_threshold})
```

这段代码中：
- `:sku` 和 `:date_threshold` 是占位符
- 实际的 `sku` 值和 `date_threshold` 值通过 `{"sku": sku, "date_threshold": date_threshold}` 传入
- **即使用户传入的 `sku` 包含恶意 SQL 代码，SQLAlchemy 也会把它当作普通文本处理**，不会当作 SQL 指令执行

### 为什么 `text()` 是安全的？

`text()` 函数告诉 SQLAlchemy："这条 SQL 里的 `:xxx` 是参数占位符，请帮我把参数值和 SQL 指令分开传给数据库。"

数据库在收到请求时，会先**编译 SQL 模板**（不含参数值），再**单独接收参数值**。这样参数值就永远不可能被误认为 SQL 指令的一部分。

---

## 3. 参数化查询 vs 字符串拼接 对比

### 危险写法：字符串拼接（f-string / format / +）

```python
# 危险！用户输入直接拼进 SQL
user_input = "'; DROP TABLE users; --"
sql = f"SELECT * FROM users WHERE name = '{user_input}'"
# 最终 SQL:
# SELECT * FROM users WHERE name = ''; DROP TABLE users; --'
# 数据库会执行两条语句，第二条会删除整张表！

result = conn.execute(sql)
```

```python
# 危险！format 方法同样不安全
sql = "SELECT * FROM orders WHERE status = '{}'".format(user_input)

# 危险！字符串拼接同样不安全
sql = "SELECT * FROM orders WHERE status = '" + user_input + "'"
```

### 安全写法：参数化查询

```python
# 安全！SQLAlchemy 自动转义特殊字符
from sqlalchemy import text

user_input = "'; DROP TABLE users; --"
sql = "SELECT * FROM users WHERE name = :name"
result = conn.execute(text(sql), {"name": user_input})
# user_input 被当作纯数据处理，永远不会被当作 SQL 代码执行
# 数据库只会查找 name 等于 "'; DROP TABLE users; --" 这个字符串的用户
```

### 对比总结

| 维度 | 字符串拼接（危险） | 参数化查询（安全） |
|------|-------------------|-------------------|
| 写法 | `f"...'{user_input}'..."` | `"...:param..."` + `{"param": value}` |
| 用户输入的处理 | 直接插入 SQL 字符串 | 作为独立参数传递给数据库 |
| 恶意输入的后果 | 可能执行额外 SQL | 仅作为数据值匹配 |
| 性能 | 每次生成新的 SQL，无法缓存 | SQL 模板可被数据库缓存复用 |
| 代码可读性 | 拼接复杂时难以维护 | 参数和 SQL 分离，清晰明了 |

---

## 4. 本项目各方法的 SQL 安全等级

以下是 `app/tools/database_tool.py` 中所有方法的安全分析：

| 方法 | SQL 方式 | 安全等级 | 说明 |
|------|---------|---------|------|
| `query(sql, params)` | `text()` + params 字典 | 安全 | 核心查询方法，所有参数通过字典绑定 |
| `execute(sql, params)` | `text()` + params 字典 | 安全 | 核心执行方法，同上 |
| `get_product_sales(sku, days)` | `:sku`, `:date_threshold` 参数化 | 安全 | 用户输入的 sku 作为参数绑定；无 sku 时使用静态 SQL |
| `get_product_by_sku(sku)` | `:sku` 参数化 | 安全 | sku 通过参数绑定 |
| `get_all_products()` | 静态 SQL，无用户输入 | 安全 | SQL 完全硬编码，无注入风险 |
| `get_product_categories()` | 静态 SQL，无用户输入 | 安全 | SQL 完全硬编码，无注入风险 |
| `get_ads_performance(ad_id, days)` | `:ad_id`, `:date_threshold` 参数化 | 安全 | ad_id 通过参数绑定；无 ad_id 时使用静态 SQL |
| `get_ads_by_platform()` | 静态 SQL，无用户输入 | 安全 | SQL 完全硬编码，无注入风险 |
| `get_campaign_performance(campaign_id)` | `:campaign_id` 参数化 | 安全 | campaign_id 通过参数绑定；无 campaign_id 时使用静态 SQL |

**结论：本项目所有方法均使用参数化查询或静态 SQL，不存在 SQL 注入风险。**

---

## 5. 面试常问的 SQL 安全问题

### Q1: "你在项目中如何防止 SQL 注入？"

**使用 STAR 方法回答（情境-任务-行动-结果）：**

> **S（情境）**：在我的 Agent_feishu 项目中，需要通过 Python 后端查询数据库中的商品销售和广告投放数据，这些数据包含用户可控的查询参数（如商品 SKU、广告 ID）。
>
> **T（任务）**：我需要确保这些用户输入不会被恶意利用来执行非授权的 SQL 操作。
>
> **A（行动）**：我使用 SQLAlchemy 的 `text()` 函数配合命名参数（`:param` 语法）实现参数化查询。所有用户输入都通过参数字典传递，而非拼接进 SQL 字符串。例如查询商品销售时使用 `WHERE sku = :sku`，然后将实际的 sku 值通过 `{"sku": user_input}` 传入。我还封装了统一的 `query()` 和 `execute()` 方法作为所有数据库操作的入口，确保整个项目的 SQL 执行方式一致且安全。
>
> **R（结果）**：经过安全审查，项目中所有 9 个数据库操作方法均不存在 SQL 注入风险。这种统一封装的方式也降低了后续开发者引入安全漏洞的可能性。

### Q2: "参数化查询为什么能防止 SQL 注入？"

> 参数化查询的核心原理是**将 SQL 指令和数据分离**。数据库引擎会先编译 SQL 模板（确定执行计划），然后再绑定参数值。参数值在编译阶段之后才填入，所以无论参数内容是什么，都不会改变 SQL 的结构。就像寄快递时，收件地址是打印在面单上的——你不可能在"包裹内容"那一栏写一个新地址让快递员改送。

### Q3: "除了参数化查询，还有哪些防御 SQL 注入的手段？"

> 1. **ORM（对象关系映射）**：如 SQLAlchemy ORM、Django ORM，通过 Python 对象操作数据库，自动生成安全的 SQL
> 2. **输入验证**：对用户输入进行白名单校验（如 SKU 只允许字母和数字）
> 3. **最小权限原则**：数据库账户只授予必要的权限，如只读查询账户不应有 DROP TABLE 权限
> 4. **WAF（Web 应用防火墙）**：在应用层之前拦截常见的 SQL 注入模式
> 5. **存储过程**：将 SQL 逻辑封装在数据库端，减少应用端直接拼接 SQL 的机会

---

## 6. 关键概念速查

| 概念 | 解释 | 类比 |
|------|------|------|
| **SQL Injection（SQL 注入）** | 攻击者通过在用户输入中嵌入恶意 SQL 代码来操纵数据库的攻击方式 | 在表格中偷偷塞入额外指令 |
| **Parameterized Query（参数化查询）** | SQL 中使用占位符代替实际值，参数值单独传递，确保数据与指令分离 | 表格设计成"只能在指定格子填写内容"的格式 |
| **Prepared Statement（预编译语句）** | 数据库预先编译 SQL 模板，再绑定参数，参数化查询的底层实现机制 | 柜员先确认业务流程，再填入具体数字 |
| **ORM（Object-Relational Mapping，对象关系映射）** | 用 Python 对象代替手写 SQL 来操作数据库的技术 | 用图形化界面操作数据库，不用写 SQL |
| **SQLAlchemy `text()`** | SQLAlchemy 库中将 SQL 字符串标记为可执行语句并启用参数绑定的函数 | 给 SQL 指令盖上"正式文件"的章，同时开启安全模式 |
| **SQL 占位符（`:param`）** | SQLAlchemy 中命名参数的标记，形如 `:sku`、`:ad_id`，运行时被实际值替换 | 表格中的空格，等待填入具体内容 |

---

> **记住一条铁律：永远不要把用户输入直接拼接进 SQL 字符串。永远使用参数化查询。**
