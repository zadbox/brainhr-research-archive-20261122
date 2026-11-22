"""
Module de matching CV/Offre refactorisé avec scoring amélioré
Inclut: embeddings, filtrage must-have, scoring nice-have, bonus expériences, re-ranking LLM
V2: Validation avec jsonschema + parallélisation
"""

import os
import json
import re
import hashlib
import numpy as np
import time
import logging
import requests
from collections import Counter
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import modules V2
from validation import validate_and_repair, check_cv_size, check_min_content
from parallel_processing import ParallelPipeline
from lib.experience_analyzer import detect_gaps_and_overlaps, format_flags_for_llm
from lib.llm_prompt_security import (
    format_untrusted_candidate_data,
    project_candidate_cv,
    secure_candidate_system_prompt,
)
from lib.models import Evidence, EvidenceMap, Flags
from lib.scoring_sections import (
    extract_offer_items,
    coverage_lex,
    score_exp,
    score_context,
    final_score,
    renorm_weights,
    DEFAULT_WEIGHTS,
    TAU,
    Y_CAP_DEFAULT,
)
from brainrh.services.llm_settings_service import (
    create_chat_client,
    resolve_llm_selection,
)

load_dotenv()


class MatchingEngine:
    """Moteur de matching CV/Offre avec scoring intelligent"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialise le moteur de matching

        Args:
            config: Configuration (dict depuis config.yaml via config_loader)
        """
        self.config = config or self._default_config()

        # Initialiser le modèle d'embeddings
        self.embedding_model = SentenceTransformer(
            self.config.get("embeddings", {}).get("model", "all-MiniLM-L6-v2")
        )

        # Client OpenAI legacy: utilisé seulement par les chemins historiques non switchés.
        api_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = OpenAI(api_key=api_key, timeout=60.0, max_retries=0) if api_key else None
        self.llm_model = self.config.get("llm", {}).get("model", "gpt-5-mini")
        self.fallback_models = self.config.get("llm", {}).get("fallback_models", ["gpt-4.1-mini", "gpt-5-mini"])

        # Températures pour les différents usages
        # NOTE: Ces températures sont utilisées UNIQUEMENT pour xAI (Grok) et l'extraction
        # GPT-5 mini ne supporte PAS le paramètre temperature (erreur 400 si fourni)
        self.temperature_extraction = self.config.get("llm", {}).get("temperature_extraction", 0.1)
        self.temperature_reranking = self.config.get("llm", {}).get("temperature_reranking", 0.2)  # Pour xAI uniquement
        
        # Seed pour déterminisme (même seed = mêmes résultats)
        self.seed = self.config.get("llm", {}).get("seed", 42)

        # Technical info removed from UI as requested
        # print(f"✅ Engine initialisé avec modèle: {self.llm_model} (temp_extract={self.temperature_extraction}, temp_rerank={self.temperature_reranking})")

        # Configuration de scoring
        self.scoring_config = self.config.get("scoring", {})

        # Initialisation des poids de sections (Exp/Tech/Summary/Soft)
        section_weights_cfg = self.config.get("scoring", {}).get("section_weights", {})
        self.section_weights = {
            "Exp": section_weights_cfg.get("experiences_professionnelles", DEFAULT_WEIGHTS["Exp"]),
            "Tech": section_weights_cfg.get("competences_techniques", DEFAULT_WEIGHTS["Tech"]),
            "Summary": section_weights_cfg.get("resume_professionnel", DEFAULT_WEIGHTS.get("Summary", 0.2)),
            "Soft": section_weights_cfg.get("competences_transversales", DEFAULT_WEIGHTS.get("Soft", 0.0)),
        }

        # Cache pour embeddings
        self.cache_folder = Path(self.config.get("paths", {}).get("cache_folder", "cache"))
        self.cache_folder.mkdir(parents=True, exist_ok=True)

        # V2: Pipeline de parallélisation
        self.pipeline = ParallelPipeline(
            max_file_workers=self.config.get("parallel", {}).get("file_workers", 4),
            max_llm_concurrent=self.config.get("parallel", {}).get("llm_concurrent", 5),
            openai_client=self.openai_client
        )

        # V2: Flags de validation
        self.validate_outputs = self.config.get("validation", {}).get("enabled", True)
        self.max_repair_attempts = self.config.get("validation", {}).get("max_repair_attempts", 3)

    def _default_config(self) -> Dict:
        """Configuration par défaut"""
        return {
            "llm": {"model": "gpt-5-mini"},
            "scoring": {
                "top_k": 50,
                "top_rerank": 10,
                "nice_have_malus_factor": 0.95,
                "bonus_experience_exacte": 0.15,
                "bonus_experience_tres_proche": 0.10,
                "bonus_experience_proche": 0.05,
                "score_min": 0.0,
                "score_max": 1.0,
                "reranking_provider": "openai",  # Default: OpenAI (peut être "xai" pour Grok)
                "xai_model": "grok-4.3",
                "xai_reasoning_effort": "low",
                "prefilter_provider": "xai",
                "prefilter_xai_model": "grok-3-mini-fast",
                "prefilter_openai_model": "gpt-4.1-mini",
                "prefilter_concurrency": 30,
                "prefilter_qps": 11.0,
                "prefilter_timeout_s": 20,
                "prefilter_retries": 0,
                "prefilter_backoff_s": 1.0,
            },
            "embeddings": {"model": "all-MiniLM-L6-v2", "cache_enabled": True},
            "paths": {"cache_folder": "cache"}
        }

    def _prefilter_stage_config(self) -> Dict[str, Any]:
        return {
            "provider": self.scoring_config.get("prefilter_provider", "xai").lower(),
            "xai_model": self.scoring_config.get("prefilter_xai_model", "grok-3-mini-fast"),
            "openai_model": self.scoring_config.get("prefilter_openai_model", "gpt-4.1-mini"),
            "concurrency": int(self.scoring_config.get("prefilter_concurrency", 30)),
            "qps": float(self.scoring_config.get("prefilter_qps", 11.0)),
            "timeout_s": int(self.scoring_config.get("prefilter_timeout_s", 20)),
            "retries": int(self.scoring_config.get("prefilter_retries", 0)),
            "backoff_s": float(self.scoring_config.get("prefilter_backoff_s", 1.0)),
        }

    def _chat_completion_for_process(
        self,
        process_id: str,
        *,
        messages: list[dict[str, str]],
        model_override: str | None = None,
        response_format: dict[str, str] | None = None,
        timeout_s: int | None = None,
        max_tokens: int | None = None,
    ):
        selection = resolve_llm_selection(process_id, model_override=model_override)
        client = create_chat_client(selection)
        payload: dict[str, Any] = {
            "model": selection.model,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if timeout_s is not None:
            payload["timeout"] = timeout_s
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if selection.provider in {"openai", "xai"}:
            payload["seed"] = self.seed
        return client.chat.completions.create(**payload), selection

    @staticmethod
    def _append_prefilter_runtime_event(
        runtime_events: Optional[List[Dict[str, Any]]],
        *,
        provider_used: str,
        model_used: str,
        fallback_used: bool,
        error: Optional[str] = None,
    ) -> None:
        if runtime_events is None:
            return
        runtime_events.append(
            {
                "provider_used": provider_used,
                "model_used": model_used,
                "fallback_used": fallback_used,
                "error": error,
            }
        )

    def _summarize_prefilter_runtime(
        self,
        runtime_events: List[Dict[str, Any]],
        *,
        duration_s: Optional[float],
    ) -> Dict[str, Any]:
        if not runtime_events:
            return {
                "provider_used": None,
                "model_used": None,
                "duration_s": None,
                "fallback_used": None,
            }

        provider_counts = Counter(
            event.get("provider_used")
            for event in runtime_events
            if event.get("provider_used")
        )
        model_counts = Counter(
            event.get("model_used")
            for event in runtime_events
            if event.get("model_used")
        )

        provider_used = None
        if provider_counts:
            provider_used = next(iter(provider_counts)) if len(provider_counts) == 1 else "mixed"

        model_used = None
        if model_counts:
            model_used = next(iter(model_counts)) if len(model_counts) == 1 else "mixed"

        return {
            "provider_used": provider_used,
            "model_used": model_used,
            "duration_s": round(duration_s, 2) if duration_s is not None else None,
            "fallback_used": any(bool(event.get("fallback_used")) for event in runtime_events),
        }

    def _call_structured_json_with_prefilter_fallback(
        self,
        *,
        system_content: str,
        user_content: str,
        timeout_s: int,
        runtime_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any] | List[Any] | None, Dict[str, Any]]:
        stage_cfg = self._prefilter_stage_config()
        openai_model = stage_cfg["openai_model"]
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        try:
            response, selection = self._chat_completion_for_process(
                "matching_prefilter",
                messages=messages,
                response_format={"type": "json_object"},
                timeout_s=timeout_s,
            )
            raw_content = response.choices[0].message.content
            runtime_meta = {
                "provider_used": selection.provider,
                "model_used": selection.model,
                "fallback_used": False,
            }
            self._append_prefilter_runtime_event(runtime_events, **runtime_meta)
            return self._safe_json_parse(raw_content), runtime_meta
        except Exception as exc:
            selected = resolve_llm_selection("matching_prefilter")
            if selected.provider == "openai":
                runtime_meta = {
                    "provider_used": selected.provider,
                    "model_used": selected.model,
                    "fallback_used": False,
                }
                self._append_prefilter_runtime_event(
                    runtime_events,
                    **runtime_meta,
                    error=str(exc),
                )
                raise
            logger.warning(
                "Pré-filtre %s indisponible (model=%s) → fallback OpenAI (%s)",
                selected.provider,
                selected.model,
                openai_model,
                exc_info=True,
            )

        runtime_meta = {
            "provider_used": "openai",
            "model_used": openai_model,
            "fallback_used": True,
        }
        try:
            fallback_selection = resolve_llm_selection(
                "matching_prefilter",
                provider_override="openai",
                model_override=openai_model,
            )
            fallback_client = create_chat_client(fallback_selection)
            response = fallback_client.chat.completions.create(
                model=fallback_selection.model,
                messages=messages,
                response_format={"type": "json_object"},
                seed=self.seed,
                timeout=timeout_s,
            )
            result = self._safe_json_parse(response.choices[0].message.content)
        except Exception as exc:
            self._append_prefilter_runtime_event(
                runtime_events,
                **runtime_meta,
                error=str(exc),
            )
            raise

        self._append_prefilter_runtime_event(runtime_events, **runtime_meta)
        return result, runtime_meta

    def clean_text(self, text: str) -> str:
        """Nettoie et normalise le texte"""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.lower().replace("\xa0", " ").strip())

    def _flatten_cv_text(self, cv: Dict) -> List[str]:
        """Aplatit le CV en liste de textes"""
        cv_text = []

        # Gérer les deux formats: avec ou sans wrapper "sections"
        if "sections" in cv:
            cv_data = cv["sections"]
        elif "content" in cv:
            cv_data = cv["content"]
        else:
            cv_data = cv

        for k, v in cv_data.items():
            if k in ["cv", "identite"]:  # Ignorer le nom du fichier et l'identité
                continue

            # SKIP null values
            if v is None:
                continue

            if isinstance(v, list):
                cv_text.extend([self.clean_text(str(x)) for x in v if x is not None])
            elif isinstance(v, dict):
                # Pour les dicts (comme mobilite), aplatir récursivement
                for sub_v in v.values():
                    if sub_v is not None:
                        cv_text.append(self.clean_text(str(sub_v)))
            else:
                cv_text.append(self.clean_text(str(v)))

        return cv_text

    def _find_nice_have_missing(
        self,
        cv: Dict,
        nice_have_list: List[str],
        job_description: str,
        runtime_events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Recherche sémantique des nice-have manquants"""
        if not nice_have_list:
            return []

        cv_text = format_untrusted_candidate_data(project_candidate_cv(cv))

        prompt = f"""Tu es un expert RH qui analyse sémantiquement les CVs.

OFFRE D'EMPLOI :
{job_description}

NICE-HAVE À CHERCHER (critères bonus) :
{json.dumps(nice_have_list, ensure_ascii=False)}

CV À ANALYSER :
{cv_text}

TÂCHE :
Identifie quels nice-have sont présents dans ce CV (même de manière sémantique).

Réponds UNIQUEMENT en JSON :
{{
    "nice_have_presents": ["nice-have 1", "nice-have 2"],
    "nice_have_manquants": ["nice-have 3", "nice-have 4"],
    "justifications": {{
        "nice-have 1": "Certification TOGAF mentionnée en section certifications",
        "nice-have 2": "Expérience Data Engineer (2018-2021, 3 ans) + Data Architect (2021-2024, 3 ans) = 6 ans > seuil requis"
    }}
}}

RÈGLES :
- Si un nice-have est mentionné explicitement ou sémantiquement → l'ajouter à "presents"
- Si un nice-have n'est pas trouvé → l'ajouter à "manquants"
- Si un nice-have impose un minimum d'années (ex: "≥5 ans en data", "10 ans SI"):
  * Analyser les expériences avec dates (gérer "présent", "actuel", années seules, etc.)
  * Cumuler la durée des expériences pertinentes pour ce critère
  * Marquer "présent" seulement si le seuil est atteint
- Pour chaque nice-have marqué "présent", fournir une justification dans le champ "justifications"
- Justification: nom exact de la certification/techno OU liste des expériences (poste, dates, durée) si durée requise
"""

        result, _runtime_meta = self._call_structured_json_with_prefilter_fallback(
            system_content=secure_candidate_system_prompt(
                "Tu es un assistant RH expert en analyse sémantique. Tu réponds UNIQUEMENT en JSON valide."
            ),
            user_content=prompt,
            timeout_s=40,
            runtime_events=runtime_events,
        )

        if isinstance(result, dict):
            return result.get("nice_have_manquants", [])

        return nice_have_list

    def _analyze_experience_bonus(self, cv: Dict, job_description: str) -> float:
        """
        Analyse les expériences et retourne un MULTIPLICATEUR (1.0 à 1.15)

        Returns:
            float: Multiplicateur entre 1.0 (aucune exp pertinente) et 1.15 (expérience très pertinente)
        """
        cv_text = format_untrusted_candidate_data(project_candidate_cv(cv))

        prompt = f"""
        Tu es un expert RH qui analyse les expériences professionnelles des candidats.

        OFFRE D'EMPLOI :
        {job_description}

        CV À ANALYSER :
        {cv_text}

        TÂCHE :
        Analyse la section "expériences_professionnelles" du CV et évalue la pertinence :
        - Expérience TRÈS PERTINENTE au poste (même domaine, même niveau) → multiplicateur 1.15
        - Expérience PERTINENTE (domaine proche, niveau similaire) → multiplicateur 1.10
        - Expérience PARTIELLEMENT PERTINENTE (quelques similitudes) → multiplicateur 1.05
        - Aucune expérience pertinente → multiplicateur 1.0

        RÈGLES:
        - Prends la MEILLEURE expérience (pas cumul)
        - Considère le domaine, le niveau de responsabilité, les technologies
        - Sois strict: seules les vraies expériences pertinentes comptent

        Réponds UNIQUEMENT en JSON :
        {{
            "pertinence": "TRÈS PERTINENTE" | "PERTINENTE" | "PARTIELLEMENT PERTINENTE" | "NON PERTINENTE",
            "justification": "phrase courte expliquant pourquoi",
            "multiplicateur": 1.15 | 1.10 | 1.05 | 1.0
        }}
        """

        try:
            response, _selection = self._chat_completion_for_process(
                "matching_prefilter",
                messages=[
                    {
                        "role": "system",
                        "content": secure_candidate_system_prompt(
                            "Tu es un assistant RH expert. Tu réponds UNIQUEMENT en JSON valide."
                        ),
                    },
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
            )

            result = self._safe_json_parse(response.choices[0].message.content)

            if isinstance(result, dict):
                mult = result.get("multiplicateur", 1.0)
                # Sécurité: clamp entre 1.0 et 1.15
                return max(1.0, min(1.15, float(mult)))

        except Exception as e:
            print(f"⚠️ Erreur bonus expériences: {str(e)}")

        return 1.0

    def vectorize_text(self, text_list: List[str]) -> np.ndarray:
        """Vectorise une liste de textes (ancienne méthode, garde pour compatibilité)"""
        if not text_list:
            return np.zeros((1, self.embedding_model.get_sentence_embedding_dimension()))

        joined = " ".join(text_list)

        # Cache des embeddings
        if self.config.get("cache", {}).get("enabled", True):
            cache_key = hashlib.sha256(joined.encode()).hexdigest()
            cache_file = self.cache_folder / f"emb_{cache_key}.npy"

            if cache_file.exists():
                return np.load(cache_file)

            # Calculer et cacher
            embedding = self.embedding_model.encode([joined])
            np.save(cache_file, embedding)
            return embedding

        return self.embedding_model.encode([joined])

    def vectorize_many_docs(self, docs_as_lists: List[List[str]], batch_size: int = None, normalize: bool = True) -> np.ndarray:
        """
        Vectorise plusieurs documents en batch (optimisé)

        Args:
            docs_as_lists: Liste de listes de strings (sections de CV aplaties)
            batch_size: Taille du batch (défaut: depuis config)
            normalize: Normaliser les embeddings (True pour cosine via dot product)

        Returns:
            np.ndarray de shape (N, d) en float32 normalisé
        """
        if not docs_as_lists:
            dim = self.embedding_model.get_sentence_embedding_dimension()
            return np.zeros((0, dim), dtype=np.float32)

        # Concaténer chaque liste en une chaîne
        texts = [" ".join(parts) for parts in docs_as_lists]

        # Batch size depuis config
        if batch_size is None:
            batch_size = self.config.get("embeddings", {}).get("batch_size", 32)

        # Encoder en batch
        embeddings = self.embedding_model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False
        )

        # Assurer float32
        return embeddings.astype(np.float32)

    def extract_must_have_with_llm(self, job_description: str, model_override: str | None = None) -> List[str]:
        """
        Extrait les must-have depuis l'offre avec LLM (format concis)

        Args:
            job_description: Description de l'offre

        Returns:
            Liste de must-have extraits (concis, actionnables, dédupliqués)
        """
        prompt = f"""Tu es un expert RH spécialisé dans l'analyse d'offres d'emploi. Ta mission: identifier les critères CRITIQUES qui sont essentiels pour le poste.

═══════════════════════════════════════════════════════════════
DÉFINITION: Qu'est-ce qu'un CRITÈRE CRITIQUE ?
═══════════════════════════════════════════════════════════════

Un critère est CRITIQUE si:
✓ L'offre utilise un vocabulaire IMPÉRATIF: "requis", "obligatoire", "indispensable", "minimum", "impératif", "nécessaire"
✓ OU l'absence du critère rend le candidat PEU QUALIFIÉ pour le poste
✓ OU une durée/niveau MINIMUM est explicitement mentionné (ex: "minimum 5 ans", "au moins Bac+5")

⚠️ IMPORTANT: Extraire AU MINIMUM 10 critères (idéalement 10-15)

Un critère N'EST PAS un must-have si:
✗ Vocabulaire OPTIONNEL: "souhaité", "apprécié", "serait un plus", "idéalement", "de préférence", "atout", "bonus"
✗ Formulation VAGUE sans seuil: "expérience confirmée", "bonne connaissance" (sans durée précise)
✗ CONTEXTE d'entreprise: lieu, type de contrat, secteur d'activité, environnement de travail

═══════════════════════════════════════════════════════════════
RÈGLES D'EXTRACTION
═══════════════════════════════════════════════════════════════

1. PRÉCISION MAXIMALE
   - Toujours inclure les durées/niveaux chiffrés: "10+ ans", "Bac+5", "Niveau C1"
   - Conserver les contextes importants: "Management équipe 20+ personnes", "Budget 5M€+"

2. CONCISION (max 10 mots)
   - ✅ BON: "Minimum 10 ans expérience architecture SI"
   - ✅ BON: "Python et Django 5+ ans"
   - ❌ MAUVAIS: "Expérience au sein d'une DSI de plusieurs centaines de collaborateurs dans un contexte de transformation digitale"

3. IGNORER SYSTÉMATIQUEMENT
   - Localisation géographique (Paris, Île-de-France, etc.)
   - Type de contrat (CDI, CDD, freelance, temps plein/partiel)
   - Secteur d'activité (banque, industrie, etc.)
   - Soft skills génériques (rigueur, autonomie, esprit d'équipe)

4. DÉTECTER LES FAUX MUST-HAVES
   - "Une certification X serait un plus" → IGNORER (optionnel)
   - "Idéalement niveau Y" → IGNORER (souhaité mais pas exigé)
   - "Expérience en Z appréciée" → IGNORER (nice-to-have)

═══════════════════════════════════════════════════════════════
EXEMPLES RÉELS PAR CATÉGORIE
═══════════════════════════════════════════════════════════════

🎓 DIPLÔME:
✅ "Bac+5 informatique ou équivalent"
✅ "Diplôme ingénieur requis"
✅ "Master en data science"

💼 EXPÉRIENCE (toujours avec durée si mentionnée):
✅ "Minimum 10 ans architecture SI"
✅ "5+ ans gestion projet IT"
✅ "Expérience management 20+ personnes"
✅ "7 ans minimum développement backend"

💻 COMPÉTENCES TECHNIQUES:
✅ "Python et Django"
✅ "AWS certifié"
✅ "Maîtrise SQL et PostgreSQL"
✅ "Docker et Kubernetes"

🗣️ LANGUES:
✅ "Anglais courant exigé"
✅ "Anglais niveau C1 minimum"
✅ "Bilingue français-anglais"

🏆 CERTIFICATIONS:
✅ "PMP obligatoire"
✅ "Certification AWS Solutions Architect"
✅ "TOGAF certifié requis"

═══════════════════════════════════════════════════════════════
CAS LIMITES - COMMENT TRANCHER ?
═══════════════════════════════════════════════════════════════

❓ "Expérience significative en Java"
→ IGNORER (pas de seuil chiffré = trop vague)

❓ "Au moins 3 ans en développement Python requis"
→ ✅ EXTRAIRE: "Minimum 3 ans développement Python"

❓ "Connaissance de Docker et Kubernetes serait un atout"
→ IGNORER ("atout" = nice-to-have)

❓ "Impératif d'avoir géré des équipes de 10+ personnes"
→ ✅ EXTRAIRE: "Management équipe 10+ personnes"

❓ "Basé à Paris ou Île-de-France"
→ IGNORER (localisation)

❓ "CDI temps plein"
→ IGNORER (type de contrat)

❓ "Minimum 15 ans d'expérience dans le secteur bancaire avec gestion de projets réglementaires"
→ ✅ EXTRAIRE: "Minimum 15 ans expérience secteur bancaire" (limite: 10 mots)

═══════════════════════════════════════════════════════════════
OFFRE À ANALYSER
═══════════════════════════════════════════════════════════════

{job_description}

═══════════════════════════════════════════════════════════════
FORMAT DE SORTIE
═══════════════════════════════════════════════════════════════

Retourne UNIQUEMENT un JSON conforme à ce schéma:
{{
  "must_haves": [
    "critère 1",
    "critère 2",
    ...
  ]
}}

⚠️ Si AUCUN critère éliminatoire n'est trouvé → {{"must_haves": []}}
⚠️ Maximum 10 mots par critère
⚠️ Toujours inclure les durées/niveaux chiffrés quand mentionnés"""

        try:
            response, selection = self._chat_completion_for_process(
                "offer_criteria",
                model_override=model_override,
                messages=[
                    {"role": "system", "content": "Tu es un expert RH spécialisé dans l'identification de critères éliminatoires. Tu réponds UNIQUEMENT en JSON valide avec des critères concis (max 10 mots chacun)."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            print(f"[DEBUG] Réponse LLM must-have ({selection.provider}/{selection.model}, premiers 200 chars): {content[:200]}")

            result = self._safe_json_parse(content)

            # Validation du format
            if not isinstance(result, dict):
                print(f"⚠️ Format must_have invalide: {type(result)} - Contenu: {result}")
                return []

            if "must_haves" not in result:
                print(f"⚠️ Clé 'must_haves' manquante. Clés trouvées: {list(result.keys())}")
                return []

            must_haves_raw = result.get("must_haves", [])

            if not must_haves_raw:
                print("⚠️ Aucun must-have extrait de l'offre (liste vide)")
                return []

            if len(must_haves_raw) < 10:
                print(f"⚠️ Seulement {len(must_haves_raw)} critères extraits (minimum recommandé: 10)")

            print(f"✅ {len(must_haves_raw)} must-have(s) brut(s) extraits")

        except Exception as e:
            print(f"❌ Erreur lors de l'extraction des must-haves: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

        # Nettoyer et dédupliquer
        must_haves_clean = []
        seen = set()

        for mh in must_haves_raw:
            # Assurer que c'est une string
            if not isinstance(mh, str):
                print(f"⚠️ Critère ignoré (pas une string): {type(mh)}")
                continue

            # Nettoyer (trim, lowercase pour déduplication)
            mh_clean = mh.strip()
            mh_lower = mh_clean.lower()

            # Ignorer les critères vides
            if not mh_clean:
                print(f"⚠️ Critère vide ignoré")
                continue

            # Ignorer les critères trop longs (>100 chars = phrase entière)
            # Note: 10 mots ≈ 70 chars, on laisse une marge
            if len(mh_clean) > 100:
                print(f"⚠️ Critère trop long ignoré (>{len(mh_clean)} chars): {mh_clean[:60]}...")
                continue

            # Ignorer localisation/contrat (UNIQUEMENT si c'est le contenu PRINCIPAL du critère)
            skip_keywords = ['cdi', 'temps plein', 'paris', 'télétravail', 'remote', 'présentiel']
            # Ne filtrer que si le mot-clé représente plus de 30% du critère
            is_location_contract = False
            for kw in skip_keywords:
                if kw in mh_lower and len(kw) / len(mh_lower) > 0.3:
                    print(f"⚠️ Critère localisation/contrat ignoré: '{mh_clean}'")
                    is_location_contract = True
                    break

            if is_location_contract:
                continue

            # Dédupliquer
            if mh_lower not in seen:
                seen.add(mh_lower)
                must_haves_clean.append(mh_clean)
                print(f"✅ Must-have accepté: '{mh_clean}'")
            else:
                print(f"⚠️ Critère dupliqué ignoré: '{mh_clean}'")

        print(f"📊 Must-haves extraits: {len(must_haves_raw)} bruts → {len(must_haves_clean)} après nettoyage")

        return must_haves_clean

    def check_single_cv_must_have(
        self,
        cv: Dict,
        indispensables: List[str],
        job_description: str,
        timeout_s: int = 20,
        runtime_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, str, Dict]:
        """
        Vérifie si un CV unique satisfait tous les must-have (format amélioré)

        Args:
            cv: CV à vérifier
            indispensables: Liste des critères indispensables
            job_description: Description de l'offre (contexte)
            timeout_s: Timeout en secondes pour l'appel LLM

        Returns:
            Tuple (accepted: bool, rationale: str, raw_trace: dict)
        """
        cv_name = cv.get('cv', 'CV sans nom')

        # Liste numérotée des critères
        criteres_liste = "\n".join([f"{j+1}. {critere}" for j, critere in enumerate(indispensables)])
        cv_text = format_untrusted_candidate_data(project_candidate_cv(cv))

        prompt = f"""Tu es un expert RH spécialisé en filtrage must-have STRICT.

🎯 MISSION: Vérifier si ce CV satisfait TOUS les critères indispensables de l'offre.

📋 CRITÈRES INDISPENSABLES (TOUS obligatoires):
{criteres_liste}

📄 CV À ANALYSER:
{cv_text}

🔍 CONTEXTE OFFRE:
{job_description}

⚠️ RÈGLES DE VÉRIFICATION:

1. **EXIGENCE STRICTE**: UN SEUL critère manquant = ÉLIMINATION immédiate (sauf flexibilité expérience)

2. **RECHERCHE INTELLIGENTE**:
   - Cherche les CONCEPTS, pas les mots exacts
   - Accepte les ÉQUIVALENTS et SYNONYMES
   - Exemple: "Python" inclut pandas, Django, Flask, FastAPI, etc.
   - Exemple: "SQL" inclut MySQL, PostgreSQL, Oracle, SQL Server, etc.
   - Exemple: "Bac+5" = Master = MSc = Ingénieur = Diplôme niveau 7 (STRICT, pas de flexibilité)

2bis. **PRÉ-FILTRE ATOMIQUE** (OBLIGATOIRE - vérification avant règle 2):
   - AVANT d'appliquer la recherche intelligente, identifie si le critère est "atomique"
   - **Critères atomiques** = mots-clés stricts, non-ambigus, outils/technos précis
     Exemples: "Canva", "Figma", "Python", "AWS", "Kubernetes", "Excel", "PowerPoint"
   - **Vérification BINAIRE** (présent/absent):
     • Cherche le mot exact (insensible à la casse) dans:
       - Section "competences_techniques" ou "outils" du CV
       - Descriptions d'expériences/projets
     • PAS d'équivalents acceptés pour les atomiques (ex: "Sketch" ≠ "Canva")
   - **Si atomique ABSENT** → present=false + commentaire explicite: "Critère atomique absent: [nom] non trouvé"
   - **Si NON-atomique** → Applique règle 2 (recherche intelligente avec équivalents)

3. **CALCUL DES ANNÉES D'EXPÉRIENCE** (CRITIQUE):

   a) **Identification du domaine**:
      - Si critère avec DOMAINE (ex: "5 ans en Data", "3 ans en Backend"):
        → Identifie TOUTES les expériences du domaine + domaines PROCHES
        → Exemples domaines proches:
          • "Data" inclut: Data Science, Data Analyst, ML Engineer, BI, Analytics, Big Data
          • "Backend" inclut: API Development, Microservices, Server-side, Architecture
          • "Frontend" inclut: UI/UX Development, React, Vue, Angular, Web client-side
        → Additionne UNIQUEMENT ces expériences

      - Si critère GÉNÉRAL (ex: "5 ans d'expérience", "3 ans minimum"):
        → Additionne TOUTES les expériences professionnelles

   b) **Addition des durées** (IMPORTANT):
      - ADDITIONNE toutes les durées pertinentes, ne prends PAS que la plus longue
      - Exemple: 2 ans entreprise A + 1.5 ans entreprise B + 1 an entreprise C = 4.5 ans TOTAL
      - Convertis en années décimales (ex: "2 ans et 6 mois" = 2.5 ans)

   c) **FLEXIBILITÉ sur le seuil** (marge de tolérance 15%):
      - Si écart ≤ 15% du seuil → ACCEPTER avec mention
      - Exemples:
        • Demandé: 5 ans → Seuil mini: 4.25 ans (85% de 5) → ACCEPTER dès 4.25 ans
        • Demandé: 3 ans → Seuil mini: 2.55 ans (85% de 3) → ACCEPTER dès 2.55 ans
        • Demandé: 10 ans → Seuil mini: 8.5 ans (85% de 10) → ACCEPTER dès 8.5 ans

      - ⚠️ Si flexibilité appliquée → MENTIONNE-LE EXPLICITEMENT dans le "commentaire":
        Exemple: "4.5 ans d'expérience en Data (légèrement sous les 5 ans, flexibilité appliquée)"

4. **DIPLÔMES** (STRICT, pas de flexibilité):
   - Vérifie le NIVEAU équivalent exact
   - Accepte équivalences: Master = Bac+5 = MSc = Ingénieur
   - PAS de flexibilité: Bac+4 ≠ Bac+5

5. **LANGUES**:
   - B2 = "courant", C1 = "bilingue", natif > B2
   - Analyse sémantique: "English fluent" = B2/C1

6. **PREUVES**:
   - Pour CHAQUE critère vérifié, cite l'ÉLÉMENT du CV qui le prouve
   - Si manquant, indique QUEL critère bloque
   - Si flexibilité expérience appliquée, DÉTAILLE le calcul dans le commentaire

🎯 FORMAT DE RÉPONSE (JSON STRICT):
{{
  "decision": "ACCEPTÉ" | "ÉLIMINÉ",
  "criteres_verifies": [
    {{
      "critere": "nom du critère",
      "present": true|false,
      "commentaire": "Explication complète incluant: calcul détaillé + preuves du CV + flexibilité si appliquée"
    }}
  ],
  "rationale": "Synthèse en 1 phrase: pourquoi accepté/éliminé (mentionne flexibilité si appliquée)",
  "element_declencheur": "Le critère manquant qui bloque (ou null si accepté)"
}}

📝 EXEMPLES DE COMMENTAIRES (preuves INTÉGRÉES dans commentaire):

Exemple 1 (avec flexibilité):
{{
  "critere": "5 ans d'expérience en Data",
  "present": true,
  "commentaire": "Critère satisfait avec flexibilité (15%). Calcul: Data Analyst 2 ans (Capgemini 2019-2021) + Data Scientist 2.5 ans (BNP Paribas 2021-2023) = 4.5 ans total. Légèrement sous les 5 ans requis mais au-dessus du seuil minimal de 4.25 ans (85%)."
}}

Exemple 2 (sans flexibilité, OK):
{{
  "critere": "3 ans d'expérience",
  "present": true,
  "commentaire": "Critère satisfait. Calcul: Dev Backend 2 ans (Société A) + Dev Fullstack 1.5 ans (Société B) = 3.5 ans d'expérience professionnelle totale."
}}

Exemple 3 (trop faible, rejeté):
{{
  "critere": "5 ans d'expérience en Backend",
  "present": false,
  "commentaire": "Critère NON satisfait. Calcul: Dev Backend 1.5 ans (Startup X) + Dev Fullstack (partie backend) 1.5 ans (Agence Y) = 3 ans total. En dessous du seuil minimal requis de 4.25 ans (85% de 5 ans)."
}}

Exemple 4 (compétence technique):
{{
  "critere": "Python",
  "present": true,
  "commentaire": "Critère satisfait. Preuves: Section compétences techniques mentionne 'Python, pandas, Django, scikit-learn'. Confirmé par expériences en tant que Data Scientist utilisant Python quotidiennement."
}}

⚠️ IMPORTANT:
- Retourne UNIQUEMENT le JSON, pas de texte avant/après
- Si UN SEUL critère manque → decision="ÉLIMINÉ" + element_declencheur renseigné
- Si TOUS présents → decision="ACCEPTÉ" + element_declencheur=null
- Pour CHAQUE critère d'expérience: DÉTAILLE le calcul dans "commentaire" + mentionne flexibilité si appliquée
"""

        try:
            result, runtime_meta = self._call_structured_json_with_prefilter_fallback(
                system_content=secure_candidate_system_prompt(
                    "Tu es un expert RH. Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."
                ),
                user_content=prompt,
                timeout_s=timeout_s,
                runtime_events=runtime_events,
            )
            result_text = json.dumps(result, ensure_ascii=False)

            # Validation du format
            decision = result.get("decision", "ÉLIMINÉ")
            rationale = result.get("rationale", "Réponse LLM invalide")
            element_declencheur = result.get("element_declencheur")

            accepted = decision == "ACCEPTÉ"

            # Log compact
            if accepted:
                print(f"✅ {cv_name}: ACCEPTÉ")
            else:
                print(f"❌ {cv_name}: ÉLIMINÉ (bloqué par: {element_declencheur or 'non précisé'})")

            return accepted, rationale, {
                **result,
                "runtime_meta": runtime_meta,
            }

        except json.JSONDecodeError as e:
            print(f"⚠️ {cv_name}: Erreur parsing JSON - {str(e)}")
            return False, f"Erreur parsing: {str(e)}", {"error": "json_decode", "raw": result_text if 'result_text' in locals() else ""}

        except Exception as e:
            print(f"❌ {cv_name}: Erreur LLM - {str(e)}")
            return False, f"Erreur LLM: {str(e)}", {"error": str(e)}

    def check_single_cv_must_have_legacy(
        self,
        cv: Dict,
        indispensables: List[str],
        job_description: str
    ) -> bool:
        """
        ANCIENNE VERSION - Conservée pour compatibilité
        Retourne uniquement bool (accepté/rejeté)
        """
        accepted, rationale, raw = self.check_single_cv_must_have(cv, indispensables, job_description)
        return accepted

    def filter_cvs_by_must_have(
        self,
        cvs: List[Dict],
        indispensables: List[str],
        job_description: str,
        use_parallel: bool = False,
        progress_callback=None
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Filtre les CVs selon les must-have indispensables

        Args:
            cvs: Liste des CVs
            indispensables: Liste des must-have indispensables
            job_description: Description de l'offre
            use_parallel: Si True, utilise la version parallélisée
            progress_callback: Callback(current, total) pour progression

        Returns:
            Liste des CVs acceptés
        """
        print(f"\n🔍 FILTRAGE PAR MUST-HAVE INDISPENSABLES")
        print(f"Critères indispensables: {len(indispensables)}")
        print(f"Mode: {'PARALLÈLE' if use_parallel else 'SÉQUENTIEL'}")

        # Vérification liste vide
        if not indispensables or all(not c.strip() for c in indispensables):
            print("⚠️ ATTENTION: Aucun critère indispensable défini → TOUS les CVs sont acceptés")
            return list(cvs), {
                "provider_used": None,
                "model_used": None,
                "duration_s": None,
                "fallback_used": None,
            }

        stage_started_at = time.perf_counter()
        runtime_events: List[Dict[str, Any]] = []

        if use_parallel:
            # Version parallèle
            try:
                from must_have_parallel import filter_cvs_by_must_have_parallel_sync

                stage_cfg = self._prefilter_stage_config()
                concurrency = min(len(cvs), stage_cfg["concurrency"])
                qps = stage_cfg["qps"]
                timeout_s = stage_cfg["timeout_s"]
                retries = stage_cfg["retries"]
                backoff_s = stage_cfg["backoff_s"]
                logger.info(
                    "Must-have prefilter config: provider=%s xai_model=%s openai_fallback=%s concurrency=%s qps=%s timeout=%ss",
                    stage_cfg["provider"],
                    stage_cfg["xai_model"],
                    stage_cfg["openai_model"],
                    concurrency,
                    qps,
                    timeout_s,
                )

                def decide_with_runtime(cv_item, must_haves, description, timeout_value):
                    return self.check_single_cv_must_have(
                        cv_item,
                        must_haves,
                        description,
                        timeout_value,
                        runtime_events=runtime_events,
                    )

                accepted, rejected, traces = filter_cvs_by_must_have_parallel_sync(
                    cvs, indispensables, job_description,
                    decide_fn=decide_with_runtime,
                    concurrency=concurrency,
                    qps=qps,
                    timeout_s=timeout_s,
                    retries=retries,
                    backoff_s=backoff_s,
                    progress_callback=progress_callback
                )

                def _trace_is_llm_unavailable(trace):
                    if not isinstance(trace, dict):
                        return False
                    rationale = str(trace.get("rationale", "")).lower()
                    raw = str(trace.get("raw", "")).lower()
                    return (
                        "erreur" in rationale
                        or "timeout" in rationale
                        or "timed out" in raw
                        or "error" in raw
                    )

                unavailable_ids = {
                    cv_id
                    for cv_id, trace in traces.items()
                    if _trace_is_llm_unavailable(trace)
                }
                if unavailable_ids:
                    recovered = []
                    still_rejected = []
                    for cv in rejected:
                        cv_id = (
                            cv.get("cv")
                            or cv.get("id")
                            or cv.get("filename")
                            or cv.get("nom")
                        )
                        if cv_id in unavailable_ids:
                            recovered.append(cv)
                        else:
                            still_rejected.append(cv)
                    if recovered:
                        print(
                            "⚠️ Filtrage must-have partiellement indisponible: "
                            f"{len(recovered)} CVs passent au scoring conservateur"
                        )
                        accepted.extend(recovered)
                        rejected = still_rejected

                if not accepted and traces and all(
                    isinstance(trace, dict)
                    and (
                        "erreur" in str(trace.get("rationale", "")).lower()
                        or "timeout" in str(trace.get("rationale", "")).lower()
                        or "error" in str(trace.get("raw", "")).lower()
                    )
                    for trace in traces.values()
                ):
                    print(
                        "⚠️ Filtrage must-have indisponible: fallback conservateur, "
                        "les CVs passent au scoring automatique"
                    )
                    runtime_meta = self._summarize_prefilter_runtime(
                        runtime_events,
                        duration_s=time.perf_counter() - stage_started_at,
                    )
                    runtime_meta["fallback_used"] = True
                    return list(cvs), runtime_meta

                print(f"\n📊 {len(accepted)} CVs acceptés sur {len(cvs)}")
                return accepted, self._summarize_prefilter_runtime(
                    runtime_events,
                    duration_s=time.perf_counter() - stage_started_at,
                )

            except ImportError:
                print("⚠️ Module must_have_parallel non trouvé, basculement en mode séquentiel")
                use_parallel = False

        # Version séquentielle (fallback ou par défaut)
        cvs_acceptes = []
        total = len(cvs)

        for idx, cv in enumerate(cvs):
            if progress_callback:
                progress_callback(idx + 1, total)

            accepted, rationale, raw = self.check_single_cv_must_have(
                cv,
                indispensables,
                job_description,
                runtime_events=runtime_events,
            )
            if accepted:
                cvs_acceptes.append(cv)

        print(f"\n📊 {len(cvs_acceptes)} CVs acceptés sur {len(cvs)}")
        return cvs_acceptes, self._summarize_prefilter_runtime(
            runtime_events,
            duration_s=time.perf_counter() - stage_started_at,
        )

    def _old_filter_cvs_by_must_have_v1(
        self,
        cvs: List[Dict],
        indispensables: List[str],
        job_description: str
    ) -> List[Dict]:
        """
        ANCIENNE VERSION - Gardée pour référence
        """
        cvs_acceptes = []

        print(f"\n🔍 FILTRAGE PAR MUST-HAVE INDISPENSABLES")
        print(f"Critères indispensables: {len(indispensables)}")

        for i, cv in enumerate(cvs):
            cv_name = cv.get("cv", f"cv_{i}")

            # Liste numérotée des critères
            criteres_liste = "\n".join([f"{j+1}. {critere}" for j, critere in enumerate(indispensables)])
            cv_text = format_untrusted_candidate_data(project_candidate_cv(cv))

            prompt = f"""
            Tu es un expert RH avec une expertise approfondie en analyse de CVs et recrutement.

            CONTEXTE DE L'OFFRE :
            {job_description}

            CRITÈRES INDISPENSABLES À VÉRIFIER (UNIQUEMENT CES CRITÈRES) :
            {criteres_liste}

            IMPORTANT : Tu ne dois vérifier QUE ces {len(indispensables)} critères indispensables.

            CV À ANALYSER :
            {cv_text}

            RÈGLES D'ANALYSE :
            - Sois INTELLIGENT et CONTEXTUEL, pas littéral
            - Cherche des CONCEPTS, pas des mots exacts
            - Accepte les ÉQUIVALENTS et SYNONYMES
            - Comprends les VARIATIONS de formulation

            RÈGLES SPÉCIALES :
            - **DIPLÔMES** : Master = Bac+5, MSc = Master, Licence = Bac+3, etc.
            - **COMPÉTENCES** : "Python" inclut pandas, numpy, Django, etc. | "SQL" inclut MySQL, PostgreSQL, etc.
            - **LANGUES** : "Français" = natif, courant, maternelle | "Anglais" = English, courant, B2, C1, etc.
            - **DOMAINES** : "Data Science" = Machine Learning = IA = Analytics = Big Data
            - **EXPÉRIENCE** : Sois PRÉCIS sur les durées - additionne TOUTES les expériences pertinentes

            Vérifie CHAQUE critère indispensable un par un. Si UN SEUL critère manque = ÉLIMINATION.

            Réponds UNIQUEMENT par :
            - "ACCEPTÉ" si TOUS les critères indispensables sont présents
            - "ÉLIMINÉ" si UN SEUL critère indispensable manque

            Ajoute une ligne avec la liste des critères indispensables manquants ou une confirmation.
            """

            response, _selection = self._chat_completion_for_process(
                "matching_prefilter",
                messages=[
                    {
                        "role": "system",
                        "content": secure_candidate_system_prompt(
                            f"Tu es un expert RH avec intelligence contextuelle. Tu vérifies UNIQUEMENT les {len(indispensables)} critères indispensables donnés."
                        ),
                    },
                    {"role": "user", "content": prompt}
                ],
            )

            decision = response.choices[0].message.content.strip()
            decision_label = "ACCEPTÉ" if decision.startswith("ACCEPTÉ") else "ÉLIMINÉ"
            print(f"📄 {cv_name} : {decision_label}")

            if decision.startswith("ACCEPTÉ"):
                cvs_acceptes.append(cv)

        print(f"\n📊 {len(cvs_acceptes)} CVs acceptés sur {len(cvs)}")
        return cvs_acceptes

    def compute_similarity_with_scoring(
        self,
        job_text: str,
        cvs: List[Dict],
        nice_have_list: List[str],
        job_description: str,
        progress_callback=None,
        offre_struct: Dict = None
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Calcule la similarité + scoring nice-have + bonus expériences
        Supporte 2 modes: scoring multi-sections (si offre_struct) ou cosinus global (fallback)
        """
        import time

        t0 = time.perf_counter()
        mode = "SECTIONNÉ" if offre_struct is not None else "GLOBAL"
        logger.info(f"📊 CALCUL DE SIMILARITÉ sur {len(cvs)} CVs (mode {mode})")

        # === CALCUL DU SCORE DE BASE (2 modes possibles) ===
        sims = np.zeros(len(cvs), dtype=np.float32)
        algorithmic_breakdown_map = {}

        if offre_struct is not None:
            # ========== NOUVEAU SCORING SECTIONNÉ ==========
            logger.info("[MODE] Scoring multi-sections activé")

            # Extraire les items et poids de l'offre
            tech_items, exp_items, summary_text = extract_offer_items(offre_struct)
            weights = offre_struct.get("scoring_weights", DEFAULT_WEIGHTS.copy())

            # Déterminer quelles sections sont demandées
            has_offer_exp = any(x.strip() for x in exp_items)
            has_offer_tech = any(x.strip() for x in tech_items)

            # Renormaliser poids si sections manquantes
            enabled = {
                "Exp": has_offer_exp,
                "Tech": has_offer_tech,
                "Summary": True,
                "Soft": False
            }
            weights = renorm_weights(weights, enabled)

            logger.debug(f"[DEBUG] Items extraits: tech={len(tech_items)}, exp={len(exp_items)}, summary={len(summary_text)} chars")
            logger.debug(f"[DEBUG] Poids sections: Exp={weights['Exp']:.2f}, Tech={weights['Tech']:.2f}, Summary={weights['Summary']:.2f}, Soft={weights['Soft']:.2f}")

            t1 = time.perf_counter()
            logger.info(f"[TIMINGS] extract_offer_items={t1-t0:.3f}s")

            # Calcul des scores par sections pour chaque CV
            t2 = time.perf_counter()

            for idx, cv in enumerate(cvs):
                cv_id = cv.get("cv", f"cv_{idx}")

                # Récupérer les sections du CV
                sections = cv.get("sections", cv)
                cv_experiences = sections.get("experiences_professionnelles", [])

                # Score Tech
                tech_score = coverage_lex(
                    tech_items, "", cv_name=cv_id, cv_sections=sections, embedding_model=self.embedding_model
                ) if has_offer_tech else 1.0

                # Score Exp + couverture
                if has_offer_exp:
                    exp_score, cov_raw, cov_w, _ = score_exp(
                        exp_items, cv_experiences, self.embedding_model,
                        tau=TAU, y_cap=Y_CAP_DEFAULT, cv_name=cv_id
                    )
                    exp_eff = exp_score * (0.5 + 0.5 * cov_w)
                else:
                    exp_score = cov_raw = cov_w = exp_eff = 1.0

                # Bloc D : contexte (titre+résumé pondérés)
                summary_score_val, _ = score_context(
                    offre_struct.get("sections", {}),
                    sections,
                    self.embedding_model,
                    cv_name=cv_id
                )

                soft_score = 0.0  # Pas de scoring soft

                # Empty policy
                cv_has_exp_content = bool(cv_experiences)
                cv_has_tech_content = bool(sections.get("competences_techniques"))

                # Flags gaps/overlaps
                # Score final avec empty policy
                score_final_val, reason_codes = final_score(
                    exp_component=exp_eff,
                    tech_score=tech_score,
                    summary_score_val=summary_score_val,
                    soft_score=soft_score,
                    weights=weights,
                    has_offer_exp=has_offer_exp,
                    has_offer_tech=has_offer_tech,
                    cv_has_exp_content=cv_has_exp_content,
                    cv_has_tech_content=cv_has_tech_content
                )

                algorithmic_breakdown_map[cv_id] = {
                    "mode": "sectioned",
                    "score_base": float(score_final_val),
                    "tech_score": float(tech_score) if has_offer_tech else None,
                    "experience_score_raw": float(exp_score) if has_offer_exp else None,
                    "experience_score_effective": float(exp_eff) if has_offer_exp else None,
                    "summary_score": float(summary_score_val),
                    "soft_score": float(soft_score),
                    "weights": {
                        "exp": float(weights["Exp"]) if "Exp" in weights else None,
                        "tech": float(weights["Tech"]) if "Tech" in weights else None,
                        "summary": float(weights["Summary"]) if "Summary" in weights else None,
                        "soft": float(weights["Soft"]) if "Soft" in weights else None,
                    },
                }

                sims[idx] = score_final_val

                # Logs détaillés
                if reason_codes:
                    for code in reason_codes:
                        logger.debug(f"Scoring {code} CV={cv_id}")
                else:
                    logger.debug(
                        f"CV={cv_id} Tech={tech_score:.3f} Exp={exp_score:.3f} ExpEff={exp_eff:.3f} Final={score_final_val:.3f}"
                    )

            t3 = time.perf_counter()
            logger.info(f"[TIMINGS] scoring_multi_sections={t3-t2:.3f}s | mean_score={np.mean(sims):.3f}")

        else:
            # ========== ANCIEN SCORING GLOBAL (COSINUS) ==========
            logger.info("[MODE] Ancien scoring global (cosinus) - fallback")

            t0 = time.perf_counter()
            job_vec = self.embedding_model.encode(
                [job_text],
                batch_size=1,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False
            ).astype(np.float32)
            t1 = time.perf_counter()

            cv_texts = [self._flatten_cv_text(cv) for cv in cvs]
            cv_lengths = [len(parts) for parts in cv_texts]
            logger.debug(f"CV texts lengths: min={min(cv_lengths)}, max={max(cv_lengths)}, mean={sum(cv_lengths)/len(cv_lengths):.1f}")
            if min(cv_lengths) == 0:
                logger.warning(f"{sum(1 for l in cv_lengths if l == 0)} CVs ont des textes vides!")

            cv_matrix = self.vectorize_many_docs(cv_texts, normalize=True)
            t2 = time.perf_counter()

            logger.debug(f"job_vec.shape={job_vec.shape}, cv_matrix.shape={cv_matrix.shape}")
            sims = (cv_matrix @ job_vec.T).ravel()
            t3 = time.perf_counter()

            logger.debug(f"sims min={sims.min():.4f}, max={sims.max():.4f}, mean={sims.mean():.4f}")
            logger.info(f"Ancien scoring global: encode_offre={t1-t0:.3f}s | encode_CV_batch={t2-t1:.3f}s | cosines={t3-t2:.3f}s | TOTAL={t3-t0:.3f}s")
            for idx, cv in enumerate(cvs):
                cv_id = cv.get("cv", f"cv_{idx}")
                algorithmic_breakdown_map[cv_id] = {
                    "mode": "global",
                    "score_base": float(sims[idx]),
                    "tech_score": None,
                    "experience_score_raw": None,
                    "experience_score_effective": None,
                    "summary_score": None,
                    "soft_score": None,
                    "weights": {
                        "exp": None,
                        "tech": None,
                        "summary": None,
                        "soft": None,
                    },
                }

        # === ÉTAPE COMMUNE: Recherche nice-have manquants EN PARALLÈLE ===
        t_nice_start = time.perf_counter()
        nice_have_map = {}
        nice_have_runtime_events: List[Dict[str, Any]] = []
        nice_have_runtime_meta = {
            "provider_used": None,
            "model_used": None,
            "duration_s": None,
            "fallback_used": None,
        }

        if nice_have_list and any(s.strip() for s in nice_have_list):
            try:
                from nice_have_parallel import find_nice_have_missing_parallel_sync

                stage_cfg = self._prefilter_stage_config()
                concurrency = min(len(cvs), stage_cfg["concurrency"])
                qps = stage_cfg["qps"]
                timeout_s = stage_cfg["timeout_s"]
                retries = stage_cfg["retries"]
                backoff_s = stage_cfg["backoff_s"]
                logger.info(
                    "Nice-have prefilter config: provider=%s xai_model=%s openai_fallback=%s concurrency=%s qps=%s timeout=%ss",
                    stage_cfg["provider"],
                    stage_cfg["xai_model"],
                    stage_cfg["openai_model"],
                    concurrency,
                    qps,
                    timeout_s,
                )

                def find_with_runtime(cv_item, criteria, description):
                    return self._find_nice_have_missing(
                        cv_item,
                        criteria,
                        description,
                        runtime_events=nice_have_runtime_events,
                    )

                nice_have_map = find_nice_have_missing_parallel_sync(
                    cvs, nice_have_list, job_description,
                    find_fn=find_with_runtime,
                    concurrency=concurrency,
                    qps=qps,
                    timeout_s=timeout_s,
                    retries=retries,
                    backoff_s=backoff_s,
                    progress_callback=progress_callback
                )

            except ImportError:
                logger.warning("⚠️ Module nice_have_parallel non trouvé, basculement en mode séquentiel")
                # Fallback séquentiel
                for idx, cv in enumerate(cvs):
                    if progress_callback:
                        progress_callback(idx + 1, len(cvs))
                    cv_id = cv.get("cv", f"cv_{idx}")
                    nice_have_map[cv_id] = self._find_nice_have_missing(
                        cv,
                        nice_have_list,
                        job_description,
                        runtime_events=nice_have_runtime_events,
                    )

        t_nice_end = time.perf_counter()
        logger.info(f"[TIMINGS] nice_have_detection={t_nice_end-t_nice_start:.3f}s")
        if nice_have_list and any(s.strip() for s in nice_have_list):
            nice_have_runtime_meta = self._summarize_prefilter_runtime(
                nice_have_runtime_events,
                duration_s=t_nice_end - t_nice_start,
            )

        # === ÉTAPE FINALE: Calcul des scores finaux avec malus nice-have ===
        scores = []

        for idx, cv in enumerate(cvs):
            # Récupérer le score de base calculé (mode sectionné ou cosinus)
            score_base = float(sims[idx])

            # Récupérer les nice-have manquants (déjà calculés en parallèle)
            cv_id = cv.get("cv", f"cv_{idx}")
            nice_have_manquants = nice_have_map.get(cv_id, [])

            # Bonus MULTIPLICATEUR pour nice-have présents (réduction si absents: 0.95 par compétence manquante)
            nombre_manquants = len(nice_have_manquants)
            bonus_factor = self.scoring_config.get("nice_have_malus_factor", 0.95)
            bonus_nice_have_multiplicateur = bonus_factor ** nombre_manquants if nombre_manquants > 0 else 1.0

            # Score final = score_base × bonus_nice_have
            score_final = score_base * bonus_nice_have_multiplicateur
            score_final = max(0.0, min(1.0, score_final))

            scores.append({
                "cv": cv.get("cv", "inconnu"),
                "score_base": float(score_base),
                "score_final": float(score_final),
                "bonus_nice_have_multiplicateur": float(bonus_nice_have_multiplicateur),
                "nice_have_manquants": nice_have_manquants,
                "nombre_manquants": nombre_manquants,
                "algorithmic_breakdown": {
                    **algorithmic_breakdown_map.get(cv_id, {
                        "mode": "global",
                        "score_base": float(score_base),
                        "tech_score": None,
                        "experience_score_raw": None,
                        "experience_score_effective": None,
                        "summary_score": None,
                        "soft_score": None,
                        "weights": {"exp": None, "tech": None, "summary": None, "soft": None},
                    }),
                    "final_algorithmic_score_before_rerank_coefficient": float(score_final),
                    "nice_to_have_missing_count": int(nombre_manquants),
                    "nice_to_have_multiplier": float(bonus_nice_have_multiplicateur),
                },
                "content": cv
            })

        # Trier tous les CVs par score (pas de limite top_k, c'est fait au re-ranking)
        sorted_scores = sorted(scores, key=lambda x: x["score_final"], reverse=True)

        logger.info(f"[TIMINGS] TOTAL compute_similarity_with_scoring={time.perf_counter()-t0:.3f}s")

        return sorted_scores, nice_have_runtime_meta

    def rerank_with_llm(self, top_cvs: List[Dict], job_description: str, progress_callback=None, top_n: int = None, nice_have_list: List[str] = None) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Re-ranking LLM du top-N avec prompt aligné et fallback robuste

        Args:
            top_cvs: Top CVs à re-ranker
            job_description: Description de l'offre
            progress_callback: Fonction callback(current, total) pour suivre la progression
            top_n: Nombre de CVs à re-ranker (override config si fourni)
            nice_have_list: Liste des nice-have de l'offre (pour calcul présents/absents)

        Returns:
            Tuple (CVs re-rankés enrichis, métadonnées runtime du reranking)
        """
        # Si top_n fourni en paramètre, on l'utilise ; sinon on prend la config
        if top_n is not None:
            cvs_to_rerank = top_cvs[:top_n]
        else:
            top_rerank = self.scoring_config.get("top_rerank", 10)
            cvs_to_rerank = top_cvs[:top_rerank]

        print(f"\n🏆 RE-RANKING LLM sur {len(cvs_to_rerank)} CVs")

        if progress_callback:
            progress_callback(0, len(cvs_to_rerank))

        # Extraire les noms de CVs pour les forcer dans le prompt
        cv_names = [cv.get('cv', 'inconnu') for cv in cvs_to_rerank]

        # Créer un résumé enrichi des CVs avec tous les détails de scoring
        cv_summaries = []
        for i, cv in enumerate(cvs_to_rerank, 1):
            cv_name = cv.get('cv', 'inconnu')
            score_base = cv.get('score_base', 0.0)
            score_final = cv.get('score_final', 0.0)
            bonus_nice_have = cv.get('bonus_nice_have_multiplicateur', 1.0)
            nice_have_manquants = cv.get('nice_have_manquants', [])
            cv_content = cv.get('content', {})

            # Extraire le contenu COMPLET du CV (pas de troncation)
            if isinstance(cv_content, dict):
                sections = cv_content.get('sections', cv_content)

                identite = sections.get('identite', {}) if isinstance(sections, dict) else {}
                candidate_first_name = (identite.get('prenom') or '').strip()
                candidate_last_name = (identite.get('nom') or '').strip()
                candidate_name = f"{candidate_first_name} {candidate_last_name}".strip() or cv_name

                # Détecter les flags (gappes & overlaps) sur TOUTES les expériences
                all_experiences = sections.get('experiences_professionnelles', []) if isinstance(sections.get('experiences_professionnelles'), list) else []
                from lib.experience_analyzer import detect_gaps_and_overlaps as detect_gaps, format_flags_for_llm as format_flags
                flags = detect_gaps(all_experiences)
                flags_summary = format_flags(flags)

                # Calculer les nice-have présents (tous sauf manquants)
                all_nice_have = set(nice_have_list) if nice_have_list else set()
                nice_have_presents = list(all_nice_have - set(nice_have_manquants)) if all_nice_have else []

                cv_summaries.append({
                    "position": i,
                    "nom_fichier": cv_name,
                    "score_base": round(score_base, 3),
                    "score_final": round(score_final, 3),
                    "bonus_nice_have_multiplicateur": round(bonus_nice_have, 3),
                    "nice_have_presents": nice_have_presents,
                    "nice_have_absents": nice_have_manquants,
                    "nombre_nice_have_presents": len(nice_have_presents),
                    "nombre_nice_have_absents": len(nice_have_manquants),
                    "contenu_complet": project_candidate_cv(sections),  # ✅ Tout le CV autorisé, sans champs racine arbitraires
                    "candidate_name": candidate_name,
                    "flags": flags_summary,  # Flags formatés pour le LLM
                    "flags_raw": {  # Flags bruts pour récupération ultérieure
                        "gappes": [{"period": g.period, "duration_months": g.duration_months, "between": g.between} for g in flags.gappes],
                        "overlaps": [{"overlap_period": o.overlap_period, "overlap_days": o.overlap_days, "experiences": o.experiences, "same_company": o.same_company} for o in flags.overlaps]
                    }
                })

        cv_summaries_text = format_untrusted_candidate_data(cv_summaries)
        cv_names_text = format_untrusted_candidate_data(cv_names)

        prompt = f"""Tu es un expert RH senior avec 15 ans d'expérience en recrutement tech.

OFFRE D'EMPLOI COMPLÈTE:
{job_description}

CVS À RE-CLASSER (du meilleur au moins bon):
{cv_summaries_text}

SYSTÈME DE SCORING (pour ta compréhension):
- Score base: Similarité sémantique CV/Offre (0.0 à 1.0) calculée par embedding
- Bonus nice-have: Multiplicateur appliqué selon les nice-have présents (formule: 0.95^nb_absents)
- Score final = score_base × bonus_nice_have

⚠️ IMPORTANT: Le score final ne prend PAS en compte l'analyse qualitative des expériences.
C'est TON rôle d'expert RH de les analyser et de re-classer les CVs en conséquence.

TA MISSION:
1. Analyse COMPARATIVEMENT les expériences professionnelles de chaque candidat :
   - Durée et pertinence des expériences par rapport au poste
   - Qualité des environnements de travail (startup, grande entreprise, international, etc.)
   - Cohérence et progression du parcours
   - Missions et responsabilités en lien avec l'offre

2. Re-classe ces {len(cvs_to_rerank)} CVs du MEILLEUR au MOINS BON en tenant compte de :
   - Le score quantitatif (base + nice-have)
   - TON analyse qualitative des expériences (facteur discriminant principal)
   - L'adéquation globale du profil

3. Pour CHAQUE CV, rédige 2 commentaires distincts et détaillés
4. **NOUVEAU**: Attribue un `coefficient_qualite_experience` (1.0 à 1.4) pour ajuster le score final.

⚠️ Attention : zéro hallucination, vérifie chaque affirmation sur le CV et recoupe les evidences avant de répondre.

FORMAT JSON OBLIGATOIRE:
{{
  "ranked_cvs": [
    {{
      "cv": "COPIE_EXACTE_NOM_FICHIER.json",
      "raisonnement_coefficient": "Chaîne de pensée explicite : base CM = 1.1 (Confirmé), AP = 7 ans → +0.1, bornes OK → 1.2",
      "coefficient_qualite_experience": 1.0,
      "commentaire_scoring": "4-6 phrases directes avec références [E1], [E2]...",
      "appreciation_globale": "8-12 phrases analytiques avec références [E1], [E3]...",
      "matrix_summary": "1 phrase courte, <= 160 caractères, pour une vue matricielle",
      "recommendation_level": "strong_fit | good_fit | mixed | weak_fit",
      "relevant_experience_years": 0.0,
      "top_strengths": ["force 1", "force 2", "force 3"],
      "watchouts": ["vigilance 1", "vigilance 2"],
      "interview_focus": ["axe entretien 1", "axe entretien 2"],
      "must_have_assessment": [
        {{
          "criterion": "copie exacte du must-have",
          "status": "met | partial | missing | unclear",
          "reason": "raison factuelle courte",
          "evidence_ids": ["E1"]
        }}
      ],
      "nice_have_assessment": [
        {{
          "criterion": "copie exacte du nice-to-have",
          "status": "met | partial | missing | unclear",
          "reason": "raison factuelle courte",
          "evidence_ids": ["E2"]
        }}
      ],
      "evidences": [
        {{"id": "E1", "type": "section", "ref": "Expérience #2 – DevOps @ Foo – Missions"}},
        {{"id": "E2", "type": "quote", "ref": "5 ans d'expertise Kubernetes en production"}},
        ...
      ],
      "evidence_map": {{
        "commentaire_scoring": ["E1", "E2"],
        "appreciation_globale": ["E1", "E3"]
      }}
    }},
    ...
  ]
}}

⚠️ RÈGLES POUR LES ÉVIDENCES (CRITIQUE):
✓ Pour chaque affirmation dans tes commentaires, ajoute une référence [E1], [E2], etc.
✓ Crée une evidence pour chaque référence avec:
  - id: identifiant unique ("E1", "E2", etc.)
  - type: "section" (repère humain), "json_path" (chemin technique), ou "quote" (citation ≤12 mots)
  - ref: le contenu de la référence
✓ Réutilise les mêmes evidences pour plusieurs phrases si approprié
✓ Dans evidence_map, liste les IDs utilisés par chaque commentaire
✓ Les champs `matrix_summary`, `recommendation_level`, `relevant_experience_years`, `top_strengths`, `watchouts`, `interview_focus`, `must_have_assessment` et `nice_have_assessment` sont STRICTEMENT des champs d'affichage. Ils ne doivent pas modifier le ranking ni le calcul du score.
✓ Dans `must_have_assessment` et `nice_have_assessment`, copie exactement le libellé des critères présents dans l'offre.
✓ Si un critère n'est pas démontré clairement par le CV, renvoie `unclear` et non `met`.

EXEMPLES D'ÉVIDENCES:
- {{"id": "E1", "type": "section", "ref": "Expérience #2 – Architecte Data @ Banque – 4 ans"}}
- {{"id": "E2", "type": "quote", "ref": "TOGAF certifié, pilotage CODIR"}}
- {{"id": "E3", "type": "json_path", "ref": "experiences[1].missions[3]"}}
- {{"id": "E4", "type": "section", "ref": "Trou de 6 mois entre Exp #2 et #3"}}

INSTRUCTIONS POUR "commentaire_scoring" (4 à 6 phrases, style direct et précis):
✓ SOIS CHIRURGICAL : va droit au but. Pas de remplissage.
✓ Explique le score (score base + impact nice-have) de façon factuelle, avec des connecteurs simples (car, donc).
✓ Mentionne les nice-have MANQUANTS et justifie les PRÉSENTS avec une preuve [E#].
✓ Français impeccable, ton professionnel et orienté décision.

INSTRUCTIONS POUR "coefficient_qualite_experience" (stabilité maximale):
✓ Remplis d'abord `raisonnement_coefficient` avec ta chaîne de pensée : base CM + ajustement AP + bornes.
✓ Méthode déterministe (toujours la même) :
   • CM (base) : Junior = 1.0 ; Confirmé = 1.1 ; Senior = 1.2 ; Expert = 1.3
   • AP (années pertinentes) : AP ≥ 6 ans → +0.1 (cap 1.4) ; AP < 1 an → −0.1 (plancher 1.0) ; sinon +0.0
   • Calcul : base CM + bonus/malus AP, puis bornes [1.0 ; 1.4]
✓ Reporte ensuite le résultat final dans `coefficient_qualite_experience`.

INSTRUCTIONS POUR "appreciation_globale" (8 à 12 phrases, style ANALYTIQUE et RIGOUREUX):
✓ PRIORITÉ ABSOLUE : EXACTITUDE. Ne cite que ce qui est écrit dans le CV.
✓ ⛔ INTERDIT : n'invente jamais de détails pour “faire joli”.
✓ Style professionnel, dense, orienté “aide à la décision”, phrases compréhensibles.
✓ Analyse la pertinence réelle (missions vs offre), cohérence et vigilances (trous ≥3 mois, chevauchements >60 jours).
✓ Termine par une recommandation claire basée uniquement sur les faits. Ajoute les références [E#] de manière fluide.

✓ EXEMPLE profil senior: "Profil exceptionnel pour ce poste de Développeur Backend Senior (coefficient: 1.4). Le candidat possède 7 ans d'expérience progressive en environnement agile, dont 4 ans en tant que lead technique sur des architectures microservices complexes chez Amazon. Cette expérience de leadership technique dans un environnement identique est un différenciateur majeur par rapport aux autres candidats. Sa maîtrise du stack Python/Django et son expertise démontrée en CI/CD + Kubernetes répondent parfaitement aux besoins. Fortement recommandé pour entretien technique approfondi."

✓ EXEMPLE profil confirmé: "Profil solide pour ce poste de Développeur Backend (coefficient: 1.2). Le candidat possède 4 ans d'expérience en architecture microservices avec une bonne maîtrise du stack Python/Django. Son parcours dans des ESN lui a permis de toucher à des environnements variés. Seule vigilance : absence de Kubernetes, mais compensable par formation rapide vu sa capacité d'apprentissage démontrée. Recommandé pour un entretien technique."

✓ EXEMPLE profil junior: "Profil junior correct pour ce poste (coefficient: 1.0). Le candidat possède 2 ans d'expérience en développement backend, principalement sur des projets de taille moyenne. Les compétences techniques sont présentes mais manquent de profondeur et d'exposition à des architectures complexes. L'expérience est un peu juste pour le niveau senior attendu. À considérer si ouverture à un profil confirmé plutôt que senior."

INSTRUCTIONS POUR LES CHAMPS MATRICE (STRICTEMENT DISPLAY-ONLY):
✓ `matrix_summary`: une seule phrase utile en réunion, <= 160 caractères.
✓ `recommendation_level`: choisis uniquement parmi `strong_fit`, `good_fit`, `mixed`, `weak_fit`.
✓ `relevant_experience_years`: nombre approximatif d'années pertinentes pour le poste, arrondi au 0.5 près.
✓ `top_strengths`: maximum 3 points courts et factuels.
✓ `watchouts`: maximum 3 vigilances courtes et factuelles.
✓ `interview_focus`: maximum 3 sujets concrets à creuser en entretien.
✓ `must_have_assessment` / `nice_have_assessment`: un objet par critère, en utilisant exactement le libellé du critère, avec `status`, `reason`, `evidence_ids`.
✓ Ces champs ne servent qu'à l'affichage. Ils ne doivent ni influencer ni justifier un changement d'ordre différent de celui déjà produit par ton analyse comparative.

NOMS DE FICHIERS À UTILISER (COPIE EXACTE - CRITIQUE):
{cv_names_text}

⚠️ RÈGLES ABSOLUES:
- Utilise EXACTEMENT les noms de fichiers ci-dessus (copie-colle)
- Ne recalcule PAS les scores, utilise-les pour ta compréhension
- Réponds UNIQUEMENT en JSON valide, sans texte avant/après
- Respecte les longueurs: 4-6 phrases pour scoring, 8-12 phrases pour appréciation

STABILITÉ — ATTRIBUTION DU COEFFICIENT (INTERNE, SANS CHANGER LA SORTIE)

Règles générales
- Tu ne classes pas les CV. Tu fournis uniquement la valeur du champ existant `coefficient_qualite_experience` ∈ {{1.0, 1.1, 1.2, 1.3, 1.4}}.
- Tu n'ajoutes, ne retires, ni ne modifies aucun autre champ du format de sortie.
- Cette section décrit uniquement la méthode interne d'attribution du coefficient. Tu DOIS toujours fournir les evidences dans le format JSON comme demandé précédemment.

Procédure interne (simple, déterministe, non rendue)
1) Identifie les exigences cœur de l'offre (missions/compétences réellement attendues).
2) Évalue la CORRESPONDANCE DES MISSIONS (CM) du CV avec ces exigences :
   - STRONG  : couverture élevée et missions très proches de l'offre
   - MEDIUM  : couverture correcte et missions globalement proches
   - WEAK    : couverture partielle et missions peu proches
   - MINIMAL : couverture faible
3) Estime les ANNÉES PERTINENTES (AP) : somme approximative des périodes où les missions du CV correspondent aux exigences cœur.
   - Ignore trous/chevauchements ; arrondis à 0.5 an près ; reste factuel.

Attribution du coefficient (discret, stable)
- Détermine une base par CM :
    MINIMAL → 1.0
    WEAK    → 1.1
    MEDIUM  → 1.2
    STRONG  → 1.3
- Ajuste selon AP :
    AP ≥ 6 ans   → +0.1   (cap à 1.4)
    1 ≤ AP < 6   → +0.0
    AP < 1 an    → −0.1   (plancher 1.0)
- Garde-fous :
    • Si CM < MEDIUM, coefficient ≤ 1.2.
    • 1.4 uniquement si (CM = STRONG) et (AP ≥ 6 ans).
- En cas d'hésitation entre deux valeurs adjacentes, choisis la plus basse (principe de stabilité).

Consignes de cohérence
- Applique exactement ces seuils à chaque réponse ; ne ré-étalonne pas la barre d'une réponse à l'autre.
- Ne recalculle pas `score_base`/`bonus_nicehave`. Tu ne fournis ici que `coefficient_qualite_experience` dans le champ prévu par le format actuel.
""".strip()

        # === ROUTING PROVIDER ===
        selection = resolve_llm_selection("matching_reranking")
        xai_reasoning_effort = self.scoring_config.get("xai_reasoning_effort", "low")
        if selection.provider == "xai" and not os.getenv("XAI_API_KEY"):
            logger.warning("matching_reranking=xai mais XAI_API_KEY est absente; bascule vers OpenAI")
            selection = resolve_llm_selection(
                "matching_reranking",
                provider_override="openai",
                model_override="gpt-5-mini",
            )
        print(f"🔀 Provider reranking: {selection.provider}")
        rerank_started_at = time.perf_counter()

        try:
            if selection.provider == "xai":
                reranked, runtime_meta = self._rerank_with_xai(
                    cvs_to_rerank=cvs_to_rerank,
                    cv_summaries=cv_summaries,
                    prompt=prompt,
                    cv_names=cv_names,
                    progress_callback=progress_callback,
                    model=selection.model,
                    reasoning_effort=xai_reasoning_effort,
                )
            else:
                reranked, runtime_meta = self._rerank_with_openai(
                    cvs_to_rerank=cvs_to_rerank,
                    cv_summaries=cv_summaries,
                    prompt=prompt,
                    cv_names=cv_names,
                    progress_callback=progress_callback,
                    selection=selection,
                )
            runtime_meta.update({
                "provider_used": selection.provider,
                "duration_s": round(time.perf_counter() - rerank_started_at, 2),
                "fallback_used": False,
            })
            return reranked, runtime_meta

        except Exception as e:
            # === FALLBACK ===
            import traceback
            print(f"❌ Exception rerank: {e} → fallback avec données préservées")
            print(f"   Traceback: {traceback.format_exc()[:200]}...")

            # Trier par score_final (données de base préservées)
            normalized_result = sorted(
                cvs_to_rerank, key=lambda x: x.get("score_final", 0.0), reverse=True
            )

            # Construire le fallback en PRÉSERVANT les données de base
            fallback_results = []
            for s in normalized_result:
                cv_name = s.get("cv") or s.get("cv_id", "inconnu")

                # Récupérer les flags automatiques s'ils existent
                cv_content = s.get("content", {})
                flags_raw = None

                # Détecter les flags pour ce CV si possible
                if isinstance(cv_content, dict):
                    sections = cv_content.get('sections', cv_content)
                    all_experiences = sections.get('experiences_professionnelles', []) if isinstance(sections.get('experiences_professionnelles'), list) else []
                    if all_experiences:
                        from lib.experience_analyzer import detect_gaps_and_overlaps as detect_gaps_fallback
                        flags_detected = detect_gaps_fallback(all_experiences)
                        flags_raw = {
                            "gappes": [{"period": g.period, "duration_months": g.duration_months, "between": g.between} for g in flags_detected.gappes],
                            "overlaps": [{"overlap_period": o.overlap_period, "overlap_days": o.overlap_days, "experiences": o.experiences, "same_company": o.same_company} for o in flags_detected.overlaps]
                        }

                fallback_results.append({
                    "cv": cv_name,
                    "coefficient_qualite_experience": 1.0,  # Neutre (pas d'analyse LLM)
                    "commentaire_scoring": (
                        f"⚠️ Re-ranking LLM indisponible (erreur: {str(e)[:100]}). "
                        f"Score base: {s.get('score_base', 0.0):.3f}, "
                        f"Bonus nice-have: {s.get('bonus_nice_have_multiplicateur', 1.0):.3f}, "
                        f"Score final: {s.get('score_final', 0.0):.3f}. "
                        f"Tri automatique par score final (coefficient neutre appliqué)."
                    ),
                    "appreciation_globale": (
                        "Analyse qualitative indisponible suite à une erreur du service de reranking LLM. "
                        "Les scores quantitatifs (embeddings + nice-have) sont valides. "
                        "Coefficient qualité fixé à 1.0 (neutre) en l'absence d'analyse RH automatisée. "
                        "Recommandation : Effectuer une analyse manuelle du CV ou relancer le matching."
                    ),
                    "evidences": [],  # Pas d'evidences sans LLM
                    "evidence_map": {},  # ✅ Normaliser None → {}
                    "flags_raw": flags_raw or {},  # ✅ Normaliser None → {}
                    "matrix_summary": "Analyse qualitative indisponible, tri basé sur le scoring automatique.",
                    "recommendation_level": "mixed",
                    "relevant_experience_years": None,
                    "top_strengths": [],
                    "watchouts": ["Analyse qualitative indisponible"],
                    "interview_focus": [],
                    "must_have_assessment": [],
                    "nice_have_assessment": [],
                })

            print(f"✅ Fallback: {len(fallback_results)} CVs retournés avec données préservées")
            fallback_meta = {
                "provider_used": selection.provider,
                "model_used": selection.model,
                "reasoning_effort_used": xai_reasoning_effort if selection.provider == "xai" else None,
                "duration_s": round(time.perf_counter() - rerank_started_at, 2),
                "attempt_count": None,
                "fallback_used": True,
            }
            return fallback_results, fallback_meta

    def _rerank_with_openai(self, cvs_to_rerank, cv_summaries, prompt, cv_names, progress_callback=None, selection=None) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Re-ranking avec provider chat OpenAI-compatible.
        """
        timeout_s = int(os.getenv("BRAINRH_RERANK_OPENAI_TIMEOUT_S", "180"))
        selection = selection or resolve_llm_selection("matching_reranking")
        print(f"⏱️ Timeout reranking {selection.provider}: {timeout_s}s")
        client = create_chat_client(selection)

        payload: dict[str, Any] = {
            "model": selection.model,
            "messages": [
                {
                    "role": "system",
                    "content": secure_candidate_system_prompt(
                        "Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."
                    ),
                },
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "timeout": timeout_s,
        }
        if selection.provider in {"openai", "xai"}:
            payload["seed"] = self.seed

        response = client.chat.completions.create(**payload)

        raw_content = response.choices[0].message.content
        logger.debug(
            "Réponse reranking %s reçue (%s caractères)",
            selection.provider,
            len(raw_content),
        )

        result = self._safe_json_parse(raw_content)

        # Valider le schéma
        if not result or "ranked_cvs" not in result:
            raise ValueError("Réponse LLM invalide (pas de clé 'ranked_cvs')")

        ranked_cvs_data = result.get("ranked_cvs", [])

        # DEBUG: Log ce que le LLM retourne
        print(f"[DEBUG OpenAI] Type ranked_cvs_data: {type(ranked_cvs_data)}")
        print(f"[DEBUG OpenAI] Nombre d'items: {len(ranked_cvs_data)}")
        print(f"[DEBUG OpenAI] Types des items: {[type(item) for item in ranked_cvs_data[:5]]}")

        # FILTRER les items invalides (None, scalaires, non-dict)
        ranked_cvs_valid = [cv for cv in ranked_cvs_data if isinstance(cv, dict)]
        if len(ranked_cvs_valid) != len(ranked_cvs_data):
            invalid_count = len(ranked_cvs_data) - len(ranked_cvs_valid)
            print(f"⚠️ [{selection.provider}] {invalid_count} items invalides ignorés dans ranked_cvs")

        if not ranked_cvs_valid:
            raise ValueError(f"Aucun CV valide dans ranked_cvs (tous null/invalides). Total items: {len(ranked_cvs_data)}")

        # Enrichir avec coefficient, evidences et flags
        cv_map_by_name = {cv.get('cv'): cv for cv in cvs_to_rerank}
        cv_summaries_by_name = {s['nom_fichier']: s for s in cv_summaries}

        enriched_result = []
        for reranked_cv in ranked_cvs_valid:  # ✅ Utiliser la liste filtrée
            cv_name = reranked_cv.get("cv", "inconnu")
            summary = cv_summaries_by_name.get(cv_name, {})
            candidate_name = summary.get("candidate_name") or cv_name

            # NORMALISER les valeurs null retournées par le LLM
            evidences = reranked_cv.get("evidences") or []
            evidence_map = reranked_cv.get("evidence_map") or {}
            flags_raw = summary.get("flags_raw") or {}

            enriched_result.append({
                "cv": cv_name,
                "candidate_name": candidate_name,
                "coefficient_qualite_experience": reranked_cv.get("coefficient_qualite_experience", 1.0),
                "commentaire_scoring": reranked_cv.get("commentaire_scoring", ""),
                "appreciation_globale": reranked_cv.get("appreciation_globale", ""),
                "evidences": evidences,
                "evidence_map": evidence_map,
                "flags_raw": flags_raw,
                "matrix_summary": reranked_cv.get("matrix_summary", ""),
                "recommendation_level": reranked_cv.get("recommendation_level", ""),
                "relevant_experience_years": reranked_cv.get("relevant_experience_years"),
                "top_strengths": reranked_cv.get("top_strengths") or [],
                "watchouts": reranked_cv.get("watchouts") or [],
                "interview_focus": reranked_cv.get("interview_focus") or [],
                "must_have_assessment": reranked_cv.get("must_have_assessment") or [],
                "nice_have_assessment": reranked_cv.get("nice_have_assessment") or [],
            })

        print(f"✅ Re-ranking {selection.provider}: {len(enriched_result)} CVs retournés")
        runtime_meta = {
            "model_used": selection.model,
            "reasoning_effort_used": None,
            "attempt_count": 1,
        }
        return enriched_result, runtime_meta

    def _call_xai_with_retry(self, payload):
        """
        Appel xAI avec retry automatique
        """
        XAI_BASE = "https://api.x.ai/v1"

        attempts = {"count": 0}

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout))
        )
        def _do_call():
            attempts["count"] += 1
            api_key = os.environ.get('XAI_API_KEY')
            if not api_key:
                raise ValueError("XAI_API_KEY non trouvée dans l'environnement")

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            resp = requests.post(
                f"{XAI_BASE}/chat/completions",
                json=payload,
                headers=headers,
                timeout=90
            )
            resp.raise_for_status()
            return resp.json()

        return _do_call(), attempts["count"]

    def _rerank_with_xai(self, cvs_to_rerank, cv_summaries, prompt, cv_names, progress_callback=None, model: str = "grok-4.3", reasoning_effort: str = "low") -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Re-ranking avec xAI
        """
        print(f"🤖 Modèle xAI utilisé: {model} (reasoning_effort={reasoning_effort})")

        # Construire le payload (format OpenAI-compatible)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": secure_candidate_system_prompt(
                        "Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."
                    ),
                },
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "reasoning_effort": reasoning_effort,
            "temperature": self.temperature_reranking,
            "seed": self.seed,  # Déterminisme: même seed = mêmes résultats
            "max_tokens": 8000,  # Augmenté pour re-ranker 10 CVs avec détails
            "stream": False
        }

        # Appel xAI avec retry
        response_json, attempt_count = self._call_xai_with_retry(payload)

        # Parser la réponse (format OpenAI-compatible)
        if "choices" not in response_json or len(response_json["choices"]) == 0:
            raise ValueError("Réponse xAI invalide (aucun choix retourné)")

        raw_content = response_json["choices"][0]["message"]["content"]
        logger.debug("Réponse reranking xAI reçue (%s caractères)", len(raw_content))

        result = self._safe_json_parse(raw_content)

        # Grok peut retourner soit un objet {"ranked_cvs": [...]}, soit directement un array [...]
        if isinstance(result, list):
            print(f"[DEBUG xAI] Grok a retourné directement un array (non-standard)")
            ranked_cvs_data = result
        elif isinstance(result, dict) and "ranked_cvs" in result:
            ranked_cvs_data = result.get("ranked_cvs", [])
        else:
            raise ValueError("Réponse LLM invalide (format de reranking inattendu)")

        if not ranked_cvs_data:
            raise ValueError("ranked_cvs est vide")

        # DEBUG: Log ce que le LLM retourne
        print(f"[DEBUG xAI] Type ranked_cvs_data: {type(ranked_cvs_data)}")
        print(f"[DEBUG xAI] Nombre d'items: {len(ranked_cvs_data)}")
        print(f"[DEBUG xAI] Types des items: {[type(item) for item in ranked_cvs_data[:5]]}")

        # FILTRER les items invalides (None, scalaires, non-dict)
        ranked_cvs_valid = [cv for cv in ranked_cvs_data if isinstance(cv, dict)]
        if len(ranked_cvs_valid) != len(ranked_cvs_data):
            invalid_count = len(ranked_cvs_data) - len(ranked_cvs_valid)
            print(f"⚠️ [xAI] {invalid_count} items invalides ignorés dans ranked_cvs")

        if not ranked_cvs_valid:
            raise ValueError(f"Aucun CV valide dans ranked_cvs (tous null/invalides). Total items: {len(ranked_cvs_data)}")

        # Enrichir (même logique que OpenAI)
        cv_map_by_name = {cv.get('cv'): cv for cv in cvs_to_rerank}
        cv_summaries_by_name = {s['nom_fichier']: s for s in cv_summaries}

        enriched_result = []
        for reranked_cv in ranked_cvs_valid:  # ✅ Utiliser la liste filtrée
            cv_name = reranked_cv.get("cv", "inconnu")
            summary = cv_summaries_by_name.get(cv_name, {})
            candidate_name = summary.get("candidate_name") or cv_name

            # NORMALISER les valeurs null retournées par le LLM
            evidences = reranked_cv.get("evidences") or []
            evidence_map = reranked_cv.get("evidence_map") or {}
            flags_raw = summary.get("flags_raw") or {}

            enriched_result.append({
                "cv": cv_name,
                "candidate_name": candidate_name,
                "coefficient_qualite_experience": reranked_cv.get("coefficient_qualite_experience", 1.0),
                "commentaire_scoring": reranked_cv.get("commentaire_scoring", ""),
                "appreciation_globale": reranked_cv.get("appreciation_globale", ""),
                "evidences": evidences,
                "evidence_map": evidence_map,
                "flags_raw": flags_raw,
                "matrix_summary": reranked_cv.get("matrix_summary", ""),
                "recommendation_level": reranked_cv.get("recommendation_level", ""),
                "relevant_experience_years": reranked_cv.get("relevant_experience_years"),
                "top_strengths": reranked_cv.get("top_strengths") or [],
                "watchouts": reranked_cv.get("watchouts") or [],
                "interview_focus": reranked_cv.get("interview_focus") or [],
                "must_have_assessment": reranked_cv.get("must_have_assessment") or [],
                "nice_have_assessment": reranked_cv.get("nice_have_assessment") or [],
            })

        print(f"✅ Re-ranking xAI (Grok): {len(enriched_result)} CVs retournés")
        runtime_meta = {
            "model_used": model,
            "reasoning_effort_used": reasoning_effort,
            "attempt_count": attempt_count,
        }
        return enriched_result, runtime_meta

    def _normalize_reranked(self, result):
        """
        Normalise le résultat du re-ranking
        """
        items = []
        if isinstance(result, dict):
            items = result.get("ranked_cvs", [])
        elif isinstance(result, list):
            items = result
        else:
            return []

        out = []
        for it in items:
            # FILTRER les items invalides (str, None, non-dict)
            if not isinstance(it, dict):
                continue
            name = it.get("cv") or it.get("cv_id")
            if not name:
                continue

            commentaire_scoring = it.get("commentaire_scoring", "")
            appreciation_globale = it.get("appreciation_globale", "")

            if not commentaire_scoring and not appreciation_globale:
                old_comment = it.get("commentaire") or it.get("justification", "")
                appreciation_globale = old_comment

            out.append({
                "cv": name,
                "commentaire_scoring": commentaire_scoring,
                "appreciation_globale": appreciation_globale,
                "score": it.get("score", 0.0)
            })
        return out

    def _safe_json_parse(self, content: str):
        """Parse JSON robuste avec fallback"""
        content = content.strip()

        # Nettoyer les balises markdown
        if content.startswith("```") and content.endswith("```"):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = content.strip()

        # Extraire JSON si texte avant/après
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Fallback
        try:
            return json.loads(content)
        except:
            logger.warning("Erreur parsing JSON LLM (longueur=%s)", len(content))
            return []


if __name__ == "__main__":
    print("🧪 Test du MatchingEngine")
    engine = MatchingEngine()
    print(f"✅ Engine initialisé avec modèle: {engine.llm_model}")
    print(f"✅ Embeddings: {engine.embedding_model}")
