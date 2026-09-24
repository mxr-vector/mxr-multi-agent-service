import time
import uuid
from typing import Any

import httpx

from database.postgre_client import get_session
from database.system.model_config import ModelConfigRepository
from exception.bad_except import bad_except

# 掩码占位标记：前端未修改密钥时回传的展示值含此串，服务层据此判定“不更新 api_key”
API_KEY_MASK = "****"


def mask_api_key(raw: str | None) -> str:
    """对 api_key 脱敏：长度 ≥ 12 保留前 4 后 4、中间以 **** 替代；否则全掩码。"""
    if not raw:
        return ""
    if len(raw) >= 12:
        return f"{raw[:4]}{API_KEY_MASK}{raw[-4:]}"
    return API_KEY_MASK


def _to_masked_dict(config) -> dict:
    """ORM 转字典并对 api_key 脱敏（对外响应统一走此出口）。"""
    data = config.to_dict()
    data["api_key"] = mask_api_key(data.get("api_key"))
    return data


def _get_candidate_models_urls(base_url: str) -> list[str]:
    """生成 OpenAI 兼容 /models 候选探测地址列表。"""
    url = base_url.strip().rstrip("/")
    if url.endswith("/models"):
        return [url]
    if url.endswith("/v1"):
        return [f"{url}/models", f"{url[:-3]}/models"]
    return [f"{url}/v1/models", f"{url}/models"]


def _extract_model_names(resp_json: Any) -> list[str]:
    """从 OpenAI 兼容 /models 响应中提取模型 ID 列表并去重排序。"""
    names: list[str] = []
    if isinstance(resp_json, dict):
        raw_list = resp_json.get("data")
        if raw_list is None:
            raw_list = resp_json.get("models")
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict):
                    m_id = item.get("id") or item.get("name")
                    if m_id and isinstance(m_id, str):
                        names.append(m_id)
                elif isinstance(item, str):
                    names.append(item)
    elif isinstance(resp_json, list):
        for item in resp_json:
            if isinstance(item, dict):
                m_id = item.get("id") or item.get("name")
                if m_id and isinstance(m_id, str):
                    names.append(m_id)
            elif isinstance(item, str):
                names.append(item)

    seen = set()
    result = []
    for n in names:
        n_clean = n.strip()
        if n_clean and n_clean not in seen:
            seen.add(n_clean)
            result.append(n_clean)
    return sorted(result)


class ModelConfigService:
    """
    模型配置业务层。

    负责编排持久层调用与业务规则：查询返回掩码 api_key、更新时 role/is_builtin
    不可变、api_key 缺省或掩码占位不覆盖、内置行禁删。每个方法在共享会话中
    开启事务并提交。配置快照刷新由路由层在写操作成功后触发（本层保持纯粹）。
    """

    async def list(self) -> list[dict]:
        """全量返回模型配置（api_key 掩码，按 role 升序）。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            items = await repo.list()
            return [_to_masked_dict(item) for item in items]

    async def get_by_role(self, role: str) -> dict:
        """按 role 查询模型配置（api_key 掩码），不存在时抛业务异常。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get_by_role(role)
            if config is None:
                bad_except(f"模型配置不存在: {role}")
            return _to_masked_dict(config)

    async def update(
        self,
        config_id: uuid.UUID,
        name: str | None = None,
        model_name: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        context_window: int | None = None,
        extra: dict | None = None,
        remark: str | None = None,
    ) -> dict:
        """
        原子更新单行模型配置（单行 UPDATE）：role/is_builtin 不可变；
        api_key 为空或为掩码占位（含 ****）时保持原值不变；不存在时抛业务异常。
        """
        # 掩码占位或空 → 视为“不修改密钥”，避免把掩码值写回覆盖真实密钥
        if not api_key or API_KEY_MASK in api_key:
            api_key = None
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"模型配置不存在: {config_id}")
            config = await repo.update(
                config_id,
                name=name,
                model_name=model_name,
                api_url=api_url,
                api_key=api_key,
                provider=provider,
                timeout=timeout,
                max_retries=max_retries,
                context_window=context_window,
                extra=extra,
                remark=remark,
            )
            await session.commit()
            return _to_masked_dict(config)

    async def delete(self, config_id: uuid.UUID) -> None:
        """带守卫的物理删除：内置行（is_builtin）拒绝删除。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"模型配置不存在: {config_id}")
            if config.is_builtin:
                bad_except("内置模型配置不允许删除")
            await repo.delete(config_id)
            await session.commit()

    async def _resolve_url_and_key(
        self,
        config_id: uuid.UUID | None,
        api_url: str | None,
        api_key: str | None,
    ) -> tuple[str, str]:
        """
        解析测试或拉取请求的目标 api_url 与真实 api_key：
        若传入 config_id，优先在未显式传递或传入掩码时回退库中保存的值。
        """
        db_url: str | None = None
        db_key: str | None = None
        if config_id:
            async with get_session() as session:
                repo = ModelConfigRepository(session)
                config = await repo.get(config_id)
                if config is None:
                    bad_except(f"模型配置不存在: {config_id}")
                db_url = config.api_url
                db_key = config.api_key

        effective_url = (api_url.strip() if api_url and api_url.strip() else db_url) or ""
        if not effective_url:
            bad_except("接口地址不能为空")
        if not (effective_url.startswith("http://") or effective_url.startswith("https://")):
            bad_except("接口地址必须以 http:// 或 https:// 开头")

        # 密钥解析：未传或为掩码占位则回退库中真实密钥
        if not api_key or API_KEY_MASK in api_key:
            effective_key = db_key or ""
        else:
            effective_key = api_key.strip()

        return effective_url, effective_key

    async def test_connection(
        self,
        config_id: uuid.UUID | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """
        测试目标模型接口连通性，探测 /v1/models 或基地址并返回耗时（ms）。
        """
        effective_url, effective_key = await self._resolve_url_and_key(config_id, api_url, api_key)
        candidates = _get_candidate_models_urls(effective_url)
        # 基地址也作为备选探针
        base_clean = effective_url.strip().rstrip("/")
        if base_clean not in candidates:
            candidates.append(base_clean)

        headers: dict[str, str] = {}
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"

        start_time = time.perf_counter()
        last_error_msg = ""
        last_status_code: int | None = None

        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            for url in candidates:
                try:
                    resp = await client.get(url, headers=headers)
                    latency_ms = max(1, round((time.perf_counter() - start_time) * 1000))
                    last_status_code = resp.status_code
                    if resp.status_code == 200:
                        return {
                            "connected": True,
                            "latency_ms": latency_ms,
                            "status_code": 200,
                            "msg": f"接口连通正常 ({latency_ms}ms)",
                        }
                    elif resp.status_code in (401, 403):
                        return {
                            "connected": False,
                            "latency_ms": latency_ms,
                            "status_code": resp.status_code,
                            "msg": f"接口可达但认证失败 (HTTP {resp.status_code}, {latency_ms}ms)",
                        }
                    elif resp.status_code == 404:
                        # 404 说明路径不对，继续尝试下一个候选地址
                        continue
                    elif resp.status_code < 500:
                        return {
                            "connected": True,
                            "latency_ms": latency_ms,
                            "status_code": resp.status_code,
                            "msg": f"接口响应正常 (HTTP {resp.status_code}, {latency_ms}ms)",
                        }
                    else:
                        last_error_msg = f"服务端异常 (HTTP {resp.status_code})"
                except httpx.TimeoutException:
                    latency_ms = round((time.perf_counter() - start_time) * 1000)
                    return {
                        "connected": False,
                        "latency_ms": latency_ms,
                        "status_code": None,
                        "msg": f"请求超时，超过 10 秒无响应 ({latency_ms}ms)",
                    }
                except httpx.ConnectError as e:
                    latency_ms = round((time.perf_counter() - start_time) * 1000)
                    return {
                        "connected": False,
                        "latency_ms": latency_ms,
                        "status_code": None,
                        "msg": f"无法连接到目标地址: {e}",
                    }
                except Exception as e:
                    last_error_msg = str(e)

        latency_ms = max(1, round((time.perf_counter() - start_time) * 1000))
        if last_status_code == 404:
            return {
                "connected": False,
                "latency_ms": latency_ms,
                "status_code": 404,
                "msg": f"服务可达但接口路径未找到 (HTTP 404, {latency_ms}ms)",
            }
        return {
            "connected": False,
            "latency_ms": latency_ms,
            "status_code": last_status_code,
            "msg": last_error_msg or f"连通失败 ({latency_ms}ms)",
        }

    async def get_available_models(
        self,
        config_id: uuid.UUID | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """
        请求远程 OpenAI 兼容接口（v1/models）拉取可用模型列表。
        """
        effective_url, effective_key = await self._resolve_url_and_key(config_id, api_url, api_key)
        candidates = _get_candidate_models_urls(effective_url)

        headers: dict[str, str] = {}
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            for url in candidates:
                try:
                    resp = await client.get(url, headers=headers)
                    latency_ms = max(1, round((time.perf_counter() - start_time) * 1000))
                    if resp.status_code == 200:
                        try:
                            resp_json = resp.json()
                        except Exception:
                            bad_except("模型列表响应非标准 JSON 格式")
                        models = _extract_model_names(resp_json)
                        return {
                            "models": models,
                            "latency_ms": latency_ms,
                        }
                    elif resp.status_code in (401, 403):
                        bad_except(f"认证失败 (HTTP {resp.status_code})，请检查 API 密钥是否正确")
                    elif resp.status_code == 404:
                        continue
                    else:
                        bad_except(f"拉取模型列表失败 (HTTP {resp.status_code})")
                except httpx.TimeoutException:
                    bad_except("请求模型列表超时，请检查接口地址或网络连接")
                except httpx.ConnectError as e:
                    bad_except(f"无法连接到目标接口地址: {e}")

        bad_except("未找到可用模型接口，目标服务可能不支持 /v1/models 协议 (HTTP 404)")

