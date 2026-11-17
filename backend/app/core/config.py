"""Settings (.env) e loader das regras de negócio em config/*.json.

Os valores de negócio vivem só nos JSONs; este módulo apenas os valida e expõe tipados.
"""

from __future__ import annotations

import json
import math
import re
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

from app.schemas.api import ScoreBand

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


class TypeRulesConfig(_Strict):
    """Parâmetros do Rule Engine (§8.3, D28). Tipos referenciados precisam existir em ``types``."""

    type_implies_channel: dict[str, str]
    cta_types: list[str]
    supplier_promo_types: list[str]
    promo_supplier_files: list[str]

    @field_validator("promo_supplier_files")
    @classmethod
    def _templates_use_only_supplier(cls, templates: list[str]) -> list[str]:
        for template in templates:
            _check_supplier_template(template)
        return templates


class TitleConfig(_Strict):
    """Parâmetros do título da tarefa (§8.9, D30)."""

    promo_template: str = Field(min_length=1)
    objective_max_words: int = Field(ge=1)

    @field_validator("promo_template")
    @classmethod
    def _template_uses_only_supplier(cls, template: str) -> str:
        _check_supplier_template(template)
        return template


def _check_supplier_template(template: str) -> None:
    try:
        template.format(supplier="")
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"modelo {template!r} inválido: só é aceito o marcador {{supplier}}"
        ) from exc


class ScoreBandRule(_Strict):
    band: ScoreBand
    min: int = Field(ge=0, le=100)


class TaskTypesConfig(_Strict):
    universal_required: list[str] = Field(min_length=1)
    classification_threshold: float = Field(ge=0, le=1)
    score_bands: list[ScoreBandRule] = Field(min_length=1)
    types: dict[str, TaskTypeRule]
    formats: dict[str, str]
    format_implies_channel: dict[str, str]
    suppliers: list[str]
    approver_default: str = Field(min_length=1)
    title: TitleConfig
    rules: TypeRulesConfig

    @model_validator(mode="after")
    def _has_fallback_type(self) -> Self:
        if "Outro" not in self.types:
            raise ValueError('types precisa conter "Outro" (destino de tipos desconhecidos)')
        return self

    @model_validator(mode="after")
    def _ordered_score_bands(self) -> Self:
        mins = [band.min for band in self.score_bands]
        if mins != sorted(mins, reverse=True) or len(set(mins)) != len(mins):
            raise ValueError("score_bands devem estar em ordem decrescente de min")
        if mins[-1] != 0:
            raise ValueError("score_bands precisa terminar com uma faixa com min 0")
        return self

    @model_validator(mode="after")
    def _rules_reference_known_types(self) -> Self:
        rules = self.rules
        referenced = {
            "rules.type_implies_channel": list(rules.type_implies_channel),
            "rules.cta_types": rules.cta_types,
            "rules.supplier_promo_types": rules.supplier_promo_types,
        }
        for field, names in referenced.items():
            unknown = [name for name in names if name not in self.types]
            if unknown:
                raise ValueError(f"{field} com tipos inexistentes: {', '.join(unknown)}")
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


class GuardrailsConfig(_Strict):
    """Parâmetros dos guardrails (§8.2, D11, D27). Textos comparados sem acento e em minúsculas."""

    attachment_words: list[str] = Field(min_length=1)
    product_min_word_length: int = Field(ge=1)
    temporal_patterns: list[str] = Field(min_length=1)

    @field_validator("temporal_patterns")
    @classmethod
    def _patterns_compile(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"regex inválida {pattern!r}: {exc}") from exc
        return patterns


class AppConfig(_Strict):
    brands: dict[str, Brand]
    task_types: TaskTypesConfig
    team: list[TeamMember]
    priorities: PrioritiesConfig
    guardrails: GuardrailsConfig


# --- Loader ----------------------------------------------------------------------------------

_BRANDS = TypeAdapter(dict[str, Brand])
_TEAM = TypeAdapter(list[TeamMember])
_TASK_TYPES = TypeAdapter(TaskTypesConfig)
_PRIORITIES = TypeAdapter(PrioritiesConfig)
_GUARDRAILS = TypeAdapter(GuardrailsConfig)


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
    """Lê e valida os arquivos de config/. Levanta ``ConfigError`` com mensagem clara."""
    brands = _load_file(config_dir, "brands.json", _BRANDS)
    task_types = _load_file(config_dir, "task_types.json", _TASK_TYPES)
    team = _load_file(config_dir, "team.json", _TEAM)
    priorities = _load_file(config_dir, "priorities.json", _PRIORITIES)
    guardrails = _load_file(config_dir, "guardrails.json", _GUARDRAILS)

    _check_team(team, task_types)
    return AppConfig(
        brands=brands,
        task_types=task_types,
        team=team,
        priorities=priorities,
        guardrails=guardrails,
    )


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
