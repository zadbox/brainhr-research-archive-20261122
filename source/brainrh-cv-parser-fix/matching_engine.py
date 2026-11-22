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
import requests
import logging
from typing import Dict, List, Any, Tuple
from pathlib import Path

from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configuration du logger
logger = logging.getLogger(__name__)

# Import modules V2
from validation import validate_and_repair, check_cv_size, check_min_content
from parallel_processing import ParallelPipeline
from lib.experience_analyzer import detect_gaps_and_overlaps, format_flags_for_llm
from lib.models import Evidence, EvidenceMap, Flags

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

        # Initialiser le client OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ OPENAI_API_KEY non trouvée")

        self.openai_client = OpenAI(api_key=api_key)
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
                "reranking_provider": "openai"  # Default: OpenAI (peut être "xai" pour Grok)
            },
            "embeddings": {"model": "all-MiniLM-L6-v2", "cache_enabled": True},
            "paths": {"cache_folder": "cache"}
        }

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

    def _find_nice_have_missing(self, cv: Dict, nice_have_list: List[str], job_description: str) -> List[str]:
        """Recherche sémantique des nice-have manquants"""
        if not nice_have_list:
            return []

        cv_text = json.dumps(cv, ensure_ascii=False)

        prompt = f"""
        Tu es un expert RH qui analyse sémantiquement les CVs.

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
        """

        response = self.openai_client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "Tu es un assistant RH expert en analyse sémantique. Tu réponds UNIQUEMENT en JSON valide."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            seed=self.seed  # Déterminisme: même seed = mêmes résultats
            # GPT-5 mini: pas de paramètre temperature
        )

        result = self._safe_json_parse(response.choices[0].message.content)

        # Logging enrichi avec justifications
        cv_name = cv.get("cv", "unknown")
        if isinstance(result, dict):
            presents = result.get("nice_have_presents", [])
            manquants = result.get("nice_have_manquants", [])
            justifications = result.get("justifications", {})
            
            if justifications:
                logger.debug(f"[NICE_HAVE_LLM] CV={cv_name}: presents={presents}, manquants={manquants}")
                for item, justif in justifications.items():
                    logger.debug(f"  → {item}: {justif}")
            else:
                logger.debug(f"[NICE_HAVE_LLM] CV={cv_name}: presents={presents}, manquants={manquants}")
            
            return result.get("nice_have_manquants", [])

        return nice_have_list

    def _analyze_experience_bonus(self, cv: Dict, job_description: str) -> float:
        """
        Analyse les expériences et retourne un MULTIPLICATEUR (1.0 à 1.15)

        Returns:
            float: Multiplicateur entre 1.0 (aucune exp pertinente) et 1.15 (expérience très pertinente)
        """
        cv_text = json.dumps(cv, ensure_ascii=False)

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
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Tu es un assistant RH expert. Tu réponds UNIQUEMENT en JSON valide."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                seed=self.seed  # Déterminisme: même seed = mêmes résultats
                # GPT-5 mini: pas de paramètre temperature
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

    def extract_must_have_with_llm(self, job_description: str) -> List[str]:
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
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Tu es un expert RH spécialisé dans l'identification de critères éliminatoires. Tu réponds UNIQUEMENT en JSON valide avec des critères concis (max 10 mots chacun)."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                seed=self.seed  # Déterminisme: même seed = mêmes résultats
                # GPT-5 mini: pas de paramètre temperature
            )

            content = response.choices[0].message.content
            print(f"[DEBUG] Réponse LLM must-have (premiers 200 chars): {content[:200]}")

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

    def extract_criteria_with_classification(self, job_description: str) -> Dict[str, List[str]]:
        """
        Extrait ET classifie automatiquement les critères en Must-have / Nice-to-have

        Args:
            job_description: Description de l'offre

        Returns:
            Dict avec {"must_haves": [...], "nice_to_haves": [...]}
        """
        prompt = f"""Tu es un expert RH spécialisé dans l'analyse d'offres d'emploi. Ta mission: identifier et CLASSIFIER automatiquement les critères selon leur importance.

═══════════════════════════════════════════════════════════════
CLASSIFICATION AUTOMATIQUE MUST-HAVE / NICE-TO-HAVE
═══════════════════════════════════════════════════════════════

Pour CHAQUE critère extrait, détermine s'il est:

✅ **MUST-HAVE** (éliminatoire) SI L'UN DE CES CAS S'APPLIQUE :

   1. VOCABULAIRE IMPÉRATIF
      - "requis", "obligatoire", "indispensable", "minimum", "impératif", "nécessaire", "exigé"
      - "au moins", "minimum X", "X ans minimum"
   
   2. EXPÉRIENCE AVEC SEUIL MINIMUM
      - "2 ans minimum", "minimum 5 ans", "au moins 3 ans"
      - "2-5 ans" → MUST-HAVE = "Minimum 2 ans d'expérience" (le seuil bas)
      - "> 5 ans" → MUST-HAVE = "Minimum 5 ans d'expérience"
   
   3. FORMATION AVEC NIVEAU REQUIS
      - "Bac+5 requis", "Bac+2 minimum", "Diplôme ingénieur"
      - Si niveau précis → MUST-HAVE (ex: "Bac+4/5" = "Bac+4 minimum")
   
   4. COMPÉTENCE FONDAMENTALE POUR LE POSTE
      - Compétence sans laquelle le poste est IMPOSSIBLE
      - Ex: Technicien auto → "Diagnostic automobile" = MUST-HAVE
      - Ex: Data Scientist → "Python" = MUST-HAVE (si métier data)
   
   5. LANGUE AVEC NIVEAU REQUIS
      - "Anglais courant", "Français courant", "Anglais professionnel"
      - Si niveau précisé (courant, professionnel, C1) → MUST-HAVE
      - Si juste "Anglais" sans niveau → NICE-TO-HAVE
   
   6. OUTIL/LOGICIEL CENTRAL AU POSTE
      - Outil métier principal (ex: "SAP" pour consultant SAP)
      - Ne PAS classer en MUST-HAVE si juste mentionné une fois

🎁 **NICE-TO-HAVE** (bonus) SI L'UN DE CES CAS S'APPLIQUE :

   1. VOCABULAIRE OPTIONNEL
      - "souhaité", "apprécié", "serait un plus", "idéalement", "de préférence", "atout", "bonus"
   
   2. FORMULATION VAGUE (sans seuil)
      - "expérience confirmée", "bonne connaissance" (SANS durée précise)
   
   3. COMPÉTENCE SECONDAIRE
      - Contexte/secteur: "expérience startup", "secteur bancaire"
      - Certification non requise: "Certification X appréciée"
   
   4. LANGUE SANS NIVEAU
      - "Anglais" (sans niveau) → NICE-TO-HAVE
      - Langue secondaire: "Espagnol un plus"

═══════════════════════════════════════════════════════════════
RÈGLES D'EXTRACTION
═══════════════════════════════════════════════════════════════

1. PRÉCISION MAXIMALE
   - Toujours inclure durées/niveaux chiffrés: "Minimum 2 ans", "Bac+4 minimum"
   - Conserver les contextes importants: "Management équipe 20+ personnes"

2. CONCISION (max 10 mots par critère)

3. IGNORER SYSTÉMATIQUEMENT
   - Localisation géographique (Paris, Île-de-France, etc.)
   - Type de contrat (CDI, CDD, freelance, temps plein/partiel)
   - Soft skills génériques (rigueur, autonomie, esprit d'équipe)

4. MINIMUM D'EXTRACTION
   - Au moins 5-8 Must-haves (expérience + formation + compétences clés + langues requises)
   - Au moins 2-4 Nice-to-haves (compétences secondaires, contexte, certifications bonus)

═══════════════════════════════════════════════════════════════
EXEMPLES DE CLASSIFICATION
═══════════════════════════════════════════════════════════════

📋 EXEMPLE 1 - Data Architect:
"Nous recherchons un Data Architect senior avec minimum 8 ans d'expérience en architecture SI.
Diplôme Bac+5 informatique requis. Maîtrise obligatoire de Python, SQL et Cloud AWS.
Une certification AWS Solutions Architect serait un plus. 
Expérience dans le secteur bancaire appréciée.
Idéalement, connaissance de Kubernetes et Docker.
Anglais courant exigé."

✅ MUST-HAVES:
- "Minimum 8 ans expérience architecture SI" (seuil minimum explicite)
- "Bac+5 informatique minimum" (niveau requis)
- "Python obligatoire" (compétence fondamentale)
- "SQL obligatoire" (compétence fondamentale)
- "Cloud AWS obligatoire" (compétence fondamentale)
- "Anglais courant" (niveau requis)

🎁 NICE-TO-HAVES:
- "Certification AWS Solutions Architect" (serait un plus)
- "Expérience secteur bancaire" (appréciée)
- "Kubernetes et Docker" (idéalement)

📋 EXEMPLE 2 - Technicien Automobile (CAS COMPLEXE):
"Technicien Assistance Technique Automobile H/F
Expérience : > 5 ans (en-tête) 
Profil recherché : Expérience confirmée (2 à 5 ans) dans le diagnostic automobile
Formation : Bac+2/3 technique en mécanique ou électronique
Compétences requises:
- Diagnostic automobile (véhicules Stellantis)
- Utilisation d'outils de diagnostic et ticketing
- Support technique niveau 1
- Français courant, anglais professionnel"

✅ MUST-HAVES (résolution contradiction) :
- "Minimum 2 ans expérience diagnostic automobile" (prendre le MINIMUM entre "> 5 ans" et "2-5 ans")
- "Bac+2 technique minimum (mécanique/électronique)" (formation technique cohérente avec poste)
- "Diagnostic automobile véhicules Stellantis" (compétence fondamentale du poste)
- "Support technique niveau 1" (mission principale)
- "Français courant" (niveau requis)
- "Anglais professionnel" (niveau requis)
- "Utilisation outils de diagnostic" (outil central au poste)

🎁 NICE-TO-HAVES:
- "Expérience secteur automobile Stellantis" (contexte sectoriel)
- "Connaissance outils ticketing" (outil secondaire)

⚠️ RÈGLE IMPORTANTE : Si contradiction entre "Expérience > 5 ans" ET "2-5 ans", TOUJOURS prendre le MINIMUM (2 ans) pour ne pas éliminer des candidats qualifiés.

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
    "critère must-have 1",
    "critère must-have 2",
    ...
  ],
  "nice_to_haves": [
    "critère nice-to-have 1",
    "critère nice-to-have 2",
    ...
  ]
}}

⚠️ Si aucun must-have → {{"must_haves": []}}
⚠️ Si aucun nice-to-have → {{"nice_to_haves": []}}
⚠️ Maximum 10 mots par critère
⚠️ Toujours inclure les durées/niveaux chiffrés"""

        try:
            # Essayer OpenAI d'abord, puis Grok en fallback
            import os
            import requests
            
            content = None
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": "Tu es un expert RH spécialisé dans la classification de critères. Tu réponds UNIQUEMENT en JSON valide avec classification automatique Must-have / Nice-to-have."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    seed=self.seed
                )
                content = response.choices[0].message.content
                print(f"[DEBUG] Réponse OpenAI classification (premiers 200 chars): {content[:200]}")
                
            except Exception as openai_error:
                error_msg = str(openai_error)
                print(f"⚠️ Erreur OpenAI lors de la classification: {error_msg}")
                
                # Si quota insuffisant et xAI disponible, basculer vers Grok
                if ("429" in error_msg or "insufficient_quota" in error_msg or "rate_limit" in error_msg.lower()) and os.getenv("XAI_API_KEY"):
                    print("🔄 Basculement vers xAI (Grok) pour la classification...")
                    
                    XAI_BASE_URL = "https://api.x.ai/v1"
                    XAI_MODEL = "grok-4-fast-reasoning"
                    
                    payload = {
                        "model": XAI_MODEL,
                        "messages": [
                            {"role": "system", "content": "Tu es un expert RH spécialisé dans la classification de critères. Tu réponds UNIQUEMENT en JSON valide avec classification automatique Must-have / Nice-to-have."},
                            {"role": "user", "content": prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1
                    }
                    
                    headers = {
                        "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}",
                        "Content-Type": "application/json"
                    }
                    
                    response = requests.post(
                        f"{XAI_BASE_URL}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=300
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"Erreur xAI API: {response.status_code} - {response.text}")
                    
                    response_json = response.json()
                    content = response_json["choices"][0]["message"]["content"]
                    print(f"[DEBUG] Réponse Grok classification (premiers 200 chars): {content[:200]}")
                else:
                    # Pas de fallback disponible, propager l'erreur
                    raise
            
            if not content:
                raise ValueError("Aucune réponse obtenue des LLM")

            result = self._safe_json_parse(content)

            # Validation du format
            if not isinstance(result, dict):
                print(f"⚠️ Format invalide: {type(result)}")
                return {"must_haves": [], "nice_to_haves": []}

            must_haves_raw = result.get("must_haves", [])
            nice_to_haves_raw = result.get("nice_to_haves", [])

            # Nettoyer et dédupliquer
            must_haves_clean = self._clean_criteria_list(must_haves_raw, "Must-have")
            nice_to_haves_clean = self._clean_criteria_list(nice_to_haves_raw, "Nice-to-have")

            print(f"✅ Classification automatique:")
            print(f"   - Must-haves: {len(must_haves_clean)}")
            print(f"   - Nice-to-haves: {len(nice_to_haves_clean)}")

            return {
                "must_haves": must_haves_clean,
                "nice_to_haves": nice_to_haves_clean
            }

        except Exception as e:
            print(f"❌ Erreur lors de la classification: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"must_haves": [], "nice_to_haves": []}

    def _clean_criteria_list(self, criteria_list: List, criteria_type: str) -> List[str]:
        """
        Nettoie et déduplique une liste de critères

        Args:
            criteria_list: Liste brute de critères
            criteria_type: "Must-have" ou "Nice-to-have" (pour logs)

        Returns:
            Liste nettoyée et dédupliquée
        """
        clean_list = []
        seen = set()

        for item in criteria_list:
            # Assurer que c'est une string
            if not isinstance(item, str):
                continue

            # Nettoyer
            item_clean = item.strip()
            item_lower = item_clean.lower()

            # Ignorer si vide
            if not item_clean:
                continue

            # Ignorer si trop long
            if len(item_clean) > 100:
                print(f"⚠️ [{criteria_type}] Critère trop long ignoré: {item_clean[:60]}...")
                continue

            # Dédupliquer
            if item_lower not in seen:
                seen.add(item_lower)
                clean_list.append(item_clean)
                print(f"✅ [{criteria_type}] Ajouté: '{item_clean}'")

        return clean_list

    def check_single_cv_must_have(
        self,
        cv: Dict,
        indispensables: List[str],
        job_description: str,
        timeout_s: int = 20
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

        prompt = f"""Tu es un expert RH spécialisé en filtrage must-have STRICT.

🎯 MISSION: Vérifier si ce CV satisfait TOUS les critères indispensables de l'offre.

📋 CRITÈRES INDISPENSABLES (TOUS obligatoires):
{criteres_liste}

📄 CV À ANALYSER:
{json.dumps(cv, ensure_ascii=False, indent=2)}

🔍 CONTEXTE OFFRE (pour référence uniquement):
{job_description}

⚠️ RÈGLES CRITIQUES (À LIRE ATTENTIVEMENT):

0. **RESPECT ABSOLU DU CRITÈRE TEL QUE FOURNI**:
   - Tu dois vérifier le critère **EXACTEMENT comme indiqué** dans la liste ci-dessus
   - ❌ NE PAS réinterprêter, reformuler ou ajouter des détails au critère
   - ❌ NE PAS utiliser le contexte de l'offre pour modifier le critère
   - Exemples:
     • Si critère = "Français" → Vérifie UNIQUEMENT la présence de "Français" (niveau NON requis)
     • Si critère = "Français courant" → Vérifie "Français" + niveau courant
     • Si critère = "Python" → Vérifie "Python" (frameworks inclus: Django, Flask, pandas OK)
     • Si critère = "5 ans d'expérience" → Vérifie 5 ans GÉNÉRAUX (pas de domaine)
   - Dans "critere" du JSON de réponse: COPIE le critère TAL QUEL depuis la liste, sans modification

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
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Tu es un expert RH. Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                seed=self.seed,  # Déterminisme: même seed = mêmes résultats
                # GPT-5 mini: pas de paramètre temperature
                timeout=timeout_s
            )

            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)

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

            return accepted, rationale, result

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
    ) -> List[Dict]:
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
            return list(cvs)  # Retourner tous les CVs sans filtrage

        if use_parallel:
            # Version parallèle
            try:
                from must_have_parallel import filter_cvs_by_must_have_parallel_sync

                # Configuration: forcer 500 max concurrent sans timeout
                concurrency = min(len(cvs), 500)
                qps = 100.0  # QPS élevé pour parallélisation rapide
                timeout_s = 300  # 5 minutes (appels LLM lents)
                retries = 1  # 1 seul retry
                backoff_s = 2.0

                accepted, rejected, traces = filter_cvs_by_must_have_parallel_sync(
                    cvs, indispensables, job_description,
                    decide_fn=self.check_single_cv_must_have,
                    concurrency=concurrency,
                    qps=qps,
                    timeout_s=timeout_s,
                    retries=retries,
                    backoff_s=backoff_s,
                    progress_callback=progress_callback
                )

                print(f"\n📊 {len(accepted)} CVs acceptés sur {len(cvs)}")
                return accepted

            except ImportError:
                print("⚠️ Module must_have_parallel non trouvé, basculement en mode séquentiel")
                use_parallel = False

        # Version séquentielle (fallback ou par défaut)
        cvs_acceptes = []
        total = len(cvs)

        for idx, cv in enumerate(cvs):
            if progress_callback:
                progress_callback(idx + 1, total)

            accepted, rationale, raw = self.check_single_cv_must_have(cv, indispensables, job_description)
            if accepted:
                cvs_acceptes.append(cv)

        print(f"\n📊 {len(cvs_acceptes)} CVs acceptés sur {len(cvs)}")
        return cvs_acceptes

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

            prompt = f"""
            Tu es un expert RH avec une expertise approfondie en analyse de CVs et recrutement.

            CONTEXTE DE L'OFFRE :
            {job_description}

            CRITÈRES INDISPENSABLES À VÉRIFIER (UNIQUEMENT CES CRITÈRES) :
            {criteres_liste}

            IMPORTANT : Tu ne dois vérifier QUE ces {len(indispensables)} critères indispensables.

            CV À ANALYSER :
            {json.dumps(cv, ensure_ascii=False, indent=2)}

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

            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": f"Tu es un expert RH avec intelligence contextuelle. Tu vérifies UNIQUEMENT les {len(indispensables)} critères indispensables donnés."},
                    {"role": "user", "content": prompt}
                ],
                seed=self.seed  # Déterminisme: même seed = mêmes résultats
            )

            decision = response.choices[0].message.content.strip()
            print(f"📄 {cv_name} : {decision[:100]}...")

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
        progress_callback=None
    ) -> List[Dict]:
        """
        Calcule la similarité + scoring nice-have + bonus expériences (VERSION OPTIMISÉE BATCH)

        Args:
            job_text: Texte de l'offre aplati
            cvs: Liste des CVs filtrés
            nice_have_list: Liste des nice-have
            job_description: Description complète de l'offre
            progress_callback: Fonction callback(current, total) pour suivre la progression

        Returns:
            Liste des Top-K CVs avec scores
        """
        import time

        print(f"\n📊 CALCUL DE SIMILARITÉ sur {len(cvs)} CVs (mode BATCH optimisé)")

        # === ÉTAPE 1: Encoder l'offre (1 seule fois, normalisé) ===
        t0 = time.perf_counter()
        job_vec = self.embedding_model.encode(
            [job_text],
            batch_size=1,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        ).astype(np.float32)  # Shape: (1, d)
        t1 = time.perf_counter()

        # === ÉTAPE 2: Encoder tous les CVs en batch ===
        cv_texts = [self._flatten_cv_text(cv) for cv in cvs]

        # Debug: vérifier que les CVs ne sont pas vides
        cv_lengths = [len(parts) for parts in cv_texts]
        print(f"[DEBUG] CV texts lengths: min={min(cv_lengths)}, max={max(cv_lengths)}, mean={sum(cv_lengths)/len(cv_lengths):.1f}")
        if min(cv_lengths) == 0:
            print(f"[WARNING] {sum(1 for l in cv_lengths if l == 0)} CVs ont des textes vides!")

        cv_matrix = self.vectorize_many_docs(cv_texts, normalize=True)  # Shape: (N, d)
        t2 = time.perf_counter()

        # === ÉTAPE 3: Calcul vectorisé des cosines (dot product car normalisé) ===
        # Debug shapes
        print(f"[DEBUG] job_vec.shape={job_vec.shape}, cv_matrix.shape={cv_matrix.shape}")

        sims = (cv_matrix @ job_vec.T).ravel()  # Shape: (N,)
        t3 = time.perf_counter()

        # Debug scores
        print(f"[DEBUG] sims min={sims.min():.4f}, max={sims.max():.4f}, mean={sims.mean():.4f}")
        print(f"[DEBUG] Premiers scores: {sims[:5]}")

        print(f"[TIMINGS] encode_offre={t1-t0:.3f}s | encode_CV_batch={t2-t1:.3f}s | cosines_matmul={t3-t2:.3f}s | TOTAL={t3-t0:.3f}s")

        # === ÉTAPE 4: Recherche nice-have manquants EN PARALLÈLE ===
        t4 = time.perf_counter()
        nice_have_map = {}

        if nice_have_list and any(s.strip() for s in nice_have_list):
            # Version parallélisée
            try:
                from nice_have_parallel import find_nice_have_missing_parallel_sync

                # Configuration: forcer 500 max concurrent sans timeout
                concurrency = min(len(cvs), 500)
                qps = 10.0
                timeout_s = 300  # 5 minutes (appels LLM lents)
                retries = 1
                backoff_s = 2.0

                nice_have_map = find_nice_have_missing_parallel_sync(
                    cvs, nice_have_list, job_description,
                    find_fn=self._find_nice_have_missing,
                    concurrency=concurrency,
                    qps=qps,
                    timeout_s=timeout_s,
                    retries=retries,
                    backoff_s=backoff_s,
                    progress_callback=progress_callback
                )

            except ImportError:
                print("⚠️ Module nice_have_parallel non trouvé, basculement en mode séquentiel")
                # Fallback séquentiel
                for idx, cv in enumerate(cvs):
                    if progress_callback:
                        progress_callback(idx + 1, len(cvs))
                    cv_id = cv.get("cv", f"cv_{idx}")
                    nice_have_map[cv_id] = self._find_nice_have_missing(cv, nice_have_list, job_description)

        t5 = time.perf_counter()
        print(f"[TIMINGS] nice_have_detection={'PARALLÈLE' if 'nice_have_parallel' in str(type(nice_have_map)) else 'séquentiel'}={t5-t4:.3f}s")

        # Logs de debug pour tracer nice_have_list et nice_have_map
        logger.debug(f"[NICE_HAVE_DEBUG] nice_have_list={nice_have_list}")
        logger.debug(f"[NICE_HAVE_DEBUG] nice_have_map size={len(nice_have_map)} entries")

        # === ÉTAPE 5: Calcul des scores finaux ===
        scores = []

        for idx, cv in enumerate(cvs):
            # Récupérer la similarité pré-calculée
            sim_base = float(sims[idx])

            # Récupérer les nice-have manquants (déjà calculés en parallèle)
            cv_id = cv.get("cv", f"cv_{idx}")
            nice_have_manquants = nice_have_map.get(cv_id, [])

            # Bonus MULTIPLICATEUR pour nice-have présents (réduction si absents: 0.95 par compétence manquante)
            nombre_manquants = len(nice_have_manquants)
            bonus_factor = self.scoring_config.get("nice_have_malus_factor", 0.95)
            bonus_nice_have_multiplicateur = bonus_factor ** nombre_manquants if nombre_manquants > 0 else 1.0

            # Logs de debug pour tracer le calcul du malus
            if nombre_manquants > 0:
                logger.debug(f"[NICE_HAVE_MALUS] CV={cv_id}: base={sim_base:.4f} × malus={bonus_nice_have_multiplicateur:.4f} (0.95^{nombre_manquants}) = final={sim_base * bonus_nice_have_multiplicateur:.4f}")
                logger.debug(f"  → Nice-have manquants ({nombre_manquants}): {nice_have_manquants}")

            # Score final = score_base × bonus_nice_have
            score_final = sim_base * bonus_nice_have_multiplicateur
            score_final = max(0.0, min(1.0, score_final))

            scores.append({
                "cv": cv.get("cv", "inconnu"),
                "score_base": float(sim_base),
                "score_final": float(score_final),
                "bonus_nice_have_multiplicateur": float(bonus_nice_have_multiplicateur),
                "nice_have_manquants": nice_have_manquants,
                "nombre_manquants": nombre_manquants,
                "content": cv
            })

        # Trier tous les CVs par score (pas de limite top_k, c'est fait au re-ranking)
        sorted_scores = sorted(scores, key=lambda x: x["score_final"], reverse=True)

        return sorted_scores

    def rerank_with_llm(self, top_cvs: List[Dict], job_description: str, progress_callback=None, top_n: int = None) -> List[Dict]:
        """
        Re-ranking LLM du top-N avec prompt aligné et fallback robuste

        Args:
            top_cvs: Top CVs à re-ranker
            job_description: Description de l'offre
            progress_callback: Fonction callback(current, total) pour suivre la progression
            top_n: Nombre de CVs à re-ranker (override config si fourni)

        Returns:
            CVs re-rankés avec commentaires
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
                all_nice_have = set(nice_have_list) if 'nice_have_list' in locals() else set()
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
                    "contenu_complet": sections,  # ✅ Tout le CV, pas juste 2 expériences + 5 compétences
                    "candidate_name": candidate_name,
                    "flags": flags_summary,  # Flags formatés pour le LLM
                    "flags_raw": {  # Flags bruts pour récupération ultérieure
                        "gappes": [{"period": g.period, "duration_months": g.duration_months, "between": g.between} for g in flags.gappes],
                        "overlaps": [{"overlap_period": o.overlap_period, "overlap_days": o.overlap_days, "experiences": o.experiences, "same_company": o.same_company} for o in flags.overlaps]
                    }
                })

        prompt = f"""Tu es un expert RH senior avec 15 ans d'expérience en recrutement tech.

OFFRE D'EMPLOI COMPLÈTE:
{job_description}

CVS À RE-CLASSER (du meilleur au moins bon):
{json.dumps(cv_summaries, ensure_ascii=False, indent=2)}

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

FORMAT JSON OBLIGATOIRE:
{{
  "ranked_cvs": [
    {{
      "cv": "COPIE_EXACTE_NOM_FICHIER.json",
      "coefficient_qualite_experience": 1.0,
      "commentaire_scoring": "4-5 lignes avec justifications nice-have et références [E1], [E2]...",
      "appreciation_globale": "6-7 lignes avec références [E1], [E3]...",
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

EXEMPLES D'ÉVIDENCES:
- {{"id": "E1", "type": "section", "ref": "Expérience #2 – Architecte Data @ Banque – 4 ans"}}
- {{"id": "E2", "type": "quote", "ref": "TOGAF certifié, pilotage CODIR"}}
- {{"id": "E3", "type": "json_path", "ref": "experiences[1].missions[3]"}}
- {{"id": "E4", "type": "section", "ref": "Trou de 6 mois entre Exp #2 et #3"}}

INSTRUCTIONS POUR "commentaire_scoring" (4-5 lignes, style technique et factuel):
✓ Explique les éléments du score: score de base et bonus nice-have
✓ **CRITIQUE**: Mentionne EXPLICITEMENT les nice-have MANQUANTS s'il y en a (liste exhaustive)
✓ Si nice-have manquants → explique l'impact sur le multiplicateur (0.95^nb_manquants)
✓ **NOUVEAU**: Pour les nice-have PRÉSENTS, ajoute une justification courte (certification mentionnée, technologie utilisée dans projet X, N ans d'expérience pertinente)
✓ **IMPORTANT**: Ajoute au moins 1-2 références [E#] pour justifier le score ou les compétences clés
✓ Ton professionnel, concis, orienté chiffres et justifications claires
✓ EXEMPLE avec manquants: "Score base de 0.75 reflétant une bonne adéquation technique [E1]. Multiplicateur de 0.9025 (×0.95²) appliqué en raison de 2 nice-have manquants : Kubernetes et CI/CD avancé. Score final: 0.68."
✓ EXEMPLE sans manquants: "Score base de 0.80 avec excellente couverture technique [E2]. Multiplicateur optimal de 1.00 : tous les nice-have présents. Docker mentionné dans 3 projets [E3], Python avancé utilisé 5 ans, PostgreSQL certifié 2021. Score final: 0.80."
✓ EXEMPLE avec critère durée: "Score base de 0.65. Multiplicateur de 0.95 (1 manquant : '≥10 ans architecte SI'). Candidat possède 7 ans d'expérience architecte [E4] (Architecte Data 2018-2021, Lead Architect 2021-2025), n'atteint pas le seuil de 10 ans requis. TOGAF présent (certifié 2019 [E5]). Score final: 0.62."

INSTRUCTIONS POUR "coefficient_qualite_experience" (nombre décimal entre 1.0 et 1.4):
✓ **CRITIQUE**: Évalue la qualité et pertinence des EXPÉRIENCES professionnelles
✓ **ESSENTIEL**: Attribue un coefficient selon cette grille STRICTE:
  • 1.4 : Expérience EXCEPTIONNELLE (leadership technique, projets majeurs, environnement identique)
  • 1.3 : Expérience TRÈS FORTE (senior, projets complexes, très grande pertinence)
  • 1.2 : Expérience FORTE (confirmé, bonne pertinence, environnement proche)
  • 1.1 : Expérience PERTINENTE (standard pour le poste, domaine connexe)
  • 1.0 : Expérience CORRECTE (junior ou peu pertinent pour le poste spécifique)
✓ Ce coefficient sera multiplié au score pour le calcul final

INSTRUCTIONS POUR "appreciation_globale" (6-7 lignes, style RH expert et qualitatif):
✓ **CRITIQUE**: Analyse EN PROFONDEUR la qualité et pertinence des EXPÉRIENCES professionnelles
✓ Justifie le coefficient attribué en comparant les expériences entre candidats
✓ Compare les expériences entre candidats (durée, environnement, missions, progression)
✓ Évalue l'adéquation globale du profil au poste recherché
✓ Identifie les 2-3 forces principales du candidat par rapport au poste
✓ **IMPORTANT**: Mentionne les DRAPEAUX DE VIGILANCE si présents (trous, chevauchements)
  - Trous ≥3 mois : Signale et demande clarification
  - Chevauchements >14 jours : Note et questionne si nécessaire
✓ Donne une recommandation RH claire et actionnable (Fortement recommandé / Recommandé / À considérer)
✓ Ton professionnel, humain, orienté décision de recrutement
✓ Ajoute des références d'evidences [E1], [E2]... pour justifier tes affirmations
✓ Commence toujours l'appréciation par le nom complet du candidat (champ "candidate_name") pour faciliter la lecture.

✓ EXEMPLE profil senior: "Profil exceptionnel pour ce poste de Développeur Backend Senior (coefficient: 1.4). Le candidat possède 7 ans d'expérience progressive en environnement agile, dont 4 ans en tant que lead technique sur des architectures microservices complexes chez Amazon. Cette expérience de leadership technique dans un environnement identique est un différenciateur majeur par rapport aux autres candidats. Sa maîtrise du stack Python/Django et son expertise démontrée en CI/CD + Kubernetes répondent parfaitement aux besoins. Fortement recommandé pour entretien technique approfondi."

✓ EXEMPLE profil confirmé: "Profil solide pour ce poste de Développeur Backend (coefficient: 1.2). Le candidat possède 4 ans d'expérience en architecture microservices avec une bonne maîtrise du stack Python/Django. Son parcours dans des ESN lui a permis de toucher à des environnements variés. Seule vigilance : absence de Kubernetes, mais compensable par formation rapide vu sa capacité d'apprentissage démontrée. Recommandé pour un entretien technique."

✓ EXEMPLE profil junior: "Profil junior correct pour ce poste (coefficient: 1.0). Le candidat possède 2 ans d'expérience en développement backend, principalement sur des projets de taille moyenne. Les compétences techniques sont présentes mais manquent de profondeur et d'exposition à des architectures complexes. L'expérience est un peu juste pour le niveau senior attendu. À considérer si ouverture à un profil confirmé plutôt que senior."

NOMS DE FICHIERS À UTILISER (COPIE EXACTE - CRITIQUE):
{json.dumps(cv_names, ensure_ascii=False)}

⚠️ RÈGLES ABSOLUES:
- Utilise EXACTEMENT les noms de fichiers ci-dessus (copie-colle)
- Ne recalcule PAS les scores, utilise-les pour ta compréhension
- Réponds UNIQUEMENT en JSON valide, sans texte avant/après
- Respecte les longueurs: 4-5 lignes pour scoring (avec justifications nice-have), 6-7 lignes pour appréciation

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
        provider = self.scoring_config.get("reranking_provider", "openai").lower()
        print(f"🔀 Provider reranking: {provider}")

        try:
            if provider == "xai":
                return self._rerank_with_xai(
                    cvs_to_rerank=cvs_to_rerank,
                    cv_summaries=cv_summaries,
                    prompt=prompt,
                    cv_names=cv_names,
                    progress_callback=progress_callback
                )
            else:  # default: openai
                return self._rerank_with_openai(
                    cvs_to_rerank=cvs_to_rerank,
                    cv_summaries=cv_summaries,
                    prompt=prompt,
                    cv_names=cv_names,
                    progress_callback=progress_callback
                )

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
                    "flags_raw": flags_raw or {}  # ✅ Normaliser None → {}
                })

            print(f"✅ Fallback: {len(fallback_results)} CVs retournés avec données préservées")
            return fallback_results

    def _rerank_with_openai(self, cvs_to_rerank, cv_summaries, prompt, cv_names, progress_callback=None):
        """
        Re-ranking avec OpenAI (méthode extraite)
        """
        response = self.openai_client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            seed=self.seed  # Déterminisme: même seed = mêmes résultats
        )

        raw_content = response.choices[0].message.content
        print(f"[DEBUG OpenAI] Réponse brute (premiers 500 chars): {raw_content[:500]}")

        result = self._safe_json_parse(raw_content)

        # Valider le schéma
        if not result or "ranked_cvs" not in result:
            raise ValueError(f"Réponse LLM invalide (pas de clé 'ranked_cvs'): {result}")

        ranked_cvs_data = result.get("ranked_cvs", [])

        # DEBUG: Log ce que le LLM retourne
        print(f"[DEBUG OpenAI] Type ranked_cvs_data: {type(ranked_cvs_data)}")
        print(f"[DEBUG OpenAI] Nombre d'items: {len(ranked_cvs_data)}")
        print(f"[DEBUG OpenAI] Types des items: {[type(item) for item in ranked_cvs_data[:5]]}")

        # FILTRER les items invalides (None, scalaires, non-dict)
        ranked_cvs_valid = [cv for cv in ranked_cvs_data if isinstance(cv, dict)]
        if len(ranked_cvs_valid) != len(ranked_cvs_data):
            invalid_count = len(ranked_cvs_data) - len(ranked_cvs_valid)
            print(f"⚠️ [OpenAI] {invalid_count} items invalides ignorés dans ranked_cvs")
            print(f"   Items invalides: {[cv for cv in ranked_cvs_data if not isinstance(cv, dict)][:3]}")

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
                "flags_raw": flags_raw
            })

        print(f"✅ Re-ranking OpenAI: {len(enriched_result)} CVs retournés")
        return enriched_result

    def _call_xai_with_retry(self, payload):
        """
        Appel xAI avec retry automatique
        """
        XAI_BASE = "https://api.x.ai/v1"

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout))
        )
        def _do_call():
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

        return _do_call()

    def _rerank_with_xai(self, cvs_to_rerank, cv_summaries, prompt, cv_names, progress_callback=None):
        """
        Re-ranking avec xAI (Grok-4-fast-reasoning)
        """
        XAI_MODEL = "grok-4-fast-reasoning"

        # Log du modèle utilisé
        print(f"🤖 Modèle xAI utilisé: {XAI_MODEL}")

        # Construire le payload (format OpenAI-compatible)
        payload = {
            "model": XAI_MODEL,
            "messages": [
                {"role": "system", "content": "Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.15,
            "seed": self.seed,  # Déterminisme: même seed = mêmes résultats
            "max_tokens": 8000,  # Augmenté pour re-ranker 10 CVs avec détails
            "stream": False
        }

        # Appel xAI avec retry
        response_json = self._call_xai_with_retry(payload)

        # Parser la réponse (format OpenAI-compatible)
        if "choices" not in response_json or len(response_json["choices"]) == 0:
            raise ValueError(f"Réponse xAI invalide: {response_json}")

        raw_content = response_json["choices"][0]["message"]["content"]
        print(f"[DEBUG xAI] Réponse brute (premiers 500 chars): {raw_content[:500]}")

        result = self._safe_json_parse(raw_content)

        # Grok peut retourner soit un objet {"ranked_cvs": [...]}, soit directement un array [...]
        if isinstance(result, list):
            print(f"[DEBUG xAI] Grok a retourné directement un array (non-standard)")
            ranked_cvs_data = result
        elif isinstance(result, dict) and "ranked_cvs" in result:
            ranked_cvs_data = result.get("ranked_cvs", [])
        else:
            raise ValueError(f"Réponse LLM invalide (ni array ni objet avec 'ranked_cvs'): {result}")

        if not ranked_cvs_data:
            raise ValueError(f"ranked_cvs est vide. Réponse complète: {result}")

        # DEBUG: Log ce que le LLM retourne
        print(f"[DEBUG xAI] Type ranked_cvs_data: {type(ranked_cvs_data)}")
        print(f"[DEBUG xAI] Nombre d'items: {len(ranked_cvs_data)}")
        print(f"[DEBUG xAI] Types des items: {[type(item) for item in ranked_cvs_data[:5]]}")

        # FILTRER les items invalides (None, scalaires, non-dict)
        ranked_cvs_valid = [cv for cv in ranked_cvs_data if isinstance(cv, dict)]
        if len(ranked_cvs_valid) != len(ranked_cvs_data):
            invalid_count = len(ranked_cvs_data) - len(ranked_cvs_valid)
            print(f"⚠️ [xAI] {invalid_count} items invalides ignorés dans ranked_cvs")
            print(f"   Items invalides: {[cv for cv in ranked_cvs_data if not isinstance(cv, dict)][:3]}")

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
                "flags_raw": flags_raw
            })

        print(f"✅ Re-ranking xAI (Grok): {len(enriched_result)} CVs retournés")
        return enriched_result

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
            print(f"⚠️ Erreur parsing JSON: {content[:200]}")
            return []


if __name__ == "__main__":
    print("🧪 Test du MatchingEngine")
    engine = MatchingEngine()
    print(f"✅ Engine initialisé avec modèle: {engine.llm_model}")
    print(f"✅ Embeddings: {engine.embedding_model}")
