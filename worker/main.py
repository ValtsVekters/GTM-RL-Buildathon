"""GTM Engine worker: runs the research crew for the web app.

POST /research streams newline-delimited JSON: one {"type": "event"} line per agent
step, then a final {"type": "result"} or {"type": "error"} line.
"""

import json
import logging
import queue
import threading
from collections.abc import Iterator
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from research.llm import LLMUnavailable
from research.run import build_crew, sample_product

app = FastAPI(title="GTM Engine worker")
log = logging.getLogger("uvicorn.error")

# One run at a time: a live run spends paid credits, and two at once would race on the quota file.
_run_lock = threading.Lock()
_DONE = object()


class ResearchRequest(BaseModel):
    product: str = Field(min_length=10, max_length=1000)
    max_leads: int = Field(default=5, ge=1, le=15)
    mode: Literal["demo", "live"] = "demo"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sample")
def sample() -> dict[str, str]:
    return {"product": sample_product()}


@app.post("/research")
def research(req: ResearchRequest) -> StreamingResponse:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A research run is already in progress. Try again when it finishes.")
    lines: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            crew = build_crew(req.mode == "demo", req.max_leads,
                              on_event=lambda e: lines.put(_line({"type": "event", "event": asdict(e)})))
            result = crew.run(req.product)
            lines.put(_line({"type": "result", "result": asdict(result)}))
        # Provider error bodies can carry account details, so the page gets a fixed message
        # and the full error goes to the worker's own log.
        except LLMUnavailable:
            log.exception("research run: no model available")
            lines.put(_line({"type": "error", "message": "No model is available. Run check_keys.py in worker/ "
                                                         "to see which API keys are missing or rejected."}))
        except Exception:  # the stream must always end with a line the page can show
            log.exception("research run failed")
            lines.put(_line({"type": "error", "message": "The research run failed. "
                                                         "The worker's terminal shows the details."}))
        finally:
            lines.put(_DONE)
            _run_lock.release()  # released by the run itself, so a closed browser tab can't unlock early

    threading.Thread(target=work, daemon=True).start()

    def stream() -> Iterator[str]:
        while (line := lines.get()) is not _DONE:
            yield line

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def _line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"
