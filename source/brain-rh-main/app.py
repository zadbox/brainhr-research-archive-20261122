"""
Interface utilisateur Streamlit pour le système de matching CV/RH
"""

import streamlit as st
import json
import os
from pathlib import Path
import pandas as pd
from typing import List, Dict
from datetime import datetime

# Imports des modules custom
from config_loader import get_config
from matching_engine import MatchingEngine
from mapper_offre import map_offre_to_sections
from rome_api import get_rome_competences
import parseur_cv
from offer_enrichment import enrich_offer_intelligently, merge_enrichment
from parallel_cv_parsing import parse_cvs_parallel_sync
import asyncio

# Imports pour gestion multi-niveaux
from project_manager import ProjectManager
from enterprise_manager import EnterpriseManager
from pages_ui import page_accueil_entreprises, page_accueil_projets, show_project_header

# Configuration de la page
st.set_page_config(
    page_title="Système de Matching CV/RH",
    page_icon="●",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Charger la configuration
@st.cache_resource
def load_config():
    return get_config()

config = load_config()

# Fonction pour convertir image en base64
import base64
def get_base64_image(image_path):
    """Convertit une image en base64 pour l'afficher en HTML"""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

# Initialiser le matching engine
@st.cache_resource
def load_matching_engine():
    return MatchingEngine(config._config)

matching_engine = load_matching_engine()

# Initialiser le gestionnaire d'entreprises
@st.cache_resource
def load_enterprise_manager():
    enterprises_folder = "enterprises"
    return EnterpriseManager(enterprises_folder)

em = load_enterprise_manager()

# ==================== ROUTING MULTI-NIVEAUX ====================
# Initialiser le session state
if 'current_enterprise' not in st.session_state:
    st.session_state['current_enterprise'] = None
if 'current_project' not in st.session_state:
    st.session_state['current_project'] = None

# NIVEAU 1: Si aucune entreprise sélectionnée → afficher la page des entreprises
if not st.session_state.get('current_enterprise'):
    page_accueil_entreprises(em)
    st.stop()

# NIVEAU 2: Si une entreprise est sélectionnée mais pas de projet → afficher les projets
current_enterprise_id = st.session_state['current_enterprise']
enterprise = em.get_enterprise(current_enterprise_id)

if not enterprise:
    st.error(f"Entreprise {current_enterprise_id} introuvable")
    st.session_state['current_enterprise'] = None
    st.rerun()

# Récupérer le dossier projects de cette entreprise
projects_folder = em.get_projects_folder(current_enterprise_id)

# Créer un ProjectManager spécifique pour cette entreprise
# IMPORTANT: Inclure enterprise_id dans le cache pour isoler les projets par entreprise
@st.cache_resource
def load_project_manager_for_enterprise(_projects_folder, enterprise_id):
    return ProjectManager(str(_projects_folder))

pm = load_project_manager_for_enterprise(projects_folder, current_enterprise_id)

if not st.session_state.get('current_project'):
    page_accueil_projets(pm, current_enterprise_id, enterprise['nom'])
    # Mettre à jour le compteur de projets de l'entreprise
    em.update_projects_count(current_enterprise_id)
    st.stop()

# NIVEAU 3: Si un projet est sélectionné → afficher le header et continuer
current_project_id = st.session_state['current_project']
show_project_header(pm, current_project_id, enterprise['nom'])

# Charger l'offre du projet (toujours recharger pour éviter mélange entre projets)
# Vérifier si le projet a changé
if st.session_state.get('loaded_project_id') != current_project_id:
    # Nouveau projet ou changement de projet → réinitialiser
    st.session_state['loaded_project_id'] = current_project_id
    st.session_state.pop('offre_data', None)
    st.session_state.pop('offre_text', None)
    st.session_state.pop('offre_parsed', None)
    st.session_state.pop('criteres_auto', None)
    st.session_state.pop('criteres_manual', None)
    st.session_state.pop('scored_cvs', None)
    st.session_state.pop('reranked_cvs', None)

# Charger l'offre du projet si elle existe
if 'offre_data' not in st.session_state:
    offre_saved = pm.load_offer(current_project_id)
    if offre_saved:
        st.session_state['offre_data'] = offre_saved
        st.session_state['offre_parsed'] = True
        # Reconstruire offre_text pour l'extraction des critères
        sections = offre_saved.get('sections', {})
        st.session_state['offre_text'] = " ".join([
            str(v) for v in sections.values() if v
        ])

# ==================== CHARTE GRAPHIQUE BRAIN RH+ ====================
st.markdown("""
<style>
    /* Import Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Variables globales - Palette BRAIN RH+ (Light Mode) */
    :root {
        --primary-navy: #1B2B4A;
        --primary-blue: #4A90E2;
        --accent-cyan: #5BC0DE;
        --neutral-dark: #2D3748;
        --neutral-medium: #718096;
        --neutral-light: #E2E8F0;
        --bg-white: #FFFFFF;
        --bg-light: #F7FAFC;
        --bg-blue: #EBF8FF;
        --success: #48BB78;
        --warning: #ED8936;
        --error: #F56565;
        --text-primary: #1B2B4A;
        --text-secondary: #718096;
        --sidebar-bg: linear-gradient(180deg, #FFFFFF 0%, #F7FAFC 100%);
    }

    /* Dark Mode Variables */
    [data-theme="dark"] {
        --primary-navy: #E2E8F0;
        --primary-blue: #63B3ED;
        --accent-cyan: #76E4F7;
        --neutral-dark: #E2E8F0;
        --neutral-medium: #A0AEC0;
        --neutral-light: #4A5568;
        --bg-white: #2D3748;
        --bg-light: #1A202C;
        --bg-blue: #2C5282;
        --success: #68D391;
        --warning: #F6AD55;
        --error: #FC8181;
        --text-primary: #FFFFFF;
        --text-secondary: #A0AEC0;
        --sidebar-bg: linear-gradient(180deg, #2D3748 0%, #1A202C 100%);
    }

    /* Application globale du dark mode */
    .stApp {
        background-color: var(--bg-light) !important;
        color: var(--text-primary) !important;
    }

    .main {
        background-color: var(--bg-light) !important;
        color: var(--text-primary) !important;
    }

    /* Reset et base */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Header avec logo */
    .brain-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 2rem;
        padding: 2rem 0 1rem 0;
        background: linear-gradient(135deg, var(--bg-white) 0%, var(--bg-blue) 100%);
        border-bottom: 2px solid var(--neutral-light);
        margin-bottom: 2rem;
    }

    .brain-logo {
        max-width: 280px;
        height: auto;
    }

    /* Headers de section */
    .section-header {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--primary-navy);
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.75rem;
        border-bottom: 3px solid var(--primary-blue);
        position: relative;
    }

    .section-header::before {
        content: '';
        position: absolute;
        bottom: -3px;
        left: 0;
        width: 60px;
        height: 3px;
        background: var(--accent-cyan);
    }

    /* Cards professionnelles */
    .pro-card {
        background: var(--bg-white);
        border: 1px solid var(--neutral-light);
        border-left: 4px solid var(--primary-blue);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 8px rgba(27, 43, 74, 0.08);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .pro-card:hover {
        box-shadow: 0 8px 16px rgba(27, 43, 74, 0.12);
        transform: translateY(-2px);
        border-left-color: var(--accent-cyan);
    }

    /* Boutons - Design moderne */
    .stButton>button {
        background: linear-gradient(135deg, var(--primary-blue) 0%, var(--accent-cyan) 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.75rem 2rem;
        font-weight: 600;
        font-size: 0.95rem;
        letter-spacing: 0.3px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(74, 144, 226, 0.25);
    }

    .stButton>button:hover {
        box-shadow: 0 6px 20px rgba(74, 144, 226, 0.35);
        transform: translateY(-2px);
    }

    .stButton>button:active {
        transform: translateY(0);
    }

    /* Bouton primary (accent) */
    button[kind="primary"] {
        background: linear-gradient(135deg, var(--primary-navy) 0%, var(--primary-blue) 100%);
        box-shadow: 0 4px 12px rgba(27, 43, 74, 0.3);
    }

    button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(27, 43, 74, 0.4);
    }

    /* Sidebar moderne avec dark mode */
    section[data-testid="stSidebar"] {
        background: var(--sidebar-bg) !important;
        border-right: 1px solid var(--neutral-light) !important;
    }

    section[data-testid="stSidebar"] > div {
        padding-top: 2rem;
    }

    /* Force text color in sidebar */
    section[data-testid="stSidebar"] * {
        color: var(--text-primary) !important;
    }

    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        color: var(--text-primary) !important;
    }

    /* Sliders dans sidebar */
    section[data-testid="stSidebar"] .stSlider label {
        color: var(--text-primary) !important;
    }

    section[data-testid="stSidebar"] .stSlider div[data-baseweb="slider"] {
        color: var(--text-primary) !important;
    }

    /* Barre de menu Deploy en haut */
    header[data-testid="stHeader"] {
        background-color: var(--bg-white) !important;
        border-bottom: 1px solid var(--neutral-light) !important;
    }

    header[data-testid="stHeader"] * {
        color: var(--text-primary) !important;
    }

    /* DARK MODE - Force text color on ALL form elements */
    [data-theme="dark"] input,
    [data-theme="dark"] textarea,
    [data-theme="dark"] select,
    [data-theme="dark"] label,
    [data-theme="dark"] .stTextInput label,
    [data-theme="dark"] .stTextArea label,
    [data-theme="dark"] .stSelectbox label,
    [data-theme="dark"] .stRadio label,
    [data-theme="dark"] .stCheckbox label,
    [data-theme="dark"] .stRadio *,
    [data-theme="dark"] .stFileUploader *,
    [data-theme="dark"] [class*="Radio"] label,
    [data-theme="dark"] [class*="Radio"] *,
    [data-theme="dark"] [class*="FileUpload"] label,
    [data-theme="dark"] [class*="FileUpload"] * {
        color: #FFFFFF !important;
    }

    /* Input fields background in dark mode */
    [data-theme="dark"] input,
    [data-theme="dark"] textarea,
    [data-theme="dark"] select {
        background-color: #2D3748 !important;
        color: #FFFFFF !important;
        border-color: #4A5568 !important;
    }

    /* Placeholder text in dark mode */
    [data-theme="dark"] input::placeholder,
    [data-theme="dark"] textarea::placeholder {
        color: #A0AEC0 !important;
        opacity: 0.7 !important;
    }

    /* Radio buttons text */
    [data-theme="dark"] .stRadio > label,
    [data-theme="dark"] .stRadio > label > div,
    [data-theme="dark"] .stRadio div[role="radiogroup"] label,
    [data-theme="dark"] .stRadio div[role="radiogroup"] > div > label,
    [data-theme="dark"] .stRadio [data-testid="stMarkdownContainer"] p,
    [data-theme="dark"] .stRadio label span {
        color: #FFFFFF !important;
    }

    /* Checkbox text */
    [data-theme="dark"] .stCheckbox > label > div,
    [data-theme="dark"] .stCheckbox label span {
        color: #FFFFFF !important;
    }

    /* File uploader text - SUPER AGRESSIF */
    [data-theme="dark"] .stFileUploader label,
    [data-theme="dark"] .stFileUploader section,
    [data-theme="dark"] .stFileUploader section > div,
    [data-theme="dark"] .stFileUploader p,
    [data-theme="dark"] .stFileUploader span,
    [data-theme="dark"] .stFileUploader small,
    [data-theme="dark"] [data-testid="stFileUploadDropzone"] label,
    [data-theme="dark"] [data-testid="stFileUploadDropzone"] span {
        color: #FFFFFF !important;
    }

    /* Slider labels and values */
    [data-theme="dark"] .stSlider label,
    [data-theme="dark"] .stSlider div[data-testid="stTickBar"] div {
        color: #FFFFFF !important;
    }

    /* Captions and small text */
    [data-theme="dark"] .caption,
    [data-theme="dark"] small,
    [data-theme="dark"] .stCaption {
        color: #A0AEC0 !important;
    }

    /* Form labels specifics */
    [data-theme="dark"] .stForm label,
    [data-theme="dark"] [data-testid="stFormSubmitButton"] {
        color: #FFFFFF !important;
    }

    /* Expander headers */
    [data-theme="dark"] .streamlit-expanderHeader {
        color: #FFFFFF !important;
        background-color: var(--bg-blue) !important;
    }

    /* Tab text */
    [data-theme="dark"] .stTabs [data-baseweb="tab"] {
        color: var(--text-secondary) !important;
    }

    [data-theme="dark"] .stTabs [aria-selected="true"] {
        color: #FFFFFF !important;
    }

    /* Selectbox dropdown (portal DOM) */
    [data-theme="dark"] [data-baseweb="popover"] {
        background-color: #2D3748 !important;
    }

    [data-theme="dark"] [data-baseweb="select"] li,
    [data-theme="dark"] [role="option"] {
        color: #FFFFFF !important;
        background-color: #2D3748 !important;
    }

    [data-theme="dark"] [data-baseweb="select"] li:hover,
    [data-theme="dark"] [role="option"]:hover {
        background-color: #4A5568 !important;
    }

    /* Streamlit native alerts in dark mode */
    [data-theme="dark"] .stAlert {
        background-color: var(--bg-secondary) !important;
        border-color: var(--border-color) !important;
    }

    [data-theme="dark"] .stAlert p,
    [data-theme="dark"] .stAlert div,
    [data-theme="dark"] .stAlert span {
        color: var(--text-primary) !important;
    }

    /* Info alerts (st.info) */
    [data-theme="dark"] [data-testid="stNotificationContentInfo"],
    [data-theme="dark"] .element-container:has([data-testid="stNotificationContentInfo"]) {
        background-color: rgba(99, 179, 237, 0.15) !important;
        border-left-color: #63B3ED !important;
    }

    [data-theme="dark"] [data-testid="stNotificationContentInfo"] *,
    [data-theme="dark"] [data-testid="stNotificationContentInfo"] p {
        color: #FFFFFF !important;
    }

    /* Success alerts (st.success) */
    [data-theme="dark"] [data-testid="stNotificationContentSuccess"],
    [data-theme="dark"] .element-container:has([data-testid="stNotificationContentSuccess"]) {
        background-color: rgba(104, 211, 145, 0.15) !important;
        border-left-color: #68D391 !important;
    }

    [data-theme="dark"] [data-testid="stNotificationContentSuccess"] *,
    [data-theme="dark"] [data-testid="stNotificationContentSuccess"] p {
        color: #FFFFFF !important;
    }

    /* Warning alerts (st.warning) */
    [data-theme="dark"] [data-testid="stNotificationContentWarning"],
    [data-theme="dark"] .element-container:has([data-testid="stNotificationContentWarning"]) {
        background-color: rgba(246, 173, 85, 0.15) !important;
        border-left-color: #F6AD55 !important;
    }

    [data-theme="dark"] [data-testid="stNotificationContentWarning"] *,
    [data-theme="dark"] [data-testid="stNotificationContentWarning"] p {
        color: #FFFFFF !important;
    }

    /* Error alerts (st.error) */
    [data-theme="dark"] [data-testid="stNotificationContentError"],
    [data-theme="dark"] .element-container:has([data-testid="stNotificationContentError"]) {
        background-color: rgba(252, 129, 129, 0.15) !important;
        border-left-color: #FC8181 !important;
    }

    [data-theme="dark"] [data-testid="stNotificationContentError"] *,
    [data-theme="dark"] [data-testid="stNotificationContentError"] p {
        color: #FFFFFF !important;
    }

    /* Inputs élégants */
    .stTextInput>div>div>input,
    .stTextArea>div>div>textarea,
    .stSelectbox>div>div>select {
        border: 2px solid var(--neutral-light);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        font-size: 0.95rem;
        transition: all 0.3s ease;
    }

    .stTextInput>div>div>input:focus,
    .stTextArea>div>div>textarea:focus,
    .stSelectbox>div>div>select:focus {
        border-color: var(--primary-blue);
        box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
        outline: none;
    }

    /* Checkbox et radio modernes */
    .stCheckbox>label {
        color: var(--neutral-dark);
        font-weight: 500;
        font-size: 0.95rem;
    }

    /* Expanders élégants */
    .streamlit-expanderHeader {
        background-color: var(--bg-blue);
        border-left: 4px solid var(--primary-blue);
        border-radius: 8px;
        font-weight: 600;
        color: var(--primary-navy);
        padding: 1rem 1.5rem;
        transition: all 0.3s ease;
    }

    .streamlit-expanderHeader:hover {
        background-color: var(--bg-white);
        border-left-color: var(--accent-cyan);
    }

    /* Tabs modernes */
    .stTabs [data-baseweb="tab-list"] {
        gap: 1rem;
        background-color: transparent;
        border-bottom: 2px solid var(--neutral-light);
    }

    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border: none;
        border-radius: 8px 8px 0 0;
        padding: 1rem 2rem;
        font-weight: 600;
        color: var(--neutral-medium);
        transition: all 0.3s ease;
    }

    .stTabs [data-baseweb="tab"]:hover {
        background-color: var(--bg-blue);
        color: var(--primary-blue);
    }

    .stTabs [aria-selected="true"] {
        background-color: var(--primary-blue);
        color: white;
    }

    /* Alerts professionnels */
    .stAlert {
        border-radius: 10px;
        border-left-width: 4px;
        padding: 1rem 1.5rem;
        font-weight: 500;
    }

    /* Metrics élégants */
    [data-testid="stMetricValue"] {
        font-size: 2.5rem;
        font-weight: 700;
        color: var(--primary-navy);
    }

    [data-testid="stMetricLabel"] {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--neutral-medium);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Progress bar */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, var(--primary-blue) 0%, var(--accent-cyan) 100%);
    }

    /* Dataframe professionnel */
    .dataframe {
        border: 1px solid var(--neutral-light);
        border-radius: 8px;
        font-size: 0.9rem;
    }

    /* Scrollbar personnalisée */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }

    ::-webkit-scrollbar-track {
        background: var(--bg-light);
    }

    ::-webkit-scrollbar-thumb {
        background: var(--neutral-light);
        border-radius: 5px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: var(--primary-blue);
    }

    /* Badge score */
    .score-badge {
        display: inline-block;
        background: linear-gradient(135deg, var(--primary-blue) 0%, var(--accent-cyan) 100%);
        color: white;
        padding: 0.5rem 1.25rem;
        border-radius: 50px;
        font-weight: 700;
        font-size: 1.1rem;
        box-shadow: 0 4px 10px rgba(74, 144, 226, 0.3);
    }

    /* Separateur élégant */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, var(--neutral-light) 50%, transparent 100%);
        margin: 2rem 0;
    }
</style>
<script>
    // Détecter et appliquer le thème Streamlit automatiquement
    function applyDarkMode() {
        const streamlitApp = window.parent.document.querySelector('[data-testid="stAppViewContainer"]');

        if (streamlitApp) {
            const bgColor = window.getComputedStyle(streamlitApp).backgroundColor;
            const rgb = bgColor.match(/\d+/g);
            if (rgb) {
                const brightness = (parseInt(rgb[0]) + parseInt(rgb[1]) + parseInt(rgb[2])) / 3;
                if (brightness < 128) {
                    document.documentElement.setAttribute('data-theme', 'dark');
                    window.parent.document.documentElement.setAttribute('data-theme', 'dark');
                } else {
                    document.documentElement.removeAttribute('data-theme');
                    window.parent.document.documentElement.removeAttribute('data-theme');
                }
            }
        }
    }

    // Appliquer au chargement et surveiller les changements
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyDarkMode);
    } else {
        applyDarkMode();
    }
    setInterval(applyDarkMode, 500);
</script>
""", unsafe_allow_html=True)


# ==================== HEADER AVEC LOGO ====================
st.markdown(f"""
<div class="brain-header">
    <img src="data:image/png;base64,{get_base64_image('logorhplus.png')}" class="brain-logo" alt="BRAIN RH+">
</div>
""", unsafe_allow_html=True)


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0; border-bottom: 2px solid var(--neutral-light);">
        <h2 style="color: var(--primary-navy); font-size: 1.3rem; margin: 0;">Configuration</h2>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Section Enrichissement
    st.markdown('<div class="section-header" style="font-size: 1.1rem;">Enrichissement</div>', unsafe_allow_html=True)

    # Toggle ROME
    rome_enabled = st.checkbox(
        "ROME (France Travail)",
        value=config.get("rome.enabled", False),
        help="Activer l'enrichissement des compétences via le référentiel ROME"
    )

    ia_enabled = st.checkbox(
        "Enrichissement IA",
        value=True,
        help="Activer l'enrichissement intelligent avec l'IA"
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Paramètres de scoring
    st.markdown('<div class="section-header" style="font-size: 1.1rem;">Scoring</div>', unsafe_allow_html=True)

    top_rerank = st.slider(
        "Top N (re-ranking final)",
        min_value=5,
        max_value=20,
        value=config.get("scoring.top_rerank", 10),
        step=1,
        help="Nombre de CVs à re-ranker avec LLM"
    )
    st.session_state['top_rerank'] = top_rerank

    st.markdown("---")

    # Informations
    st.subheader("Informations")
    st.caption(f"**Version:** 2.0")
    st.caption(f"**Embeddings:** {config.get('embeddings.model')}")
    st.caption(f"**ROME:** {'Activé' if rome_enabled else 'Désactivé'}")


# ==================== TABS ====================
tab1, tab2, tab3 = st.tabs(["1. Préparer l'offre", "2. Charger les CVs", "3. Matching"])


# ==================== TAB 1: PARSER L'OFFRE ====================
with tab1:
    st.markdown('<div class="section-header">Étape 1: Préparer l\'offre d\'emploi</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Saisir l'offre")

        # Option d'upload de fichier
        upload_method = st.radio(
            "Méthode de saisie:",
            ["Upload fichier (PDF/DOCX)", "Coller le texte"],
            horizontal=True
        )

        offre_text = ""

        if upload_method == "Upload fichier (PDF/DOCX)":
            uploaded_offre = st.file_uploader(
                "Uploadez l'offre d'emploi (PDF ou DOCX)",
                type=["pdf", "docx"],
                help="Formats supportés: PDF, DOCX"
            )

            if uploaded_offre:
                with st.spinner(f"Lecture de {uploaded_offre.name}..."):
                    try:
                        # Sauvegarder temporairement le fichier uploadé
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_offre.name) as tmp_file:
                            tmp_file.write(uploaded_offre.getvalue())
                            tmp_path = tmp_file.name

                        if uploaded_offre.name.endswith('.pdf'):
                            offre_text = parseur_cv.extract_text_from_pdf(tmp_path)
                        elif uploaded_offre.name.endswith('.docx'):
                            offre_text = parseur_cv.extract_text_from_docx(tmp_path)

                        # Nettoyer le fichier temporaire
                        os.unlink(tmp_path)

                        st.success(f"Fichier lu : {len(offre_text)} caractères")

                        # Afficher un aperçu
                        with st.expander("Aperçu du texte extrait"):
                            st.text(offre_text[:500] + "..." if len(offre_text) > 500 else offre_text)

                    except Exception as e:
                        st.error(f"Erreur lors de la lecture du fichier: {e}")
                        offre_text = ""
        else:
            offre_text = st.text_area(
                "Collez le texte de l'offre d'emploi ici:",
                height=300,
                placeholder="Exemple:\nTitre du poste : Data Scientist Junior\nExpérience requise : 1 an minimum\n..."
            )

        if st.button("Préparer l'offre", type="primary"):
            if not offre_text.strip():
                st.error("Veuillez saisir une offre d'emploi")
            else:
                with st.spinner("Parsing de l'offre en cours..."):
                    # Analyser avec OpenAI
                    from parseur_cv import PROMPT_JOB_EXTRACTION, analyze_text, clean_json_text

                    job_raw_result = analyze_text(offre_text, PROMPT_JOB_EXTRACTION)
                    job_cleaned = clean_json_text(job_raw_result)

                    try:
                        job_data = json.loads(job_cleaned)

                        # Enrichir avec ROME si activé
                        if rome_enabled and job_data.get("sections", {}).get("titre"):
                            st.info("Enrichissement via ROME en cours...")
                            titre_poste = job_data["sections"]["titre"]

                            try:
                                rome_competences = get_rome_competences(titre_poste)

                                nb_tech_avant = len(job_data["sections"]["competences_techniques"])
                                nb_trans_avant = len(job_data["sections"]["competences_transversales"])

                                if rome_competences.get("techniques"):
                                    # Éviter les doublons
                                    nouvelles_tech = [c for c in rome_competences["techniques"]
                                                     if c not in job_data["sections"]["competences_techniques"]]
                                    job_data["sections"]["competences_techniques"].extend(nouvelles_tech)

                                if rome_competences.get("transversales"):
                                    # Éviter les doublons
                                    nouvelles_trans = [c for c in rome_competences["transversales"]
                                                      if c not in job_data["sections"]["competences_transversales"]]
                                    job_data["sections"]["competences_transversales"].extend(nouvelles_trans)

                                nb_tech_apres = len(job_data["sections"]["competences_techniques"])
                                nb_trans_apres = len(job_data["sections"]["competences_transversales"])

                                nb_tech_ajoutees = nb_tech_apres - nb_tech_avant
                                nb_trans_ajoutees = nb_trans_apres - nb_trans_avant

                                if nb_tech_ajoutees > 0 or nb_trans_ajoutees > 0:
                                    st.success(f"Ajouté {nb_tech_ajoutees} compétences techniques et {nb_trans_ajoutees} transversales via ROME")
                                else:
                                    st.info("ROME activé : aucune compétence supplémentaire ajoutée (toutes déjà présentes ou API non disponible)")
                            except Exception as e:
                                st.warning(f"Enrichissement ROME échoué : {str(e)}")
                                st.info("Continuation sans ROME...")

                        # Mapper vers le format standardisé
                        job_data_normalized = map_offre_to_sections(job_data)

                        # Sauvegarder
                        offre_output_folder = Path(config.get("paths.offres_folder", "offres"))
                        offre_output_folder.mkdir(parents=True, exist_ok=True)
                        offre_path = offre_output_folder / "offre_parsed.json"

                        with open(offre_path, "w", encoding="utf-8") as f:
                            json.dump(job_data_normalized, f, ensure_ascii=False, indent=4)

                        st.success(f"Offre parsée et sauvegardée dans {offre_path}")

                        # Stocker dans session state
                        st.session_state['offre_data'] = job_data_normalized
                        st.session_state['offre_text'] = offre_text

                    except json.JSONDecodeError as e:
                        st.error(f"Erreur JSON: {e}")

    with col2:
        st.subheader("Aperçu de l'offre")

        if 'offre_data' in st.session_state:
            # Initialiser l'historique d'enrichissement si besoin
            if 'enrichment_history' not in st.session_state:
                st.session_state['enrichment_history'] = {
                    'rome': [],
                    'ia': []
                }

            offre = st.session_state['offre_data']['sections']

            # Afficher l'offre avec code couleur
            st.markdown("""
            <style>
            .element-parsed { color: #1f2937; font-weight: 500; }
            .element-rome { color: #2563eb; font-weight: 500; }
            .element-ia { color: #059669; font-weight: 500; }
            .legend { display: flex; gap: 20px; margin-bottom: 15px; font-size: 0.85em; }
            .legend-item { display: flex; align-items: center; gap: 5px; }
            .legend-color { width: 12px; height: 12px; border-radius: 2px; }
            </style>

            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color" style="background: #1f2937;"></div>
                    <span>Parsé</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #2563eb;"></div>
                    <span>ROME</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #059669;"></div>
                    <span>IA</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Afficher JSON avec scrolling
            with st.container(height=500):
                st.json(st.session_state['offre_data'])

            # Télécharger l'offre et sauvegarder dans le projet
            col_download, col_save = st.columns(2)

            with col_download:
                st.download_button(
                    label="Télécharger l'offre (JSON)",
                    data=json.dumps(st.session_state['offre_data'], ensure_ascii=False, indent=4),
                    file_name="offre_parsed.json",
                    mime="application/json"
                )

            with col_save:
                if st.button("Sauvegarder dans le projet", use_container_width=True):
                    pm.save_offer(current_project_id, st.session_state['offre_data'])
                    projet = pm.get_project(current_project_id)
                    st.success(f"Offre sauvegardée dans le projet '{projet['nom']}'")
                    st.rerun()

            # ==== BLOC ENRICHISSEMENT ====
            # Afficher seulement si au moins un enrichissement est activé dans la sidebar
            if rome_enabled or ia_enabled:
                st.markdown("---")
                st.subheader("Enrichissement")
                st.info("Les enrichissements sont activés/désactivés via les cases à cocher dans la barre latérale gauche")

                # Tabs pour ROME et IA
                tab_rome, tab_ia = st.tabs(["ROME", "IA"])

                # ===== TAB ROME =====
                with tab_rome:
                    st.info("Enrichir avec le référentiel ROME (France Travail)")

                    if rome_enabled:
                        titre_poste = offre.get('titre', '')
                        if st.button("Enrichir avec ROME"):
                            if not titre_poste:
                                st.error("Titre du poste manquant")
                            else:
                                with st.spinner("Consultation ROME..."):
                                    try:
                                        rome_competences = get_rome_competences(titre_poste)

                                        if rome_competences.get("techniques") or rome_competences.get("transversales"):
                                            st.success(f"Compétences ROME trouvées!")

                                            # Afficher les propositions ROME
                                            st.markdown("**Compétences Techniques:**")
                                            rome_tech_selections = []
                                            for idx, comp in enumerate(rome_competences.get("techniques", [])):
                                                if comp not in offre.get('competences_techniques', []):
                                                    if st.checkbox(f"{comp}", key=f"rome_tech_{idx}"):
                                                        rome_tech_selections.append(comp)

                                            st.markdown("**Compétences Transversales:**")
                                            rome_trans_selections = []
                                            for idx, comp in enumerate(rome_competences.get("transversales", [])):
                                                if comp not in offre.get('competences_transversales', []):
                                                    if st.checkbox(f"{comp}", key=f"rome_trans_{idx}"):
                                                        rome_trans_selections.append(comp)

                                            if st.button("Appliquer ROME", type="primary"):
                                                # Ajouter les compétences sélectionnées
                                                if 'competences_techniques' not in offre:
                                                    offre['competences_techniques'] = []
                                                if 'competences_transversales' not in offre:
                                                    offre['competences_transversales'] = []

                                                offre['competences_techniques'].extend(rome_tech_selections)
                                                offre['competences_transversales'].extend(rome_trans_selections)

                                                # Tracker dans l'historique
                                                st.session_state['enrichment_history']['rome'].extend(rome_tech_selections)
                                                st.session_state['enrichment_history']['rome'].extend(rome_trans_selections)

                                                st.session_state['offre_data']['sections'] = offre
                                                st.success(f"{len(rome_tech_selections) + len(rome_trans_selections)} compétences ROME ajoutées!")
                                                st.rerun()

                                        else:
                                            st.info("Aucune compétence ROME trouvée pour ce poste")

                                    except Exception as e:
                                        st.error(f"Erreur ROME: {e}")
                    else:
                        st.warning("ROME désactivé dans la configuration")

                # ===== TAB IA =====
                with tab_ia:
                    st.info("Enrichir avec l'Intelligence Artificielle")

                    metier_label = st.text_input(
                        "Libellé du métier cible:",
                        value=offre.get('titre', ''),
                        help="Ex: Développeur Python, Data Scientist, etc.",
                        key="ia_metier_label"
                    )

                    if st.button("Enrichir avec IA", type="primary"):
                        if not metier_label.strip():
                            st.error("Veuillez saisir un libellé de métier")
                        else:
                            with st.spinner("Génération des propositions IA..."):
                                try:
                                    # Appel async dans contexte Streamlit
                                    enrichment_result = asyncio.run(
                                        enrich_offer_intelligently(
                                            st.session_state['offre_data'],
                                            metier_label
                                        )
                                    )

                                    st.session_state['enrichment_result'] = enrichment_result
                                    st.success(f"Enrichissement terminé (score de complétude: {enrichment_result['coverage_score']}%)")
                                    st.rerun()

                                except Exception as e:
                                    st.error(f"Erreur lors de l'enrichissement: {e}")

                    # Afficher les propositions si disponibles
                    if 'enrichment_result' in st.session_state:
                        enrichment = st.session_state['enrichment_result']
                        propositions = enrichment['propositions']

                        st.markdown("---")
                        st.markdown(f"### 📋 Propositions IA (Complétude: {enrichment['coverage_score']}%)")

                        # Initialiser les sélections si pas déjà fait
                        if 'enrichment_selections' not in st.session_state:
                            st.session_state['enrichment_selections'] = {
                                'competences': [],
                                'outils': [],
                                'langages': [],
                                'certifications': [],
                                'missions': []
                            }

                        selections = st.session_state['enrichment_selections']

                        # Compétences
                        if propositions['competences']:
                            st.markdown("#### Compétences Techniques")
                            for idx, comp in enumerate(propositions['competences']):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**{comp['name']}** ({comp['type']})")
                                    st.caption(comp['rationale'])
                                with col2:
                                    if st.checkbox("Accepter", key=f"comp_{idx}"):
                                        if idx not in selections['competences']:
                                            selections['competences'].append(idx)
                                    elif idx in selections['competences']:
                                        selections['competences'].remove(idx)

                        # Outils
                        if propositions['outils']:
                            st.markdown("#### Outils")
                            for idx, outil in enumerate(propositions['outils']):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**{outil['name']}**")
                                    st.caption(outil['rationale'])
                                with col2:
                                    if st.checkbox("Accepter", key=f"outil_{idx}"):
                                        if idx not in selections['outils']:
                                            selections['outils'].append(idx)
                                    elif idx in selections['outils']:
                                        selections['outils'].remove(idx)

                        # Langages
                        if propositions['langages']:
                            st.markdown("#### Langages de Programmation")
                            for idx, lang in enumerate(propositions['langages']):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**{lang['name']}**")
                                    st.caption(lang['rationale'])
                                with col2:
                                    if st.checkbox("Accepter", key=f"lang_{idx}"):
                                        if idx not in selections['langages']:
                                            selections['langages'].append(idx)
                                    elif idx in selections['langages']:
                                        selections['langages'].remove(idx)

                        # Certifications
                        if propositions['certifications']:
                            st.markdown("#### Certifications")
                            for idx, cert in enumerate(propositions['certifications']):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**{cert['name']}**")
                                    st.caption(cert['rationale'])
                                with col2:
                                    if st.checkbox("Accepter", key=f"cert_{idx}"):
                                        if idx not in selections['certifications']:
                                            selections['certifications'].append(idx)
                                    elif idx in selections['certifications']:
                                        selections['certifications'].remove(idx)

                        # Missions
                        if propositions['missions']:
                            st.markdown("#### Missions Complémentaires")
                            for idx, mission in enumerate(propositions['missions']):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**{mission['text']}**")
                                    st.caption(mission['rationale'])
                                with col2:
                                    if st.checkbox("Accepter", key=f"mission_{idx}"):
                                        if idx not in selections['missions']:
                                            selections['missions'].append(idx)
                                    elif idx in selections['missions']:
                                        selections['missions'].remove(idx)

                        # Questions de clarification avec champs de réponse
                        if propositions['questions_clarification']:
                            st.markdown("#### 💬 Questions de Clarification")
                            st.markdown("*Répondez à ces questions pour enrichir automatiquement l'offre. Vos réponses seront ajoutées dans une section `informations_complementaires` du JSON.*")

                            # Initialiser le dictionnaire de réponses dans session_state
                            if 'questions_responses' not in st.session_state:
                                st.session_state['questions_responses'] = {}

                            # Afficher chaque question avec un champ de réponse
                            for idx, question in enumerate(propositions['questions_clarification']):
                                st.markdown(f"**Question {idx+1}:** {question}")
                                response_key = f"question_response_{idx}"
                                response = st.text_input(
                                    "Votre réponse :",
                                    key=response_key,
                                    placeholder="Tapez votre réponse ici...",
                                    label_visibility="collapsed"
                                )
                                # Stocker la réponse dans session_state
                                if response:
                                    st.session_state['questions_responses'][question] = response
                                st.markdown("---")

                            # Afficher un résumé des réponses en cours
                            if st.session_state.get('questions_responses'):
                                nb_reponses = len(st.session_state['questions_responses'])
                                st.info(f"📝 {nb_reponses} réponse(s) prête(s) à être intégrée(s)")

                                # Montrer un aperçu des réponses
                                with st.expander("👁️ Aperçu des réponses"):
                                    for question, response in st.session_state['questions_responses'].items():
                                        st.markdown(f"**Q:** {question}")
                                        st.markdown(f"**R:** {response}")
                                        st.markdown("---")

                        # Fusionner les sélections
                        st.markdown("---")
                        if st.button("Appliquer les sélections", type="primary"):
                            try:
                                # 1. Fusionner les enrichissements sélectionnés
                                offre_enrichie = merge_enrichment(
                                    st.session_state['offre_data'],
                                    enrichment,
                                    selections
                                )

                                # 2. Intégrer les réponses aux questions de clarification
                                if st.session_state.get('questions_responses'):
                                    from offer_enrichment import integrate_question_responses
                                    offre_enrichie = integrate_question_responses(
                                        offre_enrichie,
                                        st.session_state['questions_responses']
                                    )
                                    st.success(f"✅ {len(st.session_state['questions_responses'])} réponse(s) intégrée(s) dans l'offre")

                                # Tracker les éléments ajoutés dans l'historique
                                if 'enrichment_history' not in st.session_state:
                                    st.session_state['enrichment_history'] = {'rome': [], 'ia': []}

                                for idx in selections.get('competences', []):
                                    comp_name = propositions['competences'][idx]['name']
                                    if comp_name not in st.session_state['enrichment_history']['ia']:
                                        st.session_state['enrichment_history']['ia'].append(comp_name)

                                for idx in selections.get('outils', []):
                                    outil_name = propositions['outils'][idx]['name']
                                    if outil_name not in st.session_state['enrichment_history']['ia']:
                                        st.session_state['enrichment_history']['ia'].append(outil_name)

                                for idx in selections.get('langages', []):
                                    lang_name = propositions['langages'][idx]['name']
                                    if lang_name not in st.session_state['enrichment_history']['ia']:
                                        st.session_state['enrichment_history']['ia'].append(lang_name)

                                for idx in selections.get('certifications', []):
                                    cert_name = propositions['certifications'][idx]['name']
                                    if cert_name not in st.session_state['enrichment_history']['ia']:
                                        st.session_state['enrichment_history']['ia'].append(cert_name)

                                for idx in selections.get('missions', []):
                                    mission_text = propositions['missions'][idx]['text']
                                    if mission_text not in st.session_state['enrichment_history']['ia']:
                                        st.session_state['enrichment_history']['ia'].append(mission_text)

                                # Sauvegarder
                                offre_output_folder = Path(config.get("paths.offres_folder", "offres"))
                                offre_path = offre_output_folder / "offre_parsed_enriched.json"

                                with open(offre_path, "w", encoding="utf-8") as f:
                                    json.dump(offre_enrichie, f, ensure_ascii=False, indent=4)

                                # Mettre à jour session state
                                st.session_state['offre_data'] = offre_enrichie

                                # Nettoyer les réponses après application
                                st.session_state['questions_responses'] = {}

                                st.success(f"Offre enrichie sauvegardée : {offre_path}")

                                total_added = (
                                    len(selections.get('competences', [])) +
                                    len(selections.get('outils', [])) +
                                    len(selections.get('langages', [])) +
                                    len(selections.get('certifications', [])) +
                                    len(selections.get('missions', []))
                                )

                                st.info(f"**{total_added} éléments ajoutés:** {len(selections.get('competences', []))} compétences, {len(selections.get('outils', []))} outils, {len(selections.get('langages', []))} langages, {len(selections.get('certifications', []))} certifications, {len(selections.get('missions', []))} missions")

                                # Log dans SUIVI_PROJET.md
                                suivi_path = Path("SUIVI_PROJET.md")
                                if suivi_path.exists():
                                    with open(suivi_path, 'a', encoding='utf-8') as f:
                                        f.write(f"\n\n#### Enrichissement du {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                                        f.write(f"- **Métier:** {metier_label}\n")
                                        f.write(f"- **Coverage score:** {enrichment['coverage_score']}%\n")
                                        f.write(f"- **Compétences acceptées:** {len(selections['competences'])}\n")
                                        f.write(f"- **Outils acceptés:** {len(selections['outils'])}\n")
                                        f.write(f"- **Langages acceptés:** {len(selections['langages'])}\n")
                                        f.write(f"- **Certifications acceptées:** {len(selections['certifications'])}\n")
                                        f.write(f"- **Missions acceptées:** {len(selections['missions'])}\n")

                            except Exception as e:
                                st.error(f"Erreur lors de la fusion: {e}")
        else:
            st.info("Parsez d'abord une offre pour voir l'enrichissement intelligent")


# ==================== TAB 2: PARSER LES CVS ====================
with tab2:
    st.markdown('<div class="section-header">Étape 2: Charger les CVs</div>', unsafe_allow_html=True)

    st.info("Uploadez vos CVs (PDF ou DOCX)")

    uploaded_files = st.file_uploader(
        "Choisissez des fichiers CV",
        type=["pdf", "docx"],
        accept_multiple_files=True
    )

    if uploaded_files:
        st.write(f"{len(uploaded_files)} fichier(s) uploadé(s)")

        # Mode parallèle automatique avec lots de 500 max

        if st.button("Charger et analyser les CVs", type="primary"):
            cv_input_folder = Path(config.get("paths.cv_input_folder", "cv_input"))
            cv_json_folder = Path(config.get("paths.cv_json_folder", "cv_json"))

            cv_input_folder.mkdir(parents=True, exist_ok=True)
            cv_json_folder.mkdir(parents=True, exist_ok=True)

            # Sauvegarder les fichiers uploadés
            cv_file_paths = []
            for uploaded_file in uploaded_files:
                file_path = cv_input_folder / uploaded_file.name
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                cv_file_paths.append(file_path)

            # MODE PARALLÈLE AUTOMATIQUE avec lots de 500 max
            total_cvs = len(cv_file_paths)
            max_concurrent = min(total_cvs, 500)  # Max 500 CVs en simultané

            # Créer une barre de progression
            progress_bar = st.progress(0)
            progress_text = st.empty()
            progress_text.text(f" Parsing parallèle : 0/{total_cvs} CVs traités...")

            def update_progress(completed, total):
                """Callback de progression pour mettre à jour la barre"""
                progress = completed / total if total > 0 else 0
                progress_bar.progress(progress)
                progress_text.text(f" Parsing parallèle : {completed}/{total} CVs traités... ({int(progress * 100)}%)")

            try:
                results = parse_cvs_parallel_sync(
                    cv_files=cv_file_paths,
                    model=config.get_llm_model(),
                    concurrency=max_concurrent,
                    qps=100.0,
                    progress_callback=update_progress
                )

                # Nettoyer la barre de progression
                progress_bar.empty()
                progress_text.empty()

                st.success(f"✅ {results['success_count']}/{results['total']} CVs parsés avec succès")

                # Sauvegarder les CVs parsés en JSON
                cv_json_folder.mkdir(exist_ok=True)
                saved_files = []
                for result in results['results']:
                    if result.success and result.data:
                        # Convertir dataclass en dict
                        cv_dict = {
                            'cv': result.data.cv,
                            'nom': result.data.nom,
                            'prenom': result.data.prenom,
                            'email': result.data.email,
                            'telephone': result.data.telephone,
                            'ville': result.data.ville,
                            'synthese': result.data.synthese,
                            'competences_techniques': result.data.competences_techniques,
                            'langues': result.data.langues,
                            'certifications': result.data.certifications,
                            'experiences': result.data.experiences,
                            'formations': result.data.formations,
                        }
                        json_path = cv_json_folder / f"{Path(result.filename).stem}.json"
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(cv_dict, f, ensure_ascii=False, indent=2)
                        saved_files.append(str(json_path))

                if results['failed_count'] > 0:
                    st.warning(f"⚠️ {results['failed_count']} CVs ont échoué")

                    # Afficher les erreurs en détail
                    with st.expander("Voir les erreurs"):
                        for result in results['results']:
                            if not result.success:
                                st.error(f"{result.filename}: {result.error}")

                # Afficher les statistiques de temps
                if 'timings' in results:
                    with st.expander(" Statistiques de performance"):
                        timings = results['timings']
                        st.metric("⏱ Temps total", f"{timings['total']:.1f}s")
                        if 'peak_inflight' in timings:
                            st.metric("⚡ Pic d'appels API simultanés", timings['peak_inflight'])

                # Stocker dans session state
                st.session_state['parsed_cvs'] = saved_files

            except Exception as e:
                # Nettoyer la barre de progression en cas d'erreur
                progress_bar.empty()
                progress_text.empty()
                
                st.error(f"❌ Erreur lors du parsing parallèle: {e}")
                import traceback
                st.code(traceback.format_exc())

    # Afficher les CVs parsés
    st.markdown("---")
    st.subheader("CVs Parsés Disponibles")

    cv_json_folder = Path(config.get("paths.cv_json_folder", "cv_json"))
    if cv_json_folder.exists():
        cv_files = list(cv_json_folder.glob("*.json"))

        if cv_files:
            st.info(f"{len(cv_files)} CV(s) parsé(s) disponible(s)")

            # Sélecteur de CV pour affichage
            selected_cv = st.selectbox(
                "Sélectionnez un CV pour voir les détails:",
                options=[cv.name for cv in cv_files],
                key="cv_selector"
            )

            if selected_cv:
                cv_path = cv_json_folder / selected_cv
                with open(cv_path, 'r', encoding='utf-8') as f:
                    cv_data = json.load(f)

                # Normaliser la structure si nécessaire
                if 'sections' not in cv_data:
                    cv_data_normalized = {"sections": cv_data}
                else:
                    cv_data_normalized = cv_data

                # Afficher dans un expander
                with st.expander(f"Détails de {selected_cv}", expanded=True):
                    sections = cv_data_normalized.get('sections', {})

                    # Titre et résumé
                    if sections.get('titre'):
                        st.markdown(f"### {sections['titre']}")

                    if sections.get('resume_professionnel'):
                        st.markdown(f"**Résumé:** {sections['resume_professionnel']}")

                    col1, col2 = st.columns(2)

                    with col1:
                        # Compétences techniques
                        if sections.get('competences_techniques'):
                            st.markdown("**Compétences Techniques:**")
                            for comp in sections['competences_techniques']:
                                st.markdown(f"- {comp}")

                        # Langues
                        if sections.get('langues'):
                            st.markdown("**Langues:**")
                            for lang in sections['langues']:
                                st.markdown(f"- {lang}")

                    with col2:
                        # Compétences transversales
                        if sections.get('competences_transversales'):
                            st.markdown("**Compétences Transversales:**")
                            for comp in sections['competences_transversales']:
                                st.markdown(f"- {comp}")

                        # Certifications
                        if sections.get('certifications'):
                            st.markdown("**Certifications:**")
                            for cert in sections['certifications']:
                                st.markdown(f"- {cert}")

                    # Expériences
                    if sections.get('experiences_professionnelles'):
                        st.markdown("**Expériences Professionnelles:**")
                        for exp in sections['experiences_professionnelles']:
                            poste = exp.get('poste', 'Poste non spécifié')
                            entreprise = exp.get('entreprise', '')
                            duree = exp.get('duree', '')
                            description = exp.get('description', '')

                            exp_text = f"- **{poste}**"
                            if entreprise:
                                exp_text += f" chez {entreprise}"
                            if duree:
                                exp_text += f" ({duree})"
                            st.markdown(exp_text)
                            if description:
                                st.markdown(f"  _{description}_")

                    # Formations
                    if sections.get('formations'):
                        st.markdown("**Formations:**")
                        for form in sections['formations']:
                            diplome = form.get('diplome', 'Diplôme non spécifié')
                            etablissement = form.get('etablissement', '')
                            annee = form.get('annee', '')

                            form_text = f"- **{diplome}**"
                            if etablissement:
                                form_text += f" - {etablissement}"
                            if annee:
                                form_text += f" ({annee})"
                            st.markdown(form_text)

                # JSON brut en option (HORS de l'expander principal)
                with st.expander("Voir le JSON brut"):
                    st.json(cv_data_normalized)

                # Bouton de téléchargement
                st.download_button(
                    label=f"Télécharger {selected_cv}",
                    data=json.dumps(cv_data_normalized, ensure_ascii=False, indent=4),
                    file_name=selected_cv,
                    mime="application/json"
                )
        else:
            st.warning("Aucun CV parsé trouvé. Uploadez et parsez des CVs ci-dessus.")
    else:
        st.warning("Le dossier cv_json n'existe pas encore. Parsez d'abord des CVs.")


# ==================== TAB 3: MATCHING ====================
with tab3:
    st.markdown('<div class="section-header">Étape 3: Matching CV/Offre</div>', unsafe_allow_html=True)

    # Bouton historique en haut
    col_header1, col_header2 = st.columns([4, 1])
    with col_header2:
        if st.button("Historique", use_container_width=True):
            st.session_state['show_history'] = not st.session_state.get('show_history', False)

    # Afficher l'historique si demandé
    if st.session_state.get('show_history', False):
        st.markdown("---")
        st.subheader("Historique des Matchings")

        matchings = pm.list_matchings(current_project_id)

        if not matchings:
            st.info("Aucun matching enregistré pour ce projet")
        else:
            for matching in matchings:
                timestamp = matching['timestamp']
                candidats_count = matching['candidats_count']

                # Formatter le timestamp
                try:
                    dt = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
                    date_str = dt.strftime("%d/%m/%Y à %H:%M")
                except:
                    date_str = timestamp

                col_m1, col_m2 = st.columns([3, 1])

                with col_m1:
                    st.markdown(f"**{date_str}** - {candidats_count} candidat(s)")

                with col_m2:
                    if st.button("Charger", key=f"load_{timestamp}", use_container_width=True):
                        # Charger le matching
                        matching_data = pm.load_matching(current_project_id, timestamp)
                        if matching_data:
                            st.session_state['scored_cvs'] = matching_data.get('scored_cvs', [])
                            st.session_state['reranked_cvs'] = matching_data.get('reranked_cvs', [])
                            st.session_state['show_history'] = False
                            st.success(f"Matching du {date_str} chargé")
                            st.rerun()

        st.markdown("---")

    # Vérifier que l'offre et les CVs sont prêts
    if 'offre_data' not in st.session_state:
        st.warning("Veuillez d'abord préparer une offre (Onglet 1)")
        st.stop()

    # Charger les CVs parsés
    cv_json_folder = Path(config.get("paths.cv_json_folder", "cv_json"))
    cv_files = list(cv_json_folder.glob("*.json"))

    if not cv_files:
        st.warning("Aucun CV chargé. Veuillez d'abord charger des CVs (Onglet 2)")
        st.stop()

    st.info(f"{len(cv_files)} CV(s) disponibles pour le matching")

    # ==== ÉTAPE 1: Définir les critères ====
    st.subheader("1. Définir les critères")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("**Extraction automatique par IA:**")
        if st.button("Extraire les critères avec IA"):
            with st.spinner("Extraction en cours..."):
                job_text = st.session_state.get('offre_text', '')
                must_haves = matching_engine.extract_must_have_with_llm(job_text)
                st.session_state['criteres_auto'] = must_haves
                st.success(f"{len(must_haves)} critères extraits")

    with col2:
        st.markdown("**Saisie manuelle:**")
        manual_criteres = st.text_area(
            "Ajoutez vos propres critères (un par ligne):",
            height=150,
            placeholder="Python\n3 ans d'expérience\nBac+5\n...",
            key="manual_criteres_input"
        )

        if st.button("Ajouter critères manuels"):
            if manual_criteres.strip():
                manual_list = [line.strip() for line in manual_criteres.split("\n") if line.strip()]
                if 'criteres_manual' not in st.session_state:
                    st.session_state['criteres_manual'] = []
                st.session_state['criteres_manual'].extend(manual_list)
                st.success(f"{len(manual_list)} critères ajoutés")

    # Fusionner tous les critères (auto + manuels)
    criteres_auto = st.session_state.get('criteres_auto', [])
    criteres_manual = st.session_state.get('criteres_manual', [])
    all_criteres = criteres_auto + criteres_manual

    # Sélection des must-have et nice-to-have
    st.markdown("---")
    st.subheader("2. Classifier les critères")

    if all_criteres:
        st.markdown("**Classifiez chaque critère:**")
        st.caption("Must-have = éliminatoire | Nice-to-have = malus si manquant | N/A = ignoré")

        # Initialiser les sélections (format nouveau : dict {critere_idx: "NA"|"Must-have"|"Nice-to-have"})
        if 'critere_classification' not in st.session_state:
            st.session_state['critere_classification'] = {}

        for i, critere in enumerate(all_criteres):
            col_label, col_select = st.columns([3, 1])

            # Déterminer la source et valeur par défaut
            is_manual = critere in criteres_manual

            # Valeur par défaut: Must-have si manuel, N/A si IA
            if i not in st.session_state['critere_classification']:
                st.session_state['critere_classification'][i] = "Must-have" if is_manual else "N/A"

            with col_label:
                source_badge = "[Manuel]" if is_manual else "[IA]"
                st.write(f"{source_badge} {critere}")

            with col_select:
                select_key = f"select_{i}"
                selected = st.selectbox(
                    "Type",
                    options=["N/A", "Must-have", "Nice-to-have"],
                    index=["N/A", "Must-have", "Nice-to-have"].index(st.session_state['critere_classification'][i]),
                    key=select_key,
                    label_visibility="collapsed"
                )
                st.session_state['critere_classification'][i] = selected

        # Calculer les listes finales
        indispensables = [
            all_criteres[i] for i in range(len(all_criteres))
            if st.session_state['critere_classification'].get(i) == "Must-have"
        ]
        nice_have = [
            all_criteres[i] for i in range(len(all_criteres))
            if st.session_state['critere_classification'].get(i) == "Nice-to-have"
        ]

        # Stocker dans session_state
        st.session_state['indispensables'] = indispensables
        st.session_state['nice_have'] = nice_have

        st.markdown("---")
        if indispensables:
            st.success(f"**{len(indispensables)} Must-have éliminatoires:** {', '.join(indispensables)}")
        else:
            st.warning("Aucun must-have sélectionné → Tous les CVs seront acceptés")

        if nice_have:
            st.info(f"**{len(nice_have)} Nice-to-have (malus si manquant):** {', '.join(nice_have)}")
    else:
        st.warning("Aucun critère défini. Utilisez l'extraction IA ou la saisie manuelle.")

    # ==== ÉTAPE 2: Lancer le matching ====
    st.markdown("---")
    st.subheader("3. Lancer le matching")

    if st.button("LANCER LE MATCHING", type="primary"):
        indispensables = st.session_state.get('indispensables', [])
        nice_have = st.session_state.get('nice_have', [])

        if not indispensables:
            st.error("Veuillez sélectionner au moins un critère indispensable")
            st.stop()

        # Charger tous les CVs
        all_cvs = []
        for cv_file in cv_files:
            with open(cv_file, 'r', encoding='utf-8') as f:
                cv_data = json.load(f)

                # Normaliser la structure: si pas de wrapper "sections", l'ajouter
                if 'sections' not in cv_data:
                    # Le CV a une structure plate, créer le wrapper
                    cv_data = {"sections": cv_data}

                cv_data['cv'] = cv_file.name
                all_cvs.append(cv_data)

        # Flatten offre
        offre = st.session_state['offre_data']['sections']
        job_text = " ".join([
            str(v) for v in offre.values() if v
        ])

        # === CONFIGURATION MATCHING ===
        # st.markdown("### Configuration du matching")  # Masqué pendant le matching

        # Mode parallèle automatique
        use_parallel = True
        concurrency = min(len(all_cvs), 500)

        st.markdown("### Progression du matching")

        # === ÉTAPE 1: Filtrage must-have ===
        progress_placeholder = st.empty()
        total_cvs = len(all_cvs)
        progress_placeholder.progress(0.0, text=f"Filtrage must-have: 0/{total_cvs} CVs traités")

        # Callback de progression
        def update_progress_must_have(current, total):
            progress = current / total if total > 0 else 0
            progress_placeholder.progress(progress, text=f"Filtrage must-have: {current}/{total} CVs traités")

        # Appel de la méthode avec ou sans parallélisation
        filtered_cvs = matching_engine.filter_cvs_by_must_have(
            all_cvs,
            indispensables,
            job_text,
            use_parallel=use_parallel,
            progress_callback=update_progress_must_have
        )

        progress_placeholder.progress(1.0, text=f"Filtrage must-have terminé: {len(filtered_cvs)}/{total_cvs} CVs acceptés")
        st.success(f"{len(filtered_cvs)} CVs acceptés après filtrage must-have")

        if not filtered_cvs:
            st.error("Aucun CV ne satisfait les critères indispensables")
            st.stop()

        # === ÉTAPE 2: Calcul de similarité ===
        progress_placeholder2 = st.empty()
        progress_placeholder2.progress(0.0, text=f"Scoring: 0/{len(filtered_cvs)} CVs traités")

        scored_cvs = matching_engine.compute_similarity_with_scoring(
            job_text,
            filtered_cvs,
            nice_have,
            job_text,
            progress_callback=lambda current, total: progress_placeholder2.progress(
                current / total,
                text=f"Scoring: {current}/{total} CVs traités"
            )
        )

        progress_placeholder2.progress(1.0, text=f"Scoring terminé: {len(scored_cvs)} CVs scorés")

        if not scored_cvs:
            st.error("Aucun CV après le calcul de similarité. Le filtre must-have est peut-être trop strict.")
            st.stop()

        st.success(f"Top-{len(scored_cvs)} CVs calculés")

        # === ÉTAPE 3: Re-ranking LLM ===
        progress_placeholder3 = st.empty()
        top_rerank = min(len(scored_cvs), st.session_state.get('top_rerank', 10))
        progress_placeholder3.progress(0.0, text=f"Re-ranking: 0/{top_rerank} CVs traités")

        reranked_cvs = matching_engine.rerank_with_llm(
            scored_cvs[:top_rerank],
            job_text,
            progress_callback=lambda current, total: progress_placeholder3.progress(
                current / total,
                text=f"Re-ranking: {current}/{total} CVs traités"
            )
        )

        progress_placeholder3.progress(1.0, text=f"Re-ranking terminé: {len(reranked_cvs)} CVs classés")
        st.success("Matching terminé!")

        # Logs de débogage
        st.info(f"Résultats : {len(scored_cvs)} CVs scorés, {len(reranked_cvs)} CVs re-rankés")

        # Stocker les résultats
        st.session_state['scored_cvs'] = scored_cvs
        st.session_state['reranked_cvs'] = reranked_cvs

        # Sauvegarder les résultats dans le projet
        matching_results = {
            "scored_cvs": scored_cvs,
            "reranked_cvs": reranked_cvs if isinstance(reranked_cvs, list) else reranked_cvs.get('ranked_cvs', []),
            "indispensables": indispensables,
            "nice_have": nice_have,
            "total_cvs": total_cvs,
            "filtered_count": len(filtered_cvs),
            "scored_count": len(scored_cvs),
            "reranked_count": len(reranked_cvs) if isinstance(reranked_cvs, list) else len(reranked_cvs.get('ranked_cvs', []))
        }
        timestamp = pm.save_matching_result(current_project_id, matching_results)
        st.info(f"Résultats sauvegardés dans le projet (ID: {timestamp})")

    # ==== AFFICHAGE DES RÉSULTATS ====
    if 'reranked_cvs' in st.session_state:
        st.markdown("---")
        st.subheader("Résultats du Matching")

        reranked = st.session_state['reranked_cvs']
        scored = st.session_state['scored_cvs']

        # Si reranked est un dict avec clé "ranked_cvs" (format V2)
        if isinstance(reranked, dict) and 'ranked_cvs' in reranked:
            reranked = reranked['ranked_cvs']

        # Si reranked n'est pas une liste, le convertir
        if not isinstance(reranked, list):
            st.error(f"Format de re-ranking invalide: {type(reranked)}")
            st.stop()

        # Créer un mapping pour les scores avec TOUTES les variantes possibles
        score_map = {}
        score_list = []  # Pour fuzzy matching

        for s in scored:
            key_original = s.get('cv') or s.get('cv_id')
            if not key_original:
                continue

            # Stocker pour fuzzy matching
            score_list.append((key_original, s))

            # Variante 1: Original
            score_map[key_original] = s

            # Variante 2: Sans extension
            key_no_ext = key_original.replace('.json', '').replace('.pdf', '')
            score_map[key_no_ext] = s

            # Variante 3: Sans extension + trim spéciaux
            key_clean = key_no_ext.strip().rstrip('.-_ ')
            score_map[key_clean] = s

            # Variante 4: Lowercase pour case-insensitive
            score_map[key_original.lower()] = s
            score_map[key_no_ext.lower()] = s
            score_map[key_clean.lower()] = s

        # Fonction de matching fuzzy
        def find_best_match(cv_name_search):
            """Trouve le meilleur match pour un nom de CV"""
            # Essai 1: Match exact sur toutes les variantes
            for variant in [
                cv_name_search,
                cv_name_search.replace('.json', '').replace('.pdf', ''),
                cv_name_search.strip().rstrip('.-_ '),
                cv_name_search.lower()
            ]:
                if variant in score_map:
                    return score_map[variant]

            # Essai 2: Fuzzy matching (chercher une substring)
            search_clean = cv_name_search.replace('.json', '').replace('.pdf', '').strip().rstrip('.-_ ').lower()

            for key_orig, score_data in score_list:
                key_clean = key_orig.replace('.json', '').replace('.pdf', '').strip().rstrip('.-_ ').lower()

                # Match si l'un contient l'autre (au moins 80% du nom)
                if search_clean in key_clean or key_clean in search_clean:
                    if len(search_clean) > 0 and len(key_clean) > 0:
                        # Calculer similarité
                        min_len = min(len(search_clean), len(key_clean))
                        max_len = max(len(search_clean), len(key_clean))
                        if min_len / max_len > 0.7:  # Au moins 70% de similarité
                            return score_data

            return {}

        # IMPORTANT: Enrichir reranked avec les scores, puis trier par score_final décroissant
        reranked_with_scores = []
        for cv_result in reranked:
            if isinstance(cv_result, str):
                continue

            cv_name = cv_result.get('cv') or cv_result.get('cv_id', 'inconnu')
            cv_scores = find_best_match(cv_name)

            # Récupérer le coefficient d'expérience
            coefficient_experience = cv_result.get('coefficient_qualite_experience', 1.0)

            # Recalculer le score_final avec le coefficient d'expérience
            score_base = cv_scores.get('score_base', 0.0)
            bonus_nice_have = cv_scores.get('bonus_nice_have_multiplicateur', 1.0)
            score_final_with_coef = score_base * bonus_nice_have * coefficient_experience
            score_final_with_coef = max(0.0, min(1.0, score_final_with_coef))

            # Créer un objet combiné
            combined = {
                **cv_result,  # commentaire_scoring, appreciation_globale, cv, coefficient_qualite_experience
                'score_final': score_final_with_coef,  # Score final avec coefficient appliqué
                'score_base': score_base,
                'bonus_nice_have_multiplicateur': bonus_nice_have,
                'nombre_manquants': cv_scores.get('nombre_manquants', 0),
                'nice_have_manquants': cv_scores.get('nice_have_manquants', [])
            }
            reranked_with_scores.append(combined)

        # TRI PAR SCORE FINAL DÉCROISSANT (avec coefficient appliqué)
        reranked_with_scores.sort(key=lambda x: x['score_final'], reverse=True)

        st.success(f"Classement final par score: {len(reranked_with_scores)} candidats")

        # LÉGENDE DU SYSTÈME DE SCORING
        with st.expander("Comprendre le système de scoring", expanded=False):
            st.markdown("""
            <style>
            .scoring-legend { font-size: 0.85rem; }
            .scoring-legend h4 { font-size: 1rem; margin-top: 1rem; margin-bottom: 0.5rem; }
            .scoring-legend p { margin: 0.3rem 0; }
            .scoring-legend ul { margin: 0.3rem 0; padding-left: 1.5rem; }
            </style>
            <div class="scoring-legend">

            <h3>Score Final = Score Base × Malus Nice-have × Qualité XP</h3>

            <p>Le système utilise un <strong>scoring quantitatif</strong> (Phase 2) suivi d'un <strong>re-ranking qualitatif par IA</strong> (Phase 3) qui affine le score avec l'évaluation de l'expérience.</p>

            <hr>

            <h4>Phase 2 : Scoring Quantitatif</h4>

            <p><strong>1. Score Base (0.0 à 1.0)</strong></p>
            <p>Similarité sémantique entre le CV et l'offre, calculée par embedding vectoriel. Mesure l'adéquation globale des compétences.</p>

            <p><strong>2. Malus Nice-have (multiplicateur)</strong></p>
            <p>Applique un malus progressif pour chaque compétence nice-have manquante (souhaitables mais non bloquantes).</p>

            <p><strong>Formule :</strong> 0.95^(nb_manquants)</p>
            <ul>
            <li>0 manquant → 0.95⁰ = 1.00 (100%, aucun malus)</li>
            <li>1 manquant → 0.95¹ = 0.95 (malus -5%)</li>
            <li>2 manquants → 0.95² = 0.90 (malus -10%)</li>
            <li>3 manquants → 0.95³ = 0.86 (malus -14%)</li>
            </ul>

            <p><strong>Exemple :</strong> Score base = 0.75, 2 nice-have manquants → 0.75 × 0.90 = 0.68</p>

            <hr>

            <h4>Phase 3 : Re-ranking Qualitatif (IA)</h4>

            <p>Un Robot RH analyse comparativement les candidats du top 10 et attribue un <strong>Coefficient de Qualité d'Expérience (×1.0 à ×1.4)</strong> basé sur :</p>
            <ul>
            <li><strong>Durée et pertinence</strong> des expériences par rapport au poste</li>
            <li><strong>Qualité des environnements</strong> de travail (startup, grande entreprise, international)</li>
            <li><strong>Cohérence et progression</strong> du parcours professionnel</li>
            <li><strong>Leadership</strong> et responsabilités (lead technique, projets majeurs)</li>
            <li><strong>Adéquation</strong> au domaine du poste (environnement identique = bonus)</li>
            </ul>

            <p><strong>Grille d'évaluation du Coefficient Qualité XP :</strong></p>
            <ul>
            <li>×1.4 : Expérience exceptionnelle (leadership, environnement identique)</li>
            <li>×1.3 : Expérience très forte (senior, projets complexes)</li>
            <li>×1.2 : Expérience forte (confirmé, pertinence élevée)</li>
            <li>×1.1 : Expérience pertinente (standard pour le poste)</li>
            <li>×1.0 : Expérience correcte (junior ou peu pertinent)</li>
            </ul>

            <p><strong>Exemple complet :</strong></p>
            <p>Score base = 0.75, 1 nice-have manquant (0.95), Qualité XP = 1.3 (senior)</p>
            <p>→ Score final = 0.75 × 0.95 × 1.3 = <strong>0.93</strong></p>

            <p><strong>Résultat :</strong> Classement optimisé + 2 commentaires par candidat</p>
            <ul>
            <li>Analyse du scoring (technique + nice-have manquants)</li>
            <li>Appréciation RH (qualitative + justification coefficient + recommandation)</li>
            </ul>

            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        for i, cv_data in enumerate(reranked_with_scores, 1):
            cv_name = cv_data.get('cv', 'inconnu')
            commentaire_scoring = cv_data.get('commentaire_scoring', '')
            appreciation_globale = cv_data.get('appreciation_globale', '')

            # Fallback pour ancien format
            if not commentaire_scoring and not appreciation_globale:
                ancien_commentaire = cv_data.get('commentaire', 'Aucun commentaire')
                appreciation_globale = ancien_commentaire

            score_base = cv_data.get('score_base', 0.0)
            bonus_nice_have = cv_data.get('bonus_nice_have_multiplicateur', 1.0)
            coefficient_experience = cv_data.get('coefficient_qualite_experience', 1.0)
            nombre_manquants = cv_data.get('nombre_manquants', 0)

            # Recalculer le score final avec le coefficient d'expérience
            score_final = score_base * bonus_nice_have * coefficient_experience
            score_final = max(0.0, min(1.0, score_final))

            with st.expander(f"#{i} - {cv_name} (Score: {score_final:.3f})"):
                # Afficher les commentaires
                if commentaire_scoring:
                    st.markdown(f"**Analyse du scoring:**\n\n{commentaire_scoring}")
                else:
                    st.warning("⚠️ Analyse du scoring manquante")

                if appreciation_globale:
                    st.markdown(f"**Appréciation RH:**\n\n{appreciation_globale}")
                else:
                    st.warning("⚠️ Appréciation RH manquante")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Score final", f"{score_final:.3f}")
                with col2:
                    st.metric("Score base", f"{score_base:.3f}")
                with col3:
                    malus_nice_pct = int((bonus_nice_have - 1.0) * 100)
                    delta_text = f"{malus_nice_pct:+d}%" if malus_nice_pct != 0 else None
                    if nombre_manquants > 0:
                        delta_text = f"{nombre_manquants} manquant(s)"
                    st.metric("Malus Nice-have (×)", f"{bonus_nice_have:.3f}",
                             delta=delta_text, delta_color="inverse" if nombre_manquants > 0 else "normal")
                with col4:
                    bonus_exp_pct = int((coefficient_experience - 1.0) * 100)
                    delta_exp = f"{bonus_exp_pct:+d}%" if bonus_exp_pct != 0 else None
                    st.metric("Qualité XP (×)", f"{coefficient_experience:.2f}",
                             delta=delta_exp, delta_color="normal" if bonus_exp_pct > 0 else "inverse")

                if cv_data.get('nice_have_manquants'):
                    st.warning(f"Nice-have manquants: {', '.join(cv_data['nice_have_manquants'])}")

        # Export
        st.markdown("---")
        # Fonction pour générer l'Excel (exécutée à chaque clic)
        def generate_excel_data():
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from io import BytesIO

            # Créer workbook Excel
            wb = Workbook()
            ws = wb.active
            ws.title = "Résultats Matching"

            # Styles
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF", size=12)
            border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )

            # En-têtes
            headers = [
                "Rang", "CV", "Score Final", "Score Base",
                "Malus Nice-have (×)", "Coeff. Qualité (×)",
                "Nice-have Manquants", "Commentaire Scoring", "Appréciation Globale"
            ]

            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = border

            # Remplir les données
            for i, cv_data in enumerate(reranked_with_scores, 1):
                commentaire_scoring = cv_data.get('commentaire_scoring', '')
                appreciation_globale = cv_data.get('appreciation_globale', '')

                # Fallback pour ancien format
                if not commentaire_scoring and not appreciation_globale:
                    ancien_commentaire = cv_data.get('commentaire', '')
                    appreciation_globale = ancien_commentaire

                # Recalculer le score final avec coefficient
                score_base = cv_data.get('score_base', 0.0)
                bonus_nice_have = cv_data.get('bonus_nice_have_multiplicateur', 1.0)
                coefficient_experience = cv_data.get('coefficient_qualite_experience', 1.0)
                score_final = score_base * bonus_nice_have * coefficient_experience
                score_final = max(0.0, min(1.0, score_final))

                nice_have_manquants = cv_data.get('nice_have_manquants', [])
                nice_have_str = ", ".join(nice_have_manquants) if nice_have_manquants else "Aucun"

                row_data = [
                    i,  # Rang
                    cv_data.get('cv', 'inconnu'),
                    round(score_final, 4),
                    round(score_base, 4),
                    round(bonus_nice_have, 4),
                    round(coefficient_experience, 4),
                    nice_have_str,
                    commentaire_scoring,
                    appreciation_globale
                ]

                for col_idx, value in enumerate(row_data, start=1):
                    cell = ws.cell(row=i+1, column=col_idx, value=value)
                    cell.border = border
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

                    # Coloration score final
                    if col_idx == 3:  # Score Final
                        score_pct = value * 100
                        if score_pct >= 80:
                            cell.font = Font(bold=True, color="006100")
                        elif score_pct >= 60:
                            cell.font = Font(bold=True, color="0070C0")
                        elif score_pct >= 40:
                            cell.font = Font(color="FFC000")
                        else:
                            cell.font = Font(color="C00000")

            # Ajuster largeurs colonnes
            column_widths = [8, 40, 12, 12, 18, 18, 30, 50, 50]
            for col_idx, width in enumerate(column_widths, start=1):
                ws.column_dimensions[chr(64 + col_idx)].width = width

            # Figer première ligne
            ws.freeze_panes = "A2"

            # Sauvegarder dans BytesIO
            excel_output = BytesIO()
            wb.save(excel_output)
            excel_output.seek(0)

            return excel_output.getvalue()

        # Bouton unique qui génère et télécharge l'Excel
        st.download_button(
            label="📊 Exporter et télécharger Excel",
            data=generate_excel_data(),
            file_name="resultats_matching.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
