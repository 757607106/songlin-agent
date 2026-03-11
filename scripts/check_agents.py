#!/usr/bin/env python3
"""检查当前运行时入口是否按新版 Agent 平台正确注册。"""

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

    # 检查当前新版运行时入口
    print("=" * 60)
    print("新版运行时入口检查:")
    print("=" * 60)

    required_agents = {
        "SqlReporterAgent": "产品内置 Agent",
        "AgentPlatformAgent": "内部运行时入口",
    }

    missing = []
    for agent_id, role in required_agents.items():
        if agent_id not in agent_manager._classes:
            missing.append(agent_id)
            print(f"❌ {agent_id} 未在类注册表中")
            continue

        print(f"✅ {agent_id} 已在类注册表中")
        print(f"   角色: {role}")

        if agent_id in agent_manager._instances:
            agent = agent_manager._instances[agent_id]
            print(f"✅ {agent_id} 已实例化")
            print(f"   名称: {agent.name}")
            print(f"   描述: {agent.description}")
        else:
            missing.append(agent_id)
            print(f"❌ {agent_id} 未实例化")

        print()

    print("\n" + "=" * 60)
    print("说明：旧的 ChatbotAgent / DeepAgent / DynamicAgent 等不再显示属于正常行为。")

    # 返回状态码
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
