from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI, OpenAI
from sqlmodel import Session, select

from brainrh.database import get_session
from brainrh.models.llm_settings import LLMProcessSettingDB


@dataclass(frozen=True)
class LLMProviderDefinition:
    id: str
    label: str
    api_key_env: str
    base_url_env: str | None
    default_base_url: str | None
    models: tuple[str, ...]


@dataclass(frozen=True)
class LLMProcessDefinition:
    id: str
    label: str
    category: str
    description: str
    default_provider: str
    default_model: str
    allowed_providers: tuple[str, ...]
    provider_models: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class LLMSelection:
    process_id: str
    provider: str
    model: str
    source: str


PROVIDERS: dict[str, LLMProviderDefinition] = {
    "openai": LLMProviderDefinition(
        id="openai",
        label="OpenAI",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        default_base_url=None,
        models=(
            "gpt-5.4-mini",
            "gpt-5-mini",
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-realtime",
            "gpt-realtime-1.5",
            "gpt-realtime-2.1-mini",
        ),
    ),
    "xai": LLMProviderDefinition(
        id="xai",
        label="xAI",
        api_key_env="XAI_API_KEY",
        base_url_env="XAI_BASE_URL",
        default_base_url="https://api.x.ai/v1",
        models=("grok-4-1-fast-reasoning", "grok-4.3", "grok-3-mini-fast"),
    ),
    "mistral": LLMProviderDefinition(
        id="mistral",
        label="Mistral AI",
        api_key_env="MISTRAL_API_KEY",
        base_url_env="MISTRAL_BASE_URL",
        default_base_url="https://api.mistral.ai/v1",
        models=("mistral-large-latest", "mistral-small-latest"),
    ),
}


CHAT_PROVIDERS = ("openai", "xai", "mistral")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


DEFAULT_MATCHING_PREFILTER_PROVIDER = "xai" if _env("XAI_API_KEY") else "openai"
DEFAULT_MATCHING_RERANK_PROVIDER = "xai" if _env("XAI_API_KEY") else "openai"
DEFAULT_INTERVIEW_SHEET_PROVIDER = "xai" if _env("XAI_API_KEY") else "openai"
DEFAULT_COMPANY_CV_PROVIDER = "xai" if _env("XAI_API_KEY") else "openai"


PROCESS_DEFINITIONS: dict[str, LLMProcessDefinition] = {
    "cv_parsing": LLMProcessDefinition(
        id="cv_parsing",
        label="Parsing CV",
        category="CV",
        description="Extraction structurée des CV PDF/DOCX.",
        default_provider="openai",
        default_model="gpt-4o-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "offer_parsing": LLMProcessDefinition(
        id="offer_parsing",
        label="Parsing offre",
        category="Offres",
        description="Extraction structurée d'une offre depuis texte ou fichier.",
        default_provider="openai",
        default_model="gpt-5-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "offer_enrichment": LLMProcessDefinition(
        id="offer_enrichment",
        label="Enrichissement offre",
        category="Offres",
        description="Génération des enrichissements must-have/nice-have.",
        default_provider="openai",
        default_model="gpt-5-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "offer_criteria": LLMProcessDefinition(
        id="offer_criteria",
        label="Extraction critères",
        category="Offres",
        description="Extraction des critères must-have depuis une offre.",
        default_provider="openai",
        default_model="gpt-5-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "matching_prefilter": LLMProcessDefinition(
        id="matching_prefilter",
        label="Matching pré-filtres",
        category="Matching",
        description="Filtrage must-have et nice-have avant reranking.",
        default_provider=DEFAULT_MATCHING_PREFILTER_PROVIDER,
        default_model="grok-3-mini-fast" if DEFAULT_MATCHING_PREFILTER_PROVIDER == "xai" else "gpt-4.1-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "matching_reranking": LLMProcessDefinition(
        id="matching_reranking",
        label="Matching reranking",
        category="Matching",
        description="Analyse qualitative et reranking du top candidats.",
        default_provider=DEFAULT_MATCHING_RERANK_PROVIDER,
        default_model="grok-4.3" if DEFAULT_MATCHING_RERANK_PROVIDER == "xai" else "gpt-5-mini",
        allowed_providers=CHAT_PROVIDERS,
    ),
    "interview_sheet_generation": LLMProcessDefinition(
        id="interview_sheet_generation",
        label="Fiche d'entretien",
        category="Entretiens",
        description="Génération de la fiche d'entretien structurée.",
        default_provider=DEFAULT_INTERVIEW_SHEET_PROVIDER,
        default_model=(
            "grok-4-1-fast-reasoning"
            if DEFAULT_INTERVIEW_SHEET_PROVIDER == "xai"
            else _env("OPENAI_INTERVIEW_SHEET_MODEL", _env("OPENAI_INTERVIEW_PLAN_MODEL", "gpt-4o-mini"))
        ),
        allowed_providers=CHAT_PROVIDERS,
    ),
    "company_cv_generation": LLMProcessDefinition(
        id="company_cv_generation",
        label="CV client",
        category="CV client",
        description="Génération et vérification du CV client DOCX.",
        default_provider=DEFAULT_COMPANY_CV_PROVIDER,
        default_model=(
            _env("BRAINRH_COMPANY_CV_XAI_MODEL", "grok-4-1-fast-reasoning")
            if DEFAULT_COMPANY_CV_PROVIDER == "xai"
            else _env("BRAINRH_COMPANY_CV_GENERATION_MODEL", "gpt-5-mini")
        ),
        allowed_providers=CHAT_PROVIDERS,
    ),
    "realtime_interview_plan": LLMProcessDefinition(
        id="realtime_interview_plan",
        label="Plan entretien realtime",
        category="Entretiens realtime",
        description="Préparation du plan d'entretien avant session live.",
        default_provider="openai",
        default_model=_env("OPENAI_INTERVIEW_PLAN_MODEL", "gpt-4o-mini"),
        allowed_providers=("openai", "mistral"),
    ),
    "realtime_interview_live": LLMProcessDefinition(
        id="realtime_interview_live",
        label="Entretien live realtime",
        category="Entretiens realtime",
        description="Session WebRTC OpenAI Realtime. Provider verrouillé par l'API temps réel.",
        default_provider="openai",
        default_model=_env("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini"),
        allowed_providers=("openai",),
        provider_models={
            "openai": (
                "gpt-realtime-2.1-mini",
                "gpt-realtime-1.5",
                "gpt-realtime",
            )
        },
    ),
}


def list_process_definitions() -> list[LLMProcessDefinition]:
    return list(PROCESS_DEFINITIONS.values())


def get_process_definition(process_id: str) -> LLMProcessDefinition:
    try:
        return PROCESS_DEFINITIONS[process_id]
    except KeyError as exc:
        raise ValueError(f"Process LLM inconnu: {process_id}") from exc


def get_models_for_process(process: LLMProcessDefinition, provider: str) -> tuple[str, ...]:
    if process.provider_models and provider in process.provider_models:
        return process.provider_models[provider]
    return PROVIDERS[provider].models


def validate_provider_model(process: LLMProcessDefinition, provider: str, model: str) -> None:
    if provider not in process.allowed_providers:
        allowed = ", ".join(process.allowed_providers)
        raise ValueError(f"Provider non autorisé pour {process.id}: {provider}. Attendus: {allowed}.")
    if provider not in PROVIDERS:
        raise ValueError(f"Provider LLM inconnu: {provider}")
    allowed_models = get_models_for_process(process, provider)
    if model not in allowed_models:
        allowed = ", ".join(allowed_models)
        raise ValueError(f"Modèle non autorisé pour {process.id}/{provider}: {model}. Attendus: {allowed}.")


def is_provider_configured(provider: str) -> bool:
    import os

    return bool((os.getenv(PROVIDERS[provider].api_key_env) or "").strip())


def provider_base_url(provider: str) -> str | None:
    definition = PROVIDERS[provider]
    if definition.base_url_env:
        import os

        value = (os.getenv(definition.base_url_env) or "").strip().rstrip("/")
        if value:
            return value
    return definition.default_base_url


def _db_setting_for(session: Session, process_id: str) -> LLMProcessSettingDB | None:
    return session.exec(select(LLMProcessSettingDB).where(LLMProcessSettingDB.process_id == process_id)).first()


def resolve_llm_selection(
    process_id: str,
    *,
    session: Session | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LLMSelection:
    process = get_process_definition(process_id)

    if provider_override:
        provider = provider_override
        model = model_override or process.default_model
        validate_provider_model(process, provider, model)
        return LLMSelection(process_id=process_id, provider=provider, model=model, source="request")

    def _resolve(active_session: Session) -> LLMSelection:
        setting = _db_setting_for(active_session, process_id)
        if setting:
            try:
                model = model_override or setting.model
                validate_provider_model(process, setting.provider, model)
                return LLMSelection(process_id=process_id, provider=setting.provider, model=model, source="database")
            except ValueError:
                pass
        model = model_override or process.default_model
        validate_provider_model(process, process.default_provider, model)
        return LLMSelection(process_id=process_id, provider=process.default_provider, model=model, source="default")

    if session is not None:
        return _resolve(session)
    with get_session() as managed_session:
        return _resolve(managed_session)


def get_api_key(provider: str) -> str:
    import os

    api_key = (os.getenv(PROVIDERS[provider].api_key_env) or "").strip()
    if not api_key:
        raise ValueError(f"{PROVIDERS[provider].api_key_env} non configurée.")
    return api_key


def create_chat_client(selection: LLMSelection, *, async_client: bool = False) -> OpenAI | AsyncOpenAI:
    kwargs: dict[str, Any] = {"api_key": get_api_key(selection.provider)}
    base_url = provider_base_url(selection.provider)
    if base_url:
        kwargs["base_url"] = base_url
    if async_client:
        return AsyncOpenAI(**kwargs)
    return OpenAI(**kwargs)


def get_chat_client_for_process(
    process_id: str,
    *,
    model_override: str | None = None,
    provider_override: str | None = None,
    async_client: bool = False,
) -> tuple[OpenAI | AsyncOpenAI, LLMSelection]:
    selection = resolve_llm_selection(
        process_id,
        model_override=model_override,
        provider_override=provider_override,
    )
    return create_chat_client(selection, async_client=async_client), selection


def list_llm_process_settings(session: Session) -> list[dict[str, Any]]:
    rows = {
        row.process_id: row
        for row in session.exec(select(LLMProcessSettingDB)).all()
    }
    result: list[dict[str, Any]] = []
    for process in list_process_definitions():
        row = rows.get(process.id)
        provider = row.provider if row else process.default_provider
        model = row.model if row else process.default_model
        source = "database" if row else "default"
        try:
            validate_provider_model(process, provider, model)
        except ValueError:
            provider = process.default_provider
            model = process.default_model
            source = "default"
        result.append(
            {
                "process_id": process.id,
                "label": process.label,
                "category": process.category,
                "description": process.description,
                "provider": provider,
                "model": model,
                "source": source,
                "default_provider": process.default_provider,
                "default_model": process.default_model,
                "locked": len(process.allowed_providers) == 1,
                "lock_reason": (
                    "API temps réel OpenAI uniquement."
                    if process.id == "realtime_interview_live"
                    else None
                ),
                "providers": [
                    {
                        "id": provider_id,
                        "label": PROVIDERS[provider_id].label,
                        "configured": is_provider_configured(provider_id),
                        "models": list(get_models_for_process(process, provider_id)),
                    }
                    for provider_id in process.allowed_providers
                ],
                "updated_at": row.updated_at.isoformat() if row else None,
            }
        )
    return result


def update_llm_process_setting(
    session: Session,
    *,
    process_id: str,
    provider: str,
    model: str,
    actor_user_id: str,
) -> LLMProcessSettingDB:
    process = get_process_definition(process_id)
    validate_provider_model(process, provider, model)
    if not is_provider_configured(provider):
        raise ValueError(f"{PROVIDERS[provider].label} n'est pas configuré côté serveur.")
    row = _db_setting_for(session, process_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = LLMProcessSettingDB(
            process_id=process_id,
            provider=provider,
            model=model,
            updated_by_user_id=actor_user_id,
            updated_at=now,
        )
        session.add(row)
    else:
        row.provider = provider
        row.model = model
        row.updated_by_user_id = actor_user_id
        row.updated_at = now
    session.commit()
    session.refresh(row)
    return row
