#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具函数模块

这个模块提供了多Agent协同系统中常用的工具函数，包括：
1. ID生成和验证
2. 数据处理和转换
3. 文件操作
4. 错误处理和重试
5. 性能监控
6. 数据压缩和安全
"""

from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
import datetime


class Tools:
    def get_current_date():
        """获取当前日期"""
        return datetime.datetime.today().strftime("%Y-%m-%d")

    # 定义工具调用错误处理函数
    @tool(return_direct=True)
    def handle_global_errors(error: Exception) -> str:
        """处理工具调用错误"""
        if isinstance(error, ValueError):
            return "ValueError: Please check the input value."
        elif isinstance(error, ConnectionError):
            return "ConnectionError: Please check your network connection."
        return f"tools chain has error: {str(error)}"

    # TODO 每个agent可能需要的工具不一样，因此应当在各个agent中定义各自的工具集
    tool_node = ToolNode([get_current_date], handle_tool_errors=handle_global_errors)
