"""Workstation Agent for Kirschke RDP Workstation Portal.

This package contains the Windows service that runs on each managed workstation
to track RDP sessions and execute admin commands.
"""

from workstation_agent.service import (
    AgentConfig,
    AgentState,
    CommandHandler,
    WorkstationAgent,
    RDPWorkstationAgentService,
    main as agent_main,
)

__all__ = [
    "AgentConfig",
    "AgentState",
    "CommandHandler",
    "WorkstationAgent",
    "RDPWorkstationAgentService",
    "agent_main",
]

