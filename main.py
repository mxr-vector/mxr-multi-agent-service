from model.embeddings.client import Embeddings


def main() -> None:
    embeddings = Embeddings.from_env()
    document_vectors = embeddings.embed_documents(
        ["Hello, world!", "Provider-neutral embeddings."],
    )
    query_vector = embeddings.embed_query("Hello")
    print(document_vectors)
    print(query_vector)


if __name__ == "__main__":
    main()
