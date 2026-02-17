"""Manager Agent — orchestrates Coder, Tester, Sandbox, and OpenViking."""

import logging

from restate import ObjectContext, VirtualObject

manager = VirtualObject("manager")

log = logging.getLogger(__name__)

MAX_RETRIES = 3


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

    # ── Step 3–5: code → test → retry loop ──────────────────────────
    from src.agents.coder import generate_code
    from src.agents.tester import run_test

    error_feedback = ""
    coder_result = {}
    test_result = {}
    retries = 0

    for attempt in range(1, MAX_RETRIES + 1):
        log.info("manager: attempt %d/%d project=%s", attempt, MAX_RETRIES, project_id)
        ctx.set("retry_count", attempt)

        # Call coder
        coder_req = {"task": task, "reference": reference}
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

        # Prepare feedback for next attempt
        error_feedback = test_result.get("output", "")
        retries = attempt

    # ── Step 6: on success, archive to OpenViking ───────────────────
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

    # ── Step 7: store final state and return ────────────────────────
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
