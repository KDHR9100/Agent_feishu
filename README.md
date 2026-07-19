# Feishu E-commerce Agent

基于 LangGraph + FastAPI 构建的电商运营智能 Agent 服务。

该项目目标是探索企业级 Agent 在电商运营场景中的应用，通过 Agent Workflow 编排不同业务 Skill，并通过 Tool 调用完成商品分析、广告分析、营销内容生成等任务。

当前版本实现了 Agent 服务化部署、任务路由和 Skill 模块化设计。

---

## 1. 项目背景

在电商运营过程中，运营人员通常需要频繁完成：

- 商品销售数据分析
- 广告投放效果分析
- 营销内容生成
- 活动策略制定

传统方式需要人工查询多个系统并进行分析，效率较低。

本项目尝试构建一个面向电商运营场景的 Agent：

用户通过自然语言提出需求，Agent 自动判断任务类型，选择对应 Skill，并调用业务工具完成任务。

---

## 2. 项目架构

当前版本架构：

```
                User

                 |
                 |

            FastAPI API

                 |
                 |

          LangGraph Workflow

                 |
                 |

              Router

        /        |        \

       /         |         \

 商品分析Skill  广告分析Skill  内容生成Skill

       |          |          |

 Product Tool  Ads Tool  Content Tool

                 |

              Result

```

---

## 3. 核心技术栈

### Agent Framework

- LangGraph
- LangChain

用于：

- Agent Workflow编排
- 状态管理
- 节点调度


### Backend

- FastAPI
- Uvicorn

用于：

- 提供HTTP接口
- 服务化部署Agent


### Development Environment

- Python 3.11
- Conda


---

# 4. 当前实现功能


## 4.1 Agent Workflow

基于 LangGraph 构建任务执行流程：

```
User Input

↓

Router

↓

Skill Selection

↓

Tool Execution

↓

Generate Response

```

---

## 4.2 Skill模块

目前实现三个业务Skill：

### 商品分析 Skill

示例：

```
分析商品销量下降
```

输出：

```json
{
    "sku":"SKU10086",
    "sales_change":"-20%",
    "ad_roi":"1.2",
    "rating":"3.8"
}

```


---

### 广告分析 Skill

示例：

```
分析广告ROI
```

输出：

```json
{
    "ROI":"1.8",
    "cost":"下降15%",
    "suggestion":"优化投放素材"
}

```


---

### 内容生成 Skill

示例：

```
生成618营销文案
```

输出：

```json
{
    "copy":"618大促，新品限时优惠"
}

```

---

# 5. 项目结构


```
Agent_feishu/

├── app/

│
├── main.py                 # FastAPI入口

│
├── agent/

│   ├── state.py            # Agent状态定义

│   ├── workflow.py         # LangGraph Workflow

│   └── router.py           # 任务路由

│
├── skills/

│   ├── product_skill.py    # 商品分析Skill

│   ├── ads_skill.py        # 广告分析Skill

│   └── content_skill.py    # 内容生成Skill

│
├── tools/

│   └── product.py          # 商品数据工具

│
└── README.md

```

---

# 6. Quick Start


## 6.1 创建环境


```bash
conda create -n feishuagent python=3.11

conda activate feishuagent

```


---

## 6.2 安装依赖


```bash
pip install langgraph langchain fastapi uvicorn

```


---

## 6.3 启动服务


```bash
uvicorn app.main:app --reload

```


启动成功：

```
Uvicorn running on http://127.0.0.1:8000

```


---

# 7. API调用


打开：

```
http://127.0.0.1:8000/docs
```


请求：

```
POST /chat
```


参数：

```
message:

分析商品销量下降

```


返回：

```json
{
 "answer":
 "商品分析..."
}

```

---

# 8. Roadmap


## Phase 1 ✅

基础 Agent Workflow

- [x] FastAPI服务
- [x] LangGraph Workflow
- [x] Router
- [x] Skill模块化
- [x] Tool调用


## Phase 2 🚧

智能化升级

- [ ] LLM Router
- [ ] Function Calling
- [ ] 多Agent协作
- [ ] Prompt模板管理


## Phase 3

企业化能力

- [ ] 飞书Bot接入
- [ ] 飞书Open API Tool
- [ ] RAG知识库
- [ ] Redis Memory
- [ ] Agent Evaluation


## Phase 4

生产部署

- [ ] Docker
- [ ] 日志追踪
- [ ] API鉴权
- [ ] Kubernetes部署


---

# 9. Future Vision

最终目标：

构建一个面向电商运营团队的企业级 Agent。

用户通过飞书输入自然语言任务：

例如：

```
分析最近7天销量下降商品，并生成优化建议

```

Agent自动：

1. 理解任务
2. 查询业务数据
3. 调用对应工具
4. 生成分析报告
5. 返回飞书消息或文档


---

# License

MIT License