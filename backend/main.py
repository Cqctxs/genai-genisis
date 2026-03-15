import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from slowapi import Limiter
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

load_dotenv()

import logging.config

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
        "console": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "run.jsonl",
            "formatter": "json",
            "mode": "a",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    }
})

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()

jobs: dict[str, dict[str, Any]] = {}
job_queues: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting_server")
    yield
    log.info("shutting_down_server")


app = FastAPI(title="CodeMark API", version="0.1.0", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "vscode-webview://*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    github_token: str
    optimization_bias: str = "balanced"
    fast_mode: bool = False


class AnalyzeLocalRequest(BaseModel):
    files: dict[str, str]
    language: str = "python"
    optimization_bias: str = "balanced"
    fast_mode: bool = False


class AnalyzeResponse(BaseModel):
    job_id: str


@app.get("/api/repos")
async def list_repos(github_token: str):
    from services.github_service import list_user_repos

    try:
        repos = await list_user_repos(github_token)
        return repos
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        log.error("list_repos_failed", error=str(e))
        raise HTTPException(
            status_code=502, detail="Failed to fetch repositories from GitHub"
        )


@app.post("/api/analyze", response_model=AnalyzeResponse)
@limiter.limit("5/minute")
async def analyze_repo(request: Request, body: AnalyzeRequest):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    job_queues[job_id] = queue
    jobs[job_id] = {"status": "pending", "result": None}

    asyncio.create_task(
        _run_agent(
            job_id, str(body.repo_url), body.github_token, queue, body.optimization_bias, body.fast_mode
        )
    )

    log.info("job_created", job_id=job_id, repo_url=str(body.repo_url))
    return AnalyzeResponse(job_id=job_id)


async def _run_agent(
    job_id: str,
    repo_url: str,
    github_token: str,
    queue: asyncio.Queue,
    optimization_bias: str = "balanced",
    fast_mode: bool = False,
):
    from agent.graph import run_optimization_pipeline

    try:
        jobs[job_id]["status"] = "running"
        result = await run_optimization_pipeline(
            repo_url, github_token, queue, optimization_bias, fast_mode
        )
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        await queue.put({"event": "complete", "data": result})
    except Exception as e:
        log.error("agent_failed", job_id=job_id, error=str(e))
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        await queue.put({"event": "error", "data": {"message": str(e)}})


@app.get("/api/stream/{job_id}")
async def stream_job(job_id: str):
    if job_id not in job_queues:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        queue = job_queues[job_id]
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    data = message.get("data", "")
                    yield {
                        "event": message.get("event", "update"),
                        "data": (
                            json.dumps(data)
                            if isinstance(data, (dict, list))
                            else str(data)
                        ),
                    }
                    if message.get("event") in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": ""}
        finally:
            job_queues.pop(job_id, None)

    return EventSourceResponse(event_generator())


@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job["status"] == "running":
        raise HTTPException(status_code=202, detail="Job still running")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "Unknown error"))

    result = job.get("result", {})

    # Expose PR status and error for frontend to display
    result["pr_status"] = result.get("pr_status", "unknown")
    result["pr_error"] = result.get("pr_error")
    result["pr_url"] = result.get("pr_url", "")

    return result


@app.post("/api/analyze-local", response_model=AnalyzeResponse)
@limiter.limit("5/minute")
async def analyze_local(request: Request, body: AnalyzeLocalRequest):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    job_queues[job_id] = queue
    jobs[job_id] = {"status": "pending", "result": None}

    asyncio.create_task(
        _run_local_agent(
            job_id, body.files, body.language, queue, body.optimization_bias, body.fast_mode
        )
    )

    log.info("local_job_created", job_id=job_id, num_files=len(body.files))
    return AnalyzeResponse(job_id=job_id)


async def _run_local_agent(
    job_id: str,
    files: dict[str, str],
    language: str,
    queue: asyncio.Queue,
    optimization_bias: str = "balanced",
    fast_mode: bool = False,
):
    from agent.graph import run_local_optimization_pipeline

    try:
        jobs[job_id]["status"] = "running"
        result = await run_local_optimization_pipeline(
            files, language, queue, optimization_bias, fast_mode
        )
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        await queue.put({"event": "complete", "data": result})
    except Exception as e:
        log.error("local_agent_failed", job_id=job_id, error=str(e))
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        await queue.put({"event": "error", "data": {"message": str(e)}})


@app.get("/api/health")
async def health():
    return {"status": "ok"}
