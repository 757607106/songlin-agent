#!/usr/bin/env python3
"""测试脚本：验证所有智能体是否正确注册"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agents import agent_manager  # noqa: E402


def main():
    print("=" * 60)
    print("智能体注册状态检查")
    print("=" * 60)

    # 获取所有注册的智能体类
    print(f"\n已注册的智能体类 ({len(agent_manager._classes)} 个):")
    for agent_name, agent_class in agent_manager._classes.items():
        print(f"  - {agent_name}: {agent_class}")

    # 获取所有实例化的智能体
    print(f"\n已实例化的智能体 ({len(agent_manager._instances)} 个):")
    for agent_name, agent_instance in agent_manager._instances.items():
        print(f"  - {agent_name}")
        print(f"    name: {agent_instance.name}")
        print(f"    description: {agent_instance.description[:80]}...")
        print(f"    capabilities: {agent_instance.capabilities}")
        print()

    # 检查 SqlReporterAgent 是否存在
    print("=" * 60)
    print("SqlReporterAgent 检查:")
    print("=" * 60)

    if "SqlReporterAgent" in agent_manager._classes:
        print("✅ SqlReporterAgent 已在类注册表中")
    else:
        print("❌ SqlReporterAgent 未在类注册表中")
        print("   可能原因：")
        print("   1. 模块导入失败")
        print("   2. 类名不匹配")
        print("   3. 未继承 BaseAgent")

    if "SqlReporterAgent" in agent_manager._instances:
        print("✅ SqlReporterAgent 已实例化")
        agent = agent_manager._instances["SqlReporterAgent"]
        print(f"   名称: {agent.name}")
        print(f"   描述: {agent.description}")
    else:
        print("❌ SqlReporterAgent 未实例化")

    print("\n" + "=" * 60)

    # 返回状态码
    return 0 if "SqlReporterAgent" in agent_manager._instances else 1


if __name__ == "__main__":
    sys.exit(main())
