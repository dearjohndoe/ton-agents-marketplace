import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .template import AGENT_TEMPLATE, ENV_EXAMPLE_TEMPLATE, QUOTE_BLOCK, REQUIREMENTS_TEMPLATE


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def scaffold_agent(
        name: str,
        capability: str,
        description: str,
        price: int,
        args_schema: dict,
        result_type: str,
        result_mime_type: str | None = None,
        has_quote: bool = False,
        directory: str | None = None,
    ) -> dict:
        """Generate a new agent skeleton with all required files.

        Read catallaxy://guide/create-agent for the full step-by-step guide
        and catallaxy://spec/agent-contract for the stdin/stdout contract.
        """
        project_root = os.getenv("CATALLAXY_PROJECT_ROOT", "/media/second_disk/cont5")
        agent_dir = Path(directory or f"{project_root}/agents-examples/{name}")
        agent_dir.mkdir(parents=True, exist_ok=True)

        result_schema: dict = {"type": result_type}
        if result_mime_type:
            result_schema["mime_type"] = result_mime_type

        quote_block = QUOTE_BLOCK if has_quote else "\n"

        agent_code = AGENT_TEMPLATE.format(
            args_schema=json.dumps(args_schema, indent=4),
            result_schema=json.dumps(result_schema),
            result_type=result_type,
            quote_block=quote_block,
        )
        (agent_dir / "agent.py").write_text(agent_code)
        desc_escaped = description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        desc_line = f'"{desc_escaped}"' if ("\n" in description or '"' in description) else description
        (agent_dir / ".env.example").write_text(ENV_EXAMPLE_TEMPLATE.format(
            capability=capability,
            name=name,
            description_escaped=desc_line,
            price=price,
            has_quote=str(has_quote).lower(),
        ))
        (agent_dir / "requirements.txt").write_text(REQUIREMENTS_TEMPLATE)

        return {
            "path": str(agent_dir),
            "files": ["agent.py", ".env.example", "requirements.txt"],
        }
