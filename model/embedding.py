
from utils.env import ENV
class EmbeddingModels:

    def getLocalModels(self):
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=ENV.embeddings_model,  # 或 4B / 8B
            model_kwargs={"device": "cuda"},  # 沒GPU就用cpu
            encode_kwargs={"normalize_embeddings": True},
        )

    def getOpenAIModels(self):
        '''
        
        '''
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            api_key=ENV.get(""),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model=ENV.embeddings_model,
            check_embedding_ctx_length=False,  # 关键：不加这个会因为默认做token化校验而报 InvalidParameter 错误
        )


    def get_multi_modal_independent_model(self):
        from langchain_multi_modal import MultiModalEmbeddings
        return MultiModalEmbeddings(
            model_name=ENV.embeddings_model,
            model_kwargs={"device": "cuda"},
            encode_kwargs={"normalize_embeddings": True},
        )
