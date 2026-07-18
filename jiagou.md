ecommerce-agent/

│
├── backend/
│
│   ├── main.py                 # 服务入口
│
│   ├── api/
│   │   └── feishu.py            # 飞书Webhook
│
│   ├── agent/
│   │
│   │   ├── workflow.py          # LangGraph核心
│   │   ├── state.py
│   │   └── router.py
│
│   ├── skills/
│   │
│   │   ├── product.py           # 商品分析
│   │   ├── ads.py               # 广告分析
│   │   └── content.py           # 文案生成
│
│   ├── tools/
│   │
│   │   ├── product_api.py
│   │   ├── ads_api.py
│   │   └── feishu_api.py
│
│   ├── rag/
│   │
│   │   ├── retriever.py
│   │   └── vectorstore.py
│
│   └── memory/
│       └── redis.py
│
├── Dockerfile
│
└── requirements.txt
