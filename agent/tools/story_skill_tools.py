"""
剧本生成技能读取工具（story-ai-workspace）。

把 agent/skills 技能包的只读加载原语包装为可 bind_tools 的工具，供剧本生成
模型在生成前自主阅读技能文档（渐进披露：SKILL.md 全文 → 按需 references）：

- 工具作用域由服务端隐式绑定当前风格的技能包目录（模型只传包内相对路径，
  不感知也不可选择技能包——最小权限）；
- 工具实例仅提供 schema 供 bind_tools；执行由 agent/graph/story 的创作
  工具循环按 SKILL_READ_TOOL_NAME 分派到 loader.read_skill_file 原语
  （对齐 chat_graph 的 TOOL_IMPLS 分派模式，仅一个工具故不建映射表）；
- 读取失败（越界/后缀/不存在）以返回文本承载，不抛异常，不阻断生成流。
"""

from langchain_core.tools import tool

from agent.skills.loader import read_skill_file

# 工具名常量：生成编排按此分派执行
SKILL_READ_TOOL_NAME = "skill_read"


def build_skill_read_tool(skill_dir: str):
    """构建绑定当前风格技能包作用域的 skill_read 工具（bind_tools 用）。

    每次生成按 style.skill_dir 现造：闭包捕获作用域，模型入参只有 path，
    从 schema 层面杜绝跨技能包读取。
    """

    @tool(SKILL_READ_TOOL_NAME)
    def skill_read(path: str) -> str:
        """读取当前风格技能包内的技能文档全文。

        生成剧本前先调用本工具完整阅读 SKILL.md，再依据 SKILL.md 中的指引
        按需读取参考资料（风格权威定义、剧本范例、生图配方等）。

        Args:
            path: 技能包内相对路径，须取自系统提示给出的文件清单，
                例如 "SKILL.md"、"references/好剧本.md"。
        """
        return read_skill_file(skill_dir, path)

    return skill_read
