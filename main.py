from model.embeddings.factory import get_embedding_client


def main() -> None:
    embedding_client = get_embedding_client()
    document_vectors = embedding_client.embed_documents(
        ["Hello, world!", "Provider-neutral embeddings."],
    )
    query_vector = embedding_client.embed_query("Hello")
    print(document_vectors)
    print(query_vector)


if __name__ == "__main__":
    main()
