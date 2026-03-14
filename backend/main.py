import asyncio
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

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    github_token: str


class AnalyzeResponse(BaseModel):
    job_id: str


@app.post("/api/analyze", response_model=AnalyzeResponse)
@limiter.limit("5/minute")
async def analyze_repo(request: Request, body: AnalyzeRequest):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    job_queues[job_id] = queue
    jobs[job_id] = {"status": "pending", "result": None}

    asyncio.create_task(
        _run_agent(job_id, str(body.repo_url), body.github_token)
    )

    log.info("job_created", job_id=job_id, repo_url=str(body.repo_url))
    return AnalyzeResponse(job_id=job_id)


async def _run_agent(job_id: str, repo_url: str, github_token: str):
    from agent.graph import run_optimization_pipeline

    queue = job_queues[job_id]
    try:
        jobs[job_id]["status"] = "running"
        result = await run_optimization_pipeline(repo_url, github_token, queue)
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
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {
                    "event": message.get("event", "update"),
                    "data": str(message.get("data", "")),
                }
                if message.get("event") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": ""}

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

    return job.get("result", {})


@app.get("/api/health")
async def health():
    return {"status": "ok"}
