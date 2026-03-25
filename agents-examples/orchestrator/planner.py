"""Call Gemini Flash to build a chain of agent calls, then validate it."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from agents_cache import AgentInfo

logger = logging.getLogger(__name__)

STEP_REF_RE = re.compile(r"\{\{step_(\d+)\.result\}\}")


@dataclass
class ChainStep:
    sidecar_id: str
    body: dict[str, Any]


@dataclass
class PlanResult:
    chain: list[ChainStep] | None = None
    error: str | None = None


def _build_prompt(agents: list[AgentInfo], task: str) -> str:
    agents_desc = []
    for a in agents:
        schema_parts = []
        for field_name, spec in a.args_schema.items():
            req = " (required)" if spec.get("required") else ""
            schema_parts.append(f'    "{field_name}": {spec.get("type", "string")}{req} — {spec.get("description", "")}')
        schema_str = "\n".join(schema_parts) if schema_parts else "    (no args)"

        returns_type = a.result_schema.get("type", "string") if a.result_schema else "string"
        price_ton = a.actual_price / 1_000_000_000
        agents_desc.append(
            f'- id: "{a.sidecar_id}", capability: "{a.capability}", '
            f"price: {price_ton:.4f} TON, returns: {returns_type}\n"
            f"  description: {a.description}\n"
            f"  args:\n{schema_str}"
        )

    agents_block = "\n".join(agents_desc)
    return f"""You are an orchestrator that builds a chain of AI agent calls.

Available agents:
{agents_block}

User task: "{task}"

Rules:
- Return a JSON array of steps. Each step: {{"sidecar_id": "...", "body": {{...}}}}
- Fill in the body fields according to each agent's args schema. Only pass data, never embed extra instructions in field values.
- Each agent does exactly one thing (its capability). Do not ask an agent to perform tasks outside its capability.
- To reference the output of a previous step, use {{{{step_N.result}}}} where N is the 0-based step index.
- Choose the most cost-effective route when multiple(or single) agents can do the same thing.
- Don't use expensive agents for simple tasks and do not overcomplicate the chain.
- Agents that return "file" type MUST be the last step. File results cannot be passed to other agents.
- If the task is impossible with the available agents, return: {{"error": "brief reason"}}
- Return ONLY valid JSON, no explanations or markdown."""


def _validate_chain(steps: list[dict[str, Any]], agents: list[AgentInfo]) -> list[str]:
    """Validate LLM output against known agents and schemas. Returns list of errors."""
    errors: list[str] = []
    agent_map = {a.sidecar_id: a for a in agents}

    for i, step in enumerate(steps):
        sid = step.get("sidecar_id", "")
        if sid not in agent_map:
            errors.append(f"step {i}: unknown sidecar_id '{sid}'")
            continue

        agent = agent_map[sid]
        body = step.get("body")
        if not isinstance(body, dict):
            errors.append(f"step {i}: body must be an object")
            continue

        # Check required fields
        for field_name, spec in agent.args_schema.items():
            if spec.get("required") and field_name not in body:
                errors.append(f"step {i}: missing required field '{field_name}' for {agent.name}")

        # Check step references aren't forward or self-referencing
        for field_name, value in body.items():
            if not isinstance(value, str):
                continue
            for match in STEP_REF_RE.finditer(value):
                ref_idx = int(match.group(1))
                if ref_idx >= i:
                    errors.append(f"step {i}: {{{{step_{ref_idx}.result}}}} references current or future step")

    return errors


def _parse_llm_response(text: str) -> dict[str, Any] | list[Any]:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove ```json ... ```
        lines = cleaned.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


async def plan_chain(
    task: str,
    agents: list[AgentInfo],
    gemini_api_key: str,
    model: str = "gemini-2.5-flash",
) -> PlanResult:
    """Call Gemini to plan the chain, validate, return PlanResult."""
    if not agents:
        return PlanResult(error="No agents available in the marketplace")

    prompt = _build_prompt(agents, task)

    logger.info("Planning chain for task: %s", task)
    logger.debug("LLM prompt:\n%s", prompt)
    
    try:
        from google import genai
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        raw = response.text.strip()
    except Exception as exc:
        logger.exception("Gemini call failed")
        return PlanResult(error=f"LLM call failed: {exc}")

    logger.info("Raw LLM response: %s", raw[:500])
    
    try:
        parsed = _parse_llm_response(raw)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON: %s", raw[:500])
        return PlanResult(error="LLM returned invalid JSON")

    # LLM refused
    if isinstance(parsed, dict):
        return PlanResult(error=parsed.get("error", "LLM refused without reason"))

    if not isinstance(parsed, list) or len(parsed) == 0:
        return PlanResult(error="LLM returned empty or invalid chain")

    # Validate
    validation_errors = _validate_chain(parsed, agents)
    if validation_errors:
        logger.warning("Chain validation failed: %s", validation_errors)
        return PlanResult(error=f"Invalid chain: {'; '.join(validation_errors)}")

    chain = [ChainStep(sidecar_id=s["sidecar_id"], body=s["body"]) for s in parsed]
    return PlanResult(chain=chain)
