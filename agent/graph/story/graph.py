"""
剧本创作图（LangGraph）—— 技能工具循环（渐进披露）+ 流式正文外发。

职责划分（对齐 agent/graph/chat_graph.py 范式）：
- 图负责 AI 编排：系统提示装配（技能文件清单 / 制作参数 / 历史按输入预算
  裁剪）、生成模型装配（输出预算与停顿超时的故事链路专用覆盖）、技能工具
  循环（bind_tools skill_read → 模型先完整阅读 SKILL.md、再按需读取
  references → ToolMessage 回填 → 漏读作废纠正 → 超轮数切无工具模型强制
  收尾 → 空响应重试）；
- 业务（SSE 帧序号与队列、写库时序、互斥、双轨剥离与角色卡落库、终态收尾）
  留在 service/story/generation.py，不感知模型与工具细节（见 design D9）。

节点（全部 async）：
- compose：唯一节点。按 _SKILL_TOOL_ROUND_CAP 上限内循环调用生成模型：
  工具轮 content 不出帧（转发策略见 _stream_round），已读技能的轮次缓冲
  转正实时外发；未读技能直接输出的轮次整轮作废并纠正一次，仍漏读则接受
  输出并记审计标记 skipped_skill_read；轮数超限回填占位 ToolMessage 后切
  无工具模型强制收尾（对齐 chat_graph 的悬空 tool_calls 处理）。

流式契约（stream_mode）：
- custom（get_stream_writer）：{"type": "think", "text": ...} 进度、
  {"type": "answer", "delta": ...} 正文增量、{"type": "audit",
  "skill_audit": {...}} 审计快照（服务层不转发给前端，仅并入任务 params；
  失败路径也能拿到失败前的已读文件清单）；
- updates：终态 {"answer", "skill_audit"} 供服务层落库收尾。

入口：模块级单例 `story_graph = StoryGraph()`，`story_graph.get()` 惰性编译。
无 checkpointer：每轮生成相互独立、历史经业务表注入系统提示（见 design D1）。
调用时 config 可携带 `{"configurable": {"session_id": session_id_hex}}`（仅日志
关联用）；输入 state 为 `{idea, style_key, params_snapshot, history_lines}`。
"""

import asyncio
from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from agent.constants.enums.story import StoryNode
from agent.prompts.story import HISTORY_EMPTY, SCRIPT_SYSTEM_PROMPT
from agent.skills.loader import get_style, read_skill_file, readable_file_hint
from agent.tools.story_skill_tools import SKILL_READ_TOOL_NAME, build_skill_read_tool
from core.config_snapshot import CFG
from exception.bad_except import bad_except
from model.chat.factory import build_chat_model
from model.visual.factory import build_visual_model
from service.story.storage import image_to_data_uri
from utils.logger import logger
from utils.token_count import count_messages_tokens, count_tokens

# 输入预算安全边际（覆盖估算偏差，对齐 chat_graph）
_INPUT_BUDGET_SAFETY_MARGIN = 0.10
# 历史文本行级固定开销（行分隔/角色标记）
_LINE_FIXED_TOKENS = 2
# 技能工具循环轮数上限（SKILL.md 必读 + references 按需，留余量；超限强制收尾）
_SKILL_TOOL_ROUND_CAP = 6
# 答案缓冲转正阈值：已读技能的轮次累计流式增量超该字符数即实时转发
_ANSWER_FORWARD_CHARS = 300
# 技能漏读纠正次数上限（超出后接受输出并记审计标记，防死循环）
_SKILL_READ_CORRECTION_LIMIT = 1
# 预算守卫对工具结果的截断下限（低于该长度不再截断，保持文档可读性）
_TOOL_RESULT_MIN_KEEP = 2000
# 生成模型的输出预算覆盖：当前生成模型强制深度思考（reasoning token 与正文
# 共享 max_tokens 上限），完整剧本 + 角色卡 JSON 需要远大于全局默认（8192）
# 的空间——实锤：思考耗尽全局预算时最终轮正文为空
_STORY_MAX_OUTPUT_TOKENS = 32768
# 生成链路停顿超时覆盖（秒）：提交工具结果后的创作轮携带大上下文（技能文档
# 全文），强制深度思考下首个 chunk 延迟可超全局 chat.timeout（60s）——实锤：
# shangmeiying/handdrawn 创作轮 60s 无字节致 ReadTimeout 失败。同时覆盖 httpx
# 读超时与 SDK 的 chunk 间隔超时（缺省 120s），两层对齐同一值
_STORY_STALL_TIMEOUT = 300
# 空响应重试上限（深度思考耗尽预算/网关瞬态空流的兜底；重试后仍空走失败
# 路径，不落库空产物）
_EMPTY_OUTPUT_RETRY_LIMIT = 1


def _trim_history_lines(lines: list[str], budget: int, model_name: str) -> str:
    """历史行按预算从最旧丢弃（对齐 chat_graph._trim_text_lines_to_budget）。"""
    if budget <= 0 or not lines:
        return ""
    acc = 0
    kept: list[str] = []
    for line in reversed(lines):
        cost = count_tokens(model_name, line) + _LINE_FIXED_TOKENS
        if acc + cost > budget:
            break
        acc += cost
        kept.append(line)
    if len(kept) < len(lines):
        logger.debug(f"[STORY] 历史预算裁剪：{len(lines)} → {len(kept)} 行")
    return "\n".join(reversed(kept))


def _build_story_model(
    max_tokens: int = _STORY_MAX_OUTPUT_TOKENS,
    timeout: int = _STORY_STALL_TIMEOUT,
    stream_chunk_timeout: float = float(_STORY_STALL_TIMEOUT),
    temperature: float = 0.7,
):
    """故事对话模型：默认采用多模态模型（基于 OpenAI 兼容接口）。

    优先使用配置快照中的 visual 多模态模型角色（支持文本与图片多模态输入）；
    若 visual 角色未定义或缺少配置，平滑回退至 chat 对话模型角色。
    """
    try:
        if hasattr(CFG, "visual") and CFG.visual and CFG.visual.model_name:
            return build_visual_model(
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                stream_chunk_timeout=stream_chunk_timeout,
            )
    except Exception as exc:
        logger.warning(f"[STORY] 加载 visual 多模态模型失败，回退至 chat 模型: {exc}")

    return build_chat_model(
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        stream_chunk_timeout=stream_chunk_timeout,
    )


def _input_budget(context_window: int | None = None) -> int:
    """输入预算 = context_window − 输出预留 − 安全边际（vLLM 按输入+max_tokens 校验）。"""
    window = context_window or getattr(CFG.chat, "context_window", 200000)
    return (
        window
        - CFG.chat_max_output_tokens
        - int(window * _INPUT_BUDGET_SAFETY_MARGIN)
    )


def _ensure_within_budget(messages: list, budget: int, model_name: str) -> None:
    """每轮模型调用前兜底：超预算时从最早的工具结果起截断（保留前缀）。

    技能文档读取结果在上下文内累积（单文件可达数万字符），长文档堆积或小
    窗口配置下可能超限；仅剩系统提示与需求仍超限（配置异常）时告警并尽力
    发送（对齐 chat_graph 口径）。
    """
    for _ in range(50):  # 渐进截断上限，防御异常输入下的死循环
        if count_messages_tokens(model_name, messages) <= budget:
            return
        trimmed = False
        for idx, msg in enumerate(messages):
            if (
                isinstance(msg, ToolMessage)
                and isinstance(msg.content, str)
                and len(msg.content) > _TOOL_RESULT_MIN_KEEP
            ):
                keep = max(_TOOL_RESULT_MIN_KEEP, len(msg.content) // 2)
                messages[idx] = msg.model_copy(update={"content": msg.content[:keep]})
                trimmed = True
                break
        if not trimmed:
            logger.warning(
                f"[STORY] 输入仍超预算 {budget}（技能文档/需求超限，尽力发送）"
            )
            return


async def _stream_round(
    model,
    messages: list,
    *,
    allow_forward: bool,
    on_answer,
) -> tuple[AIMessage | None, str, bool, bool]:
    """单轮流式调用模型；返回 (累积响应, 未转发内容, 是否已转正, 是否见工具调用)。

    转发策略（正确性优先 + 保留流式体验）：
    - 本轮一旦出现 tool_call 增量即判定为工具轮，其后 content 一律不出帧；
    - allow_forward=False（未读过技能的轮次）时 content 全程只进缓冲，由调用
      方在轮末决定转发（接受）或作废（漏读纠正）；
    - allow_forward=True 时缓冲达 _ANSWER_FORWARD_CHARS 即转正（缓冲一次性
      发出并实时转发后续增量），未达阈值的短输出由调用方在轮末一次性补发。
    """
    buffer: list[str] = []
    buffer_chars = 0
    forwarded = False
    tool_seen = False
    response = None
    async for chunk in model.astream(messages):
        response = chunk if response is None else response + chunk
        if getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None):
            tool_seen = True
        delta = chunk.content if isinstance(chunk.content, str) else ""
        if not delta or tool_seen:
            continue
        if forwarded:
            on_answer(delta)
            continue
        buffer.append(delta)
        buffer_chars += len(delta)
        if allow_forward and buffer_chars >= _ANSWER_FORWARD_CHARS:
            for piece in buffer:
                on_answer(piece)
            buffer.clear()
            buffer_chars = 0
            forwarded = True
    pending = "" if forwarded or tool_seen else "".join(buffer)
    return response, pending, forwarded, tool_seen


async def _run_skill_read(skill_dir: str, tool_call: dict) -> str:
    """执行一次 skill_read 工具调用；任何异常转为错误文本（不炸生成流）。"""
    args = dict(tool_call.get("args") or {})
    path = str(args.get("path") or "").strip()
    if not path:
        return "读取被拒绝：path 不能为空，请从技能包文件清单中选择。"
    try:
        return await asyncio.to_thread(read_skill_file, skill_dir, path)
    except Exception as exc:  # 防御：原语设计为不抛，此处兜底
        logger.warning(f"[STORY] 技能读取异常 {path}: {exc}")
        return f"文件读取失败：{path}。"


class StoryState(TypedDict, total=False):
    """创作图状态：输入字段每轮由服务层覆盖，输出为创作结果与技能审计。"""

    # 输入：创作需求 / 风格键（图内经 get_style 解析技能包）/ 制作参数快照 /
    # 历史消息行（服务层自业务表读取并做单条截断）/ 多模态图片列表
    idea: str
    style_key: str
    params_snapshot: dict
    history_lines: list[str]
    images: list[str]
    # 输出：流式累积的模型全文 + 技能调用审计
    answer: str
    skill_audit: dict


class StoryGraph:
    """剧本创作图封装：持有编译单例（get() 惰性编译，无外部装配依赖）。

    模型不在构造期固化：节点每次调用时按当前配置快照现造，
    以便模型配置热更新自下一请求生效（图结构与配置无关，无需重编译）。
    """

    def __init__(self):
        # 编译后的创作图缓存（首次 get() 时编译）
        self._compiled = None

    # ---------- 辅助 ----------
    @staticmethod
    def _safe_stream_writer():
        """安全获取 custom 流写入器；脱离图执行上下文（直接调用节点/单测）时返回 None。"""
        try:
            from langgraph.config import get_stream_writer

            return get_stream_writer()
        except RuntimeError:
            return None

    # ---------- 节点 ----------
    async def compose_node(self, state: StoryState, config: RunnableConfig):
        """创作节点：技能工具循环（渐进披露）→ 最终轮正文流式外发。

        循环规则（决策完备）：
        - 每轮流式累积响应；轮末含 tool_calls → 工具轮：该轮 content 丢弃
          （不出帧）、逐个执行 skill_read（文件读取仅本地只读，不执行技能包
          脚本）、回填 ToolMessage、发 think 事件，继续循环；
        - 无 tool_calls → 最终轮：answer 增量经 custom 事件外发（缓冲转正）；
        - 未读技能的轮次整轮作废并纠正一次（作废内容不出帧），纠正后仍漏读
          则接受输出并记 skipped_skill_read；
        - 工具轮数达 _SKILL_TOOL_ROUND_CAP：回填占位 ToolMessage（带
          tool_calls 的响应必须紧跟 role=tool 消息，否则严格后端续写请求返回
          400）后切无工具模型强制收尾；
        - 完全空响应（深度思考耗尽输出预算/网关瞬态空流）重试一次，仍空抛错
          走失败路径（不落库空产物，用户可重试）。
        每轮模型调用前经 _ensure_within_budget 对工具结果做预算兜底截断。
        """
        writer = self._safe_stream_writer()
        session_hex = (config or {}).get("configurable", {}).get("session_id", "-")
        style = get_style(state["style_key"])
        idea = state["idea"]
        params_snapshot = state.get("params_snapshot") or {}
        history_lines = state.get("history_lines") or []
        images = state.get("images") or []
        model_role = (
            CFG.visual
            if (hasattr(CFG, "visual") and CFG.visual and CFG.visual.model_name)
            else CFG.chat
        )
        model_name = model_role.model_name
        answer_parts: list[str] = []
        # 技能调用审计：custom 事件增量外发（失败路径服务层也能拿到已读清单）
        skill_audit = {"tool_rounds": 0, "files_read": [], "skipped_skill_read": False}

        def _emit(event: dict) -> None:
            if writer is not None:
                writer(event)

        def _emit_answer(delta: str) -> None:
            answer_parts.append(delta)
            _emit({"type": "answer", "delta": delta})

        def _emit_audit() -> None:
            _emit(
                {
                    "type": "audit",
                    "skill_audit": {
                        **skill_audit,
                        "files_read": list(skill_audit["files_read"]),
                    },
                }
            )

        # 解析多模态图片
        image_uris: list[str] = []
        for img in images:
            if not img:
                continue
            try:
                if img.startswith(("data:", "http://", "https://")):
                    image_uris.append(img)
                else:
                    image_uris.append(image_to_data_uri(img))
            except Exception as exc:
                logger.warning(f"[STORY] 图片转 data URI 失败 {img}: {exc}")

        image_hint = ""
        if image_uris:
            image_hint = (
                "\n\n=== 参考图片 ===\n"
                "用户上传了参考图片，请结合你的多模态视觉理解能力深入分析参考图片中的角色长相、身材体态、发型发色、"
                "妆容服饰与场景细节，在创作剧本故事与提取角色卡时充分体现参考图中的形象特征，确保角色设定与参考图高度一致。"
            )

        # 系统提示装配：技能文件清单 + 参数 + 历史（按输入预算裁剪）
        params_hint = "\n".join(
            f"- {key}: {value}" for key, value in params_snapshot.items() if value
        )
        skill_hint = readable_file_hint(style)
        budget = _input_budget(model_role.context_window)
        fixed_cost = count_tokens(
            model_name,
            SCRIPT_SYSTEM_PROMPT.format(
                style_name=style.name,
                skill_files_hint=skill_hint,
                params_hint=params_hint,
                history_block="",
                idea_block=idea,
            ),
        )
        history_block = _trim_history_lines(
            history_lines, budget - fixed_cost, model_name
        ) or (HISTORY_EMPTY if not history_lines else "")
        system_prompt = (
            SCRIPT_SYSTEM_PROMPT.format(
                style_name=style.name,
                skill_files_hint=skill_hint,
                params_hint=params_hint,
                history_block=history_block or HISTORY_EMPTY,
                idea_block=idea,
            )
            + image_hint
        )
        if image_uris:
            user_content: list[dict] = [{"type": "text", "text": idea}]
            for uri in image_uris:
                user_content.append({"type": "image_url", "image_url": {"url": uri}})
            user_message = HumanMessage(content=user_content)
        else:
            user_message = HumanMessage(content=idea)

        messages: list = [
            SystemMessage(content=system_prompt),
            user_message,
        ]
        # 对话模型默认采用多模态模型（基于 OpenAI 兼容接口）
        model = _build_story_model().bind_tools([build_skill_read_tool(style.skill_dir)])

        read_count = 0
        corrections = 0
        tool_rounds = 0
        empty_retries = 0
        creation_announced = False
        while True:
            if read_count and not creation_announced:
                # 已读技能的轮次才可能开始创作：提示进展（custom think 事件）
                _emit({"type": "think", "text": "正在创作剧本..."})
                creation_announced = True
            _ensure_within_budget(messages, budget, model_name)
            response, pending, forwarded, _tool_seen = await _stream_round(
                model,
                messages,
                allow_forward=read_count > 0,
                on_answer=_emit_answer,
            )
            if response is None:
                response = AIMessage(content="")
            if not response.tool_calls:
                if read_count == 0 and corrections < _SKILL_READ_CORRECTION_LIMIT:
                    # 漏读技能直接输出：整轮作废并纠正重试（内容不出帧）
                    corrections += 1
                    logger.warning(
                        f"[STORY] 模型跳过技能阅读直接输出，作废并纠正重试 session={session_hex}"
                    )
                    messages.append(
                        SystemMessage(
                            content=(
                                "你跳过了技能文档阅读步骤，该次输出已作废。"
                                "请先调用 skill_read 完整阅读 SKILL.md，并依据其指引"
                                "读取相关参考资料，然后再输出完整剧本与角色卡。"
                            )
                        )
                    )
                    continue
                if not response.content:
                    # 完全空响应（深度思考耗尽输出预算/网关瞬态空流）：提示重试
                    # 一次；仍空则抛错走失败路径（不落库空产物，用户可重试）
                    if empty_retries < _EMPTY_OUTPUT_RETRY_LIMIT:
                        empty_retries += 1
                        logger.warning(
                            f"[STORY] 模型输出为空，重试 session={session_hex}"
                        )
                        messages.append(
                            SystemMessage(
                                content=(
                                    "上一轮输出为空。请立即直接输出完整剧本与角色卡，"
                                    "不要再调用工具。"
                                )
                            )
                        )
                        continue
                    bad_except("模型未返回内容，请重试")
                if pending:
                    _emit_answer(pending)
                if read_count == 0:
                    skill_audit["skipped_skill_read"] = True
                    logger.warning(
                        f"[STORY] 技能阅读纠正后仍未读取，接受输出 session={session_hex}"
                    )
                break
            if forwarded:
                # 罕见：转正后的轮次仍出现工具调用（流式顺序异常），已转发
                # 正文无法收回，记录告警供排查（落库序号由累积内容保证）
                logger.warning(
                    f"[STORY] 工具轮检测到已转发内容（流式顺序异常）session={session_hex}"
                )
            messages.append(response)
            if tool_rounds >= _SKILL_TOOL_ROUND_CAP:
                # 达到技能阅读轮数上限：回填占位 ToolMessage（带 tool_calls 的
                # 响应必须紧跟 role=tool 消息，否则严格后端续写请求返回 400），
                # 再切无工具模型强制收尾（对齐 chat_graph）
                for tool_call in response.tool_calls:
                    messages.append(
                        ToolMessage(
                            content="已达到技能阅读轮数上限，本次调用未执行。",
                            tool_call_id=tool_call["id"],
                        )
                    )
                messages.append(
                    SystemMessage(
                        content="已达到技能阅读轮数上限，请立即基于已阅读的技能文档与创作需求输出完整剧本与角色卡，不要再调用工具。"
                    )
                )
                _ensure_within_budget(messages, budget, model_name)
                _resp2, pending2, _fwd2, _ts2 = await _stream_round(
                    _build_story_model(),
                    messages,
                    allow_forward=True,
                    on_answer=_emit_answer,
                )
                if pending2:
                    _emit_answer(pending2)
                break
            tool_rounds += 1
            skill_audit["tool_rounds"] = tool_rounds
            for tool_call in response.tool_calls:
                name = tool_call.get("name", "")
                args = dict(tool_call.get("args") or {})
                path = str(args.get("path") or "").strip()
                if name != SKILL_READ_TOOL_NAME:
                    result = f"未知工具 {name}，请使用 skill_read 阅读技能文档。"
                else:
                    _emit({"type": "think", "text": f"正在阅读技能文档：{path}"})
                    result = await _run_skill_read(style.skill_dir, tool_call)
                    read_count += 1
                    if path:
                        skill_audit["files_read"].append(path)
                messages.append(
                    ToolMessage(content=result, tool_call_id=tool_call["id"])
                )
            _emit_audit()

        skill_audit["tool_rounds"] = tool_rounds
        _emit_audit()
        return {"answer": "".join(answer_parts), "skill_audit": skill_audit}

    # ---------- 组装图 ----------
    def build(self):
        """构建并编译创作图。

        无 checkpointer：每轮生成相互独立（历史经业务表注入系统提示，见 design
        D1），不需要图状态恢复。
        """
        workflow = StateGraph(StoryState)

        workflow.add_node(StoryNode.COMPOSE.value, self.compose_node)

        workflow.add_edge(START, StoryNode.COMPOSE.value)
        workflow.add_edge(StoryNode.COMPOSE.value, END)

        return workflow.compile()

    def get(self):
        """获取创作图惰性单例：首次调用时编译（无外部装配依赖）。"""
        if self._compiled is None:
            self._compiled = self.build()
        return self._compiled


# 模块级单例：服务层通过 story_graph.get() 获取编译图
story_graph = StoryGraph()
