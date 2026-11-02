"""FastAPI server: generates puzzles and serves the solver UI.

Run:  uvicorn server.app:app --reload
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crossword.difficulty import ALL_AIDS, GEOMETRY, PRESETS
from crossword.export import to_html, to_puz
from crossword.generate import GenerationError, Puzzle, default_wordlist, generate

WEB = Path(__file__).resolve().parent.parent / "web"
CACHE_SIZE = 200

@asynccontextmanager
async def lifespan(_: FastAPI):
    default_wordlist()  # load the word list once, before the first request
    yield


app = FastAPI(title="Procedural Crosswords", lifespan=lifespan)
_cache: OrderedDict[str, Puzzle] = OrderedDict()
_lock = Lock()


class PuzzleRequest(BaseModel):
    level: int = Field(3, ge=1, le=5)
    seed: int | None = Field(None, ge=0, le=2**53)
    size: int | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    clue_tier: int | None = Field(None, ge=1, le=4)
    aids: list[str] | None = None
    starter_letters: int | None = Field(None, ge=0, le=20)


def _remember(p: Puzzle) -> None:
    with _lock:
        _cache[p.id] = p
        _cache.move_to_end(p.id)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def _get(pid: str) -> Puzzle:
    with _lock:
        p = _cache.get(pid)
    if p is None:
        raise HTTPException(404, "puzzle not found (it may have expired); regenerate it from its seed")
    return p


@app.get("/api/presets")
def presets() -> dict:
    return {"presets": [d.to_dict() for d in PRESETS.values()],
            "sizes": sorted(GEOMETRY), "aids": list(ALL_AIDS)}


@app.post("/api/puzzle")
def create_puzzle(req: PuzzleRequest) -> dict:
    if req.size is not None and req.size not in GEOMETRY:
        raise HTTPException(422, f"size must be one of {sorted(GEOMETRY)}")
    try:
        p = generate(req.level, req.seed, size=req.size, min_score=req.min_score,
                     clue_tier=req.clue_tier, aids=req.aids, starter_letters=req.starter_letters)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except GenerationError as e:
        raise HTTPException(503, str(e))
    _remember(p)
    return p.to_dict()


@app.get("/api/puzzle/{pid}")
def get_puzzle(pid: str) -> dict:
    return _get(pid).to_dict()


@app.get("/api/puzzle/{pid}/puz")
def get_puz(pid: str) -> Response:
    p = _get(pid)
    return Response(to_puz(p), media_type="application/x-crossword",
                    headers={"Content-Disposition": f'attachment; filename="crossword-{pid}.puz"'})


@app.get("/api/puzzle/{pid}/print", response_class=HTMLResponse)
def get_print(pid: str, answers: bool = False) -> str:
    return to_html(_get(pid), show_answers=answers)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
