# RAG 知识库升级设计

> 将知识库从"玩具级混合检索"升级为现代 RAG 架构：向量数据库 + 两阶段检索 + 重排序 + 多格式导入。不改变单进程 MVP 架构约束。

## 一、当前状态与目标

### 1.1 当前状态

- SQLite 存储所有数据，向量以 JSON 字段存于 `knowledge_chunk_embeddings`
- 混合检索：关键词(45%) + FTS(25%) + 向量(30%) 固定权重合并
- 只支持 `.md` / `.txt` 文本导入
- 无查询增强，无重排序

### 1.2 目标

| 维度 | 当前 | 目标 |
|------|------|------|
| 向量存储 | SQLite JSON 字段 | Chroma 嵌入式向量数据库 |
| 检索策略 | 三路固定权重合并 | 查询重写 → 多路粗筛 → LLM 精排 |
| 分块 | 固定长度简单切分 | 段落感知 + overlap |
| 文件格式 | .md / .txt | .md / .txt / .pdf / 网页 |
| 召回质量 | 低（固定权重不适应不同查询） | 高（LLM 理解语义相关性） |

### 1.3 不做的事

- 不引入独立服务（Chroma 嵌入式模式，和 SQLite 一样的本地文件）
- 不改 `KnowledgeService` 对外接口（`search()` / `ingest()` 签名不变）
- 不移除 SQLite（文档元信息、chunk 元数据继续存 SQLite，Chroma 只管向量）
- 不支持扫描件 PDF（需要 OCR，未来再加）

## 二、架构变化

### 2.1 存储层

```
之前:
  SQLite: knowledge_documents + knowledge_chunks + knowledge_chunk_embeddings

之后:
  SQLite: knowledge_documents + knowledge_chunks（移除 embedding_json 列）
  Chroma: knowledge_chunks collection（存向量 + metadata + 文本）
```

Chroma 嵌入式模式，数据存本地目录 `./chroma_data/`，零运维。

### 2.2 依赖

```toml
dependencies = [
    "chromadb>=0.5.0",
    "pypdf>=5.0.0",
    "html2text>=2024.0",
]
```

## 三、Chroma Collection 设计

```
collection name: "knowledge_chunks"

schema:
  id:          "doc_{doc_id}_chunk_{chunk_index}"   # 确定性 ID，幂等
  embedding:   Qwen3-Embedding 1024 维向量
  metadata:
    chunk_id:      123                              # SQLite chunk id
    document_id:   5
    scope_type:    "public" | "user" | "group"
    scope_id:      "user_xxx" | "group_xxx" | ""
    domain:        "global" | "qa"
    source:        "confluence/onboarding.md"
    title:         "入职指南"
    chunk_index:   0
  document:     "入职第一周需要完成以下事项..."       # chunk 全文
```

Composite key `(document_id, chunk_index)` 保证幂等：重复导入同文件时先删旧 chunks 再插入。

## 四、检索流程

### 4.1 完整管线

```
用户查询: "上次讨论的用户增长方案？"
│
├─ Step 1: Query Rewriting（新增）
│   输入: 原始查询
│   输出: [原始查询, "用户拉新策略", "新用户获取方案"]
│   LLM 轻量调用，temperature=0.3
│
├─ Step 2: Multi-path Coarse Retrieval
│   ├─ 关键词匹配 (现有，保持)           → top-20
│   ├─ SQLite FTS (现有，保持)           → top-20
│   └─ Chroma 向量检索 (替代 JSON 向量)  → top-20
│   每路 top-20，合并去重按 chunk_id → 候选集 ~40-50 条
│
├─ Step 3: LLM Re-rank（新增）
│   输入: 原始查询 + 候选集文本列表
│   输出: top-5 最相关片段 + 相关性分数
│   逐条打分 0-10，按分排序
│
└─ Step 4: 返回 + 来源引用
   返回格式: [
     {chunk, title, source, score, scope_type, domain},
     ...
   ]
```

### 4.2 与当前检索的对比

| | 当前 | 目标 |
|------|------|------|
| 向量检索 | 遍历所有 chunks 逐条算 cosine | Chroma ANN 近似检索 |
| 合并策略 | 固定权重 0.45/0.25/0.30 | 粗筛不分权 → LLM 精排 |
| 查询增强 | 无 | Query Rewriting 多角度召回 |
| 结果数 | 固定 limit=5 | 粗筛 40-50 → 精排 top-5 |

### 4.3 Chroma 权限过滤

Chroma 原生 `where` 过滤替代 SQLite JOIN：

```python
collection.query(
    query_embeddings=[vec],
    n_results=20,
    where={
        "$or": [
            {"scope_type": "public"},
            {"scope_type": "user", "scope_id": user_id},
        ]
    }
)
```

## 五、分块策略

### 5.1 通用分块（.md / .txt）

从固定长度改为段落感知：

```python
def chunk_text(text: str, chunk_size=800, overlap=100) -> list[ChunkInput]:
    # 1. 按双换行切段落
    # 2. 段落过长时按句子二次切分
    # 3. 相邻块保留 overlap 字符重叠
    # 4. 返回 [ChunkInput(chunk_index, content, token_count), ...]
```

保持 `chunk_text()` 接口不变，内部增强，不影响现有调用方。

### 5.2 PDF 导入

```
pypdf.PdfReader → 逐页提取文本
  → 按空行/标题识别段落边界
  → 段落级分块（复用 chunk_text 逻辑）
  → 写入 Chroma
```

不依赖 OCR，只处理文本层 PDF。

### 5.3 网页导入

```
httpx.get(url) → html2text.HTML2Text().handle(html)
  → 正则去掉导航/页脚/广告噪声
  → 纯文本 → chunk_text()
  → 写入 Chroma
```

### 5.4 统一 CLI

扩展 `butler-ingest-knowledge` 命令，根据扩展名/URL 自动选解析器：

```bash
# 现有（保持）
butler-ingest-knowledge --file ./docs/readme.md --title "README"
# 新增
butler-ingest-knowledge --file ./docs/report.pdf --title "Q4报告"
butler-ingest-knowledge --url https://wiki.internal/onboarding --title "入职指南"
```

所有格式统一走 `KnowledgeService.ingest()`，内部按扩展名分发。

## 六、数据迁移

```
现有 knowledge_chunk_embeddings 表
  → 遍历所有 chunks
  → 已有 Qwen3 embedding → 直接写入 Chroma
  → 无 embedding 或 API key 变化 → 重新嵌入
  → 写入 Collection
  → 验证条目数一致后，删除 SQLite 向量表
```

迁移脚本：`src/cli/migrate_to_chroma.py`，幂等可重跑。

## 七、文件布局

```
新增/重写:
  src/knowledge/
  ├── chunking.py          # 增强: 段落感知分块 + overlap
  ├── embedding.py         # 不变
  ├── service.py           # 重写: Chroma 集成 + 两阶段检索 + 重排序
  ├── schemas.py           # 增强: 新返回字段 (relevance_score)
  ├── parsers/
  │   ├── __init__.py
  │   ├── markdown.py      # 从 service.py 提取
  │   ├── pdf.py            # 新增: pypdf 解析
  │   └── web.py            # 新增: 网页抓取
  └── reranker.py           # 新增: LLM 重排序 prompt

  src/cli/
  ├── ingest_knowledge.py  # 增强: 支持 --url 和 PDF import
  └── migrate_to_chroma.py # 新增: 一次性迁移脚本

修改:
  src/main.py              # 初始化 Chroma client + 注入 KnowledgeService
  pyproject.toml           # 新增 chromadb, pypdf, html2text 依赖

废弃:
  src/models/knowledge.py  # 移除 KnowledgeChunkEmbedding ORM (保留表用于迁移)
```

## 八、不兼容变更

- `knowledge_chunk_embeddings` 表迁移后废弃。迁移脚本保证数据不丢失
- `KnowledgeService` 构造函数新增 `chroma_client` 参数（可选，向后兼容——不传则回退到旧检索逻辑）
- `KnowledgeChunkEmbedding` ORM 标记为 deprecated，新代码不再写入
