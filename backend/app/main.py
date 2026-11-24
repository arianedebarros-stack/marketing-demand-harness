"""App FastAPI: rotas da §9 e conversão dos erros de domínio em códigos HTTP."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.state_machine import InvalidTransition
from app.llm.fallback import LLMUnavailableError
from app.services.errors import (
    ConflictError,
    DuplicateTaskError,
    NotFoundError,
    TaskCreationError,
    UnprocessableError,
)
from app.services.triage import TriageNotReadyError

app = FastAPI(title="Marketing Demand Harness")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.exception_handler(DuplicateTaskError)
def _duplicate(request: Request, exc: DuplicateTaskError) -> JSONResponse:
    return JSONResponse(status_code=409, content=exc.conflict.model_dump(mode="json"))


@app.exception_handler(InvalidTransition)
def _invalid_transition(request: Request, exc: InvalidTransition) -> JSONResponse:
    return _error(409, str(exc))


@app.exception_handler(TriageNotReadyError)
def _triage_not_ready(request: Request, exc: TriageNotReadyError) -> JSONResponse:
    return _error(409, str(exc))


@app.exception_handler(ConflictError)
def _conflict(request: Request, exc: ConflictError) -> JSONResponse:
    return _error(409, str(exc))


@app.exception_handler(NotFoundError)
def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error(404, str(exc))


@app.exception_handler(UnprocessableError)
def _unprocessable(request: Request, exc: UnprocessableError) -> JSONResponse:
    return _error(422, str(exc))


@app.exception_handler(LLMUnavailableError)
def _llm_unavailable(request: Request, exc: LLMUnavailableError) -> JSONResponse:
    return _error(502, str(exc))


@app.exception_handler(TaskCreationError)
def _task_creation_failed(request: Request, exc: TaskCreationError) -> JSONResponse:
    return _error(502, f"falha ao criar a tarefa no sistema externo: {exc}")
