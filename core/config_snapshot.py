"""
进程内配置快照（CFG）—— 模型配置与运行参数的运行期只读事实源。

设计（见 openspec/changes/add-model-config-hot-reload/design.md D2/D3）：
- 读写分离：数据库读取是 async，而模型工厂等消费方是同步函数。CFG 在启动时
  一次性把 sys_model_config 全部角色行（角色集合来自字典 model_types，运行期
  可增删）与 sys_config 白名单标量参数加载为不可变快照，运行期以同步属性
  访问读取（零 IO）。
- fail-fast：`await CFG.load()` 在 lifespan 启动执行，任一必需项缺失或校验失败
  即抛异常拒绝启动（与 ENV_CONFIG.require 语义一致）。
- 写时刷新 + last-known-good：配置写接口 commit 成功后调用 `await CFG.refresh()`，
  校验通过则原子替换快照并清空 rerank client 缓存；失败则保留旧快照、记 error 日志、
  返回 False（不影响本次写操作的成败）。
- 独立脚本引导：不经 lifespan 的入口（main.py demo、各模块 __main__ 冒烟块）
  在使用模型工厂前需先加载快照：同步上下文调 `CFG.load_blocking()`，
  已在事件循环内则 `await CFG.load()`。
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

from database.postgre_client import get_session
from database.system.config import ConfigRepository
from database.system.model_config import ModelConfigRepository
from utils.logger import logger

# 模型角色分类字典类型键（sys_dict_type.type / sys_dict_data.dict_type）：
# 字典项的 value 即 sys_model_config.role，新增模型类型只需维护字典与配置行，
# 无需改代码（对齐前端 ModelCard 的 model_types 消费约定）
MODEL_TYPES_DICT_KEY = "model_types"
# 正整数标量运行参数键（sys_config.key），全部为必需正整数
INT_SCALAR_KEYS = (
    "RAG_CANDIDATE_POOL_SIZE",
    "RAG_FINAL_TOP_K",
    "RAG_REFLECT_ROUND_CAP",
    "CHAT_CHECKPOINT_TTL_DAYS",
    "CHAT_HISTORY_MAX_MESSAGES",
    "CHAT_MAX_OUTPUT_TOKENS",
)
# 自托管 drawio embed 实例地址（http(s) URL，前端 iframe 加载与 postMessage origin 校验用）
DRAWIO_EMBED_URL_KEY = "DRAWIO_EMBED_URL"
# 标量运行参数白名单键全集（/system/configs/scalars 的返回范围）
SCALAR_KEYS = INT_SCALAR_KEYS + (DRAWIO_EMBED_URL_KEY,)


def scalar_value_type(key: str) -> str:
    """标量参数的值类型（供前端数据驱动校验；类型权威随消费契约定义在此）。

    int=正整数、url=http(s) 地址、text=无格式约束（非契约的内置参数）。
    前端经 /scalars 响应拿到此值即可按需校验，无需镜像后端白名单键。
    """
    if key in INT_SCALAR_KEYS:
        return "int"
    if key == DRAWIO_EMBED_URL_KEY:
        return "url"
    return "text"


# chat/visual 角色的超时/重试缺省值（NULL 时回落，保持迁移前 ENV 行为）
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 2
# 上下文窗口(token)缺省值（NULL 时回落，目前 chat 使用）
DEFAULT_CONTEXT_WINDOW = 200000


@dataclass(frozen=True)
class ModelRoleConfig:
    """单个模型角色的不可变配置（对应 sys_model_config 一行）。"""

    role: str
    model_name: str
    api_url: str
    api_key: str
    provider: str | None
    timeout: int | None
    max_retries: int | None
    context_window: int


@dataclass(frozen=True)
class ConfigSnapshot:
    """一次加载得到的完整配置快照（不可变；刷新时整体原子替换）。

    roles 为 {模型角色: 配置} 映射：角色集合来自字典 model_types（运行期可
    增删），新增模型类型只需维护字典与 sys_model_config 行，无需改代码；
    标量运行参数仍为固定契约字段。
    """

    roles: dict[str, ModelRoleConfig]
    rag_candidate_pool_size: int
    rag_final_top_k: int
    rag_reflect_round_cap: int
    chat_checkpoint_ttl_days: int
    chat_history_max_messages: int
    chat_max_output_tokens: int
    drawio_embed_url: str


def _coerce_role(role: str, row, errors: list[str]) -> ModelRoleConfig | None:
    """把一行模型配置转为快照对象，缺失/非法项追加到 errors 并返回 None。"""
    if row is None:
        errors.append(f"缺少模型配置角色行: role={role}")
        return None
    # api_key 允许为空：本地 vLLM / 免鉴权 OpenAI 兼容端点无需凭证，
    # 空值透传为 "Authorization: Bearer "，不影响调用（仅 model_name/api_url 必填）
    for field in ("model_name", "api_url"):
        if not (getattr(row, field, None) or "").strip():
            errors.append(f"模型配置 role={role} 的必填字段为空: {field}")
    timeout = row.timeout
    max_retries = row.max_retries
    if role in ("chat", "visual"):
        # chat/visual 的超时与重试为必需数值，NULL 时回落缺省，保持迁移前行为
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
    return ModelRoleConfig(
        role=role,
        model_name=(row.model_name or "").strip(),
        api_url=(row.api_url or "").strip(),
        api_key=(row.api_key or "").strip(),
        provider=(row.provider or None),
        timeout=timeout,
        max_retries=max_retries,
        context_window=(
            row.context_window
            if row.context_window is not None
            else DEFAULT_CONTEXT_WINDOW
        ),
    )


def _coerce_positive_int(key: str, raw: str | None, errors: list[str]) -> int:
    """把标量参数解析为正整数，缺失/非法/非正数追加到 errors 并返回占位 0。"""
    if raw is None:
        errors.append(f"缺少必需运行参数: {key}")
        return 0
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        errors.append(f"运行参数 {key} 不是合法整数: {raw!r}")
        return 0
    if value <= 0:
        errors.append(f"运行参数 {key} 必须为正整数: {value}")
    return value


def _coerce_http_url(key: str, raw: str | None, errors: list[str]) -> str:
    """把标量参数解析为 http(s) URL，缺失/非法追加到 errors 并返回空串占位。"""
    value = (raw or "").strip()
    if not value:
        errors.append(f"缺少必需运行参数: {key}")
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append(f"运行参数 {key} 必须为合法的 http(s) URL: {raw!r}")
    return value


async def _load_model_roles() -> tuple[str, ...]:
    """从字典 model_types 读取全部启用模型角色（value 即 sys_model_config.role）。

    角色集合随字典增删自动变化：新增模型类型只需在系统字典维护 model_types
    项并插入对应 sys_model_config 行，无需改代码；字典类型缺失或没有任何
    启用项时抛错拒绝启动（fail-fast，语义与 ENV_CONFIG.require 一致）。
    字典数据属系统字典模块，统一经 DictDataService 查询（不直接触碰其 repository），
    status="active" 由 service 过滤，仅返回启用角色。
    """
    from service.system.dict import DictDataService

    rows = await DictDataService().list_by_type(MODEL_TYPES_DICT_KEY, status="active")
    roles = tuple(row["value"] for row in rows)
    if not roles:
        raise ValueError(
            f"缺少模型角色分类字典: {MODEL_TYPES_DICT_KEY}"
            "（请先在系统字典中维护模型类型）"
        )
    return roles


async def _build_snapshot() -> ConfigSnapshot:
    """从数据库全量加载并校验，返回不可变快照；任一必需项缺失/非法则抛 ValueError。"""
    errors: list[str] = []
    async with get_session() as session:
        model_rows = await ModelConfigRepository(session).list()
        config_repo = ConfigRepository(session)
        scalar_raw = {key: (await config_repo.get_by_key(key)) for key in SCALAR_KEYS}
    # 字典数据经 DictDataService 查询（service 内部自管会话）
    model_roles = await _load_model_roles()

    by_role = {row.role: row for row in model_rows}
    roles = {
        role: _coerce_role(role, by_role.get(role), errors) for role in model_roles
    }
    scalars = {
        key: _coerce_positive_int(
            key, scalar_raw[key].value if scalar_raw[key] else None, errors
        )
        for key in INT_SCALAR_KEYS
    }
    drawio_row = scalar_raw[DRAWIO_EMBED_URL_KEY]
    drawio_embed_url = _coerce_http_url(
        DRAWIO_EMBED_URL_KEY, drawio_row.value if drawio_row else None, errors
    )

    if errors:
        raise ValueError("配置快照加载失败：\n- " + "\n- ".join(errors))

    return ConfigSnapshot(
        roles=roles,
        rag_candidate_pool_size=scalars["RAG_CANDIDATE_POOL_SIZE"],
        rag_final_top_k=scalars["RAG_FINAL_TOP_K"],
        rag_reflect_round_cap=scalars["RAG_REFLECT_ROUND_CAP"],
        chat_checkpoint_ttl_days=scalars["CHAT_CHECKPOINT_TTL_DAYS"],
        chat_history_max_messages=scalars["CHAT_HISTORY_MAX_MESSAGES"],
        chat_max_output_tokens=scalars["CHAT_MAX_OUTPUT_TOKENS"],
        drawio_embed_url=drawio_embed_url,
    )


class _ConfigManager:
    """配置快照单例管理器：启动加载、写时刷新、运行期同步读取。

    模型角色配置通过 __getattr__ 按角色名动态访问（CFG.<role>），角色集合
    由字典 model_types 决定；标量运行参数保持显式 property。
    """

    def __init__(self) -> None:
        self._snapshot: ConfigSnapshot | None = None

    async def load(self) -> None:
        """lifespan 启动加载；失败直接抛出以拒绝启动（fail-fast）。"""
        self._snapshot = await _build_snapshot()
        logger.info(
            f"[CFG] 配置快照加载完成（模型角色 {len(self._snapshot.roles)}"
            f" + 标量参数 {len(SCALAR_KEYS)}）"
        )

    def load_blocking(self) -> None:
        """同步脚本入口的引导加载：供不经 lifespan 的独立脚本/冒烟块使用。

        在无事件循环的同步上下文中一次性加载快照，并在临时事件循环关闭前
        释放引擎连接池（asyncpg 连接绑定创建时的循环，残留池内会毒化后续
        asyncio.run 开启的新循环）；已在事件循环内时由 asyncio.run 报错拦下，
        此时应改用 `await CFG.load()`。
        """

        async def _bootstrap() -> None:
            from database.postgre_client import get_async_engine

            await self.load()
            await get_async_engine().dispose()

        asyncio.run(_bootstrap())

    async def refresh(self) -> bool:
        """
        写时刷新：重新加载并校验，通过则原子替换快照并清空 rerank client 缓存；
        失败保留旧快照、记 error 日志、返回 False（不抛给调用方）。
        """
        try:
            new_snapshot = await _build_snapshot()
        except Exception as exc:
            logger.error(
                f"[CFG] 配置刷新校验失败，沿用旧快照（last-known-good）：{exc}"
            )
            return False
        self._snapshot = new_snapshot
        # rerank client 在构造时固化了模型名/凭证，刷新后需清缓存以令新配置生效
        try:
            from model.rerank.factory import RerankFactory

            RerankFactory._build_client.cache_clear()
        except Exception as exc:  # 清缓存失败不应阻断刷新
            logger.warning(f"[CFG] rerank client 缓存清理失败：{exc}")
        logger.info("[CFG] 配置快照已刷新")
        return True

    @property
    def _current(self) -> ConfigSnapshot:
        if self._snapshot is None:
            raise RuntimeError(
                "配置快照尚未加载：Web 服务经 lifespan 执行 await CFG.load()；"
                "独立脚本/冒烟块需先调用 CFG.load_blocking()（事件循环内用 await CFG.load()）"
            )
        return self._snapshot

    # ---------- 模型角色配置（同步读取；角色集合来自字典 model_types） ----------
    def __getattr__(self, name: str) -> ModelRoleConfig:
        """按角色名读取模型配置（CFG.<role>，角色由字典 model_types 动态决定）。

        新增模型类型无需修改本类；角色名不存在时抛 AttributeError，快照未加载
        时由 _current 抛出明确 RuntimeError。
        """
        roles = self._current.roles
        if name in roles:
            return roles[name]
        raise AttributeError(
            f"模型角色不在配置快照中: {name!r}"
            "（字典 model_types 未定义该分类，或 sys_model_config 缺少对应角色行）"
        )

    # ---------- 标量运行参数（同步读取） ----------
    @property
    def rag_candidate_pool_size(self) -> int:
        return self._current.rag_candidate_pool_size

    @property
    def rag_final_top_k(self) -> int:
        return self._current.rag_final_top_k

    @property
    def rag_reflect_round_cap(self) -> int:
        return self._current.rag_reflect_round_cap

    @property
    def chat_checkpoint_ttl_days(self) -> int:
        return self._current.chat_checkpoint_ttl_days

    @property
    def chat_history_max_messages(self) -> int:
        return self._current.chat_history_max_messages

    @property
    def chat_max_output_tokens(self) -> int:
        return self._current.chat_max_output_tokens

    @property
    def drawio_embed_url(self) -> str:
        return self._current.drawio_embed_url


# 全局单例：消费方 import CFG 后同步读取，写接口 commit 成功后 await CFG.refresh()
CFG = _ConfigManager()
