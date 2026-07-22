"""
RAG 检索工具（模型调用）。

将 `database.qdrant_client.QdrantManager` 的语义检索封装为可直接注册进
LangGraph 的 retriever tool，供 agent 决策是否调用。文档摄取（抓取 → 切分 →
写入）属于非模型调用的处理流程，见 `utils.ducument.ingest_web_pages`。

设计要点：
- retriever tool 返回 str（非 List[Document]），以匹配 LangGraph 节点函数的预期输入；
- 向量化统一走 embedding 工厂，QdrantManager 内部完成，本模块不关心 provider / 模型名。
"""

from langchain_core.tools import tool

from database.qdrant_client import QdrantManager
from utils.ducument import RAG_COLLECTION

# 单次检索返回的分片数量
RAG_TOP_K = 5

@tool
def retrieve_documents(query: str) -> str:
    """搜索知识库并返回与问题相关的文档内容。"""
    points = QdrantManager(RAG_COLLECTION).search(query, top_k=RAG_TOP_K)
    return "\n\n".join(point.payload.get("text", "") for point in points)


if __name__ == "__main__":
    # 手动冒烟测试：先经 utils.ducument.ingest_web_pages 摄取，再检索
    print(retrieve_documents.invoke({"query": "types of reward hacking"}))
