def main() -> None:
    from model.embeddings.langchain_adapter import get_langchain_embeddings

    embedding_client = get_langchain_embeddings()
    document_vectors = embedding_client.embed_documents(
        ["Hello, world!", "Provider-neutral embeddings."],
    )
    query_vector = embedding_client.embed_query("Hello")
    print(document_vectors)
    print(query_vector)


if __name__ == "__main__":
    main()
