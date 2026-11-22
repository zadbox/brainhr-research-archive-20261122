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


def apply_dark_mode_script():
    """Script JavaScript pour détecter et appliquer le thème dark mode"""
    return r"""
    <script>
        // Détecter et appliquer le thème Streamlit
        function applyTheme() {
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
            document.addEventListener('DOMContentLoaded', applyTheme);
        } else {
            applyTheme();
        }
        setInterval(applyTheme, 500);
    </script>
    """


def page_accueil_entreprises(em: EnterpriseManager):
    """
    Page d'accueil: liste des entreprises + création

    Args:
        em: Instance de EnterpriseManager
    """
    # CSS pour page d'accueil avec dark mode
    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght@300;400;500;600;700" rel="stylesheet">
    <style>
        /* Variables pour thème clair et sombre */
        :root {
            --bg-primary: #FFFFFF;
            --bg-secondary: #F7FAFC;
            --bg-card: #FFFFFF;
            --text-primary: #1B2B4A;
            --text-secondary: #718096;
            --border-color: #E2E8F0;
            --accent-blue: #4A90E2;
            --accent-cyan: #5BC0DE;
            --shadow-light: rgba(27, 43, 74, 0.08);
            --shadow-medium: rgba(27, 43, 74, 0.12);
        }

        [data-theme="dark"] {
            --bg-primary: #1A202C;
            --bg-secondary: #2D3748;
            --bg-card: #2D3748;
            --text-primary: #E2E8F0;
            --text-secondary: #A0AEC0;
            --border-color: #4A5568;
            --accent-blue: #63B3ED;
            --accent-cyan: #76E4F7;
            --shadow-light: rgba(0, 0, 0, 0.3);
            --shadow-medium: rgba(0, 0, 0, 0.5);
        }

        .stApp {
            background-color: var(--bg-primary);
            color: var(--text-primary);
        }

        section[data-testid="stSidebar"] {
            background-color: var(--bg-secondary) !important;
        }

        .section-header-home {
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-primary);
            padding-bottom: 0.75rem;
            border-bottom: 3px solid var(--accent-blue);
            position: relative;
            margin: 2rem 0 1.5rem 0;
        }

        .section-header-home::before {
            content: '';
            position: absolute;
            bottom: -3px;
            left: 0;
            width: 60px;
            height: 3px;
            background: var(--accent-cyan);
        }

        .enterprise-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-blue);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 8px var(--shadow-light);
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .enterprise-card:hover {
            box-shadow: 0 8px 16px var(--shadow-medium);
            transform: translateY(-2px);
            border-left-color: var(--accent-cyan);
        }

        .enterprise-title {
            margin: 0;
            color: var(--text-primary);
            font-size: 1.4rem;
            font-weight: 700;
        }

        .enterprise-meta {
            display: flex;
            gap: 2rem;
            margin: 1rem 0;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }

        .material-symbols-outlined {
            font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
            vertical-align: middle;
            margin-right: 0.25rem;
        }

        /* Force white text in sidebar for dark mode */
        section[data-testid="stSidebar"] * {
            color: var(--text-primary) !important;
        }
    </style>
    """ + apply_dark_mode_script(), unsafe_allow_html=True)

    # Header avec logo
    logo_base64 = get_base64_image('logorhplus.png')

    st.markdown(f"""
    <div style="text-align: center; padding: 1.5rem 0; margin-bottom: 2rem; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 2px 8px var(--shadow-light);">
        <img src="data:image/png;base64,{logo_base64}" style="max-width: 400px; height: auto; display: block; margin: 0 auto;" alt="BRAIN RH+">
        <h1 style="color: var(--text-primary); font-size: 1.8rem; margin: 1rem 0 0 0; font-weight: 700;">Plateforme de Matching CV/RH</h1>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-header-home"><span class="material-symbols-outlined">business</span>Mes Entreprises Clientes</div>', unsafe_allow_html=True)

    # Bouton création en haut
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("+ Nouvelle Entreprise", type="primary", use_container_width=True):
            st.session_state['show_create_enterprise_form'] = True

    # Formulaire de création entreprise
    if st.session_state.get('show_create_enterprise_form', False):
        with st.form("create_enterprise_form"):
            st.subheader("Ajouter une entreprise cliente")

            nom = st.text_input(
                "Nom de l'entreprise *",
                placeholder="Ex: Banque de France"
            )

            secteur = st.text_input(
                "Secteur d'activité",
                placeholder="Ex: Banque, Finance, Technologie..."
            )

            col_submit, col_cancel = st.columns(2)
            with col_submit:
                submitted = st.form_submit_button("Créer", use_container_width=True)
            with col_cancel:
                cancelled = st.form_submit_button("Annuler", use_container_width=True)

            if submitted:
                if not nom or len(nom.strip()) < 2:
                    st.error("Le nom doit contenir au moins 2 caractères")
                else:
                    entreprise = em.create_enterprise(nom.strip(), secteur.strip())
                    st.success(f"Entreprise '{entreprise['nom']}' créée avec succès!")
                    st.session_state['show_create_enterprise_form'] = False
                    st.rerun()

            if cancelled:
                st.session_state['show_create_enterprise_form'] = False
                st.rerun()

    # Liste des entreprises
    st.markdown("---")

    enterprises = em.list_enterprises()

    if not enterprises:
        st.info("Aucune entreprise trouvée. Créez votre première entreprise cliente pour commencer !")
    else:
        st.caption(f"{len(enterprises)} entreprise(s)")

        for enterprise in enterprises:
            enterprise_id = enterprise['id']

            # Métadonnées
            created = datetime.fromisoformat(enterprise['created_at']).strftime("%d/%m/%Y")
            projects_count = enterprise.get('projects_count', 0)
            secteur = enterprise.get('secteur', 'Non spécifié')

            # Card entreprise
            st.markdown(f"""
            <div class="enterprise-card">
                <div>
                    <h3 class="enterprise-title">{enterprise['nom']}</h3>
                </div>
                <div class="enterprise-meta">
                    <div><span class="material-symbols-outlined">category</span><strong>{secteur}</strong></div>
                    <div><span class="material-symbols-outlined">folder</span><strong>{projects_count}</strong> projet(s)</div>
                    <div><span class="material-symbols-outlined">calendar_today</span><strong>{created}</strong></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Bouton pour ouvrir l'entreprise
            col_open, col_delete = st.columns([3, 1])

            with col_open:
                if st.button("Voir les projets", key=f"open_ent_{enterprise_id}", use_container_width=True, type="primary"):
                    st.session_state['current_enterprise'] = enterprise_id
                    st.session_state['current_project'] = None  # Reset projet
                    st.rerun()

            with col_delete:
                if st.button("Supprimer", key=f"delete_ent_{enterprise_id}", use_container_width=True):
                    if projects_count > 0:
                        st.warning("Impossible de supprimer une entreprise avec des projets actifs")
                    else:
                        em.delete_enterprise(enterprise_id)
                        st.success("Entreprise supprimée")
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)


def page_accueil_projets(pm: ProjectManager, enterprise_id: str = None, enterprise_name: str = ""):
    """
    Page liste des projets pour une entreprise + création

    Args:
        pm: Instance de ProjectManager
        enterprise_id: ID de l'entreprise (optionnel pour compatibilité)
        enterprise_name: Nom de l'entreprise pour le fil d'Ariane
    """

    # CSS pour page d'accueil avec dark mode
    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght@300;400;500;600;700" rel="stylesheet">
    <style>
        /* Variables pour thème clair et sombre */
        :root {
            --bg-primary: #FFFFFF;
            --bg-secondary: #F7FAFC;
            --bg-card: #FFFFFF;
            --text-primary: #1B2B4A;
            --text-secondary: #718096;
            --border-color: #E2E8F0;
            --accent-blue: #4A90E2;
            --accent-cyan: #5BC0DE;
            --shadow-light: rgba(27, 43, 74, 0.08);
            --shadow-medium: rgba(27, 43, 74, 0.12);
        }

        [data-theme="dark"] {
            --bg-primary: #1A202C;
            --bg-secondary: #2D3748;
            --bg-card: #2D3748;
            --text-primary: #E2E8F0;
            --text-secondary: #A0AEC0;
            --border-color: #4A5568;
            --accent-blue: #63B3ED;
            --accent-cyan: #76E4F7;
            --shadow-light: rgba(0, 0, 0, 0.3);
            --shadow-medium: rgba(0, 0, 0, 0.5);
        }

        /* Appliquer le dark mode à toute la page Streamlit */
        .stApp {
            background-color: var(--bg-primary);
            color: var(--text-primary);
        }

        /* Sidebar dark mode */
        section[data-testid="stSidebar"] {
            background-color: var(--bg-secondary) !important;
        }

        section[data-testid="stSidebar"] .stMarkdown {
            color: var(--text-primary) !important;
        }

        .section-header-home {
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-primary);
            padding-bottom: 0.75rem;
            border-bottom: 3px solid var(--accent-blue);
            position: relative;
            margin: 2rem 0 1.5rem 0;
        }

        .section-header-home::before {
            content: '';
            position: absolute;
            bottom: -3px;
            left: 0;
            width: 60px;
            height: 3px;
            background: var(--accent-cyan);
        }

        .project-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-blue);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 8px var(--shadow-light);
            transition: all 0.3s ease;
        }

        .project-card:hover {
            box-shadow: 0 8px 16px var(--shadow-medium);
            transform: translateY(-2px);
            border-left-color: var(--accent-cyan);
        }

        .project-title {
            margin: 0;
            color: var(--text-primary);
            font-size: 1.3rem;
            font-weight: 700;
        }

        .status-badge {
            display: inline-block;
            margin-top: 0.5rem;
            padding: 0.3rem 0.9rem;
            border-radius: 16px;
            font-size: 0.8rem;
            font-weight: 600;
            color: white;
        }

        .status-active {
            background: linear-gradient(135deg, #48BB78 0%, #38A169 100%);
        }

        .status-archived {
            background: linear-gradient(135deg, #718096 0%, #4A5568 100%);
        }

        .project-meta {
            display: flex;
            gap: 2rem;
            margin: 1rem 0;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }

        .project-desc {
            color: var(--text-primary);
            margin: 0.5rem 0;
            line-height: 1.5;
        }

        .material-symbols-outlined {
            font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
            vertical-align: middle;
            margin-right: 0.25rem;
        }

        /* Force white text in sidebar for dark mode */
        section[data-testid="stSidebar"] * {
            color: var(--text-primary) !important;
        }
    </style>
    """ + apply_dark_mode_script(), unsafe_allow_html=True)

    # Header simple et compact avec logo
    logo_base64 = get_base64_image('logorhplus.png')

    st.markdown(f"""
    <div style="text-align: center; padding: 1.5rem 0; margin-bottom: 2rem; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 2px 8px var(--shadow-light);">
        <img src="data:image/png;base64,{logo_base64}" style="max-width: 400px; height: auto; display: block; margin: 0 auto;" alt="BRAIN RH+">
        <h1 style="color: var(--text-primary); font-size: 1.8rem; margin: 1rem 0 0 0; font-weight: 700;">Plateforme de Matching CV/RH</h1>
    </div>
    """, unsafe_allow_html=True)

    # Fil d'Ariane cliquable
    if enterprise_name:
        col_breadcrumb, col_new = st.columns([3, 1])

        with col_breadcrumb:
            # Boutons fil d'Ariane sur une ligne
            cols = st.columns([1, 0.1, 2.5])

            with cols[0]:
                # Bouton Accueil
                if st.button("Accueil", key="breadcrumb_home_proj"):
                    st.session_state['current_enterprise'] = None
                    st.session_state['current_project'] = None
                    st.rerun()

            with cols[1]:
                st.markdown('<span style="color: var(--text-secondary); line-height: 2.5;">›</span>', unsafe_allow_html=True)

            with cols[2]:
                # Entreprise actuelle (non cliquable car on y est)
                st.markdown(f'<div style="line-height: 2.5; font-weight: 600; color: var(--text-primary);">{enterprise_name}</div>', unsafe_allow_html=True)

        with col_new:
            if st.button("+ Nouveau Projet", type="primary", use_container_width=True):
                st.session_state['show_create_form'] = True

    st.markdown('<div class="section-header-home"><span class="material-symbols-outlined">folder</span>Projets de Recrutement</div>', unsafe_allow_html=True)

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
        st.info("Aucun projet trouvé. Créez votre premier projet pour commencer !")
    else:
        st.caption(f"{len(projects)} projet(s)")

        for projet_summary in projects:
            projet_id = projet_summary['id']

            # Charger les détails complets
            projet = pm.get_project(projet_id)
            if not projet:
                continue

            # Card projet professionnelle
            # Métadonnées
            created = datetime.fromisoformat(projet['created_at']).strftime("%d/%m/%Y")
            last_mod = datetime.fromisoformat(projet['last_modified'])
            now = datetime.now()
            delta = now - last_mod

            if delta.days > 0:
                activite = f"{delta.days}j"
            elif delta.seconds > 3600:
                activite = f"{delta.seconds // 3600}h"
            elif delta.seconds > 60:
                activite = f"{delta.seconds // 60}min"
            else:
                activite = "maintenant"

            matchings_count = projet.get('matchings_count', 0)
            status_badge = "Actif" if projet['status'] == "actif" else "Archivé"
            status_class = "status-active" if projet['status'] == "actif" else "status-archived"

            # Card HTML avec nouvelle charte graphique
            description_html = f'<p class="project-desc">{projet["description"][:200]}...</p>' if projet.get('description') else ''

            st.markdown(f"""
            <div class="project-card">
                <div>
                    <h3 class="project-title">{projet['nom']}</h3>
                    <span class="status-badge {status_class}">{status_badge}</span>
                </div>
                <div class="project-meta">
                    <div><span class="material-symbols-outlined">calendar_today</span><strong>{created}</strong></div>
                    <div><span class="material-symbols-outlined">schedule</span><strong>{activite}</strong></div>
                    <div><span class="material-symbols-outlined">analytics</span><strong>{matchings_count}</strong> matching(s)</div>
                </div>
                {description_html}
            </div>
            """, unsafe_allow_html=True)

            # Boutons en dessous
            col_open, col_archive = st.columns([3, 1])

            with col_open:
                if st.button("Ouvrir le projet", key=f"open_{projet_id}", use_container_width=True, type="primary"):
                    st.session_state['current_project'] = projet_id
                    st.rerun()

            with col_archive:
                if projet['status'] == "actif":
                    if st.button("Archiver", key=f"archive_{projet_id}", use_container_width=True):
                        pm.update_project(projet_id, {"status": "archive"})
                        st.success("Projet archivé")
                        st.rerun()
                else:
                    if st.button("Restaurer", key=f"restore_{projet_id}", use_container_width=True):
                        pm.update_project(projet_id, {"status": "actif"})
                        st.success("Projet restauré")
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)


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
