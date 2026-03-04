import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaudeBridge:
    def __init__(self, cli_path: str = "", timeout: int = 300, cwd: str = "",
                 mcp_config: dict | None = None):
        self._cli = cli_path or shutil.which("claude") or "claude"
        self._timeout = timeout
        self._cwd = cwd or str(Path(__file__).resolve().parent.parent)
        self._mcp_config = mcp_config

    async def send_prompt(self, prompt: str, session_id: str) -> str:
        """Send a prompt to Claude Code CLI and return the response text."""
        cmd = [
            self._cli,
            "--print",
            "--session-id", session_id,
        ]

        if self._mcp_config:
            cmd.extend(["--mcp-config", json.dumps(self._mcp_config)])

        cmd.append(prompt)

        # Remove CLAUDECODE env var so the subprocess doesn't think it's nested
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        logger.info("Running claude CLI with session %s", session_id)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self._cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return "[Timeout] Claude did not respond within the configured time limit."
        except FileNotFoundError:
            return f"[Error] Claude CLI not found at '{self._cli}'. Make sure it is installed and in PATH."

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            logger.error("Claude CLI error (rc=%d): %s", proc.returncode, err)
            return f"[Error] Claude CLI exited with code {proc.returncode}:\n{err}"

        return stdout.decode(errors="replace").strip()
