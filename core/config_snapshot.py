"""
进程内配置快照（CFG）—— 模型配置与运行参数的运行期只读事实源。

设计（见 openspec/changes/add-model-config-hot-reload/design.md D2/D3）：
- 读写分离：数据库读取是 async，而模型工厂等消费方是同步函数。CFG 在启动时
  一次性把 sys_model_config（chat/rewrite/visual/rerank 四行）与 sys_config
  白名单标量参数加载为不可变快照，运行期以同步属性访问读取（零 IO）。
- fail-fast：`await CFG.load()` 在 lifespan 启动执行，任一必需项缺失或校验失败
  即抛异常拒绝启动（与 ENV_CONFIG.require 语义一致）。
- 写时刷新 + last-known-good：配置写接口 commit 成功后调用 `await CFG.refresh()`，
  校验通过则原子替换快照并清空 rerank client 缓存；失败则保留旧快照、记 error 日志、
  返回 False（不影响本次写操作的成败）。
"""

from dataclasses import dataclass

from database.postgre_client import get_session
from database.system.config import ConfigRepository
from database.system.model_config import ModelConfigRepository
from utils.logger import logger

# 四个模型角色（sys_model_config.role），四行必须齐全
MODEL_ROLES = ("chat", "rewrite", "visual", "rerank")
# 标量运行参数白名单键（sys_config.key），全部为必需正整数
SCALAR_KEYS = (
    "RAG_CANDIDATE_POOL_SIZE",
    "RAG_FINAL_TOP_K",
    "RAG_REFLECT_ROUND_CAP",
    "CHAT_CHECKPOINT_TTL_DAYS",
    "CHAT_HISTORY_MAX_MESSAGES",
)
# chat/visual 角色的超时/重试缺省值（NULL 时回落，保持迁移前 ENV 行为）
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 2


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


@dataclass(frozen=True)
class ConfigSnapshot:
    """一次加载得到的完整配置快照（不可变；刷新时整体原子替换）。"""

    chat: ModelRoleConfig
    rewrite: ModelRoleConfig
    visual: ModelRoleConfig
    rerank: ModelRoleConfig
    rag_candidate_pool_size: int
    rag_final_top_k: int
    rag_reflect_round_cap: int
    chat_checkpoint_ttl_days: int
    chat_history_max_messages: int


def _coerce_role(role: str, row, errors: list[str]) -> ModelRoleConfig | None:
    """把一行模型配置转为快照对象，缺失/非法项追加到 errors 并返回 None。"""
    if row is None:
        errors.append(f"缺少模型配置角色行: role={role}")
        return None
    for field in ("model_name", "api_url", "api_key"):
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


async def _build_snapshot() -> ConfigSnapshot:
    """从数据库全量加载并校验，返回不可变快照；任一必需项缺失/非法则抛 ValueError。"""
    errors: list[str] = []
    async with get_session() as session:
        model_rows = await ModelConfigRepository(session).list()
        config_repo = ConfigRepository(session)
        scalar_raw = {key: (await config_repo.get_by_key(key)) for key in SCALAR_KEYS}

    by_role = {row.role: row for row in model_rows}
    roles = {
        role: _coerce_role(role, by_role.get(role), errors) for role in MODEL_ROLES
    }
    scalars = {
        key: _coerce_positive_int(
            key, scalar_raw[key].value if scalar_raw[key] else None, errors
        )
        for key in SCALAR_KEYS
    }

    if errors:
        raise ValueError("配置快照加载失败：\n- " + "\n- ".join(errors))

    return ConfigSnapshot(
        chat=roles["chat"],
        rewrite=roles["rewrite"],
        visual=roles["visual"],
        rerank=roles["rerank"],
        rag_candidate_pool_size=scalars["RAG_CANDIDATE_POOL_SIZE"],
        rag_final_top_k=scalars["RAG_FINAL_TOP_K"],
        rag_reflect_round_cap=scalars["RAG_REFLECT_ROUND_CAP"],
        chat_checkpoint_ttl_days=scalars["CHAT_CHECKPOINT_TTL_DAYS"],
        chat_history_max_messages=scalars["CHAT_HISTORY_MAX_MESSAGES"],
    )


class _ConfigManager:
    """配置快照单例管理器：启动加载、写时刷新、运行期同步读取。"""

    def __init__(self) -> None:
        self._snapshot: ConfigSnapshot | None = None

    async def load(self) -> None:
        """lifespan 启动加载；失败直接抛出以拒绝启动（fail-fast）。"""
        self._snapshot = await _build_snapshot()
        logger.info("[CFG] 配置快照加载完成（模型角色 4 + 标量参数 5）")

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
            raise RuntimeError("配置快照尚未加载（CFG.load 应在 lifespan 启动时执行）")
        return self._snapshot

    # ---------- 模型角色配置（同步读取） ----------
    @property
    def chat(self) -> ModelRoleConfig:
        return self._current.chat

    @property
    def rewrite(self) -> ModelRoleConfig:
        return self._current.rewrite

    @property
    def visual(self) -> ModelRoleConfig:
        return self._current.visual

    @property
    def rerank(self) -> ModelRoleConfig:
        return self._current.rerank

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


# 全局单例：消费方 import CFG 后同步读取，写接口 commit 成功后 await CFG.refresh()
CFG = _ConfigManager()
