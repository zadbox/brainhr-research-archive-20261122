"""
Analyseur d'expériences professionnelles
Détecte les trous (gappes) et chevauchements (overlaps) dans le parcours
"""

import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Tuple, Optional

from lib.models import Gap, Overlap, Flags


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse une date depuis les formats courants des CVs

    Formats supportés:
    - MM/YYYY
    - YYYY-MM
    - YYYY
    - "Présent", "Actuel", "En cours", "Current", etc.

    Args:
        date_str: Chaîne de date à parser

    Returns:
        datetime object ou None si parsing échoue
    """
    if not date_str:
        return None

    # Nettoyer la chaîne
    date_str = date_str.strip().lower()

    # Dates "en cours" (marqueurs étendus)
    if any(k in date_str for k in ['présent', 'present', 'current', 'actuel', 'en cours', 'now', 'à ce jour', 'a ce jour', 'poste actuel']):
        return datetime.now()

    # Format MM/YYYY
    match = re.match(r'(\d{1,2})/(\d{4})', date_str)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        # Valider que le mois est entre 1 et 12
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return datetime(year, month, 1)
        return None

    # Format YYYY-MM
    match = re.match(r'(\d{4})-(\d{1,2})', date_str)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        # Valider que le mois est entre 1 et 12
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return datetime(year, month, 1)
        return None

    # Format YYYY/MM
    match = re.match(r'(\d{4})/(\d{1,2})', date_str)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        try:
            return datetime(year, month, 1)
        except ValueError:
            return None

    # Format MM-YYYY
    match = re.match(r'(\d{1,2})-(\d{4})', date_str)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        try:
            return datetime(year, month, 1)
        except ValueError:
            return None

    # Format YYYY seulement (prendre janvier par défaut pour début, décembre pour fin)
    match = re.match(r'(\d{4})', date_str)
    if match:
        year = int(match.group(1))
        return datetime(year, 1, 1)  # On prendra 1er janvier par défaut

    return None


def months_between(date1: datetime, date2: datetime) -> int:
    """Calcule le nombre de mois entre deux dates"""
    delta = relativedelta(date2, date1)
    return abs(delta.years * 12 + delta.months)


def days_between(date1: datetime, date2: datetime) -> int:
    """Calcule le nombre de jours entre deux dates"""
    return abs((date2 - date1).days)


def detect_gaps_and_overlaps(experiences: List[Dict[str, Any]]) -> Flags:
    """
    Détecte les trous et chevauchements dans les expériences professionnelles

    Args:
        experiences: Liste des expériences (doit contenir date_debut, date_fin, poste, entreprise)

    Returns:
        Flags object contenant gappes (≥3 mois) et overlaps (>60 jours / 2 mois) détectés
    """
    gaps = []
    overlaps = []

    # Parser et trier les expériences par date de fin décroissante
    parsed_exps = []
    for i, exp in enumerate(experiences):
        date_debut = parse_date(exp.get('date_debut', ''))
        date_fin = parse_date(exp.get('date_fin', ''))

        # ✅ Place date_fin à la fin du mois pour éviter les "mois fantômes"
        if date_fin:
            date_fin = (date_fin + relativedelta(months=1)) - relativedelta(days=1)

        if date_debut and date_fin:
            parsed_exps.append({
                'index': i,
                'poste': exp.get('poste', 'Inconnu'),
                'entreprise': exp.get('entreprise', 'Inconnu'),
                'date_debut': date_debut,
                'date_fin': date_fin,
                'original': exp
            })

    # Trier par date de fin décroissante
    parsed_exps.sort(key=lambda x: x['date_fin'], reverse=True)

    # Détecter les gappes (trous >= 3 mois)
    for i in range(len(parsed_exps) - 1):
        exp_current = parsed_exps[i]      # plus récente
        exp_next = parsed_exps[i + 1]     # plus ancienne

        # ✅ VRAI trou seulement si l'ancienne FINIT avant que la récente ne COMMENCE
        if exp_next['date_fin'] < exp_current['date_debut']:
            gap_months = months_between(exp_next['date_fin'], exp_current['date_debut'])

            if gap_months >= 3:
                period = f"{exp_next['date_fin'].strftime('%Y-%m')} → {exp_current['date_debut'].strftime('%Y-%m')}"
                between = f"Expérience #{exp_next['index']+1} ({exp_next['entreprise']}) et Expérience #{exp_current['index']+1} ({exp_current['entreprise']})"

                gaps.append(Gap(
                    period=period,
                    duration_months=gap_months,
                    between=between,
                    cv_excerpt=None
                ))

    # Détecter les overlaps (chevauchements > 14 jours)
    for i in range(len(parsed_exps)):
        for j in range(i + 1, len(parsed_exps)):
            exp_a = parsed_exps[i]
            exp_b = parsed_exps[j]

            # Vérifier si les périodes se chevauchent
            # Chevauchement si: début_B < fin_A ET début_A < fin_B
            if exp_b['date_debut'] < exp_a['date_fin'] and exp_a['date_debut'] < exp_b['date_fin']:
                # Calculer la période de chevauchement
                overlap_start = max(exp_a['date_debut'], exp_b['date_debut'])
                overlap_end = min(exp_a['date_fin'], exp_b['date_fin'])

                overlap_days_count = days_between(overlap_start, overlap_end)

                # Ignorer les chevauchements ≤ 60 jours (peuvent être normaux)
                if overlap_days_count > 60:  # 2 mois ≈ 60 jours
                    overlap_period = f"{overlap_start.strftime('%Y-%m')} → {overlap_end.strftime('%Y-%m')}"
                    experiences_str = f"Expérience #{exp_a['index']+1} ({exp_a['entreprise']}) et Expérience #{exp_b['index']+1} ({exp_b['entreprise']})"
                    same_company = exp_a['entreprise'].lower() == exp_b['entreprise'].lower()

                    overlaps.append(Overlap(
                        overlap_period=overlap_period,
                        overlap_days=overlap_days_count,
                        experiences=experiences_str,
                        same_company=same_company,
                        cv_excerpt=None  # Pourrait être enrichi
                    ))

    return Flags(gappes=gaps, overlaps=overlaps)


def format_flags_for_llm(flags: Flags) -> str:
    """
    Formate les flags pour inclusion dans le prompt LLM

    Args:
        flags: Flags object

    Returns:
        Chaîne formatée pour le prompt
    """
    if not flags.gappes and not flags.overlaps:
        return "Aucun flag détecté (pas de trous ni de chevauchements significatifs)."

    parts = []

    if flags.gappes:
        parts.append(f"⚠️ TROUS DÉTECTÉS ({len(flags.gappes)}):")
        for gap in flags.gappes:
            parts.append(f"  - {gap.period} ({gap.duration_months} mois) entre {gap.between}")

    if flags.overlaps:
        parts.append(f"⚠️ CHEVAUCHEMENTS DÉTECTÉS ({len(flags.overlaps)}):")
        for overlap in flags.overlaps:
            same_company_str = " (même entreprise)" if overlap.same_company else ""
            parts.append(f"  - {overlap.overlap_period} ({overlap.overlap_days} jours) : {overlap.experiences}{same_company_str}")

    return "\n".join(parts)


# ==================== EXTENSIONS OPTIONNELLES ====================

def _formation_to_exp_blocks(cv_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convertit les formations en blocs d'expérience pour couvrir les périodes d'études
    et éviter les faux trous pendant la scolarité
    """
    blocks = []
    for f in (cv_json.get("formations") or []):
        d0 = (f.get("date_debut") or "").strip()
        d1 = (f.get("date_fin") or "").strip()
        an = (f.get("annee_obtention") or f.get("annee") or "").strip()

        # Si pas de dates mais année d'obtention, couvrir l'année civile
        if (not d0 or not d1) and an.isdigit() and len(an) == 4:
            d0, d1 = f"01/{an}", f"12/{an}"

        if d0 and d1:
            blocks.append({
                "poste": f.get("diplome", "Formation"),
                "entreprise": f.get("ecole", "Etablissement"),
                "date_debut": d0,
                "date_fin": d1,
                "missions": []
            })
    return blocks


def detect_gaps_and_overlaps_with_education(cv_json: Dict[str, Any]) -> Flags:
    """
    Détecte les trous et chevauchements en incluant les périodes de formation
    Wrapper autour de detect_gaps_and_overlaps qui enrichit la timeline avec les formations
    Seuils: gaps ≥3 mois, overlaps >60 jours (2 mois)
    """
    exps = list(cv_json.get("experiences_professionnelles") or []) + _formation_to_exp_blocks(cv_json)
    return detect_gaps_and_overlaps(exps)


def _is_stage(exp: Dict[str, Any]) -> bool:
    """Détecte si une expérience est un stage"""
    txt = " ".join([
        (exp.get("poste") or ""),
        (exp.get("entreprise") or ""),
        " ".join(exp.get("missions") or [])
    ]).lower()
    return any(k in txt for k in ["stage", "intern", "internship", "stagiaire"])


def detect_gaps_and_overlaps_augmented(cv_json: Dict[str, Any], stage_break_ok_months: int = 10) -> Flags:
    """
    Détecte les trous et chevauchements avec enrichissements:
    - Inclut les formations dans la timeline
    - Tolère les trous stage↔stage ≤ stage_break_ok_months mois (creux académique)
    Seuils: gaps ≥3 mois, overlaps >60 jours (2 mois)
    """
    exps = list(cv_json.get("experiences_professionnelles") or []) + _formation_to_exp_blocks(cv_json)

    # Parse + tri + fin de mois
    parsed = []
    for i, exp in enumerate(exps):
        d0 = parse_date(exp.get('date_debut', ''))
        d1 = parse_date(exp.get('date_fin', ''))

        # Place date_fin à la fin du mois
        if d1:
            d1 = (d1 + relativedelta(months=1)) - relativedelta(days=1)

        if d0 and d1:
            parsed.append({
                'index': i,
                'poste': exp.get('poste', 'Inconnu'),
                'entreprise': exp.get('entreprise', 'Inconnu'),
                'date_debut': d0,
                'date_fin': d1,
                'is_stage': _is_stage(exp),
                'original': exp
            })

    parsed.sort(key=lambda x: x['date_fin'], reverse=True)

    gaps, overlaps = [], []

    # Gaps : même logique + tolérance stage↔stage
    for i in range(len(parsed) - 1):
        cur, nxt = parsed[i], parsed[i + 1]

        # Vrai trou seulement si l'ancienne finit avant que la récente commence
        if nxt['date_fin'] < cur['date_debut']:
            gap_months = months_between(nxt['date_fin'], cur['date_debut'])

            if gap_months >= 3:
                # ✅ Tolérance: si stage↔stage et gap ≤ stage_break_ok_months, ignorer (creux académique)
                if cur['is_stage'] and nxt['is_stage'] and gap_months <= stage_break_ok_months:
                    continue

                period = f"{nxt['date_fin'].strftime('%Y-%m')} → {cur['date_debut'].strftime('%Y-%m')}"
                between = f"Expérience #{nxt['index']+1} ({nxt['entreprise']}) et Expérience #{cur['index']+1} ({cur['entreprise']})"

                gaps.append(Gap(
                    period=period,
                    duration_months=gap_months,
                    between=between,
                    cv_excerpt=None
                ))

    # Overlaps : inchangé (> 14 jours)
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            a, b = parsed[i], parsed[j]

            if b['date_debut'] < a['date_fin'] and a['date_debut'] < b['date_fin']:
                overlap_start = max(a['date_debut'], b['date_debut'])
                overlap_end = min(a['date_fin'], b['date_fin'])
                overlap_days = days_between(overlap_start, overlap_end)

                if overlap_days > 60:  # 2 mois ≈ 60 jours
                    overlaps.append(Overlap(
                        overlap_period=f"{overlap_start.strftime('%Y-%m')} → {overlap_end.strftime('%Y-%m')}",
                        overlap_days=overlap_days,
                        experiences=f"Expérience #{a['index']+1} ({a['entreprise']}) et Expérience #{b['index']+1} ({b['entreprise']})",
                        same_company=(a['entreprise'].lower() == b['entreprise'].lower()),
                        cv_excerpt=None
                    ))

    return Flags(gappes=gaps, overlaps=overlaps)
