"""
Router CVs - Parsing et gestion des CVs
"""

import json
import asyncio
import hashlib
from io import BytesIO
import mimetypes
import os
import shutil
import tempfile
from zipfile import BadZipFile, ZipFile
from pathlib import Path
from typing import List, Dict
from urllib.parse import quote
from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
import logging

from api.dependencies import (
    get_current_user,
    get_project_tenant_context,
    require_project_writer,
    resolve_project_or_404,
)
from brainrh.models.auth import UserDB, UserRole
from brainrh.services.request_limiter import InMemoryRateLimiter
from brainrh.services.auth_service import (
    TenantContext,
    list_accessible_enterprise_ids,
    list_direct_project_grant_ids,
)
from brainrh.settings import (
    get_max_batch_upload_size_bytes,
    get_max_single_upload_size_bytes,
    get_parse_rate_limit_requests,
    get_parse_rate_limit_window_seconds,
)
from lib.models import CVParseResponse, CVParseResult, CV
from lib.parallel_engine import parse_cvs_parallel_async, parse_cvs_parallel_sync
from unified_project_manager import UnifiedProjectManager
from brainrh.services import CVService, EnterpriseService, CVFileService, ProjectService
from brainrh.services.file_storage import FileStorage
from brainrh.database import get_session
from brainrh.services.talent_profile_service import TalentProfileService
from brainrh.services.resume_service import ResumeService
from brainrh.services.application_service import ApplicationService

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialiser unified project manager
project_manager = UnifiedProjectManager(enterprises_folder="enterprises")

ALLOWED_CV_EXTENSIONS = {".pdf", ".docx"}
MAX_DOCX_ENTRY_COUNT = 300
MAX_DOCX_UNCOMPRESSED_SIZE_BYTES = 50 * 1024 * 1024


def _parse_identity(request: Request, user: UserDB) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{user.id}:{client_ip}"


def _enforce_parse_rate_limit(request: Request, user: UserDB) -> None:
    allowed, retry_after = InMemoryRateLimiter.consume(
        bucket="cv-parse",
        key=_parse_identity(request, user),
        limit=get_parse_rate_limit_requests(),
        window_seconds=get_parse_rate_limit_window_seconds(),
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Trop de demandes de parsing. Réessayez plus tard.",
            headers={"Retry-After": str(retry_after)},
        )


def _validate_pdf_payload(content: bytes, filename: str) -> None:
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail=f"Type de fichier invalide pour '{filename or 'inconnu'}'.",
        )


def _validate_docx_payload(content: bytes, filename: str) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise HTTPException(
                    status_code=400,
                    detail=f"Structure DOCX invalide pour '{filename or 'inconnu'}'.",
                )
            if len(infos) > MAX_DOCX_ENTRY_COUNT:
                raise HTTPException(
                    status_code=400,
                    detail=f"Structure DOCX trop complexe pour '{filename or 'inconnu'}'.",
                )
            total_uncompressed = 0
            for info in infos:
                if info.file_size < 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Structure DOCX invalide pour '{filename or 'inconnu'}'.",
                    )
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"DOCX trop volumineux après décompression: {filename}.",
                    )
    except HTTPException:
        raise
    except BadZipFile as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Structure DOCX invalide pour '{filename or 'inconnu'}'.",
        ) from exc


def _validate_cv_payload(content: bytes, suffix: str, filename: str) -> None:
    if suffix == ".pdf":
        _validate_pdf_payload(content, filename)
        return
    if suffix == ".docx":
        _validate_docx_payload(content, filename)
        return
    raise HTTPException(
        status_code=400,
        detail=f"Type de fichier non supporté pour '{filename or 'inconnu'}'.",
    )


async def _read_upload_payloads(files: List[UploadFile]) -> list[dict]:
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    max_single = get_max_single_upload_size_bytes()
    max_batch = get_max_batch_upload_size_bytes()
    batch_size = 0
    payloads: list[dict] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        suffix = Path(filename).suffix.lower() or ".pdf"
        if suffix not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Type de fichier non supporté pour '{filename or 'inconnu'}'.",
            )

        content = await upload.read()
        file_size = len(content)
        if file_size == 0:
            raise HTTPException(status_code=400, detail=f"Fichier vide: {filename or 'inconnu'}")
        if file_size > max_single:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier trop volumineux: {filename}. Limite {max_single} octets.",
            )
        _validate_cv_payload(content, suffix, filename)

        batch_size += file_size
        if batch_size > max_batch:
            raise HTTPException(
                status_code=413,
                detail=f"Volume total trop important. Limite {max_batch} octets.",
            )

        payloads.append(
            {
                "filename": filename,
                "content": content,
                "content_type": upload.content_type,
                "suffix": suffix,
            }
        )

    return payloads


@router.post("/parse", response_model=CVParseResponse)
async def parse_cvs(
    request: Request,
    files: List[UploadFile] = File(...),
    model: str | None = Query(default=None, description="Modèle LLM legacy à utiliser"),
    concurrency: int = Query(default=25, ge=1, le=50, description="CVs traités en parallèle"),
    qps: float = Query(default=10.0, ge=0.1, le=20.0, description="Requêtes/seconde max"),
    current_user: UserDB = Depends(get_current_user),
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
    _enforce_parse_rate_limit(request, current_user)
    file_payloads = await _read_upload_payloads(files)

    # Sauvegarder les fichiers temporairement
    temp_dir = Path(tempfile.mkdtemp(prefix="brainrh-cvs-"))
    temp_files = []
    try:
        for payload in file_payloads:
            suffix = payload["suffix"]
            fd, raw_path = tempfile.mkstemp(dir=temp_dir, suffix=suffix)
            tmp_path = Path(raw_path)
            with os.fdopen(fd, "wb") as buffer:
                buffer.write(payload["content"])
            temp_files.append(tmp_path)

        # Parsing parallèle avec lib/ depuis la route ASGI async.
        results = await parse_cvs_parallel_async(
            cv_files=temp_files,
            model=model,
            concurrency=concurrency,
            qps=qps,
        )

        return CVParseResponse(**results)

    except Exception as e:
        logger.exception("Erreur lors du parsing batch CV")
        raise HTTPException(status_code=500, detail="Erreur lors du parsing des CVs") from e

    finally:
        # Nettoyer fichiers temporaires
        for tmp_file in temp_files:
            try:
                tmp_file.unlink(missing_ok=True)
            except:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/parse/stream")
async def parse_cvs_stream(
    request: Request,
    files: List[UploadFile] = File(...),
    project_id: str = Query(default=None, description="ID du projet (optionnel)"),
    model: str | None = Query(default=None),
    concurrency: int = Query(default=25, ge=1, le=50),
    qps: float = Query(default=10.0, ge=0.1, le=20.0),
    current_user: UserDB = Depends(get_current_user),
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
    _enforce_parse_rate_limit(request, current_user)
    tenant_context = None
    if project_id:
        tenant_context = require_project_writer(project_id, current_user)

    # LIRE TOUS LES FICHIERS AVANT LE GÉNÉRATEUR
    # (FastAPI ferme les UploadFile dès que l'endpoint retourne avec StreamingResponse)
    logger.info(f"📥 Réception de {len(files)} fichiers pour parsing")
    files_data = await _read_upload_payloads(files)

    async def event_generator():
        temp_dir = Path(tempfile.mkdtemp(prefix="brainrh-cvs-"))
        temp_files = []
        original_filenames = {}  # Mapping: temp_path -> original_filename
        file_hashes: Dict[str, str] = {}  # Mapping: temp_path -> sha256_digest

        try:
            # Sauvegarder fichiers temporairement EN GARDANT le nom original
            for file_data in files_data:
                logger.info(f"🔍 Traitement de {file_data['filename']}...")
                suffix = Path(file_data['filename'] or "").suffix or ".pdf"
                fd, raw_path = tempfile.mkstemp(dir=temp_dir, suffix=suffix)
                tmp_path = Path(raw_path)

                content = file_data['content']
                logger.info(f"  📝 Contenu récupéré: {len(content)} bytes")

                # Écrire le fichier
                with os.fdopen(fd, "wb") as buffer:
                    buffer.write(content)
                    buffer.flush()

                # Vérifier que le fichier existe et est lisible
                if tmp_path.exists():
                    file_size = tmp_path.stat().st_size
                    logger.info(f"  ✅ Fichier temporaire créé: {tmp_path.name} ({file_size} bytes)")
                else:
                    logger.error(f"  ❌ Le fichier temporaire n'existe pas: {tmp_path}")
                    raise FileNotFoundError(f"Impossible de créer le fichier temporaire: {tmp_path}")

                temp_files.append(tmp_path)
                # Garder le mapping
                original_filenames[str(tmp_path)] = file_data['filename']

                # Calculer le hash SHA256 du fichier
                file_hash = hashlib.sha256(content).hexdigest()
                file_hashes[str(tmp_path)] = file_hash

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
                    enterprise_id = tenant_context.enterprise_id if tenant_context else None
                    project = project_manager.get_project(project_id, enterprise_id)
                    if project:
                        # Utiliser get_project_path pour trouver le bon chemin
                        project_path = project_manager.get_project_path(project_id, enterprise_id)
                        if project_path:
                            # Créer le dossier cvs_parsed s'il n'existe pas
                            cvs_parsed_dir = project_path / "cvs_parsed"
                            cvs_parsed_dir.mkdir(parents=True, exist_ok=True)

                            # Créer le dossier cvs_original/ pour stocker les fichiers sources
                            cvs_original_dir = project_path / "cvs_original"
                            cvs_original_dir.mkdir(parents=True, exist_ok=True)

                            # Construire le référentiel des hash existants
                            existing_hashes: Dict[str, str] = {}  # hash -> filename
                            try:
                                existing_cvs = CVService.list_by_project(project_id)
                                for cv_meta in existing_cvs:
                                    file_path = cv_meta.get("file_path")
                                    if file_path:
                                        existing_bytes = FileStorage.load_bytes(file_path)
                                        existing_hash = hashlib.sha256(existing_bytes).hexdigest()
                                        existing_hashes[existing_hash] = cv_meta.get("filename")
                                logger.info(f"📋 Référentiel construit: {len(existing_hashes)} hash existants")
                            except Exception as hash_err:
                                logger.warning(f"⚠️ Erreur construction référentiel hash: {hash_err}")

                            # Cache local pour éviter les collisions dans le même batch
                            used_filenames_in_batch = set()
                            # Cache pour détecter les doublons dans le batch actuel
                            batch_hashes: Dict[str, str] = {}  # hash -> filename

                            # Sauvegarder chaque CV parsé avec succès
                            for result in results['results']:
                                if result.success and result.data:
                                    # Garder en mémoire le nom fourni par l'utilisateur
                                    original_filename = result.filename

                                    # DÉTECTION DE DOUBLON PAR HASH
                                    # Retrouver le hash du fichier uploadé
                                    current_hash = None
                                    source_temp_file = None
                                    for temp_path_str, original_name in original_filenames.items():
                                        if original_name == original_filename:
                                            current_hash = file_hashes.get(temp_path_str)
                                            source_temp_file = Path(temp_path_str)
                                            break

                                    # Vérifier si doublon existant dans le projet
                                    if current_hash and current_hash in existing_hashes:
                                        existing_filename = existing_hashes[current_hash]
                                        logger.info(
                                            f"🛑 CV dupliqué détecté : '{original_filename}' "
                                            f"identique à '{existing_filename}' (hash={current_hash[:8]}...)"
                                        )
                                        # Émettre événement SSE pour informer le frontend
                                        duplicate_event = {
                                            "type": "duplicate",
                                            "filename": original_filename,
                                            "existing_filename": existing_filename,
                                            "reason": "Fichier identique déjà présent dans le projet"
                                        }
                                        yield f"event: duplicate\n"
                                        yield f"data: {json.dumps(duplicate_event)}\n\n"
                                        continue  # Skip save/indexation

                                    # Vérifier si doublon dans le batch actuel
                                    if current_hash and current_hash in batch_hashes:
                                        first_filename = batch_hashes[current_hash]
                                        logger.info(
                                            f"🛑 CV dupliqué détecté dans le batch : '{original_filename}' "
                                            f"identique à '{first_filename}' (hash={current_hash[:8]}...)"
                                        )
                                        # Émettre événement SSE pour informer le frontend
                                        duplicate_event = {
                                            "type": "duplicate",
                                            "filename": original_filename,
                                            "existing_filename": first_filename,
                                            "reason": "Fichier dupliqué dans le même batch"
                                        }
                                        yield f"event: duplicate\n"
                                        yield f"data: {json.dumps(duplicate_event)}\n\n"
                                        continue  # Skip save/indexation

                                    # Pas de doublon → ajouter au cache batch
                                    if current_hash:
                                        batch_hashes[current_hash] = original_filename

                                    # DÉTECTION DE COLLISION - Générer nom unique si nécessaire
                                    final_filename, collision_detected = CVService.get_unique_filename(
                                        project_id=project_id,
                                        original_filename=original_filename
                                    )

                                    # Vérifier collision dans le batch en cours (race condition)
                                    path = Path(final_filename)
                                    base = path.stem
                                    ext = path.suffix
                                    json_name = f"{base}.json"
                                    counter = 0

                                    while json_name in used_filenames_in_batch:
                                        counter += 1
                                        final_filename = f"{base}_{counter}{ext}"
                                        json_name = f"{base}_{counter}.json"
                                        collision_detected = True

                                    # Marquer ce nom comme utilisé dans le batch
                                    used_filenames_in_batch.add(json_name)

                                    if collision_detected:
                                        logger.warning(
                                            "🔄 Collision détectée pour '%s' → renommé en '%s'",
                                            original_filename,
                                            final_filename
                                        )

                                    # Utiliser le nom final (original ou avec suffixe)
                                    result.filename = final_filename
                                    if result.data:
                                        result.data.cv = final_filename

                                    cv_filename = Path(final_filename).stem + ".json"
                                    cv_path = cvs_parsed_dir / cv_filename
                                    CVFileService.save_cv_json(str(cv_path), result.data.model_dump())
                                    logger.info(f"✅ CV sauvegardé: {cv_filename}")

                                    # Copier le fichier source (PDF/DOCX) dans cvs_original/
                                    original_file_path_rel = None
                                    try:
                                        # Retrouver le fichier temp correspondant à ce CV
                                        source_temp_file = None
                                        temp_key_to_remove = None
                                        for temp_path_str, original_name in original_filenames.items():
                                            if original_name == original_filename:
                                                source_temp_file = Path(temp_path_str)
                                                temp_key_to_remove = temp_path_str
                                                break

                                        if temp_key_to_remove is not None:
                                            original_filenames.pop(temp_key_to_remove, None)

                                        if source_temp_file and source_temp_file.exists():
                                            # Copier vers cvs_original/ avec le nom original
                                            original_dest = cvs_original_dir / result.filename
                                            FileStorage.save_local_file(str(original_dest), source_temp_file)
                                            logger.info(f"📄 Fichier original copié: {result.filename}")

                                            # Calculer le chemin relatif pour file_path
                                            original_file_path_rel = FileStorage.resolve_relative_path(original_dest)
                                    except Exception as copy_err:
                                        logger.warning(f"⚠️ Impossible de copier le fichier original pour {result.filename}: {copy_err}")

                                    # Indexer dans cv_meta
                                    try:
                                        cv_data = result.data.model_dump()
                                        identite = cv_data.get("identite", {})
                                        candidat_nom = identite.get("nom")
                                        if identite.get("prenom"):
                                            candidat_nom = f"{identite.get('nom')} {identite.get('prenom')}" if candidat_nom else identite.get("prenom")

                                        json_path_rel = FileStorage.resolve_relative_path(cv_path)

                                        CVService.create_or_update_cv({
                                            "filename": cv_filename,
                                            "project_id": project_id,
                                            "json_path": json_path_rel,
                                            "file_path": original_file_path_rel,  # Chemin relatif du PDF/DOCX original
                                            "candidat_nom": candidat_nom,
                                            "candidat_titre": cv_data.get("titre")
                                        })
                                        logger.info(f"📇 CV indexé (legacy): {candidat_nom or cv_filename}")

                                        # BMT-NEXT-019: Shadow Write
                                        try:
                                            enterprise_id = project.get("enterprise_id")
                                            if enterprise_id:
                                                with get_session() as session:
                                                    identite = cv_data.get("identite", {})
                                                    email = identite.get("email") or f"dummy_{final_filename}@example.com"
                                                    first_name = identite.get("prenom")
                                                    last_name = identite.get("nom")
                                                    phone = identite.get("telephone")
                                                    if isinstance(phone, list):
                                                        phone = phone[0] if phone else None

                                                    # Retrieve or create profile
                                                    profiles = TalentProfileService.list_profiles(session, enterprise_id, email=email)
                                                    if profiles:
                                                        talent = profiles[0]
                                                    else:
                                                        talent = TalentProfileService.create_profile(
                                                            session,
                                                            enterprise_id=enterprise_id,
                                                            email=email,
                                                            first_name=first_name,
                                                            last_name=last_name,
                                                            phone=phone
                                                        )

                                                    # ResumeVersion
                                                    resume = ResumeService.create_version(
                                                        session,
                                                        talent_profile_id=talent.id,
                                                        enterprise_id=enterprise_id,
                                                        storage_path=original_file_path_rel,
                                                        parsed_json_str=json.dumps(cv_data, ensure_ascii=False)
                                                    )

                                                    # Application
                                                    ApplicationService.create_application(
                                                        session,
                                                        talent_profile_id=talent.id,
                                                        project_id=project_id,
                                                        enterprise_id=enterprise_id,
                                                        resume_version_id=resume.id
                                                    )
                                                    logger.info(f"✅ Shadow write complet pour {email} (Talent #{talent.id}, Resume #{resume.id})")
                                        except Exception as shadow_err:
                                            logger.warning(f"⚠️ Erreur Shadow write pour {final_filename}: {shadow_err}")


                                    except Exception as idx_err:
                                        logger.info(f"❌ Erreur indexation CV {cv_filename}: {idx_err}")
                except Exception as e:
                    logger.info(f"Erreur lors de la sauvegarde des CVs dans le projet: {e}")

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
            # Log détaillé de l'erreur avec traceback complet
            import traceback
            full_traceback = traceback.format_exc()
            logger.exception("❌ ERREUR PARSING SSE - Trace complète:")
            logger.error(f"❌ PARSING ERROR:\n{full_traceback}")
            logger.error(f"Type d'erreur: {type(e).__name__}")
            logger.error(f"Message: {str(e)}")
            logger.error(f"Nombre de fichiers traités: {len(temp_files)}")
            logger.error(f"Fichiers temp: {[str(f) for f in temp_files]}")

            # Événement error
            yield f"event: error\n"
            yield f"data: {json.dumps({'code': 'PARSING_ERROR', 'message': 'Erreur lors du parsing des CVs'})}\n\n"

        finally:
            # Nettoyer fichiers temporaires
            for tmp_file in temp_files:
                try:
                    tmp_file.unlink(missing_ok=True)
                except Exception:
                    pass
            shutil.rmtree(temp_dir, ignore_errors=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/all", response_model=List[CV])
async def list_all_cvs(current_user: UserDB = Depends(get_current_user)):
    """
    Liste tous les CVs parsés de tous les projets

    **Retourne:**
    - Liste de tous les CVs parsés avec leurs métadonnées complètes
    """
    try:
        # Utiliser CVService pour lister tous les CVs (indexés dans cv_meta)
        if current_user.role == UserRole.platform_admin:
            cv_metas = CVService.list_all()
        else:
            cv_metas = []
            seen_pairs: set[tuple[str, str]] = set()
            allowed_enterprise_ids = set(
                list_accessible_enterprise_ids(current_user, required_roles={UserRole.viewer})
            )
            for enterprise_id in allowed_enterprise_ids:
                for cv_meta in CVService.list_by_enterprise(enterprise_id):
                    pair = (cv_meta["project_id"], cv_meta["filename"])
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    cv_metas.append(cv_meta)
            for project_id in list_direct_project_grant_ids(
                current_user,
                required_roles={UserRole.viewer},
            ):
                project = project_manager.get_project(project_id)
                if not project:
                    continue
                project_enterprise_id = project.get("enterprise_id")
                if not project_enterprise_id or project_enterprise_id in allowed_enterprise_ids:
                    continue
                for cv_meta in CVService.list_by_enterprise(project_enterprise_id):
                    if cv_meta.get("project_id") != project_id:
                        continue
                    pair = (cv_meta["project_id"], cv_meta["filename"])
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    cv_metas.append(cv_meta)

        # Récupérer tous les projets et entreprises
        projects_map = {}
        enterprises_map = {}
        try:
            # Charger toutes les entreprises
            all_enterprises = EnterpriseService.list_enterprise_summaries()
            for ent in all_enterprises:
                enterprises_map[ent["id"]] = ent["nom"]

            # Charger tous les projets
            all_projects = ProjectService.list_project_summaries()
            for proj in all_projects:
                ent_id = proj.get("enterprise_id")
                projects_map[proj["id"]] = {
                    "enterprise_id": ent_id,
                    "enterprise_nom": enterprises_map.get(ent_id) if ent_id else None
                }
        except Exception as e:
            logger.warning(f"Impossible de charger les projets: {e}")

        cv_payloads = await asyncio.to_thread(
            CVFileService.load_cv_json_batch,
            [cv_meta["json_path"] for cv_meta in cv_metas],
        )

        cvs = []
        for cv_meta, loaded_cv_data in zip(cv_metas, cv_payloads):
            try:
                cv_data = dict(loaded_cv_data) if loaded_cv_data else None
                if cv_data:

                        # Ajouter les métadonnées projet/entreprise
                        project_id = cv_meta.get("project_id")
                        if project_id and project_id in projects_map:
                            cv_data["project_id"] = project_id
                            cv_data["enterprise_id"] = projects_map[project_id].get("enterprise_id")
                            cv_data["enterprise_nom"] = projects_map[project_id].get("enterprise_nom")

                        cvs.append(CV(**cv_data))
            except Exception as e:
                logger.info(f"Erreur lecture CV {cv_meta['filename']}: {e}")
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
async def list_project_cvs(
    project_id: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Liste tous les CVs parsés d'un projet

    **Paramètres:**
    - `project_id`: ID du projet

    **Retourne:**
    - Liste des CVs parsés avec leurs métadonnées complètes
    """
    try:
        project = resolve_project_or_404(project_id)

        # Récupérer enterprise_id et enterprise_nom du projet
        enterprise_id = project.get("enterprise_id")
        enterprise_nom = None
        if enterprise_id:
            try:
                enterprise_data = EnterpriseService.get_enterprise(enterprise_id)
                if enterprise_data:
                    enterprise_nom = enterprise_data["nom"]
            except Exception as e:
                logger.warning(f"Impossible de charger l'entreprise {enterprise_id}: {e}")

        # BMT-NEXT-023: Lecture depuis ApplicationDB avec fallback legacy
        cvs = []
        with get_session() as session:
            candidates = ApplicationService.get_project_candidates(session, project_id)

            for cand in candidates:
                if cand.get("cv_data"):
                    try:
                        cv_data = cand["cv_data"]
                        # Ajouter les métadonnées projet/entreprise
                        cv_data["project_id"] = project_id
                        cv_data["enterprise_id"] = enterprise_id
                        cv_data["enterprise_nom"] = enterprise_nom

                        # Si nom_complet est dispo mais pas au bon endroit, on l'injecte
                        if not cv_data.get("identite", {}).get("nom") and cand.get("last_name"):
                            if "identite" not in cv_data:
                                cv_data["identite"] = {}
                            cv_data["identite"]["nom"] = cand["last_name"]
                            cv_data["identite"]["prenom"] = cand.get("first_name")

                        cvs.append(CV(**cv_data))
                    except Exception as e:
                        logger.info(f"Erreur mapping CV pour le candidat {cand.get('email')}: {e}")
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


@router.get("/projects/{project_id}/cvs/{cv_id}/download")
async def download_project_cv(
    project_id: str,
    cv_id: str,
    download: bool = True,
    proxy: bool = False,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    del tenant
    metadata = CVService.get_cv_metadata(project_id, cv_id)
    if not metadata or not metadata.get("file_path"):
        raise HTTPException(status_code=404, detail=f"CV source '{cv_id}' introuvable")

    storage_path = metadata["file_path"]
    original_name = Path(storage_path).name or Path(cv_id).name
    disposition = "attachment" if download else "inline"
    media_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    if proxy:
        try:
            payload = FileStorage.load_bytes(storage_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"CV source '{cv_id}' introuvable") from exc

        safe_name = original_name.replace("\\", "_").replace('"', '\\"')
        encoded_name = quote(original_name)
        return StreamingResponse(
            iter([payload]),
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f"{disposition}; filename=\"{safe_name}\"; filename*=UTF-8''{encoded_name}"
                ),
            },
        )

    signed_url = FileStorage.generate_download_url(
        storage_path,
        filename=original_name,
        disposition=disposition,
    )
    if signed_url:
        return RedirectResponse(url=signed_url, status_code=307)

    try:
        absolute_path = FileStorage.validate_and_resolve_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not absolute_path.exists() or not absolute_path.is_file():
        raise HTTPException(status_code=404, detail=f"CV source '{cv_id}' introuvable")

    response = FileResponse(
        path=str(absolute_path),
        filename=original_name,
        media_type=media_type,
    )
    response.headers["Content-Disposition"] = f'{disposition}; filename="{original_name}"'
    return response


@router.get("/{cv_id}", response_model=CV)
async def get_cv(cv_id: str, current_user: UserDB = Depends(get_current_user)):
    """
    Récupère un CV parsé par son ID (nom de fichier)

    **Note:** Cette route nécessite un système de stockage persistant.
    Pour l'instant, non implémentée (fichiers temporaires seulement).
    """
    del current_user
    raise HTTPException(status_code=501, detail="Endpoint non implémenté (stockage persistant requis)")


@router.delete("/{cv_id}")
async def delete_cv(cv_id: str, current_user: UserDB = Depends(get_current_user)):
    """
    Supprime un CV parsé (fichier JSON + entrée DB)

    **Paramètres:**
    - `cv_id`: Nom du fichier CV (identifiant unique)

    **Retourne:**
    - Message de confirmation
    """
    try:
        if current_user.role != UserRole.platform_admin:
            raise HTTPException(status_code=403, detail="Suppression réservée au platform_admin")
        # cv_id = filename du CV
        success = CVService.delete_cv(filename=cv_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"CV '{cv_id}' introuvable")

        logger.info(f"✅ CV supprimé: {cv_id}")
        return {"message": f"CV '{cv_id}' supprimé avec succès"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression CV {cv_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression du CV: {str(e)}"
        )
