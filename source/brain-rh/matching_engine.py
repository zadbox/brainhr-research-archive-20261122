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
from typing import Dict, List, Any, Tuple
from pathlib import Path

from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv

# Import modules V2
from validation import validate_and_repair, check_cv_size, check_min_content
from parallel_processing import ParallelPipeline

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
        self.fallback_models = self.config.get("llm", {}).get("fallback_models", ["gpt-4.1-mini", "gpt-4o-mini"])
        self.temperature_extraction = self.config.get("llm", {}).get("temperature_extraction", 0.1)
        self.temperature_reranking = self.config.get("llm", {}).get("temperature_reranking", 0.2)
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
            "llm": {"model": "gpt-4o-mini", "temperature_extraction": 0.1},
            "scoring": {
                "top_k": 50,
                "top_rerank": 10,
                "nice_have_malus_factor": 0.9,
                "bonus_experience_exacte": 0.15,
                "bonus_experience_tres_proche": 0.10,
                "bonus_experience_proche": 0.05,
                "score_min": 0.0,
                "score_max": 1.0
            },
            "embeddings": {"model": "all-MiniLM-L6-v2", "cache_enabled": True},
            "paths": {"cache_folder": "cache"}
        }

    def clean_text(self, text: str) -> str:
        """Nettoie et normalise le texte"""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.lower().replace("\xa0", " ").strip())

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
                temperature=1.0  # Explicitement définir température (requis pour gpt-5-mini)
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

🔍 CONTEXTE OFFRE:
{job_description}

⚠️ RÈGLES DE VÉRIFICATION:

1. **EXIGENCE STRICTE**: UN SEUL critère manquant = ÉLIMINATION immédiate
2. **RECHERCHE INTELLIGENTE**:
   - Cherche les CONCEPTS, pas les mots exacts
   - Accepte les ÉQUIVALENTS et SYNONYMES
   - Exemple: "Python" inclut pandas, Django, Flask, FastAPI, etc.
   - Exemple: "SQL" inclut MySQL, PostgreSQL, Oracle, SQL Server, etc.
   - Exemple: "Bac+5" = Master = MSc = Ingénieur = Diplôme niveau 7

3. **QUANTITATIF**:
   - Expérience: ADDITIONNE toutes les expériences pertinentes
   - Niveau langue: B2 = "courant", C1 = "bilingue", natif > B2
   - Diplôme: vérifie le NIVEAU équivalent

4. **PREUVES**:
   - Pour CHAQUE critère vérifié, cite l'ÉLÉMENT du CV qui le prouve
   - Si manquant, indique QUEL critère bloque

🎯 FORMAT DE RÉPONSE (JSON STRICT):
{{
  "decision": "ACCEPTÉ" | "ÉLIMINÉ",
  "criteres_verifies": [
    {{
      "critere": "nom du critère",
      "present": true|false,
      "preuve": "élément exact du CV qui prouve (ou null si absent)",
      "commentaire": "explication courte"
    }}
  ],
  "rationale": "Synthèse en 1 phrase: pourquoi accepté/éliminé",
  "element_declencheur": "Le critère manquant qui bloque (ou null si accepté)"
}}

⚠️ IMPORTANT:
- Retourne UNIQUEMENT le JSON, pas de texte avant/après
- Si UN SEUL critère manque → decision="ÉLIMINÉ" + element_declencheur renseigné
- Si TOUS présents → decision="ACCEPTÉ" + element_declencheur=null
"""

        try:
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Tu es un expert RH. Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                # temperature NOT supported by gpt-5-mini, uses default 1.0
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

                # Configuration depuis config.yaml
                concurrency = self.config.get("llm", {}).get("llm_concurrent", 5)
                qps = self.config.get("llm", {}).get("qps", 3.0)
                timeout_s = int(self.config.get("llm", {}).get("timeout", 20000)) // 1000
                retries = int(self.config.get("llm", {}).get("max_retries", 2))
                backoff_s = float(self.config.get("llm", {}).get("retry_delay", 1000)) / 1000.0

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
                temperature=1
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

        # === ÉTAPE 4: Boucle sur les CVs pour appliquer la logique métier (inchangée) ===
        scores = []

        for idx, cv in enumerate(cvs):
            if progress_callback:
                progress_callback(idx + 1, len(cvs))

            # Récupérer la similarité pré-calculée
            sim_base = float(sims[idx])

            # Recherche nice-have manquants
            nice_have_manquants = []
            if nice_have_list:
                nice_have_manquants = self._find_nice_have_missing(cv, nice_have_list, job_description)

            # Malus MULTIPLICATEUR pour nice-have manquants (0.95 par compétence manquante)
            nombre_manquants = len(nice_have_manquants)
            malus_factor = self.scoring_config.get("nice_have_malus_factor", 0.95)
            malus_multiplicateur = malus_factor ** nombre_manquants if nombre_manquants > 0 else 1.0

            # Bonus MULTIPLICATEUR pour expériences pertinentes (1.0 à 1.15)
            bonus_multiplicateur = self._analyze_experience_bonus(cv, job_description)

            # Score final = score_base × malus × bonus
            # Exemples:
            # - score_base=0.6, 0 manquant, exp très pertinente → 0.6 × 1.0 × 1.15 = 0.69
            # - score_base=0.6, 2 manquants, exp pertinente → 0.6 × 0.9025 × 1.10 = 0.596
            score_final = sim_base * malus_multiplicateur * bonus_multiplicateur
            score_final = max(0.0, min(1.0, score_final))

            scores.append({
                "cv": cv.get("cv", "inconnu"),
                "score_base": float(sim_base),
                "score_final": float(score_final),
                "malus_multiplicateur": float(malus_multiplicateur),
                "bonus_multiplicateur": float(bonus_multiplicateur),
                "nice_have_manquants": nice_have_manquants,
                "nombre_manquants": nombre_manquants,
                "content": cv
            })

        # Trier tous les CVs par score (pas de limite top_k, c'est fait au re-ranking)
        sorted_scores = sorted(scores, key=lambda x: x["score_final"], reverse=True)

        return sorted_scores

    def rerank_with_llm(self, top_cvs: List[Dict], job_description: str, progress_callback=None) -> List[Dict]:
        """
        Re-ranking LLM du top-N avec prompt aligné et fallback robuste

        Args:
            top_cvs: Top CVs à re-ranker
            job_description: Description de l'offre
            progress_callback: Fonction callback(current, total) pour suivre la progression

        Returns:
            CVs re-rankés avec commentaires
        """
        top_rerank = self.scoring_config.get("top_rerank", 10)
        cvs_to_rerank = top_cvs[:top_rerank]

        print(f"\n🏆 RE-RANKING LLM sur {len(cvs_to_rerank)} CVs")

        if progress_callback:
            progress_callback(0, len(cvs_to_rerank))

        # Extraire les noms de CVs pour les forcer dans le prompt
        cv_names = [cv.get('cv', 'inconnu') for cv in cvs_to_rerank]

        # Créer un résumé simplifié des CVs (pas tout le JSON)
        cv_summaries = []
        for i, cv in enumerate(cvs_to_rerank, 1):
            cv_name = cv.get('cv', 'inconnu')
            score = cv.get('score_final', 0.0)
            cv_content = cv.get('content', {})

            # Extraire quelques infos clés
            if isinstance(cv_content, dict):
                sections = cv_content.get('sections', cv_content)
                competences = sections.get('competences_techniques', [])[:5] if isinstance(sections.get('competences_techniques'), list) else []
                experiences = sections.get('experiences_professionnelles', [])[:2] if isinstance(sections.get('experiences_professionnelles'), list) else []

                cv_summaries.append({
                    "position": i,
                    "nom_fichier": cv_name,
                    "score_base": round(score, 3),
                    "competences_cles": competences,
                    "experiences": experiences
                })

        prompt = f"""Tu es un expert RH. Re-classe ces {len(cvs_to_rerank)} CVs pour l'offre d'emploi.

OFFRE:
{job_description[:800]}

CVs À CLASSER:
{json.dumps(cv_summaries, ensure_ascii=False, indent=2)}

INSTRUCTIONS CRITIQUES:
1. Utilise EXACTEMENT les noms de fichiers fournis (copie-colle)
2. Classe du meilleur au moins bon (ordre = classement)
3. Justifie en UNE phrase courte (<100 chars)
4. Réponds UNIQUEMENT en JSON, rien d'autre

⚠️ IMPORTANT: NE PAS recalculer les scores, juste RÉORDONNER les CVs.

FORMAT OBLIGATOIRE:
{{
  "ranked_cvs": [
    {{"cv": "COPIE_EXACTE_NOM_FICHIER_1", "commentaire": "Justification courte"}},
    {{"cv": "COPIE_EXACTE_NOM_FICHIER_2", "commentaire": "Justification courte"}},
    ...
  ]
}}

NOMS DE FICHIERS À UTILISER (COPIE EXACTE):
{json.dumps(cv_names, ensure_ascii=False)}

⚠️ CRITIQUE: Copie-colle EXACTEMENT les noms de fichiers ci-dessus dans ta réponse.
""".strip()

        try:
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Tu réponds UNIQUEMENT en JSON valide conforme au schéma demandé."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                # temperature NOT supported by gpt-5-mini, uses default 1.0
            )

            result = self._safe_json_parse(response.choices[0].message.content)

            if progress_callback:
                progress_callback(len(cvs_to_rerank) // 2, len(cvs_to_rerank))

            # Debug: afficher le type et un aperçu du résultat
            print(f"   Type retourné: {type(result)}")
            result_str = json.dumps(result, ensure_ascii=False)
            print(f"   Aperçu (200 chars): {result_str[:200]}...")

            # On attend {"ranked_cvs":[...]}
            if isinstance(result, dict) and "ranked_cvs" in result:
                items = result["ranked_cvs"]
            else:
                print(f"⚠️ Rerank: format inattendu {type(result)} → fallback")
                items = []

            # Validation et normalisation stricte
            normalized_result = []
            valid_cv_names = set(cv_names)  # Set des noms valides

            for it in (items if isinstance(items, list) else []):
                if isinstance(it, str):
                    continue

                cv_name = it.get("cv") or it.get("cv_id")
                if not cv_name:
                    continue

                # VALIDATION: Le nom doit être dans la liste des CVs originaux
                if cv_name not in valid_cv_names:
                    # Essayer de trouver un match proche
                    matched = False
                    for valid_name in valid_cv_names:
                        # Match si substring (au moins 80% du nom)
                        if cv_name in valid_name or valid_name in cv_name:
                            cv_name = valid_name  # Forcer le nom valide
                            matched = True
                            break

                    if not matched:
                        print(f"⚠️ Nom invalide '{cv_name}' ignoré (pas dans la liste)")
                        continue

                normalized_result.append({
                    "cv": cv_name,  # Nom validé et corrigé
                    "commentaire": it.get("commentaire") or it.get("justification", "")
                    # PAS de "score" ici - les scores viennent de scored_cvs, pas du LLM
                })

            if progress_callback:
                progress_callback(len(cvs_to_rerank), len(cvs_to_rerank))

            # Validation finale: Tous les CVs doivent être présents
            returned_names = set(r["cv"] for r in normalized_result)
            missing_cvs = valid_cv_names - returned_names

            if missing_cvs:
                print(f"⚠️ {len(missing_cvs)} CVs manquants dans le re-ranking, ajout automatique")
                # Ajouter les CVs manquants à la fin
                for cv in cvs_to_rerank:
                    if cv.get("cv") in missing_cvs:
                        normalized_result.append({
                            "cv": cv.get("cv"),
                            "commentaire": "Ajouté automatiquement (manquant dans re-ranking)"
                            # PAS de "score" - vient de scored_cvs
                        })

            # Fallback si rien
            if not normalized_result:
                print("⚠️ Rerank vide → fallback tri score_final")
                normalized_result = sorted(
                    cvs_to_rerank, key=lambda x: x.get("score_final", 0.0), reverse=True
                )
                normalized_result = [
                    {
                        "cv": s.get("cv") or s.get("cv_id", "inconnu"),
                        "commentaire": "Tri automatique (re-ranking échoué)"
                        # PAS de "score" - vient de scored_cvs
                    }
                    for s in normalized_result
                ]

            print(f"✅ Re-ranking: {len(normalized_result)} CVs retournés (validés)")
            return normalized_result

        except Exception as e:
            print(f"❌ Exception rerank: {e} → fallback")
            normalized_result = sorted(
                cvs_to_rerank, key=lambda x: x.get("score_final", 0.0), reverse=True
            )
            return [
                {
                    "cv": s.get("cv") or s.get("cv_id", "inconnu"),
                    "commentaire": "Tri automatique (re-ranking échoué)"
                    # PAS de "score" - vient de scored_cvs
                }
                for s in normalized_result
            ]

    def _normalize_reranked(self, result):
        """
        Normalise le résultat du re-ranking pour garantir un format uniforme.
        Accepte dict {"ranked_cvs": [...]} ou liste directe.
        Retourne toujours une liste avec clés "cv" et "commentaire".
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
            if isinstance(it, str):
                continue
            name = it.get("cv") or it.get("cv_id")
            if not name:
                continue
            out.append({
                "cv": name,
                "commentaire": it.get("commentaire") or it.get("justification", ""),
                "score": it.get("score", 0.0)
            })
        return out

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
            "nice_have_manquants": ["nice-have 3", "nice-have 4"]
        }}

        RÈGLES :
        - Si un nice-have est mentionné explicitement ou sémantiquement → l'ajouter à "presents"
        - Si un nice-have n'est pas trouvé → l'ajouter à "manquants"
        - Être généreux dans l'interprétation sémantique pour les nice-have
        """

        response = self.openai_client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "Tu es un assistant RH expert en analyse sémantique. Tu réponds UNIQUEMENT en JSON valide."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=1
        )

        result = self._safe_json_parse(response.choices[0].message.content)

        if isinstance(result, dict):
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
                temperature=1.0
            )

            result = self._safe_json_parse(response.choices[0].message.content)

            if isinstance(result, dict):
                mult = result.get("multiplicateur", 1.0)
                # Sécurité: clamp entre 1.0 et 1.15
                return max(1.0, min(1.15, float(mult)))

        except Exception as e:
            print(f"⚠️ Erreur bonus expériences: {str(e)}")

        return 1.0

    def _safe_json_parse(self, content: str) -> Any:
        """Parse JSON de manière sécurisée"""
        content = content.strip()

        # Retirer les balises markdown
        if content.startswith("```"):
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
        content = content.replace("json", "").strip()

        # Chercher un JSON valide
        match = re.search(r"(\[.*\]|\{.*\})", content, re.DOTALL)
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
    # Test du matching engine
    print("🧪 Test du MatchingEngine")

    engine = MatchingEngine()
    print(f"✅ Engine initialisé avec modèle: {engine.llm_model}")
    print(f"✅ Embeddings: {engine.embedding_model}")
