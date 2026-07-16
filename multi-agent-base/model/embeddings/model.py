from utils.env import ENV,ModelConfig
from langchain_core.embeddings import Embeddings



class EmbeddingOpenAIModels:

    def getLocalTextModel(self):
        """
        OpenAI兼容协议，仅支持文本向量。
        DashScope云端 / 自建vLLM-TEI服务通用，同一个类只是环境变量指向不同地址。
        """
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            api_key=ENV.get(ModelConfig.EMBEDDING_API_LOCAL_KEY),
            base_url=ENV.get(ModelConfig.EMBEDDING_API_LOCAL_URL),
            model="text-embedding-v4"
        )

    def getCloudTextModel(self):
        """
        OpenAI兼容协议，仅支持文本向量。
        DashScope云端通用，同一个类只是环境变量指向不同地址。
        """
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            api_key=ENV.get(ModelConfig.EMBEDDING_API_CLOUD_KEY),
            base_url=ENV.get(ModelConfig.EMBEDDING_API_CLOUD_URL),
            model="text-embedding-v4",
        )


class EmbeddingDashScopeModels:
    def getTextModel(self, inputs: Union[str, List[str]],text_type: str="document") -> str:
        """
        DashScope原生协议，支持多模态独立向量（embed_image）+ 多模态融合向量（embed_fusion）。
        目前只有云端有这个服务，没有开源框架支持自建。
        https://bailian.console.aliyun.com/cn-beijing?tab=doc#/doc/?type=model&url=2842587

        text_type: 'query'：用于用户输入的查询文本。模型将生成一个类似“标题”的向量，更具方向性，专为“提问”和“查找”进行优化。

        text_type: 'document' (默认值)：用于存入底库的文档文本。模型将生成一个类似“正文”的向量，包含更全面的信息，专为“被匹配”进行优化。
        """
        import dashscope
        from http import HTTPStatus
        resp = dashscope.TextEmbedding.call(
            model="text-embedding-v4",
            input=inputs,
            dimension=1024,
            text_type=text_type
        )
        if resp.status_code == HTTPStatus.OK:
            return resp.output

    def getMultiIndependent(self, inputs: List[Dict[str, str]], text_type: str = "document") -> List[str]:
        '''
        输入可以是视频
        video = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"
        input = [{'video': video}]
        或图片
        image = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
        input = [{'image': image}]
        '''
        import dashscope
        resp = dashscope.MultiModalEmbedding.call(
            # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx",
            api_key=ENV.get(ModelConfig.CLOUD_EMBEDDING_API_KEY),
            model="tongyi-embedding-vision-plus",
            input=inputs,
            dimension=1024,
            text_type=text_type
        )
        if resp.status_code == HTTPStatus.OK:
            return resp.output
