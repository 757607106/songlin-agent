"""DynamicAgent — 动态多智能体模块

支持三种多智能体协作模式：
- disabled: 单智能体模式
- supervisor: LangGraph Supervisor 子图模式（子智能体过程完全可观测）
- deep_agents: Deep Agents task() 模式（高效并行执行）
"""

from .context import DynamicAgentContext
from .graph import DynamicAgent

__all__ = [
    "DynamicAgent",
    "DynamicAgentContext",
]

# 模块元数据
__version__ = "1.0.0"
__author__ = "Yuxi-Know Team"
__description__ = "支持多种协作模式的动态多智能体"
