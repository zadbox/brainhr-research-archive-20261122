"""
Module de parsing parallèle des CVs
Utilise asyncio + Semaphore pour traiter plusieurs CVs simultanément
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any
import json
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv
import parseur_cv

load_dotenv()

# Client OpenAI async
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def parse_single_cv_async(
    cv_text: str,
    cv_filename: str,
    model: str = "gpt-5-mini",
    temperature: float = 0.1,
    semaphore: asyncio.Semaphore = None
) -> Dict[str, Any]:
    """
    Parse un CV de manière asynchrone avec GPT

    Args:
        cv_text: Texte extrait du CV
        cv_filename: Nom du fichier CV
        model: Modèle LLM à utiliser
        temperature: Température (0.1 pour extraction structurée)
        semaphore: Semaphore pour limiter la concurrence

    Returns:
        Dict avec données parsées ou erreur
    """
    async with semaphore if semaphore else asyncio.Semaphore(5):
        try:
            print(f"🔄 Parsing de {cv_filename}...")

            response = await client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": "Tu es un assistant qui analyse des CV. Tu réponds UNIQUEMENT en JSON valide."},
                    {"role": "user", "content": f"{parseur_cv.PROMPT_CV_EXTRACTION}\n\n{cv_text}"}
                ],
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            cleaned_result = parseur_cv.clean_json_text(result_text)
            parsed_data = json.loads(cleaned_result)

            print(f"✅ {cv_filename} parsé avec succès")

            return {
                "filename": cv_filename,
                "success": True,
                "data": parsed_data
            }

        except Exception as e:
            print(f"❌ Erreur pour {cv_filename}: {e}")
            return {
                "filename": cv_filename,
                "success": False,
                "error": str(e)
            }


async def parse_cvs_parallel(
    cv_files: List[Path],
    cv_json_folder: Path,
    model: str = "gpt-5-mini",
    temperature: float = 0.1,
    max_concurrent: int = 5
) -> Dict[str, Any]:
    """
    Parse plusieurs CVs en parallèle avec contrôle de concurrence

    Args:
        cv_files: Liste de Path vers les fichiers CVs (PDF/DOCX)
        cv_json_folder: Dossier de sortie pour les JSONs
        model: Modèle LLM à utiliser
        temperature: Température (0.1 pour extraction)
        max_concurrent: Nombre max d'appels LLM simultanés

    Returns:
        Dict avec statistiques (success_count, failed_count, results)
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = []

    # Créer le dossier de sortie
    cv_json_folder.mkdir(parents=True, exist_ok=True)

    # Extraction du texte (synchrone, rapide)
    cv_texts = []
    for cv_file in cv_files:
        ext = cv_file.suffix.lower()

        try:
            if ext == ".pdf":
                cv_text = parseur_cv.extract_text_from_pdf(str(cv_file))
            elif ext == ".docx":
                cv_text = parseur_cv.extract_text_from_docx(str(cv_file))
            else:
                print(f"⚠️ Format non supporté: {cv_file.name}")
                continue

            cv_texts.append({
                "filename": cv_file.name,
                "text": cv_text
            })
        except Exception as e:
            print(f"❌ Erreur d'extraction pour {cv_file.name}: {e}")

    # Parsing parallèle avec LLM
    for cv_info in cv_texts:
        task = parse_single_cv_async(
            cv_text=cv_info["text"],
            cv_filename=cv_info["filename"],
            model=model,
            temperature=temperature,
            semaphore=semaphore
        )
        tasks.append(task)

    print(f"🚀 Lancement du parsing parallèle de {len(tasks)} CVs (max {max_concurrent} simultanés)...")

    # Exécuter toutes les tâches en parallèle
    results = await asyncio.gather(*tasks)

    # Sauvegarder les résultats
    success_count = 0
    failed_count = 0
    saved_files = []

    for result in results:
        if result["success"]:
            # Sauvegarder le JSON
            json_filename = Path(result["filename"]).stem + ".json"
            json_path = cv_json_folder / json_filename

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result["data"], f, ensure_ascii=False, indent=4)

            saved_files.append(json_filename)
            success_count += 1
        else:
            failed_count += 1

    print(f"\n📊 Résumé:")
    print(f"  ✅ Succès: {success_count}")
    print(f"  ❌ Échecs: {failed_count}")

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total": len(results),
        "saved_files": saved_files,
        "results": results
    }


# Fonction wrapper pour Streamlit (contexte synchrone)
def parse_cvs_parallel_sync(
    cv_files: List[Path],
    cv_json_folder: Path,
    model: str = "gpt-5-mini",
    temperature: float = 0.1,
    max_concurrent: int = 5
) -> Dict[str, Any]:
    """
    Wrapper synchrone pour Streamlit

    Usage:
        from parallel_cv_parsing import parse_cvs_parallel_sync

        results = parse_cvs_parallel_sync(
            cv_files=[Path("cv1.pdf"), Path("cv2.pdf")],
            cv_json_folder=Path("cv_json"),
            max_concurrent=5
        )

        st.success(f"✅ {results['success_count']} CVs parsés")
    """
    return asyncio.run(parse_cvs_parallel(
        cv_files=cv_files,
        cv_json_folder=cv_json_folder,
        model=model,
        temperature=temperature,
        max_concurrent=max_concurrent
    ))


# Test si exécuté directement
if __name__ == "__main__":
    async def test():
        # Exemple de test
        test_folder = Path("cv_input")
        output_folder = Path("cv_json")

        if not test_folder.exists():
            print("⚠️ Créez d'abord un dossier cv_input avec des CVs")
            return

        cv_files = list(test_folder.glob("*.pdf")) + list(test_folder.glob("*.docx"))

        if not cv_files:
            print("⚠️ Aucun fichier CV trouvé dans cv_input/")
            return

        print(f"📁 {len(cv_files)} CV(s) trouvés")

        results = await parse_cvs_parallel(
            cv_files=cv_files,
            cv_json_folder=output_folder,
            max_concurrent=5
        )

        print(f"\n✅ Parsing terminé: {results['success_count']}/{results['total']} succès")

    asyncio.run(test())
