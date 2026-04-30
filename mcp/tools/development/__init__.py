from mcp.server.fastmcp import FastMCP

from . import deploy, scaffold, status, test, validate

__all__ = ["register_development_tools"]


def register_development_tools(mcp: FastMCP) -> None:
    scaffold.register(mcp)
    test.register(mcp)
    validate.register(mcp)
    deploy.register(mcp)
    status.register(mcp)
