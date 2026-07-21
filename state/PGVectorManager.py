from langchain_postgres import PGVector
from model.embeddings.client import Embeddings
from database.postgres import PostgresConfig
from functools import lru_cache

@lru_cache(maxsize=1)
def _get_retriever():
    vectorstore = PGVector.from_documents(
        documents=doc_splits,
        embedding=Embeddings(),
        connection=PostgresConfig.connection,
    )
    return vectorstore.as_retriever()
