from utils.env import ENV, ModelConfig
from functools import lru_cache
import dashscope
from http import HTTPStatus


class DashScopeClientCfg:
    @staticmethod
    @lru_cache(maxsize=6)
    def get_client(
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> dashscope:
        dashscope.base_http_api_url = base_url or ENV.embedding_api_url
        dashscope.api_key = api_key or ENV.embedding_api_key
        return dashscope

    @classmethod
    def embed_documents(
        cls, model_name: str, input: Union[str, List[str]], text_type: str = "document"
    ) -> str:
        """
        批量文档向量
        """

        client = cls.get_client()
        resp = client.TextEmbedding.call(
            model=model_name, input=input, dimension=1024, text_type=text_type
        )
        if resp.status_code == HTTPStatus.OK:
            return resp.output

    @classmethod
    def embed_multi_independent(
        cls,
        model_name: str,
        input: List[Dict[str, str]],
        text_type: str = "document",
        isfusion=False,
    ) -> List[str]:
        """
        输入可以是视频
        video = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"
        input = [{'video': video}]
        或图片
        image = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
        input = [{'image': image}]
        """
        client = cls.get_client()
        resp = client.MultiModalEmbedding.call(
            model=model_name,
            input=input,
            dimension=1024,
            enable_fusion=isfusion,
            text_type=text_type,
        )
        if resp.status_code == HTTPStatus.OK:
            return resp.output


DashScopeClient = DashScopeClientCfg()
