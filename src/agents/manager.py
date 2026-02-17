"""Manager Agent — orchestrates Coder, Tester, Sandbox, and OpenViking."""

import logging

from restate import ObjectContext, VirtualObject

manager = VirtualObject("manager")

log = logging.getLogger(__name__)

MAX_RETRIES = 3

_PLAN_SYSTEM_PROMPT = """\
You are a senior software architect. Given a user task and optional reference material, \
produce a clear, refined development specification for a Python coder.

Your output must include:
1. A one-sentence summary of what needs to be built
2. Functional requirements (bullet list)
3. Any constraints or edge cases to handle
4. Expected output format when the code runs

Be concise and precise. The coder will use your spec to generate code."""

_ERROR_ANALYSIS_PROMPT = """\
You are a debugging expert. Given the original task, the generated code, and the execution \
output (which failed), analyze the root cause and provide actionable fix suggestions.

Your output must include:
1. Root cause analysis (what went wrong and why)
2. Specific fix suggestions (concrete code changes)
3. Any edge cases the previous attempt missed

Be concise and actionable. Your analysis will be fed back to the coder for the next attempt."""


@manager.handler()
async def handle_task(ctx: ObjectContext, req: dict) -> dict:
    """Orchestrate the full code-generation workflow.

    req: {"task": str}
    returns: dict with status, code, test_output, retries, etc.
    """
    task = req["task"]
    project_id = ctx.key()

    log.info("manager.handle_task project=%s task=%s", project_id, task[:80])
    ctx.set("status", "started")
    ctx.set("retry_count", 0)

    # ── Step 1: create sandbox project ──────────────────────────────
    from src.infra.sandbox import create_project

    await ctx.service_call(create_project, arg=project_id)
    log.info("manager: sandbox project created project=%s", project_id)

    # ── Step 2: retrieve reference from OpenViking ──────────────────
    async def _ov_retrieve():
        from src.config import cfg
        from src.infra.ov_client import OVClient

        client = OVClient(cfg.ov_data_path)
        try:
            client.init()
            result = client.retrieve(task)
            return result
        except Exception:
            log.exception("manager: OV retrieve failed, continuing without reference")
            return ""
        finally:
            client.close()

    reference = await ctx.run("ov_retrieve", _ov_retrieve)
    log.info("manager: OV reference length=%d", len(reference))

    # ── Step 3: LLM-driven task planning ────────────────────────────
    plan_user_prompt = f"User task: {task}"
    if reference:
        plan_user_prompt += f"\n\nReference material:\n{reference}"

    async def _llm_plan():
        from src.config import cfg
        from src.infra.llm import LLMClient

        client = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model_name)
        return client.chat(_PLAN_SYSTEM_PROMPT, plan_user_prompt)

    refined_task = await ctx.run("llm_plan", _llm_plan)
    log.info("manager: LLM plan length=%d", len(refined_task))

    # ── Step 4–6: code → test → retry loop ──────────────────────────
    from src.agents.coder import generate_code
    from src.agents.tester import run_test

    error_feedback = ""
    coder_result = {}
    test_result = {}
    retries = 0

    for attempt in range(1, MAX_RETRIES + 1):
        log.info("manager: attempt %d/%d project=%s", attempt, MAX_RETRIES, project_id)
        ctx.set("retry_count", attempt)

        # Call coder with refined task
        coder_req = {"task": refined_task, "reference": reference}
        if error_feedback:
            coder_req["error_feedback"] = error_feedback
        coder_result = await ctx.object_call(generate_code, key=project_id, arg=coder_req)
        log.info("manager: coder returned filename=%s", coder_result.get("filename"))

        # Call tester
        test_result = await ctx.object_call(
            run_test,
            key=project_id,
            arg={"project_id": project_id, "filename": coder_result["filename"]},
        )
        log.info("manager: tester result passed=%s", test_result.get("passed"))

        if test_result.get("passed"):
            retries = attempt - 1
            break

        # LLM-driven error analysis for the next retry
        test_output = test_result.get("output", "")
        code = coder_result.get("code", "")
        error_user_prompt = (
            f"Original task:\n{refined_task}\n\n"
            f"Generated code:\n```python\n{code}\n```\n\n"
            f"Execution output:\n{test_output}"
        )

        async def _llm_error_analysis():
            from src.config import cfg
            from src.infra.llm import LLMClient

            client = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model_name)
            return client.chat(_ERROR_ANALYSIS_PROMPT, error_user_prompt)

        error_feedback = await ctx.run(
            f"llm_error_analysis_{attempt}", _llm_error_analysis
        )
        log.info("manager: LLM error analysis length=%d", len(error_feedback))
        retries = attempt

    # ── Step 7: on success, archive to OpenViking ───────────────────
    final_status = "success" if test_result.get("passed") else "failed"
    code = coder_result.get("code", "")

    if final_status == "success":
        from src.infra.sandbox import read_file

        file_content = await ctx.service_call(
            read_file, arg={"project_id": project_id, "filename": coder_result["filename"]}
        )
        code = file_content.get("content", code)

        async def _ov_archive():
            from src.config import cfg
            from src.infra.ov_client import OVClient

            uri = f"viking://code/{project_id}/{coder_result['filename']}"
            client = OVClient(cfg.ov_data_path)
            try:
                client.init()
                client.add(code, uri)
                log.info("manager: archived to OV uri=%s", uri)
            except Exception:
                log.exception("manager: OV archive failed (non-fatal)")
            finally:
                client.close()

        await ctx.run("ov_archive", _ov_archive)

    # ── Step 8: store final state and return ────────────────────────
    ctx.set("status", final_status)
    log.info(
        "manager.handle_task DONE project=%s status=%s retries=%d",
        project_id, final_status, retries,
    )

    return {
        "project_id": project_id,
        "status": final_status,
        "retries": retries,
        "code": code,
        "test_output": test_result.get("output", ""),
        "test_analysis": test_result.get("analysis", ""),
    }
