"""Coder Agent — generates code via LLM and writes it to sandbox."""

import logging
import re

from restate import ObjectContext, VirtualObject

coder = VirtualObject("coder")

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Python code generator. You receive a task description and optional reference code.
Generate clean, working Python code that fulfills the task.
Always wrap your code in a single ```python ... ``` block.
The code must be self-contained and runnable via `python main.py`.
Include a simple demonstration / test at the bottom (e.g. print results) so the output can be verified."""


@coder.handler()
async def generate_code(ctx: ObjectContext, req: dict) -> dict:
    """Generate code for a task and write it to the sandbox.

    req: {"task": str, "reference": str, "error_feedback": str (optional)}
    returns: {"filename": "main.py", "code": str}
    """
    project_id = ctx.key()
    task = req["task"]
    reference = req.get("reference", "")
    error_feedback = req.get("error_feedback", "")

    log.info("coder.generate_code project=%s task=%s", project_id, task[:80])

    # Build the user prompt
    user_parts = [f"Task: {task}"]
    if reference:
        user_parts.append(f"\nReference code/knowledge:\n{reference}")
    if error_feedback:
        user_parts.append(
            f"\nPrevious attempt failed with the following error. "
            f"Fix the code accordingly:\n{error_feedback}"
        )
    user_prompt = "\n".join(user_parts)

    # LLM call must be a side effect wrapped in ctx.run
    async def _call_llm():
        from src.config import cfg
        from src.infra.llm import LLMClient

        client = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model_name)
        return client.chat(_SYSTEM_PROMPT, user_prompt)

    response = await ctx.run("llm_generate_code", _call_llm)
    log.info("coder.generate_code llm response length=%d", len(response))

    # Extract code from markdown block
    code = _extract_code(response)
    log.debug("coder.generate_code extracted code length=%d", len(code))

    # Write code to sandbox
    from src.infra.sandbox import write_file

    filename = "main.py"
    await ctx.service_call(
        write_file,
        arg={"project_id": project_id, "filename": filename, "content": code},
    )
    log.info("coder.generate_code wrote %s to sandbox project=%s", filename, project_id)

    return {"filename": filename, "code": code}


def _extract_code(text: str) -> str:
    """Extract the first ```python ... ``` block, or fall back to the full text."""
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: try generic code block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Last resort: return the whole response
    log.warning("coder._extract_code: no code block found, using raw response")
    return text.strip()
