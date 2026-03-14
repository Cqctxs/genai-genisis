import asyncio

import structlog
from e2b_code_interpreter import Sandbox

log = structlog.get_logger()

SANDBOX_TIMEOUT = 60


async def run_benchmark(
    code: str,
    language: str,
    repo_files: dict[str, str] | None = None,
) -> dict:
    """Execute benchmark code in an E2B sandbox and return results."""
    log.info("starting_sandbox", language=language)

    def _run():
        sbx = Sandbox(timeout=SANDBOX_TIMEOUT)
        try:
            if repo_files:
                for path, content in repo_files.items():
                    sbx.files.write(path, content)

            if language == "python":
                sbx.commands.run("pip install pyinstrument", timeout=30)
                execution = sbx.run_code(code)
            else:
                sbx.commands.run("npm init -y && npm install", timeout=30)
                sbx.files.write("benchmark.js", code)
                execution = sbx.run_code(
                    "const result = require('./benchmark.js'); console.log(JSON.stringify(result));"
                )

            stdout = "".join(line.text for line in execution.logs.stdout)
            stderr = "".join(line.text for line in execution.logs.stderr)

            return {
                "stdout": stdout,
                "stderr": stderr,
                "error": str(execution.error) if execution.error else None,
            }
        finally:
            sbx.kill()

    result = await asyncio.to_thread(_run)
    log.info("sandbox_complete", has_error=result.get("error") is not None)
    return result


async def get_sandbox_specs() -> str:
    """Return a description of the E2B sandbox environment."""
    return "E2B Cloud Sandbox - 2 vCPU, 512MB RAM"
