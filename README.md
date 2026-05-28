# Personal Steward Agent

本地运行的个人管家 Multi-Agent 第一版，包含：

- 主管 Agent
- 学习规划 Agent
- PPT 制作 Agent
- 前沿资讯 Agent
- 本地 RAG 个人知识库
- 页面内通知中心
- 本地定时任务和错过任务补偿

## Run

```bash
python3 -m uvicorn app.main:app --reload --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

## Optional Environment Variables

第一版内置本地启发式模型，未配置 API Key 也能运行。后续可通过以下变量接入真实模型：

```bash
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## Data

所有数据默认保存在本地 `data/` 目录：

- `data/agent.db`: SQLite 主数据库
- `data/uploads/`: 上传资料
- `data/generated/`: 生成的 PPT
- `data/chroma/`: 本地向量库
