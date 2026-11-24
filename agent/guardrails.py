"""Guardrails: the radar reports groups, not people.

Names never reach the agents (the MCP server only hands out masked ids), so the remaining risk is an agent
calling one masked account a bot or a fake. `accusations` finds that; the output guardrail on every agent
uses it, and the pipeline asks the agent once more to rewrite before dropping the sentence.
"""

from __future__ import annotations

import re

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, output_guardrail
from pydantic import BaseModel

ACCOUNT = r"acct_[0-9a-f]{6}"
LABEL = (r"(?:(?:clearly|obviously|likely|probably|definitely|almost certainly)\s+)?(?:an?\s+)?"
         r"(?:(?:obvious|clear|likely|probable|definite)\s+)?(?:bot|fake|troll|scammer|sock ?puppet|shill|paid)")
ACCUSATION = re.compile(rf"\b{ACCOUNT}\b[^.;\n]{{0,40}}?\b(?:is|was|looks like|appears to be|must be)\s+{LABEL}\b", re.I)


def accusations(text: str) -> list[str]:
    """Sentences that pin a label on one masked account."""
    return [m.group(0) for m in ACCUSATION.finditer(text or "")]


def _text_of(output) -> str:
    if isinstance(output, BaseModel):
        return " ".join(str(v) for v in output.model_dump().values())
    return str(output)


@output_guardrail
async def groups_not_people(context: RunContextWrapper, agent: Agent, output) -> GuardrailFunctionOutput:
    found = accusations(_text_of(output))
    return GuardrailFunctionOutput(output_info={"accusations": found}, tripwire_triggered=bool(found))


def scrub(text: str) -> str:
    """Last resort after a rewrite still accuses someone: replace the accusation itself."""
    return ACCUSATION.sub("this account is part of the flagged group", text or "")
