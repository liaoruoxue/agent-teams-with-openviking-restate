"""Tester Agent — runs code in the sandbox and analyzes results."""

import logging

from restate import ObjectContext, VirtualObject

tester = VirtualObject("tester")

log = logging.getLogger(__name__)


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

    # Determine pass/fail
    passed = _analyse_result(returncode, stdout, stderr)
    analysis = _build_analysis(passed, returncode, stdout, stderr)

    log.info("tester.run_test project=%s passed=%s", project_id, passed)

    return {"passed": passed, "output": combined_output, "analysis": analysis}


def _analyse_result(returncode: int, stdout: str, stderr: str) -> bool:
    """Simple heuristic: pass if returncode is 0 and no obvious errors."""
    if returncode != 0:
        return False
    error_signals = ["Traceback", "Error:", "Exception:", "FAIL", "AssertionError"]
    for signal in error_signals:
        if signal in stderr or signal in stdout:
            return False
    return True


def _build_analysis(passed: bool, returncode: int, stdout: str, stderr: str) -> str:
    if passed:
        return f"Test PASSED. Return code {returncode}. Output looks clean."
    parts = [f"Test FAILED. Return code {returncode}."]
    if stderr.strip():
        parts.append(f"Stderr: {stderr[:500]}")
    if "Traceback" in stdout:
        parts.append(f"Traceback found in stdout: {stdout[:500]}")
    return " ".join(parts)
