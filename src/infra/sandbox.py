"""Sandbox manager — a stateless Restate Service for local file & process ops."""

import logging
import os
import subprocess

from restate import Context, Service

log = logging.getLogger(__name__)

sandbox = Service("sandbox")

_BASE = "/tmp/lbg"


@sandbox.handler()
async def create_project(ctx: Context, project_id: str) -> dict:
    """Create a project directory under /tmp/lbg/<project_id>."""
    base = f"{_BASE}/{project_id}"

    async def _create():
        os.makedirs(base, exist_ok=True)
        return {"project_id": project_id, "path": base}

    result = await ctx.run("create_project", _create)
    log.info("sandbox.create_project id=%s path=%s", project_id, base)
    return result


@sandbox.handler()
async def write_file(ctx: Context, req: dict) -> dict:
    """Write a file into the project sandbox."""
    project_id = req["project_id"]
    filename = req["filename"]
    content = req["content"]
    path = f"{_BASE}/{project_id}/{filename}"

    async def _write():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    written = await ctx.run("write_file", _write)
    log.info("sandbox.write_file path=%s length=%d", written, len(content))
    return {"path": written}


@sandbox.handler()
async def read_file(ctx: Context, req: dict) -> dict:
    """Read a file from the project sandbox."""
    project_id = req["project_id"]
    filename = req["filename"]
    path = f"{_BASE}/{project_id}/{filename}"

    async def _read():
        with open(path) as f:
            return f.read()

    content = await ctx.run("read_file", _read)
    log.info("sandbox.read_file path=%s length=%d", path, len(content))
    return {"content": content}


@sandbox.handler()
async def exec_command(ctx: Context, req: dict) -> dict:
    """Execute a shell command inside the project sandbox."""
    project_id = req["project_id"]
    command = req["command"]
    base = f"{_BASE}/{project_id}"

    async def _exec():
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            cwd=base, timeout=30,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    out = await ctx.run("exec", _exec)
    log.info(
        "sandbox.exec_command project=%s cmd=%s rc=%s",
        project_id, command[:80], out["returncode"],
    )
    return out
