"""Tester Agent — runs code in the sandbox and analyzes results via LLM."""

import logging
import re

from restate import ObjectContext, VirtualObject

tester = VirtualObject("tester")

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a test-result analyst. You receive the execution output of a Python script \
(stdout, stderr, return code) and must decide whether the execution was successful.

Analyze the output carefully:
- Check return code (0 usually means success)
- Look for tracebacks, exceptions, assertion errors
- Verify the output looks reasonable for the given task

At the end of your analysis, you MUST include exactly one verdict line:
VERDICT: PASS
or
VERDICT: FAIL

Always include a brief explanation before the verdict."""


@tester.handler()
async def run_test(ctx: ObjectContext, req: dict) -> dict:
    """Execute a file in the sandbox and decide pass/fail.

    req: {"project_id": str, "filename": str}
    returns: {"passed": bool, "output": str, "analysis": str}
    """
    project_id = req["project_id"]
    filename = req["filename"]

    log.info("tester.run_test project=%s filename=%s", project_id, filename)

    from src.infra.sandbox import exec_command

    result = await ctx.service_call(
        exec_command,
        arg={"project_id": project_id, "command": f"python {filename}"},
    )

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    returncode = result.get("returncode", -1)
    combined_output = f"stdout:\n{stdout}\nstderr:\n{stderr}\nreturncode: {returncode}"

    log.info(
        "tester.run_test project=%s rc=%s stdout_len=%d stderr_len=%d",
        project_id, returncode, len(stdout), len(stderr),
    )

    # Ask LLM to analyse the execution result
    user_prompt = (
        f"Execution output of `python {filename}`:\n\n{combined_output}"
    )

    async def _llm_analyse():
        from src.config import cfg
        from src.infra.llm import LLMClient

        client = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model_name)
        return client.chat(_SYSTEM_PROMPT, user_prompt)

    llm_response = await ctx.run("llm_analyse", _llm_analyse)
    log.info("tester.run_test llm_analyse response length=%d", len(llm_response))

    verdict = _parse_verdict(llm_response)
    if verdict is not None:
        passed = verdict
        analysis = llm_response
    else:
        # Fallback to heuristic if LLM didn't return a clear verdict
        log.warning("tester: LLM returned no clear verdict, falling back to heuristic")
        passed = _analyse_result(returncode, stdout, stderr)
        analysis = llm_response

    log.info("tester.run_test project=%s passed=%s", project_id, passed)

    return {"passed": passed, "output": combined_output, "analysis": analysis}


def _parse_verdict(llm_response: str) -> bool | None:
    """Extract VERDICT: PASS or VERDICT: FAIL from LLM response.

    Returns True for PASS, False for FAIL, None if no verdict found.
    """
    match = re.search(r"VERDICT:\s*(PASS|FAIL)", llm_response, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper() == "PASS"


def _analyse_result(returncode: int, stdout: str, stderr: str) -> bool:
    """Heuristic fallback: pass if returncode is 0 and no obvious errors."""
    if returncode != 0:
        return False
    error_signals = ["Traceback", "Error:", "Exception:", "FAIL", "AssertionError"]
    for signal in error_signals:
        if signal in stderr or signal in stdout:
            return False
    return True
