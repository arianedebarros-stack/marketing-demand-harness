"""Settings (.env) e loader das regras de negócio em config/*.json.

Os valores de negócio vivem só nos JSONs; este módulo apenas os valida e expõe tipados.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


class ConfigError(Exception):
    """Erro de configuração com mensagem legível (arquivo, campo e motivo)."""


def _format_validation_error(source: str, error: ValidationError) -> str:
    lines = [f"{source}: configuração inválida"]
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(raiz)"
        lines.append(f"  - {location}: {item['msg']}")
    return "\n".join(lines)


# --- Settings (.env) -----------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://harness:harness@localhost:5432/harness"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_fallback: bool = True
    task_manager: Literal["local", "asana"] = "local"
    asana_token: SecretStr | None = None
    asana_project_gid: str | None = None
    app_timezone: str = "America/Sao_Paulo"
    config_dir: Path = DEFAULT_CONFIG_DIR

    @field_validator("anthropic_api_key", "asana_token", "asana_project_gid", mode="before")
    @classmethod
    def _empty_as_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"fuso horário desconhecido: {value!r}") from exc
        return value

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @classmethod
    def load(cls, env_file: Path | None = DEFAULT_ENV_FILE) -> Self:
        """Carrega as settings convertendo erros de validação em ``ConfigError``."""
        try:
            return cls(_env_file=env_file)
        except ValidationError as exc:
            raise ConfigError(_upper_env_names(_format_validation_error(".env", exc))) from exc


def _upper_env_names(message: str) -> str:
    for name in Settings.model_fields:
        message = message.replace(f"  - {name}:", f"  - {name.upper()}:")
    return message


# --- Modelos de config/*.json --------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Brand(_Strict):
    name: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    mandatory_cta: str | None


class TaskTypeRule(_Strict):
    required: list[str]
    promo_required: list[str] = Field(default_factory=list)
    impact: int = Field(ge=0, le=100)


class TaskTypesConfig(_Strict):
    universal_required: list[str]
    classification_threshold: float = Field(ge=0, le=1)
    types: dict[str, TaskTypeRule]
    formats: dict[str, str]
    format_implies_channel: dict[str, str]
    suppliers: list[str]
    approver_default: str = Field(min_length=1)

    @model_validator(mode="after")
    def _has_fallback_type(self) -> Self:
        if "Outro" not in self.types:
            raise ValueError('types precisa conter "Outro" (destino de tipos desconhecidos)')
        return self


class TeamMember(_Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    skills: list[str]
    capacity: int = Field(gt=0)
    open_base: int = Field(ge=0)


class PriorityWeights(_Strict):
    urgency: float = Field(ge=0, le=1)
    impact: float = Field(ge=0, le=1)
    dependencies: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sum_to_one(self) -> Self:
        total = self.urgency + self.impact + self.dependencies + self.risk
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"os pesos devem somar 1 (soma atual: {total:g})")
        return self


class PriorityBand(_Strict):
    level: Literal["Crítica", "Alta", "Normal", "Baixa"]
    min: float = Field(ge=0, le=100)


class UrgencyStep(_Strict):
    max_hours: float | None = Field(default=..., gt=0)
    score: float = Field(ge=0, le=100)


class PrioritiesConfig(_Strict):
    weights: PriorityWeights
    bands: list[PriorityBand] = Field(min_length=1)
    urgency_by_hours: list[UrgencyStep] = Field(min_length=1)
    urgency_without_deadline: float = Field(ge=0, le=100)
    dependency_scores: list[float] = Field(min_length=1)
    deadline_hour: int = Field(ge=0, le=23)

    @model_validator(mode="after")
    def _ordered_tables(self) -> Self:
        mins = [band.min for band in self.bands]
        if mins != sorted(mins, reverse=True):
            raise ValueError("bands devem estar em ordem decrescente de min")
        if mins[-1] != 0:
            raise ValueError("bands precisa terminar com uma faixa com min 0")

        steps = self.urgency_by_hours
        if steps[-1].max_hours is not None:
            raise ValueError("urgency_by_hours precisa terminar com max_hours null")
        hours: list[float] = []
        for step in steps[:-1]:
            if step.max_hours is None:
                raise ValueError("urgency_by_hours só pode ter max_hours null no último item")
            hours.append(step.max_hours)
        if hours != sorted(hours):
            raise ValueError("urgency_by_hours deve ter max_hours em ordem crescente")
        return self


class AppConfig(_Strict):
    brands: dict[str, Brand]
    task_types: TaskTypesConfig
    team: list[TeamMember]
    priorities: PrioritiesConfig


# --- Loader ----------------------------------------------------------------------------------

_BRANDS = TypeAdapter(dict[str, Brand])
_TEAM = TypeAdapter(list[TeamMember])
_TASK_TYPES = TypeAdapter(TaskTypesConfig)
_PRIORITIES = TypeAdapter(PrioritiesConfig)


def _load_file[T](config_dir: Path, name: str, adapter: TypeAdapter[T]) -> T:
    path = config_dir / name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"{name}: arquivo não encontrado em {config_dir}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{name}: JSON inválido na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}"
        ) from exc
    try:
        return adapter.validate_python(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(name, exc)) from exc


def load_app_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> AppConfig:
    """Lê e valida os 4 arquivos de config/. Levanta ``ConfigError`` com mensagem clara."""
    brands = _load_file(config_dir, "brands.json", _BRANDS)
    task_types = _load_file(config_dir, "task_types.json", _TASK_TYPES)
    team = _load_file(config_dir, "team.json", _TEAM)
    priorities = _load_file(config_dir, "priorities.json", _PRIORITIES)

    _check_team(team, task_types)
    return AppConfig(brands=brands, task_types=task_types, team=team, priorities=priorities)


def _check_team(team: list[TeamMember], task_types: TaskTypesConfig) -> None:
    ids = [member.id for member in team]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ConfigError(f"team.json: ids duplicados: {', '.join(duplicated)}")
    for member in team:
        unknown = [skill for skill in member.skills if skill not in task_types.types]
        if unknown:
            raise ConfigError(
                f"team.json: {member.id} tem skills que não existem em task_types.json: "
                f"{', '.join(unknown)}"
            )


# --- Acesso cacheado para a aplicação --------------------------------------------------------


@lru_cache
def get_settings() -> Settings:
    return Settings.load()


@lru_cache
def get_app_config() -> AppConfig:
    return load_app_config(get_settings().config_dir)
