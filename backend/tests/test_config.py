import json
import shutil
from pathlib import Path

import pytest

from app.core.config import (
    DEFAULT_CONFIG_DIR,
    REPO_ROOT,
    AppConfig,
    ConfigError,
    Settings,
    load_app_config,
)


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    """Cópia de config/ para os testes poderem corromper arquivos sem tocar no original."""
    target = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, target)
    return target


def _rewrite(path: Path, mutate: object) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --- carregamento das 4 configs reais ---------------------------------------------------


def test_loads_all_real_configs() -> None:
    config = load_app_config(DEFAULT_CONFIG_DIR)

    assert isinstance(config, AppConfig)
    assert config.brands["construja"].name == "Construjá"
    ferja_cta = config.brands["ferja"].mandatory_cta
    assert ferja_cta == "Encontre Ferjá nas melhores lojas do seu bairro."
    assert config.brands["construdigi"].mandatory_cta is None

    assert config.task_types.classification_threshold == 0.7
    assert config.task_types.types["Arte"].promo_required == ["product", "price", "validity"]
    assert config.task_types.types["Vídeo"].promo_required == []
    assert config.task_types.formats["instagram|feed"] == "1080 × 1350 px"
    assert "Krona" in config.task_types.suppliers
    assert config.task_types.approver_default == "Gestor de Marketing"
    assert config.task_types.rules.type_implies_channel == {"Push": "App", "E-mail": "E-mail"}
    assert "Banner Site" in config.task_types.rules.cta_types
    assert config.task_types.rules.supplier_promo_types == ["Arte", "Social Media"]

    assert [m.id for m in config.team] == ["designer-a", "designer-b", "videomaker", "analista"]
    assert config.team[0].capacity == 15

    assert config.priorities.weights.urgency == 0.40
    assert config.priorities.bands[0].level == "Crítica"
    assert config.priorities.urgency_by_hours[-1].max_hours is None
    assert config.priorities.deadline_hour == 18

    assert "planilha" in config.guardrails.attachment_words
    assert config.guardrails.product_min_word_length == 4
    assert config.guardrails.temporal_patterns


# --- erros claros ----------------------------------------------------------------------


def test_invalid_json_syntax_names_file_and_position(config_copy: Path) -> None:
    (config_copy / "brands.json").write_text('{\n  "construja": {,\n}', encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_app_config(config_copy)

    message = str(exc.value)
    assert "brands.json" in message
    assert "JSON inválido" in message
    assert "linha 2" in message


def test_missing_file_names_file(config_copy: Path) -> None:
    (config_copy / "team.json").unlink()

    with pytest.raises(ConfigError, match=r"team\.json.*não encontrado"):
        load_app_config(config_copy)


def test_schema_error_names_file_and_field(config_copy: Path) -> None:
    _rewrite(config_copy / "team.json", lambda d: d[0].update(capacity="quinze"))

    with pytest.raises(ConfigError) as exc:
        load_app_config(config_copy)

    message = str(exc.value)
    assert "team.json" in message
    assert "0.capacity" in message


def test_unknown_key_is_rejected(config_copy: Path) -> None:
    _rewrite(config_copy / "brands.json", lambda d: d["ferja"].update(tom="errado"))

    with pytest.raises(ConfigError, match=r"(?s)brands\.json.*ferja\.tom"):
        load_app_config(config_copy)


@pytest.mark.parametrize(
    ("file", "mutate", "expected"),
    [
        (
            "priorities.json",
            lambda d: d["weights"].update(urgency=0.5),
            "pesos devem somar 1",
        ),
        (
            "priorities.json",
            lambda d: d.update(bands=[{"level": "Alta", "min": 70}]),
            "faixa com min 0",
        ),
        (
            "priorities.json",
            lambda d: d["urgency_by_hours"].pop(),
            "max_hours null",
        ),
        (
            "priorities.json",
            lambda d: d.update(deadline_hour=24),
            "deadline_hour",
        ),
        (
            "task_types.json",
            lambda d: d.update(classification_threshold=1.5),
            "classification_threshold",
        ),
        (
            "task_types.json",
            lambda d: d["types"].pop("Outro"),
            "Outro",
        ),
        (
            "task_types.json",
            lambda d: d["rules"]["cta_types"].append("Mágica"),
            "Mágica",
        ),
        (
            "task_types.json",
            lambda d: d["rules"]["type_implies_channel"].update({"Mágica": "App"}),
            "Mágica",
        ),
        (
            "task_types.json",
            lambda d: d["rules"]["supplier_promo_types"].append("Mágica"),
            "Mágica",
        ),
        (
            "task_types.json",
            lambda d: d["rules"]["promo_supplier_files"].append("Logo {marca}"),
            "{marca}",
        ),
        (
            "team.json",
            lambda d: d[0]["skills"].append("Mágica"),
            "Mágica",
        ),
        (
            "guardrails.json",
            lambda d: d["temporal_patterns"].append("(sem fechar"),
            "regex inválida",
        ),
    ],
)
def test_semantic_errors_are_clear(
    config_copy: Path, file: str, mutate: object, expected: str
) -> None:
    _rewrite(config_copy / file, mutate)

    with pytest.raises(ConfigError) as exc:
        load_app_config(config_copy)

    assert file in str(exc.value)
    assert expected in str(exc.value)


# --- settings (.env) -------------------------------------------------------------------


def test_settings_read_env_example() -> None:
    settings = Settings(_env_file=REPO_ROOT / ".env.example")

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.llm_provider == "anthropic"
    assert settings.llm_fallback is True
    assert settings.task_manager == "local"
    assert settings.app_timezone == "America/Sao_Paulo"
    assert settings.anthropic_api_key is None
    assert settings.config_dir == DEFAULT_CONFIG_DIR


def test_settings_env_vars_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASANA_TOKEN", "segredo")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "fake"
    assert settings.asana_token is not None
    assert settings.asana_token.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_settings_reject_invalid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        Settings.load(env_file=None)


def test_settings_reject_unknown_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "Marte/Olympus")

    with pytest.raises(ConfigError, match="APP_TIMEZONE"):
        Settings.load(env_file=None)
