"""Catallaxy MCP Server — gives LLM full autonomy over Catallaxy marketplace."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from tools.discovery import register_discovery_tools
from tools.invocation import register_invocation_tools
from tools.development import register_development_tools
from resources.agent_contract import register_agent_contract
from resources.sidecar_env import register_sidecar_env
from resources.payment_protocol import register_payment_protocol
from resources.result_types import register_result_types
from resources.create_guide import register_create_guide
from resources.gotchas import register_gotchas

from config import REGISTRY_ADDRESS  # noqa: F401 — re-exported for convenience

mcp = FastMCP("Catallaxy")

register_discovery_tools(mcp)
register_invocation_tools(mcp)
register_development_tools(mcp)
register_agent_contract(mcp)
register_sidecar_env(mcp)
register_payment_protocol(mcp)
register_result_types(mcp)
register_create_guide(mcp)
register_gotchas(mcp)

if __name__ == "__main__":
    mcp.run()
