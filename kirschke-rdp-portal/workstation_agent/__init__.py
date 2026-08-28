"""Workstation agent package with lazy service imports."""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentConfig",
    "AgentState",
    "CommandHandler",
    "WorkstationAgent",
    "RDPWorkstationAgentService",
    "agent_main",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from workstation_agent import service

    exports = {
        "AgentConfig": service.AgentConfig,
        "AgentState": service.AgentState,
        "CommandHandler": service.CommandHandler,
        "WorkstationAgent": service.WorkstationAgent,
        "RDPWorkstationAgentService": service.RDPWorkstationAgentService,
        "agent_main": service.main,
    }
    return exports[name]
