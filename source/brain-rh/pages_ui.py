#!/usr/bin/env python3
"""
Pages UI pour la gestion multi-niveaux: Entreprises > Projets > Détail
"""

import streamlit as st
from project_manager import ProjectManager
from enterprise_manager import EnterpriseManager
from datetime import datetime
import base64


def get_base64_image(image_path):
    """Convertit une image en base64"""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()


def page_dashboard(em: EnterpriseManager):
    """
    Page Dashboard avec KPI et sidebar fixe

    Args:
        em: Instance de EnterpriseManager
    """
    # Charger le logo
    logo_base64 = get_base64_image('assets/BLight.png')
    
    # CSS style OpenAI avec sidebar fixe
    st.markdown(f"""
    <style>
        /* Reset et variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        /* Palette minimaliste */
        :root {{
            --bg-main: #0D0D0D;
            --bg-card: #1A1A1A;
            --bg-hover: #262626;
            --text-primary: #ECECEC;
            --text-secondary: #8E8E93;
            --border: #2C2C2C;
            --accent: #4A90E2;
        }}
        
        /* Sidebar Streamlit stylisée */
        section[data-testid="stSidebar"] {{
            position: fixed !important;
            left: 0 !important;
            top: 0 !important;
            width: 260px !important;
            height: 100vh !important;
            background: #000000 !important;
            border-right: 1px solid var(--border) !important;
            z-index: 1001 !important;
        }}
        
        section[data-testid="stSidebar"] > div {{
            background: #000000 !important;
            padding: 0 !important;
        }}
        
        /* Boutons de navigation dans la sidebar */
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            color: var(--text-secondary) !important;
            border: none !important;
            border-left: 3px solid transparent !important;
            border-radius: 0 !important;
            padding: 0.75rem 1.5rem !important;
            font-weight: 500 !important;
            font-size: 0.9rem !important;
            text-align: left !important;
            transition: all 0.2s ease !important;
            width: 100% !important;
        }}
        
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
            border-left-color: var(--accent) !important;
        }}
        
        /* Corps principal plein écran */
        .stApp {{
            background-color: var(--bg-main);
        }}
        
        .main {{
            background-color: var(--bg-main);
            padding: 0 !important;
            max-width: 100% !important;
            margin-left: 260px !important;
        }}
        
        .main .block-container {{
            padding: 2rem 3rem !important;
            max-width: 100% !important;
        }}
        
        /* Masquer la sidebar HTML custom (on utilise la sidebar Streamlit) */
        .custom-sidebar {{
            display: none !important;
        }}
        
        .sidebar-logo {{
            padding: 1.5rem 1rem;
            border-bottom: 1px solid var(--border);
            text-align: center;
        }}
        
        .sidebar-logo img {{
            width: 40px;
            height: auto;
            opacity: 0.9;
            margin-top: 2.5rem;
            margin-bottom: 1rem;
            display: block;
            margin-left: auto;
            margin-right: auto;
        }}
        
        .sidebar-nav {{
            flex: 1;
            padding: 1rem 0;
            overflow-y: auto;
        }}
        
        .nav-item {{
            padding: 0.75rem 1.5rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            border-left: 3px solid transparent;
        }}
        
        .nav-item:hover {{
            background: var(--bg-hover);
            color: var(--text-primary);
            border-left-color: var(--accent);
        }}
        
        .nav-item.active {{
            background: var(--bg-card);
            color: var(--text-primary);
            border-left-color: var(--accent);
        }}
        
        .sidebar-footer {{
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 0.8rem;
        }}
        
        /* KPI Cards */
        .kpi-container {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
            margin-bottom: 3rem;
        }}
        
        .kpi-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            transition: all 0.2s ease;
        }}
        
        .kpi-card:hover {{
            border-color: var(--accent);
            transform: translateY(-2px);
        }}
        
        .kpi-label {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .kpi-value {{
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--text-primary);
            line-height: 1;
        }}
        
        /* Page title */
        .page-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: var(--text-primary);
            margin: 0 0 2rem 0;
            letter-spacing: -0.02em;
        }}
    </style>
    
    <!-- Sidebar fixe custom -->
    <div class="custom-sidebar">
        <div class="sidebar-logo">
            <img src="data:image/png;base64,{logo_base64}" alt="Brain RH">
        </div>
        <div class="sidebar-nav" id="sidebar-nav">
        </div>
        <div class="sidebar-footer">
            Brain RH+ v1.0
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation sidebar avec boutons invisibles
    with st.sidebar:
        # Logo en haut
        st.markdown(f'''
        <div style="text-align: center; padding: 2rem 1rem 1.5rem 1rem; border-bottom: 1px solid var(--border);">
            <img src="data:image/png;base64,{logo_base64}" style="width: 40px; height: auto; opacity: 0.9;" alt="Brain RH">
        </div>
        ''', unsafe_allow_html=True)
        
        st.markdown('<div style="margin-top: 1rem;"></div>', unsafe_allow_html=True)
        
        # Dashboard (actif)
        if st.button("Dashboard", key="nav_dashboard", use_container_width=True):
            st.session_state['current_page'] = 'dashboard'
            st.rerun()
        
        # Clients
        if st.button("Clients", key="nav_clients", use_container_width=True):
            st.session_state['current_page'] = 'clients'
            st.session_state['current_enterprise'] = None
            st.session_state['current_project'] = None
            st.rerun()
        
        # Projets
        if st.button("Projets", key="nav_projets", use_container_width=True):
            st.session_state['current_page'] = 'projets'
            st.rerun()
        
        # Base de données
        if st.button("Base de données", key="nav_matching", use_container_width=True):
            st.session_state['current_page'] = 'matching'
            st.rerun()
        
        # Footer en bas
        st.markdown('''
        <div style="position: fixed; bottom: 0; left: 0; width: 260px; padding: 1rem 1.5rem; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 0.8rem;">
            Brain RH+ v1.0
        </div>
        ''', unsafe_allow_html=True)
    
    # Titre
    st.markdown('<h1 class="page-title">Dashboard</h1>', unsafe_allow_html=True)
    
    # Calculer les KPI
    enterprises = em.list_enterprises()
    nb_clients = len(enterprises)
    
    # Compter les projets
    nb_projets = 0
    for ent in enterprises:
        projects_folder = em.get_projects_folder(ent['id'])
        if projects_folder and projects_folder.exists():
            pm = ProjectManager(str(projects_folder))
            nb_projets += len(pm.list_projects(status='active'))
    
    # TODO: Compter les matchings (à implémenter selon votre logique)
    nb_matchings = 0
    
    # Afficher les KPI
    st.markdown(f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-label">Clients</div>
            <div class="kpi-value">{nb_clients}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Projets</div>
            <div class="kpi-value">{nb_projets}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Matchings</div>
            <div class="kpi-value">{nb_matchings}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Section activités récentes (optionnel)
    st.markdown('<h2 style="color: var(--text-primary); font-size: 1.2rem; margin-top: 2rem;">Activités récentes</h2>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); font-size: 0.9rem;">Aucune activité récente</p>', unsafe_allow_html=True)


def page_accueil_entreprises(em: EnterpriseManager):
    """
    Page d'accueil: liste des entreprises en table minimaliste

    Args:
        em: Instance de EnterpriseManager
    """
    # Charger le logo
    logo_base64 = get_base64_image('assets/BLight.png')
    
    # CSS style OpenAI avec table minimaliste
    st.markdown(f"""
    <style>
        /* Reset et variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        /* Palette minimaliste */
        :root {{
            --bg-main: #0D0D0D;
            --bg-card: #1A1A1A;
            --bg-hover: #1A1A1A;
            --text-primary: #ECECEC;
            --text-secondary: #8E8E93;
            --border: #2C2C2C;
            --accent: #4A90E2;
        }}
        
        /* Sidebar Streamlit stylisée */
        section[data-testid="stSidebar"] {{
            position: fixed !important;
            left: 0 !important;
            top: 0 !important;
            width: 260px !important;
            height: 100vh !important;
            background: #000000 !important;
            border-right: 1px solid var(--border) !important;
            z-index: 1001 !important;
        }}
        
        section[data-testid="stSidebar"] > div {{
            background: #000000 !important;
            padding: 0 !important;
        }}
        
        /* Boutons de navigation dans la sidebar */
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            color: var(--text-secondary) !important;
            border: none !important;
            border-left: 3px solid transparent !important;
            border-radius: 0 !important;
            padding: 0.75rem 1.5rem !important;
            font-weight: 500 !important;
            font-size: 0.9rem !important;
            text-align: left !important;
            transition: all 0.2s ease !important;
            width: 100% !important;
        }}
        
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
            border-left-color: var(--accent) !important;
        }}
        
        /* Corps principal plein écran */
        .stApp {{
            background-color: var(--bg-main);
        }}
        
        .main {{
            background-color: var(--bg-main);
            padding: 0 !important;
            max-width: 100% !important;
            margin-left: 260px !important;
        }}
        
        .main .block-container {{
            padding: 2rem 3rem !important;
            max-width: 100% !important;
        }}
        
        /* Titre page */
        .page-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: var(--text-primary);
            margin: 0 0 0.5rem 0;
        }}
        
        .page-subtitle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }}
        
        /* Bouton nouveau client */
        .new-client-btn {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-bottom: 1.5rem;
        }}
        
        .new-client-btn:hover {{
            background: var(--bg-card);
            border-color: var(--accent);
            color: var(--text-primary);
        }}
        
        /* Table minimaliste */
        .clients-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }}
        
        .clients-table thead {{
            border-bottom: 1px solid var(--border);
        }}
        
        .clients-table th {{
            text-align: left;
            padding: 0.75rem 1rem;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        
        .clients-table tbody tr {{
            border-bottom: 1px solid var(--border);
            transition: background 0.15s ease;
            cursor: pointer;
        }}
        
        .clients-table tbody tr:hover {{
            background: var(--bg-hover);
        }}
        
        .clients-table td {{
            padding: 1rem;
            font-size: 0.9rem;
            color: var(--text-primary);
        }}
        
        .clients-table td.client-name {{
            font-weight: 500;
            color: var(--text-primary);
        }}
        
        .clients-table td.client-sector {{
            color: var(--text-secondary);
        }}
        
        .clients-table td.client-projects {{
            color: var(--text-secondary);
            font-variant-numeric: tabular-nums;
        }}
        
        .clients-table td.client-date {{
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}
        
        .clients-table td.client-actions {{
            text-align: right;
        }}
        
        /* Boutons d'action dans la table */
        .action-btn {{
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 1.1rem;
            padding: 0.25rem 0.5rem;
            cursor: pointer;
            transition: color 0.2s ease;
            margin-left: 0.5rem;
        }}
        
        .action-btn:hover {{
            color: var(--text-primary);
        }}
        
        .action-btn.delete:hover {{
            color: #F56565;
        }}
        
        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
        }}
        
        .empty-state-title {{
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.75rem;
        }}
        
        /* Formulaire */
        .stTextInput > div > div > input {{
            background: var(--bg-main) !important;
            border: 1px solid var(--border) !important;
            border-radius: 6px !important;
            color: var(--text-primary) !important;
            padding: 0.625rem 0.875rem !important;
            font-size: 0.9rem !important;
        }}
        
        .stTextInput > div > div > input:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 1px var(--accent) !important;
        }}
        
        .stTextInput > label {{
            color: var(--text-primary) !important;
            font-size: 0.9rem !important;
            font-weight: 500 !important;
            margin-bottom: 0.5rem !important;
        }}
        
        /* Boutons Streamlit dans le corps */
        .stButton > button {{
            background: transparent !important;
            color: var(--text-secondary) !important;
            border: 1px solid var(--border) !important;
            border-radius: 4px !important;
            padding: 0.35rem 0.75rem !important;
            font-weight: 400 !important;
            font-size: 0.8rem !important;
            transition: all 0.2s ease !important;
            min-height: auto !important;
            height: auto !important;
        }}
        
        .stButton > button:hover {{
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
            border-color: var(--border) !important;
        }}
        
        /* Style spécial pour les noms de clients (boutons cliquables dans col_nom) */
        div[data-testid="column"]:first-child .stButton > button {{
            background: transparent !important;
            border: none !important;
            color: var(--accent) !important;
            font-weight: 400 !important;
            font-size: 0.9rem !important;
            padding: 0 !important;
            text-align: left !important;
            justify-content: flex-start !important;
            text-decoration: none !important;
            cursor: pointer !important;
        }}
        
        div[data-testid="column"]:first-child .stButton > button:hover {{
            color: var(--accent) !important;
            background: transparent !important;
            text-decoration: underline !important;
            opacity: 0.8 !important;
        }}
        
        .stButton > button[kind="primary"] {{
            background: var(--accent) !important;
            color: white !important;
            border-color: var(--accent) !important;
            padding: 0.625rem 1.25rem !important;
            font-size: 0.9rem !important;
        }}
        
        .stButton > button[kind="primary"]:hover {{
            background: #3A7BC8 !important;
        }}
        
        /* Boutons nouveau client/projet en haut */
        button[key="new_client_btn"],
        button[key="new_project_btn"] {{
            background: transparent !important;
            border: 1px solid var(--border) !important;
            color: var(--text-primary) !important;
            padding: 0.5rem 1rem !important;
            font-size: 1.2rem !important;
            font-weight: 300 !important;
            border-radius: 6px !important;
            min-height: 40px !important;
            height: 40px !important;
        }}
        
        button[key="new_client_btn"]:hover,
        button[key="new_project_btn"]:hover {{
            background: var(--bg-card) !important;
            border-color: var(--accent) !important;
        }}
        
        .sidebar-nav {{
            flex: 1;
            padding: 1rem 0;
            overflow-y: auto;
        }}
        
        .nav-item {{
            padding: 0.75rem 1.5rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            border-left: 3px solid transparent;
        }}
        
        .nav-item:hover {{
            background: var(--bg-hover);
            color: var(--text-primary);
            border-left-color: var(--accent);
        }}
        
        .nav-item.active {{
            background: var(--bg-card);
            color: var(--text-primary);
            border-left-color: var(--accent);
        }}
        
        .sidebar-footer {{
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 0.8rem;
        }}
        
        /* Header simple avec bouton + */
        .page-header {{
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .page-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: var(--text-primary);
            margin: 0;
            letter-spacing: -0.02em;
        }}
        
        /* Bouton + minimaliste */
        button[data-testid="baseButton-secondary"] {{
            background: var(--bg-card) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--border) !important;
            border-radius: 8px !important;
            padding: 0 !important;
            font-weight: 400 !important;
            font-size: 1.75rem !important;
            line-height: 1 !important;
            min-width: 42px !important;
            width: 42px !important;
            height: 42px !important;
            transition: all 0.2s ease !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }}
        
        button[data-testid="baseButton-secondary"]:hover {{
            background: var(--accent) !important;
            color: white !important;
            border-color: var(--accent) !important;
            transform: scale(1.05) !important;
        }}
        
        /* Cards entreprises cliquables */
        .enterprise-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 0.75rem;
            transition: all 0.2s ease;
            cursor: pointer;
            position: relative;
        }}
        
        .enterprise-card:hover {{
            background: var(--bg-hover);
            border-color: var(--accent);
        }}
        
        .enterprise-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 0.75rem;
        }}
        
        .enterprise-name {{
            font-size: 1.05rem;
            font-weight: 500;
            color: var(--text-primary);
            margin: 0;
        }}
        
        .delete-zone {{
            color: var(--text-secondary);
            font-size: 0.85rem;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            transition: all 0.2s ease;
        }}
        
        .delete-zone:hover {{
            color: #FF4444;
            background: rgba(255, 68, 68, 0.1);
        }}
        
        .enterprise-details {{
            display: flex;
            gap: 1.25rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}
        
        .enterprise-details span {{
            display: inline-flex;
            align-items: center;
        }}
        
        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 5rem 2rem;
            color: var(--text-secondary);
        }}
        
        .empty-state-title {{
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }}
        
        /* Formulaire */
        .form-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
        }}
        
        .form-modal {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 2rem;
            width: 90%;
            max-width: 500px;
        }}
        
        .form-title {{
            font-size: 1.3rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 1.5rem;
        }}
        
        /* Inputs */
        .stTextInput > div > div > input {{
            background: var(--bg-main);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-primary);
            padding: 0.625rem 0.875rem;
            font-size: 0.9rem;
        }}
        
        .stTextInput > div > div > input:focus {{
            border-color: var(--accent);
            box-shadow: 0 0 0 1px var(--accent);
        }}
        
        .stTextInput > label {{
            color: var(--text-primary);
            font-size: 0.9rem;
            font-weight: 500;
            margin-bottom: 0.5rem;
        }}
        
        /* Boutons formulaire */
        .stButton > button {{
            background: transparent;
            color: var(--text-primary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.625rem 1.25rem;
            font-weight: 500;
            font-size: 0.9rem;
            transition: all 0.2s ease;
        }}
        
        .stButton > button:hover {{
            background: var(--bg-hover);
            border-color: var(--accent);
        }}
        
        .stButton > button[kind="primary"] {{
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }}
        
        .stButton > button[kind="primary"]:hover {{
            background: #3A7BC8;
        }}
        
        /* Messages */
        .stSuccess, .stError, .stWarning {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.75rem 1rem;
            font-size: 0.9rem;
        }}
    </style>
    """, unsafe_allow_html=True)

    # Navigation sidebar
    with st.sidebar:
        # Logo en haut
        st.markdown(f'''
        <div style="text-align: center; padding: 2rem 1rem 1.5rem 1rem; border-bottom: 1px solid var(--border);">
            <img src="data:image/png;base64,{logo_base64}" style="width: 40px; height: auto; opacity: 0.9;" alt="Brain RH">
    </div>
        ''', unsafe_allow_html=True)
        
        st.markdown('<div style="margin-top: 1rem;"></div>', unsafe_allow_html=True)
        
        # Dashboard
        if st.button("Dashboard", key="nav_dashboard_clients", use_container_width=True):
            st.session_state['current_page'] = 'dashboard'
            st.rerun()
        
        # Clients (actif)
        if st.button("Clients", key="nav_clients_clients", use_container_width=True):
            st.session_state['current_page'] = 'clients'
            st.rerun()
        
        # Projets
        if st.button("Projets", key="nav_projets_clients", use_container_width=True):
            st.session_state['current_page'] = 'projets'
            st.rerun()
        
        # Base de données
        if st.button("Base de données", key="nav_matching_clients", use_container_width=True):
            st.session_state['current_page'] = 'matching'
            st.rerun()
        
        # Footer en bas
        st.markdown('''
        <div style="position: fixed; bottom: 0; left: 0; width: 260px; padding: 1rem 1.5rem; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 0.8rem;">
            Brain RH+ v1.0
        </div>
        ''', unsafe_allow_html=True)

    # Header minimaliste
    col1, col2 = st.columns([10, 1])
    with col1:
        st.markdown('<h1 class="page-title">Clients</h1>', unsafe_allow_html=True)
    with col2:
        if st.button("+ Nouveau client", key="new_client_btn"):
            st.session_state['show_create_enterprise_form'] = True

    # Formulaire de création
    if st.session_state.get('show_create_enterprise_form', False):
        with st.form("create_enterprise_form", clear_on_submit=False):
            st.markdown('<div class="form-title">Nouveau client</div>', unsafe_allow_html=True)

            nom = st.text_input(
                "Nom de l'entreprise",
                placeholder="Ex: Banque de France",
                key="new_ent_nom"
            )

            secteur = st.text_input(
                "Secteur d'activité",
                placeholder="Ex: Finance, Technologie, Santé...",
                key="new_ent_secteur"
            )

            st.markdown("<br>", unsafe_allow_html=True)
            
            col_submit, col_cancel = st.columns([1, 1])
            with col_submit:
                submitted = st.form_submit_button("Créer", use_container_width=True, type="primary")
            with col_cancel:
                cancelled = st.form_submit_button("Annuler", use_container_width=True)

            if submitted:
                if not nom or len(nom.strip()) < 2:
                    st.error("Le nom doit contenir au moins 2 caractères")
                else:
                    entreprise = em.create_enterprise(nom.strip(), secteur.strip() if secteur else "Non spécifié")
                    st.success(f"Client '{entreprise['nom']}' créé")
                    st.session_state['show_create_enterprise_form'] = False
                    st.rerun()

            if cancelled:
                st.session_state['show_create_enterprise_form'] = False
                st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

    # Liste des entreprises
    enterprises = em.list_enterprises()

    if not enterprises:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-title">Aucun client</div>
            <div>Créez votre premier client pour commencer</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # En-tête de la table (HTML statique)
        st.markdown('''
        <div style="display: flex; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); margin-bottom: 0.5rem;">
            <div style="flex: 3; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Nom</div>
            <div style="flex: 2; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Secteur</div>
            <div style="flex: 1; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Projets</div>
            <div style="flex: 2; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Date de création</div>
            <div style="flex: 1; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; text-align: right;">Actions</div>
        </div>
        ''', unsafe_allow_html=True)
        
        # Lignes de la table (composants Streamlit natifs)
        for enterprise in enterprises:
            enterprise_id = enterprise['id']
            nom = enterprise['nom']
            secteur = enterprise.get('secteur', 'Non spécifié')
            projects_count = enterprise.get('projects_count', 0)
            created = datetime.fromisoformat(enterprise['created_at']).strftime("%d/%m/%Y")
            
            # Container pour la ligne avec hover effect
            with st.container():
                # Utiliser des colonnes pour simuler les cellules du tableau
                col_nom, col_secteur, col_projets, col_date, col_actions = st.columns([3, 2, 1, 2, 1])
                
                with col_nom:
                    # Nom cliquable pour ouvrir les projets
                    if st.button(nom, key=f"open_{enterprise_id}", help="Voir les projets du client"):
                        st.session_state['current_enterprise'] = enterprise_id
                        st.session_state['current_project'] = None
                        st.rerun()

                with col_secteur:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.9rem;">{secteur}</div>', unsafe_allow_html=True)
                
                with col_projets:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.9rem;">{projects_count}</div>', unsafe_allow_html=True)
                
                with col_date:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.85rem;">{created}</div>', unsafe_allow_html=True)
                
                with col_actions:
                    # Boutons d'action (icônes uniquement)
                    btn_col1, btn_col2 = st.columns([1, 1])
                    
                    with btn_col1:
                        if st.button("✎", key=f"edit_{enterprise_id}", help="Modifier"):
                            # Fonctionnalité de modification à implémenter
                            pass
                    
                    with btn_col2:
                        if st.button("×", key=f"del_{enterprise_id}", help="Supprimer"):
                            # Suppression directe sans confirmation
                            em.delete_enterprise(enterprise_id)
                            st.rerun()

                # Séparateur de ligne
                st.markdown('<div style="border-bottom: 1px solid var(--border); margin: 0;"></div>', unsafe_allow_html=True)


def page_accueil_projets(pm: ProjectManager, enterprise_id: str = None, enterprise_name: str = ""):
    """
    Page liste des projets pour une entreprise + création

    Args:
        pm: Instance de ProjectManager
        enterprise_id: ID de l'entreprise (optionnel pour compatibilité)
        enterprise_name: Nom de l'entreprise pour le fil d'Ariane
    """
    # Charger le logo
    logo_base64 = get_base64_image('assets/BLight.png')

    # CSS style OpenAI minimaliste
    st.markdown(f"""
    <style>
        /* Reset et variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        /* Palette minimaliste */
        :root {{
            --bg-main: #0D0D0D;
            --bg-card: #1A1A1A;
            --bg-hover: #262626;
            --text-primary: #ECECEC;
            --text-secondary: #8E8E93;
            --border: #2C2C2C;
            --accent: #4A90E2;
        }}
        
        /* Sidebar Streamlit stylisée */
        section[data-testid="stSidebar"] {{
            position: fixed !important;
            left: 0 !important;
            top: 0 !important;
            width: 260px !important;
            height: 100vh !important;
            background: #000000 !important;
            border-right: 1px solid var(--border) !important;
            z-index: 1001 !important;
        }}
        
        section[data-testid="stSidebar"] > div {{
            background: #000000 !important;
            padding: 0 !important;
        }}
        
        /* Boutons de navigation dans la sidebar */
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            color: var(--text-secondary) !important;
            border: none !important;
            border-left: 3px solid transparent !important;
            border-radius: 0 !important;
            padding: 0.75rem 1.5rem !important;
            font-weight: 500 !important;
            font-size: 0.9rem !important;
            text-align: left !important;
            transition: all 0.2s ease !important;
            width: 100% !important;
        }}
        
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
            border-left-color: var(--accent) !important;
        }}
        
        /* Corps principal plein écran */
        .stApp {{
            background-color: var(--bg-main);
        }}
        
        .main {{
            background-color: var(--bg-main);
            padding: 0 !important;
            max-width: 100% !important;
            margin-left: 260px !important;
        }}
        
        .main .block-container {{
            padding: 2rem 3rem !important;
            max-width: 100% !important;
        }}
        
        /* Breadcrumb */
        .breadcrumb {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .breadcrumb-link {{
            color: var(--accent);
            cursor: pointer;
            transition: opacity 0.2s ease;
        }}
        
        .breadcrumb-link:hover {{
            opacity: 0.8;
        }}
        
        .breadcrumb-current {{
            color: var(--text-primary);
        }}
        
        /* Titre page */
        .page-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: var(--text-primary);
            margin: 0 0 0.5rem 0;
        }}
        
        .page-subtitle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }}
        
        /* Bouton + minimaliste */
        .new-project-btn {{
            position: fixed;
            top: 2rem;
            right: 3rem;
            width: 40px;
            height: 40px;
            background: var(--bg-card) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--border) !important;
            border-radius: 8px !important;
            font-size: 1.75rem !important;
            font-weight: 300 !important;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s ease !important;
        }}
        
        .new-project-btn:hover {{
            background: var(--bg-hover) !important;
            border-color: var(--accent) !important;
            transform: scale(1.05);
        }}
        
        /* Cards projets */
        .project-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            transition: all 0.2s ease;
            cursor: pointer;
        }}
        
        .project-card:hover {{
            background: var(--bg-hover);
            border-color: var(--accent);
        }}
        
        .project-name {{
            color: var(--text-primary);
            font-size: 1rem;
            font-weight: 500;
            margin-bottom: 0.5rem;
        }}
        
        .project-meta {{
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}
        
        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
        }}
        
        .empty-state-title {{
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.75rem;
        }}
        
        /* Formulaire */
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea {{
            background: var(--bg-main) !important;
            border: 1px solid var(--border) !important;
            border-radius: 6px !important;
            color: var(--text-primary) !important;
            padding: 0.625rem 0.875rem !important;
            font-size: 0.9rem !important;
        }}
        
        .stTextInput > div > div > input:focus,
        .stTextArea > div > div > textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 1px var(--accent) !important;
        }}
        
        .stTextInput > label,
        .stTextArea > label {{
            color: var(--text-primary) !important;
            font-size: 0.9rem !important;
            font-weight: 500 !important;
            margin-bottom: 0.5rem !important;
        }}
        
        /* Boutons Streamlit dans le corps */
        .stButton > button {{
            background: transparent !important;
            color: var(--text-secondary) !important;
            border: 1px solid var(--border) !important;
            border-radius: 4px !important;
            padding: 0.35rem 0.75rem !important;
            font-weight: 400 !important;
            font-size: 0.8rem !important;
            transition: all 0.2s ease !important;
            min-height: auto !important;
            height: auto !important;
        }}
        
        .stButton > button:hover {{
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
            border-color: var(--border) !important;
        }}
        
        /* Style spécial pour les noms de projets (boutons cliquables dans col_nom) */
        div[data-testid="column"]:first-child .stButton > button {{
            background: transparent !important;
            border: none !important;
            color: var(--text-primary) !important;
            font-weight: 500 !important;
            font-size: 0.9rem !important;
            padding: 0 !important;
            text-align: left !important;
            justify-content: flex-start !important;
        }}
        
        div[data-testid="column"]:first-child .stButton > button:hover {{
            color: var(--accent) !important;
            background: transparent !important;
            text-decoration: underline !important;
        }}
        
        /* Bouton nouveau projet en haut */
        button[key="new_project_btn"] {{
            background: transparent !important;
            border: 1px solid var(--border) !important;
            color: var(--text-primary) !important;
            padding: 0.5rem 1rem !important;
            font-size: 1.2rem !important;
            font-weight: 300 !important;
            border-radius: 6px !important;
            min-height: 40px !important;
            height: 40px !important;
        }}
        
        button[key="new_project_btn"]:hover {{
            background: var(--bg-card) !important;
            border-color: var(--accent) !important;
        }}
    </style>
    """, unsafe_allow_html=True)

    # Navigation sidebar
    with st.sidebar:
        # Logo en haut
        st.markdown(f'''
        <div style="text-align: center; padding: 2rem 1rem 1.5rem 1rem; border-bottom: 1px solid var(--border);">
            <img src="data:image/png;base64,{logo_base64}" style="width: 40px; height: auto; opacity: 0.9;" alt="Brain RH">
        </div>
        ''', unsafe_allow_html=True)
        
        st.markdown('<div style="margin-top: 1rem;"></div>', unsafe_allow_html=True)
        
        # Dashboard
        if st.button("Dashboard", key="nav_dashboard_projets", use_container_width=True):
            st.session_state['current_page'] = 'dashboard'
            st.session_state['current_enterprise'] = None
            st.session_state['current_project'] = None
            st.rerun()
        
        # Clients (actif)
        if st.button("Clients", key="nav_clients_projets", use_container_width=True):
            st.session_state['current_page'] = 'clients'
            st.rerun()
        
        # Projets
        if st.button("Projets", key="nav_projets_projets", use_container_width=True):
            st.session_state['current_page'] = 'projets'
            st.rerun()
        
        # Base de données
        if st.button("Base de données", key="nav_matching_projets", use_container_width=True):
            st.session_state['current_page'] = 'matching'
            st.rerun()
        
        # Footer en bas
        st.markdown('''
        <div style="position: fixed; bottom: 0; left: 0; width: 260px; padding: 1rem 1.5rem; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 0.8rem;">
            Brain RH+ v1.0
    </div>
        ''', unsafe_allow_html=True)

    # Breadcrumb avec bouton retour
    if enterprise_name:
        st.markdown(f'''
        <div class="breadcrumb">
            <span class="breadcrumb-link" onclick="document.getElementById('btn_back_to_clients').click()">Clients</span>
            <span>›</span>
            <span class="breadcrumb-current">{enterprise_name}</span>
        </div>
        ''', unsafe_allow_html=True)
        
        # Bouton invisible pour le clic JavaScript
        if st.button("← Retour aux clients", key="btn_back_to_clients", help="Retour à la liste des clients"):
                    st.session_state['current_enterprise'] = None
                    st.session_state['current_project'] = None
                    st.rerun()

        st.markdown('<br>', unsafe_allow_html=True)

    # Header avec bouton nouveau projet
    col1, col2 = st.columns([8, 2])
    with col1:
        st.markdown(f'<h1 class="page-title">Projets - {enterprise_name}</h1>', unsafe_allow_html=True)
    with col2:
        if st.button("+ Nouveau projet", key="new_project_btn"):
                st.session_state['show_create_form'] = True

    # Formulaire de création (modal simulé)
    if st.session_state.get('show_create_form', False):
        with st.form("create_project_form"):
            st.subheader("Créer un nouveau projet")

            nom = st.text_input(
                "Nom du projet *",
                placeholder="Ex: Recrutement Architecte SI Data/IA"
            )

            description = st.text_area(
                "Description (optionnel)",
                placeholder="Ex: Recrutement d'un architecte senior pour la DSI...",
                height=100
            )

            col_submit, col_cancel = st.columns(2)
            with col_submit:
                submitted = st.form_submit_button("Créer", use_container_width=True)
            with col_cancel:
                cancelled = st.form_submit_button("Annuler", use_container_width=True)

            if submitted:
                if not nom or len(nom.strip()) < 3:
                    st.error("Le nom doit contenir au moins 3 caractères")
                else:
                    # Créer le projet
                    projet = pm.create_project(nom.strip(), description.strip())
                    st.success(f"Projet '{projet['nom']}' créé avec succès!")
                    st.session_state['show_create_form'] = False
                    st.session_state['current_project'] = projet['id']
                    st.rerun()

            if cancelled:
                st.session_state['show_create_form'] = False
                st.rerun()

    # Liste des projets
    st.markdown("---")

    # Filtres
    col_filter1, col_filter2 = st.columns([3, 1])
    with col_filter1:
        search_query = st.text_input("Rechercher", placeholder="Nom du projet...", label_visibility="collapsed")
    with col_filter2:
        filter_status = st.selectbox(
            "Statut",
            ["Tous", "Actifs", "Archivés"],
            label_visibility="collapsed"
        )

    # Charger les projets
    status_filter = None
    if filter_status == "Actifs":
        status_filter = "actif"
    elif filter_status == "Archivés":
        status_filter = "archive"

    projects = pm.list_projects(status=status_filter)

    # Appliquer le filtre de recherche
    if search_query:
        projects = [
            p for p in projects
            if search_query.lower() in p['nom'].lower() or
               search_query.lower() in p.get('description', '').lower()
        ]

    # Afficher les projets
    if not projects:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-title">Aucun projet</div>
            <div>Créez votre premier projet pour commencer</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # En-tête de la table
        st.markdown('''
        <div style="display: flex; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); margin-bottom: 0.5rem;">
            <div style="flex: 3; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Nom</div>
            <div style="flex: 2; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Statut</div>
            <div style="flex: 1; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Matchings</div>
            <div style="flex: 2; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Date de création</div>
            <div style="flex: 1; font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; text-align: right;">Actions</div>
        </div>
        ''', unsafe_allow_html=True)
        
        # Lignes de la table
        for projet_summary in projects:
            projet_id = projet_summary['id']

            # Charger les détails complets
            projet = pm.get_project(projet_id)
            if not projet:
                continue

            # Métadonnées
            nom = projet['nom']
            status_text = "Actif" if projet['status'] == "actif" else "Archivé"
            matchings_count = projet.get('matchings_count', 0)
            created = datetime.fromisoformat(projet['created_at']).strftime("%d/%m/%Y")
            
            # Container pour la ligne
            with st.container():
                col_nom, col_status, col_matchings, col_date, col_actions = st.columns([3, 2, 1, 2, 1])
                
                with col_nom:
                    # Nom cliquable pour ouvrir le projet
                    if st.button(nom, key=f"open_proj_{projet_id}", help="Voir le matching"):
                        st.session_state['current_project'] = projet_id
                        st.rerun()
                
                with col_status:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.9rem;">{status_text}</div>', unsafe_allow_html=True)
                
                with col_matchings:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.9rem;">{matchings_count}</div>', unsafe_allow_html=True)
                
                with col_date:
                    st.markdown(f'<div style="padding: 1rem 0; color: var(--text-secondary); font-size: 0.85rem;">{created}</div>', unsafe_allow_html=True)
                
                with col_actions:
                    # Boutons d'action
                    btn_col1, btn_col2 = st.columns([1, 1])
                    
                    with btn_col1:
                        # Archiver/Restaurer
                        if projet['status'] == "actif":
                            if st.button("⊙", key=f"archive_{projet_id}", help="Archiver"):
                                pm.update_project(projet_id, {"status": "archive"})
                                st.rerun()
                        else:
                            if st.button("↻", key=f"restore_{projet_id}", help="Restaurer"):
                                pm.update_project(projet_id, {"status": "actif"})
                                st.rerun()

                    with btn_col2:
                        # Supprimer
                        if st.button("×", key=f"del_proj_{projet_id}", help="Supprimer"):
                            pm.delete_project(projet_id)
                            st.rerun()
                
                # Séparateur de ligne
                st.markdown('<div style="border-bottom: 1px solid var(--border); margin: 0;"></div>', unsafe_allow_html=True)


def show_project_header(pm: ProjectManager, project_id: str, enterprise_name: str = ""):
    """
    Affiche le header du projet actif avec fil d'Ariane

    Args:
        pm: Instance de ProjectManager
        project_id: ID du projet actif
        enterprise_name: Nom de l'entreprise pour le fil d'Ariane
    """
    projet = pm.get_project(project_id)
    if not projet:
        st.error(f"Projet {project_id} introuvable")
        return

    # Fil d'Ariane avec liens cliquables
    col_breadcrumb, col_spacer = st.columns([3, 1])

    with col_breadcrumb:
        # Créer les boutons du fil d'Ariane sur une seule ligne
        cols = st.columns([1, 0.1, 1.5, 0.1, 2.5])

        with cols[0]:
            # Bouton Accueil
            if st.button("Accueil", key="breadcrumb_home"):
                st.session_state['current_enterprise'] = None
                st.session_state['current_project'] = None
                st.rerun()

        with cols[1]:
            st.markdown('<span style="color: var(--text-secondary); line-height: 2.5;">›</span>', unsafe_allow_html=True)

        with cols[2]:
            # Bouton Entreprise
            if st.button(enterprise_name if enterprise_name else 'Entreprise', key="breadcrumb_enterprise"):
                st.session_state['current_project'] = None
                st.rerun()

        with cols[3]:
            st.markdown('<span style="color: var(--text-secondary); line-height: 2.5;">›</span>', unsafe_allow_html=True)

        with cols[4]:
            # Projet actuel (non cliquable)
            st.markdown(f'<div style="line-height: 2.5; font-weight: 600; color: var(--text-primary);">{projet["nom"]}</div>', unsafe_allow_html=True)

    # Header projet moderne simplifié (juste le titre et les stats)
    st.markdown("---")

    matchings_count = projet.get('matchings_count', 0)
    st.markdown(f"""
    <div style="padding: 0.5rem 0;">
        <h2 style="margin: 0; color: var(--text-primary); font-size: 1.6rem; font-weight: 700;">
            <span class="material-symbols-outlined">folder_open</span> {projet['nom']}
        </h2>
        <p style="margin: 0.25rem 0 0 0; color: var(--text-secondary); font-size: 0.9rem;">
            {matchings_count} matching(s) effectué(s)
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
