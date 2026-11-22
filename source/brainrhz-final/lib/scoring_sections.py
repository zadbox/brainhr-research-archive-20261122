# -*- coding: utf-8 -*-
"""
Module de scoring par sections (Exp + Tech + Summary + Soft)
Remplace le cosinus global par un scoring pondéré multi-composantes

ATTENTION: Ce module respecte strictement la spec fonctionnelle
Ne pas modifier les formules sans validation de l'architecte
"""

import math
import re
import unicodedata
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

# ==================== CONSTANTES ====================

TAU = 0.55  # Seuil de couverture pour cosinus
EPS = 1e-9  # Epsilon pour éviter division par zéro
Y_CAP_DEFAULT = 10.0  # Cap linéaire sur années totales
AMBIGUOUS = {"r", "c", "go"}  # Tokens ambigus à ignorer

# Poids par défaut
DEFAULT_WEIGHTS = {
    "Exp": 0.40,
    "Tech": 0.40,
    "Summary": 0.20,
    "Soft": 0.00,
}

# Mapping mois FR → int
_FR_MONTHS = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "janv": 1, "févr": 2, "avr": 4, "juil": 7, "sept": 9,
    "oct": 10, "nov": 11, "déc": 12,
}


# ==================== NORMALISATION ====================

def norm(s: str) -> str:
    """
    Nettoie et normalise une chaîne (minuscules, sans accents, espaces normalisés)

    Args:
        s: Chaîne à normaliser

    Returns:
        Chaîne normalisée
    """
    if not s:
        return ""
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(s.split())


# ==================== UTILITAIRES CONTEXTE (BLOC D) ====================

def strip_parens_for_context(text: str) -> str:
    """
    Retire les parenthèses et leur contenu pour le calcul de contexte
    Ex: "Architecte Data (H/F)" → "architecte data"
    """
    if not text:
        return ""
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = text.lower().strip()
    return re.sub(r"\s+", " ", text)


def _embed_norm(texts: List[str], embedding_model) -> np.ndarray:
    """
    Encode et normalise des textes avec le modèle d'embeddings

    Args:
        texts: Liste de textes à encoder
        embedding_model: Modèle d'embeddings

    Returns:
        Matrice d'embeddings normalisés (n, d)
    """
    if not texts:
        return np.zeros((0, 768), dtype=np.float32)
    return embedding_model.encode(
        texts,
        batch_size=len(texts),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False
    ).astype(np.float32)


def _sim01(a: str, b: str, embedding_model) -> float:
    """
    Calcule la similarité cosinus entre deux textes, normalisée sur [0,1]

    Args:
        a: Premier texte
        b: Second texte
        embedding_model: Modèle d'embeddings

    Returns:
        Similarité cosinus normalisée via (cos+1)/2
    """
    if not a or not b:
        return 0.0
    Ea = _embed_norm([a], embedding_model)
    Eb = _embed_norm([b], embedding_model)
    if Ea.size == 0 or Eb.size == 0:
        return 0.0
    cos = float((Ea @ Eb.T)[0, 0])
    return max(0.0, (cos + 1.0) / 2.0)


# ==================== UTILITAIRES PARENTHESES-AWARE ====================

def _strip_accents(s: str) -> str:
    """Supprime les accents d'une chaîne"""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm_paren(s: str) -> str:
    """Normalise (lowercase, trim, espaces uniques) sans supprimer parenthèses"""
    if not s:
        return ""
    s = _strip_accents(s).lower().strip()
    return re.sub(r"\s+", " ", s)


_PAREN_SPLIT = re.compile(r"[;,/]| ou | and ", re.IGNORECASE)


def strip_parentheses(text: str) -> str:
    """
    Retire toutes les parenthèses et leur contenu
    Ex: "SAFe (Scaled Agile Framework)" → "safe"
    """
    if not text:
        return ""
    no_paren = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    return _norm_paren(no_paren)


def extract_parenthetical_contents(text: str) -> List[str]:
    """
    Extrait le contenu des parenthèses, splitte par séparateurs
    Ex: "SAFe (Scaled Agile Framework)" → ["scaled agile framework"]
    """
    if not text:
        return []
    insides = re.findall(r"\(([^)]*)\)", text)
    out = []
    for inside in insides:
        parts = [p.strip() for p in _PAREN_SPLIT.split(inside) if p.strip()]
        out.extend(parts or [inside.strip()])
    return [_norm_paren(x) for x in out if _norm_paren(x)]


def explode_paren_variants(item: str) -> set:
    """
    Génère toutes les variantes d'un item
    Ex: "SAFe (Scaled Agile Framework)" → {"safe (scaled agile framework)", "safe", "scaled agile framework"}
    Filtre les numéros de version (v1.2, etc.)
    """
    variants = set()
    if not item:
        return variants

    orig = _norm_paren(item)
    if orig:
        variants.add(orig)

    base = strip_parentheses(item)
    if base:
        variants.add(base)

    variants.update(extract_parenthetical_contents(item))

    # Filtrer les numéros de version
    clean = set()
    for v in variants:
        if re.fullmatch(r"v?\d+(\.\d+)*", v):
            continue
        clean.add(v)

    return clean


def canonical_for_embedding(label: str) -> str:
    """
    Retourne la forme canonique (sans parenthèses) pour embeddings
    Ex: "SAFe (Scaled Agile Framework)" → "safe"
    """
    base = strip_parentheses(label)
    return base or _norm_paren(label)


# ==================== PARSING DATES ====================

def _parse_date_any(s: str) -> Optional[datetime]:
    """
    Parse une date flexible : "mars 2024", "2020-05", "2021", "present", etc.

    Args:
        s: Chaîne de date

    Returns:
        datetime ou None si parsing échoue
    """
    if not s:
        return None

    s_norm = norm(s)

    # "present", "actuel", "aujourd'hui"
    if any(keyword in s_norm for keyword in ["present", "actuel", "aujourdhui", "now", "current"]):
        return datetime.now()

    # Format "mois YYYY" (français)
    for month_name, month_num in _FR_MONTHS.items():
        if month_name in s_norm:
            # Extraire l'année
            year_match = re.search(r'\b(20\d{2})\b', s_norm)
            if year_match:
                year = int(year_match.group(1))
                try:
                    return datetime(year, month_num, 1)
                except ValueError:
                    # Mois invalide, continuer le parsing
                    continue

    # Format "YYYY-MM" ou "YYYY/MM"
    match = re.search(r'\b(20\d{2})[-/](0[1-9]|1[0-2])\b', s)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        try:
            return datetime(year, month, 1)
        except ValueError:
            # Date invalide, essayer autre format
            pass

    # Format "YYYY" seul
    match = re.search(r'\b(20\d{2})\b', s)
    if match:
        year = int(match.group(1))
        try:
            return datetime(year, 1, 1)
        except ValueError:
            # Année invalide, retourner None
            pass

    return None


def years_between(start: str, end: str) -> float:
    """
    Calcule le nombre d'années entre deux dates

    Args:
        start: Date de début
        end: Date de fin (None ou "present" = maintenant)

    Returns:
        Nombre d'années (float)
    """
    d0 = _parse_date_any(start)
    d1 = _parse_date_any(end) if end else datetime.now()

    if not d0:
        return 0.0
    if not d1:
        d1 = datetime.now()

    return max(0.0, (d1 - d0).days / 365.25)


def years_since_end(date_str: Optional[str]) -> float:
    """
    Calcule le nombre d'années depuis la fin d'une expérience

    Args:
        date_str: Date de fin

    Returns:
        Nombre d'années depuis la fin (float)
    """
    d = _parse_date_any(date_str)
    if not d:
        return 0.0
    return max(0.0, (datetime.now() - d).days / 365.25)


# ==================== POIDS ====================

def renorm_weights(weights: Dict[str, float], enabled: Dict[str, bool]) -> Dict[str, float]:
    """
    Renormalise les poids en excluant les sections désactivées

    Args:
        weights: Poids originaux
        enabled: Dict indiquant quelles sections sont actives

    Returns:
        Poids renormalisés
    """
    ordered = ("Exp", "Tech", "Summary", "Soft")
    w2 = {k: (weights.get(k, 0.0) if enabled.get(k, True) else 0.0) for k in ordered}
    total = sum(w2.values())
    if total <= EPS:
        # Si tout est à 0, distribution équitable
        return {k: 0.25 for k in ordered}
    return {k: (v / total) for k, v in w2.items()}


# ==================== SCORING TECH (LEXICAL) ====================

def build_cv_text_for_skills(cv: Dict) -> str:
    """
    Construit le texte du CV pour la recherche lexicale de compétences

    Args:
        cv: CV structuré

    Returns:
        Texte concaténé normalisé
    """
    parts = [
        cv.get("titre", ""),
        cv.get("resume_professionnel", "")
    ]
    parts += cv.get("competences_techniques", []) or []

    for e in cv.get("experiences_professionnelles", []) or []:
        parts += (e.get("missions") or [])

    for p in cv.get("projets", []) or []:
        if isinstance(p, dict):
            parts += p.get("technologies", []) or []

    return " ".join(norm(x) for x in parts if norm(x))


def present_token(skill: str, cv_text: str) -> int:
    """
    Vérifie si un token de compétence est présent dans le CV (match exact)

    Args:
        skill: Compétence à chercher
        cv_text: Texte du CV normalisé

    Returns:
        1 si présent, 0 sinon
    """
    sk = norm(skill)
    if not sk or sk in AMBIGUOUS:
        return 0

    # Match exact avec word boundaries
    pattern = re.compile(rf"(?<!\w){re.escape(sk)}(?!\w)")
    return 1 if pattern.search(cv_text) else 0


def coverage_lex(
    offer_items: List[str],
    cv_text: str,
    cv_name: str = "unknown",
    cv_sections: Optional[Dict] = None,
    embedding_model=None,
    mode: str = "continuous"
) -> float:
    """
    Score TECH = similarité (LEX + SEM) entre les skills OFFRE et ceux du CV.
    On conserve l'API (retour float), mais on bascule sur l'approche décrite :
      - Liste OFFRE: competences_techniques ∪ outils ∪ langages
      - CV.skills: competences_techniques ∪ certifications[].nom
      - CV.missions: experiences_professionnelles[].missions[]
    Paramètre `cv_sections` déjà présent dans matching_engine pour build_cv_text_for_skills.

    Args:
        offer_items: Liste de compétences/outils demandés
        cv_text: Texte du CV normalisé (non utilisé dans cette version)
        cv_name: Nom du CV (pour logs DEBUG)
        cv_sections: Sections structurées du CV
        embedding_model: Modèle d'embeddings
        mode: "binary" ou "continuous" (défaut)

    Returns:
        Score de couverture [0, 1]
    """
    import re

    # 1) Normalisation des listes
    def _norm(s: str) -> str:
        if not s:
            return ""
        return " ".join(s.strip().lower().split())

    def _tokens(s: str) -> List[str]:
        STOP = {"de","du","des","la","le","les","et","en","à","au","aux","sur","pour","par","avec",
                "d","l","un","une","the","of","in","on","to","and"}
        return [
            t for t in re.sub(r"[^a-z0-9+.#\- ]", " ", s.lower()).split()
            if t and t not in STOP
        ]

    def _tri_sim(a: str, b: str) -> float:
        a = re.sub(r"\s+", " ", a.lower())
        b = re.sub(r"\s+", " ", b.lower())
        A = {a[i:i+3] for i in range(len(a) - 2)} if len(a) >= 3 else set()
        B = {b[i:i+3] for i in range(len(b) - 2)} if len(b) >= 3 else set()
        return (len(A & B) / len(A | B)) if A and B else 0.0

    def _dyn_tau(skill_text: str, base_tau: float) -> float:
        toks = _tokens(skill_text)
        tau = base_tau
        if len("".join(toks)) <= 4:
            tau += 0.08  # skill très court
        if len(toks) >= 2:
            tau -= 0.03  # multi-mots
        return max(0.50, min(0.95, tau))

    def _embed(texts: List[str]) -> np.ndarray:
        if not texts or embedding_model is None:
            return np.zeros((0, 768), dtype=np.float32)
        return embedding_model.encode(
            texts,
            batch_size=len(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        ).astype(np.float32)

    # 2) Préparer listes OFFRE / CV avec expansion des variantes
    offer_variants = set()
    for item in offer_items or []:
        offer_variants |= explode_paren_variants(item)

    if not offer_variants:
        logger.debug(f"[SCORING_TECH] CV={cv_name} score=1.000 (no items requested)")
        return 1.0

    cv_skill_variants = set()
    cv_missions = []
    if cv_sections:
        for item in cv_sections.get("competences_techniques", []) or []:
            cv_skill_variants |= explode_paren_variants(item)
        for cert in cv_sections.get("certifications", []) or []:
            nom = (cert or {}).get("nom")
            if nom:
                cv_skill_variants |= explode_paren_variants(nom)

        for exp in cv_sections.get("experiences_professionnelles", []) or []:
            for mission in exp.get("missions", []) or []:
                canonical = canonical_for_embedding(mission)
                if canonical:
                    cv_missions.append(canonical)

    # 3) Embeddings (uniquement pour missions, plus besoin pour skills)
    E_miss = _embed(cv_missions)

    scores = []
    for item in offer_items or []:  # Itérer sur items originaux
        item_variants = explode_paren_variants(item)

        # Match lexical exact via intersection des variantes
        if item_variants & cv_skill_variants:  # Intersection non vide
            scores.append(1.0)
            continue

        # Fallback sémantique sur missions avec forme canonique
        canonical = canonical_for_embedding(item)
        Es = _embed([canonical])
        if Es.shape[0] == 0:
            scores.append(0.0)
            continue

        # max cosine côté missions
        sim_miss = 0.0
        best_idx = -1
        if len(E_miss):
            sims = (E_miss @ Es.T).ravel()
            best_idx = int(np.argmax(sims))
            cos = float(sims[best_idx])
            sim_miss = max(0.0, (cos + 1.0) / 2.0)

        tau_miss = _dyn_tau(canonical, base_tau=0.78)

        guard_ok = False
        if best_idx >= 0 and cv_missions:
            tok_overlap = len(set(_tokens(canonical)) & set(_tokens(cv_missions[best_idx]))) > 0
            tri_ok = _tri_sim(canonical, cv_missions[best_idx]) >= 0.20
            guard_ok = tok_overlap or tri_ok

        if mode == "binary":
            hit = (sim_miss >= tau_miss and guard_ok)
            s_score = 1.0 if hit else 0.0
        else:
            r_miss = max(0.0, (sim_miss - tau_miss) / max(1e-9, 1 - tau_miss)) if guard_ok else 0.0
            s_score = r_miss

        scores.append(s_score)

    tech_score = float(np.mean(scores)) if scores else 0.0
    logger.debug(f"[SCORING_TECH] CV={cv_name} score={tech_score:.3f} (hybrid lexical+semantic)")
    return tech_score


# ==================== SCORING SUMMARY ====================

def summary_score(offer_summary: str, cv_summary: str, embedding_model, cv_name: str = "unknown") -> float:
    """
    Calcule la similarité cosinus entre les résumés/titres

    Args:
        offer_summary: Résumé de l'offre
        cv_summary: Résumé du CV
        embedding_model: Modèle d'embeddings (SentenceTransformer)
        cv_name: Nom du CV (pour logs DEBUG)

    Returns:
        Score de similarité [0, 1]
    """
    off = norm(offer_summary)
    cv = norm(cv_summary)

    if not off or not cv:
        logger.debug(f"[SCORING_SUMMARY] CV={cv_name} score=0.000 (empty summary)")
        return 0.0

    # Encoder
    embeddings = embedding_model.encode(
        [off, cv],
        batch_size=2,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False
    )

    # Cosinus (dot product car normalisé)
    score = float((embeddings[1:2] @ embeddings[0:1].T)[0, 0])

    logger.debug(
        f"[SCORING_SUMMARY] CV={cv_name} score={score:.3f} "
        f"offer_len={len(off)} cv_len={len(cv)}"
    )

    return score


# ==================== SCORING EXPÉRIENCE ====================

def score_exp(
    offer_items_texts: List[str],
    cv_experiences: List[Dict],
    embedding_model,
    tau: float = TAU,
    y_cap: float = Y_CAP_DEFAULT,
    cv_name: str = "unknown"
) -> Tuple[float, float, float, List[Dict]]:
    """
    Calcule le score d'expérience avec cosinus + pondération années + cap linéaire

    Formule :
    - Pour chaque bullet d'offre :
        - Pour chaque expérience CV : cosinus max + poids log(1 + années)
        - Moyenne pondérée intra-exp
        - Cap linéaire sur années totales : V = min(sum_années, y_cap) / y_cap
        - Score item = s_avg * V

    Args:
        offer_items_texts: Liste de phrases/bullets d'offre (missions, projets...)
        cv_experiences: Liste des expériences du CV
        embedding_model: Modèle d'embeddings
        tau: Seuil de couverture
        y_cap: Cap sur années totales
        cv_name: Nom du CV (pour logs DEBUG)

    Returns:
        (score_exp, coverage_raw, coverage_weighted, details)
    """
    items = [norm(x) for x in (offer_items_texts or []) if norm(x)]
    if not items:
        logger.debug(f"[SCORING_EXP] CV={cv_name} score=1.000 (no items requested)")
        return 1.0, 1.0, 1.0, []

    # Préparer les expériences avec bullets non vides
    exps = []
    for e in (cv_experiences or []):
        bullets = [norm(b) for b in (e.get("missions") or []) if norm(b)]
        if not bullets:
            continue
        y = years_between(e.get("date_debut"), e.get("date_fin"))
        recency_years = years_since_end(e.get("date_fin"))
        exps.append({"bullets": bullets, "y": max(0.0, y), "recency_years": recency_years})

    if not exps:
        logger.debug(f"[SCORING_EXP] CV={cv_name} score=0.000 (no experience with bullets)")
        return 0.0, 0.0, 0.0, []

    # Log des expériences trouvées
    y_total_init = sum(p["y"] for p in exps)
    logger.debug(
        f"[SCORING_EXP] CV={cv_name} n_exp={len(exps)} n_offer_items={len(items)} "
        f"y_total={y_total_init:.1f} y_cap={y_cap}"
    )

    # Encoder les bullets de chaque expérience
    for p in exps:
        p["Eb"] = embedding_model.encode(
            p["bullets"],
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )  # Shape: (nb, d)

    cov_raw = 0
    cov_w = 0
    scores = []
    per_item = []

    # Pour chaque item d'offre
    for off in items:
        Eo = embedding_model.encode(
            [off],
            batch_size=1,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )  # Shape: (1, d)

        s_list, t_list = [], []
        for p in exps:
            # Max cosinus entre l'item d'offre et tous les bullets de cette exp
            s_e = float((p["Eb"] @ Eo.T).max())
            # Poids concave : log(1 + années)
            t_e = math.log(1.0 + p["y"])
            recency_years = p.get("recency_years", 0.0)
            if recency_years > 3.0:
                t_e *= 0.97 ** (recency_years - 3.0)
            s_list.append(s_e)
            t_list.append(t_e)

        den_t = sum(t_list)
        if den_t <= EPS:
            scores.append(0.0)
            per_item.append({"offer_item": off, "score_item": 0.0})
            continue

        # Moyenne pondérée des similarités
        s_avg = sum(s * t for s, t in zip(s_list, t_list)) / (den_t + EPS)

        # Cap linéaire sur années totales
        y_total = sum(p["y"] for p in exps)
        V = min(y_total, y_cap) / y_cap

        # Score pondéré
        wsc = s_avg * V

        scores.append(wsc)
        cov_raw += int(max(s_list) >= tau)
        cov_w += int(wsc >= tau)

        # Log détaillé pour ce bullet d'offre
        logger.debug(
            f"[SCORING_EXP]   bullet={off[:50]+'...' if len(off) > 50 else off} "
            f"s_avg={s_avg:.3f} V={V:.3f} wsc={wsc:.3f} raw_max={max(s_list):.3f}"
        )
        # Log des cosinus par exp
        for i, (s_e, t_e) in enumerate(zip(s_list, t_list)):
            logger.debug(
                f"[SCORING_EXP]     exp#{i} cosine={s_e:.3f} years={exps[i]['y']:.1f} "
                f"weight={t_e:.3f}"
            )

        per_item.append({
            "offer_item": off,
            "s_avg": s_avg,
            "V": V,
            "score_item": wsc,
            "raw_max": max(s_list)
        })

    n = len(scores)
    final_score_exp = sum(scores) / n
    final_cov_raw = cov_raw / n
    final_cov_w = cov_w / n

    # Log final
    logger.debug(
        f"[SCORING_EXP] CV={cv_name} FINAL score={final_score_exp:.3f} "
        f"cov_raw={final_cov_raw:.3f} cov_w={final_cov_w:.3f}"
    )

    return (
        final_score_exp,
        final_cov_raw,
        final_cov_w,
        per_item
    )


# ==================== EMPTY POLICY & FINAL SCORE ====================

def final_score(
    exp_component: float,
    tech_score: float,
    summary_score_val: float,
    soft_score: float,
    weights: Dict[str, float],
    has_offer_exp: bool,
    has_offer_tech: bool,
    cv_has_exp_content: bool,
    cv_has_tech_content: bool
) -> Tuple[float, List[str]]:
    """
    Calcule le score final avec empty policy

    Empty Policy :
    - Si offre demande Exp mais CV n'a pas de contenu Exp → score = 0
    - Si offre demande Tech mais CV n'a pas de contenu Tech → score = 0

    Args:
        exp_component: Score Exp (éventuellement Exp_eff)
        tech_score: Score Tech
        summary_score_val: Score Summary
        soft_score: Score Soft
        weights: Poids des composantes
        has_offer_exp: Offre demande Exp ?
        has_offer_tech: Offre demande Tech ?
        cv_has_exp_content: CV a du contenu Exp ?
        cv_has_tech_content: CV a du contenu Tech ?

    Returns:
        (score_final, reason_codes)
    """
    reason_codes = []

    # Empty policy
    if has_offer_exp and not cv_has_exp_content:
        return 0.0, ["EXP_EMPTY"]
    if has_offer_tech and not cv_has_tech_content:
        return 0.0, ["TECH_EMPTY"]

    # Calcul final
    final = (
        weights.get("Exp", 0.0) * exp_component +
        weights.get("Tech", 0.0) * tech_score +
        weights.get("Summary", 0.0) * summary_score_val +
        weights.get("Soft", 0.0) * soft_score
    )

    return max(0.0, min(1.0, final)), reason_codes


# ==================== SCORING CONTEXTE (BLOC D) ====================

def extract_offer_context(sections: Dict) -> Tuple[str, str]:
    """
    Extrait le contexte de l'offre (titre + résumé)

    Args:
        sections: Sections de l'offre

    Returns:
        (titre_nettoyé, resume_nettoyé)
    """
    titre = strip_parens_for_context(sections.get("titre", ""))
    resume = strip_parens_for_context(sections.get("resume_professionnel", ""))
    return titre, resume


def extract_cv_context(cv_json: Dict) -> Tuple[str, str]:
    """
    Extrait le contexte du CV (titre + résumé)

    Args:
        cv_json: Données du CV

    Returns:
        (titre_nettoyé, resume_nettoyé)
    """
    titre = strip_parens_for_context(cv_json.get("titre", ""))
    resume = strip_parens_for_context(cv_json.get("resume_professionnel", ""))
    return titre, resume


def score_context(
    sections_offre: Dict,
    cv_json: Dict,
    embedding_model,
    weight_title: float = 0.6,
    weight_resume: float = 0.4,
    cv_name: Optional[str] = None
) -> Tuple[float, Dict[str, Optional[float]]]:
    """
    Calcule le score de contexte (bloc D) entre l'offre et le CV
    Mesure l'alignement sémantique titre + résumé avec rééquilibrage

    Args:
        sections_offre: Sections de l'offre
        cv_json: Données du CV
        embedding_model: Modèle d'embeddings
        weight_title: Poids du titre (défaut 0.6)
        weight_resume: Poids du résumé (défaut 0.4)
        cv_name: Nom du CV pour logging

    Returns:
        (score_contexte [0,1], debug_info)
    """
    cv_prefix = f"CV={cv_name} " if cv_name else ""

    offer_title, offer_resume = extract_offer_context(sections_offre)
    cv_title, cv_resume = extract_cv_context(cv_json)

    logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Offer: title='{offer_title[:50] if offer_title else 'N/A'}...' resume={'présent' if offer_resume else 'absent'}")
    logger.debug(f"[SCORING_CONTEXT] {cv_prefix}CV: title='{cv_title[:50] if cv_title else 'N/A'}...' resume={'présent' if cv_resume else 'absent'}")

    # Calcul des similarités (None si absent des deux côtés)
    sim_title = _sim01(offer_title, cv_title, embedding_model) if offer_title and cv_title else None
    sim_resume = _sim01(offer_resume, cv_resume, embedding_model) if offer_resume and cv_resume else None

    if sim_title is not None:
        logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Similarité titre: {sim_title:.3f}")
    if sim_resume is not None:
        logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Similarité résumé: {sim_resume:.3f}")

    # Rééquilibrage sur les composantes disponibles
    weights, scores = [], []
    if sim_title is not None:
        weights.append(weight_title)
        scores.append(sim_title)
    if sim_resume is not None:
        weights.append(weight_resume)
        scores.append(sim_resume)

    # Si rien de disponible des deux côtés
    if not weights:
        logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Aucune composante disponible → score=0.0")
        return 0.0, {
            "sim_title": None,
            "sim_resume": None,
            "weight_title": 0.0,
            "weight_resume": 0.0
        }

    # Renormalisation des poids
    total_w = sum(weights)
    weights = [w / total_w for w in weights]
    score = float(sum(w * s for w, s in zip(weights, scores)))

    w_title_final = weights[0] if sim_title is not None else 0.0
    w_resume_final = weights[-1] if sim_resume is not None else 0.0

    logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Poids rééquilibrés: titre={w_title_final:.2f} résumé={w_resume_final:.2f}")
    logger.debug(f"[SCORING_CONTEXT] {cv_prefix}Score final contexte: {score:.3f}")

    debug = {
        "sim_title": sim_title,
        "sim_resume": sim_resume,
        "weight_title": w_title_final,
        "weight_resume": w_resume_final
    }
    return score, debug


# ==================== EXTRACTION ITEMS OFFRE ====================

def extract_offer_items(offer_data: Dict) -> Tuple[List[str], List[str], str]:
    """
    Extrait les items Tech, Exp et Summary de l'offre

    Args:
        offer_data: Données de l'offre (format JSON avec sections)

    Returns:
        (tech_items, exp_items, summary_text)
    """
    sections = offer_data.get("sections", {})

    # Tech items
    tech_items = []
    tech_items += sections.get("competences_techniques", []) or []
    tech_items += sections.get("outils", []) or []
    tech_items += sections.get("langages", []) or []

    # Exp items (phrases de missions, projets, description)
    exp_items = []

    # Missions déclarées
    for exp in sections.get("experiences_professionnelles", []) or []:
        for mission in exp.get("missions", []) or []:
            if isinstance(mission, str) and len(mission.strip()) > 0:
                exp_items.append(mission.strip())

    # Projets (supporte list[str] ET list[dict])
    for project in sections.get("projets", []) or []:
        if isinstance(project, str):
            if project.strip():
                exp_items.append(project.strip())
        elif isinstance(project, dict):
            desc = project.get("description")
            if isinstance(desc, str) and desc.strip():
                exp_items.append(desc.strip())
            for mission in project.get("missions", []) or []:
                if isinstance(mission, str) and mission.strip():
                    exp_items.append(mission.strip())

    # Description globale (phrases découpées)
    desc = sections.get("description")
    if isinstance(desc, str) and desc.strip():
        for sentence in re.split(r"[.;•\n]+", desc):
            sentence = sentence.strip()
            if sentence and len(sentence.split()) >= 2:  # ≥2 tokens utiles
                exp_items.append(sentence)

    # Summary (titre + résumé)
    summary_parts = []
    if sections.get("titre"):
        summary_parts.append(sections["titre"])
    if sections.get("resume_professionnel"):
        summary_parts.append(sections["resume_professionnel"])
    summary_text = " ".join(summary_parts)

    return tech_items, exp_items, summary_text
