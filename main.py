def main():
    print("Hello from multi-agent-service!")

    #--------openai-------

    # from model.embeddings.clients.openai import OpenAIClient
    # embed_docs = OpenAIClient.embed_documents("Qwen3-Embedding-0.6B", "Hello, world!")
    # print(embed_docs)

    #--------cohere-------
    from model.embeddings.clients.cohere import CohereClient 
    embed_docs = CohereClient.embed_documents("Qwen3-Embedding-0.6B", "Hello, world!")

    import json
    print(embed_docs)

   


if __name__ == "__main__":
    main()
