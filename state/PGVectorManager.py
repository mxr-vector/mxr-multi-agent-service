from langchain_postgres import PGVector
from model.embeddings.langchain_adapter import get_langchain_embeddings
from database.postgres import PostgresConfig
from functools import lru_cache
from utils.ducument import doc_splits


@lru_cache(maxsize=1)
def _get_retriever():
    embeddings = get_langchain_embeddings()
    vectorstore = PGVector.from_documents(
        documents=doc_splits,
        embedding=embeddings,
        connection=PostgresConfig.connection,
    )
    return vectorstore.as_retriever()
