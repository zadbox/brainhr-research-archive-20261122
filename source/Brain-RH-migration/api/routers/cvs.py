"""
Router CVs - Parsing et gestion des CVs
"""

import json
import asyncio
from pathlib import Path
from typing import List
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from tempfile import NamedTemporaryFile

from lib.models import CVParseResponse, CVParseResult, CV
from lib.parallel_engine import parse_cvs_parallel_sync
from lib.cv_parsing import parse_cv_from_file, get_openai_client

import sys
sys.path.insert(0, '/Users/houssam/Downloads/Brain RH migration')
from project_manager import ProjectManager

router = APIRouter()

# Initialiser project manager
project_manager = ProjectManager(projects_folder="projects")


@router.post("/parse", response_model=CVParseResponse)
async def parse_cvs(
    files: List[UploadFile] = File(...),
    model: str = Query(default="gpt-5-mini", description="Modèle LLM à utiliser"),
    concurrency: int = Query(default=500, ge=1, le=1000, description="CVs traités en parallèle"),
    qps: float = Query(default=100.0, ge=0.1, le=100.0, description="Requêtes/seconde max")
):
    """
    Parse plusieurs CVs en mode batch

    Retourne les résultats une fois tous les CVs traités.
    Pour un feedback temps-réel, utiliser `/cvs/parse/stream`

    **Paramètres:**
    - `files`: Fichiers CVs (PDF ou DOCX)
    - `model`: Modèle LLM (default: gpt-5-mini)
    - `concurrency`: Nombre max de CVs traités en parallèle (default: 500)
    - `qps`: Requêtes par seconde max vers OpenAI (default: 10.0)

    **Retourne:**
    - `success_count`: Nombre de CVs parsés avec succès
    - `failed_count`: Nombre de CVs en échec
    - `total`: Nombre total de CVs
    - `results`: Liste des résultats (CVParseResult)
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    # Sauvegarder les fichiers temporairement
    temp_files = []
    try:
        for file in files:
            # Créer fichier temporaire avec bonne extension
            suffix = Path(file.filename).suffix
            with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                temp_files.append(Path(tmp.name))

        # Parsing parallèle avec lib/
        results = parse_cvs_parallel_sync(
            cv_files=temp_files,
            model=model,
            concurrency=concurrency,
            qps=qps
        )

        return CVParseResponse(**results)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du parsing: {str(e)}")

    finally:
        # Nettoyer fichiers temporaires
        for tmp_file in temp_files:
            try:
                tmp_file.unlink()
            except:
                pass


@router.post("/parse/stream")
async def parse_cvs_stream(
    files: List[UploadFile] = File(...),
    project_id: str = Query(default=None, description="ID du projet (optionnel)"),
    model: str = Query(default="gpt-5-mini"),
    concurrency: int = Query(default=500, ge=1, le=1000),
    qps: float = Query(default=100.0, ge=0.1, le=100.0)
):
    """
    Parse plusieurs CVs avec streaming SSE (Server-Sent Events)

    Envoie des événements en temps réel pendant le traitement:
    - `progress`: Progression (current, total, progress)
    - `result`: CV parsé (success, data, error)
    - `done`: Fin du traitement (summary)
    - `error`: Erreur globale

    **Consommation côté client (JavaScript):**
    ```javascript
    const eventSource = new EventSource('/api/v1/cvs/parse/stream');

    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      console.log(`${data.current}/${data.total}`);
    });

    eventSource.addEventListener('result', (e) => {
      const data = JSON.parse(e.data);
      console.log('CV parsé:', data);
    });

    eventSource.addEventListener('done', (e) => {
      const data = JSON.parse(e.data);
      console.log('Terminé:', data.summary);
      eventSource.close();
    });
    ```
    """
    if not files:
        async def error_stream():
            yield f"event: error\n"
            yield f"data: {json.dumps({'code': 'NO_FILES', 'message': 'Aucun fichier fourni'})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_generator():
        temp_files = []
        original_filenames = {}  # Mapping: temp_path -> original_filename

        try:
            # Sauvegarder fichiers temporairement EN GARDANT le nom original
            for file in files:
                suffix = Path(file.filename).suffix
                with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    content = await file.read()
                    tmp.write(content)
                    temp_path = Path(tmp.name)
                    temp_files.append(temp_path)
                    # Garder le mapping
                    original_filenames[str(temp_path)] = file.filename

            total = len(temp_files)
            success_count = 0
            failed_count = 0

            # Queue pour communiquer entre threads
            progress_queue = asyncio.Queue()

            # Callback de progression (appelé depuis le thread de parsing)
            def progress_callback(current, total_cvs):
                # Utiliser call_soon_threadsafe pour émettre depuis un thread
                asyncio.get_event_loop().call_soon_threadsafe(
                    progress_queue.put_nowait,
                    {'current': current, 'total': total_cvs}
                )

            # Lancer le parsing dans un thread séparé
            parse_task = asyncio.create_task(
                asyncio.to_thread(
                    parse_cvs_parallel_sync,
                    cv_files=temp_files,
                    model=model,
                    concurrency=concurrency,
                    qps=qps,
                    progress_callback=progress_callback
                )
            )

            # Émettre les événements progress au fur et à mesure
            while not parse_task.done():
                try:
                    # Attendre un événement progress avec timeout
                    progress_data = await asyncio.wait_for(progress_queue.get(), timeout=0.1)

                    # Émettre événement progress
                    current = progress_data['current']
                    total_cvs = progress_data['total']
                    progress = current / total_cvs if total_cvs > 0 else 0.0

                    yield f"event: progress\n"
                    yield f"data: {json.dumps({'step': 'parsing', 'current': current, 'total': total_cvs, 'progress': progress, 'message': f'Parsing {current}/{total_cvs} CVs...'})}\n\n"

                except asyncio.TimeoutError:
                    # Pas de nouvel événement, continuer à attendre
                    continue

            # Récupérer les résultats finaux
            results = await parse_task

            # Remplacer les noms temporaires par les noms originaux
            for result in results['results']:
                temp_filename = result.filename
                # Chercher dans le mapping (avec ou sans extension)
                for temp_path, original_name in original_filenames.items():
                    if Path(temp_path).name == temp_filename or str(temp_path) == temp_filename:
                        result.filename = original_name
                        if result.data:
                            result.data.cv = original_name
                        break

            # Sauvegarder les CVs dans le projet si project_id fourni
            if project_id:
                try:
                    project = project_manager.get_project(project_id)
                    if project:
                        # Créer le dossier cvs_parsed s'il n'existe pas
                        cvs_parsed_dir = Path("projects") / project_id / "cvs_parsed"
                        cvs_parsed_dir.mkdir(parents=True, exist_ok=True)

                        # Sauvegarder chaque CV parsé avec succès
                        for result in results['results']:
                            if result.success and result.data:
                                # Utiliser le nom original (maintenant corrigé)
                                cv_filename = Path(result.filename).stem + ".json"
                                cv_path = cvs_parsed_dir / cv_filename
                                with open(cv_path, 'w', encoding='utf-8') as f:
                                    json.dump(result.data.model_dump(), f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"Erreur lors de la sauvegarde des CVs dans le projet: {e}")

            # Émettre les résultats
            for result in results['results']:
                if result.success:
                    success_count += 1
                else:
                    failed_count += 1

                # Événement result
                yield f"event: result\n"
                yield f"data: {result.model_dump_json()}\n\n"

            # Événement done
            yield f"event: done\n"
            yield f"data: {json.dumps({'summary': {'success_count': success_count, 'failed_count': failed_count, 'total': total}})}\n\n"

        except Exception as e:
            # Événement error
            yield f"event: error\n"
            yield f"data: {json.dumps({'code': 'PARSING_ERROR', 'message': str(e)})}\n\n"

        finally:
            # Nettoyer fichiers temporaires
            for tmp_file in temp_files:
                try:
                    tmp_file.unlink()
                except:
                    pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/all", response_model=List[CV])
async def list_all_cvs():
    """
    Liste tous les CVs parsés de tous les projets

    **Retourne:**
    - Liste de tous les CVs parsés avec leurs métadonnées complètes
    """
    try:
        cvs = []

        # 1. Lire depuis le nouveau système: enterprises/{enterprise_id}/projects/{project_id}/cvs_parsed/
        enterprises_folder = Path("enterprises")
        if enterprises_folder.exists():
            for enterprise_dir in enterprises_folder.iterdir():
                if not enterprise_dir.is_dir() or enterprise_dir.name.startswith('_'):
                    continue

                projects_dir = enterprise_dir / "projects"
                if not projects_dir.exists():
                    continue

                for project_dir in projects_dir.iterdir():
                    if not project_dir.is_dir() or project_dir.name.startswith('_'):
                        continue

                    cvs_parsed_dir = project_dir / "cvs_parsed"
                    if not cvs_parsed_dir.exists():
                        continue

                    for cv_file in cvs_parsed_dir.glob("*.json"):
                        try:
                            with open(cv_file, 'r', encoding='utf-8') as f:
                                cv_data = json.load(f)
                                cvs.append(CV(**cv_data))
                        except Exception as e:
                            print(f"Erreur lecture CV {cv_file}: {e}")
                            continue

        # 2. Lire depuis l'ancien système: projects/{project_id}/cvs_parsed/
        old_projects_folder = Path("projects")
        if old_projects_folder.exists():
            for project_dir in old_projects_folder.iterdir():
                if not project_dir.is_dir() or project_dir.name.startswith('_'):
                    continue

                cvs_parsed_dir = project_dir / "cvs_parsed"
                if not cvs_parsed_dir.exists():
                    continue

                for cv_file in cvs_parsed_dir.glob("*.json"):
                    try:
                        with open(cv_file, 'r', encoding='utf-8') as f:
                            cv_data = json.load(f)
                            # Éviter les doublons (même nom de fichier)
                            if not any(cv.cv == cv_data.get('cv') for cv in cvs):
                                cvs.append(CV(**cv_data))
                    except Exception as e:
                        print(f"Erreur lecture CV {cv_file}: {e}")
                        continue

        # Trier par nom de fichier
        cvs.sort(key=lambda x: x.cv)

        return cvs

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des CVs: {str(e)}"
        )


@router.get("/projects/{project_id}/cvs", response_model=List[CV])
async def list_project_cvs(project_id: str):
    """
    Liste tous les CVs parsés d'un projet

    **Paramètres:**
    - `project_id`: ID du projet

    **Retourne:**
    - Liste des CVs parsés avec leurs métadonnées complètes
    """
    try:
        # Vérifier que le projet existe
        project = project_manager.get_project(project_id)
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Projet {project_id} introuvable"
            )

        # Chemin vers le dossier cvs_parsed du projet
        project_dir = Path("projects") / project_id
        cvs_parsed_dir = project_dir / "cvs_parsed"

        if not cvs_parsed_dir.exists():
            return []

        # Charger tous les fichiers JSON dans cvs_parsed/
        cvs = []
        for cv_file in cvs_parsed_dir.glob("*.json"):
            try:
                with open(cv_file, 'r', encoding='utf-8') as f:
                    cv_data = json.load(f)
                    # Créer un objet CV depuis les données
                    cvs.append(CV(**cv_data))
            except Exception as e:
                # Skip les fichiers corrompus
                print(f"Erreur lecture CV {cv_file}: {e}")
                continue

        # Trier par nom de fichier
        cvs.sort(key=lambda x: x.cv)

        return cvs

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des CVs: {str(e)}"
        )


@router.get("/{cv_id}", response_model=CV)
async def get_cv(cv_id: str):
    """
    Récupère un CV parsé par son ID (nom de fichier)

    **Note:** Cette route nécessite un système de stockage persistant.
    Pour l'instant, non implémentée (fichiers temporaires seulement).
    """
    raise HTTPException(status_code=501, detail="Endpoint non implémenté (stockage persistant requis)")


@router.delete("/{cv_id}")
async def delete_cv(cv_id: str):
    """
    Supprime un CV parsé

    **Note:** Non implémenté pour l'instant (stockage persistant requis)
    """
    raise HTTPException(status_code=501, detail="Endpoint non implémenté (stockage persistant requis)")
