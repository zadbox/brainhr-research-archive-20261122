#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script d'initialisation de la base de données
À exécuter une seule fois après l'installation

Usage:
    python scripts/init_db.py
"""

from sqlmodel import SQLModel
from brainrh.database import init_db, DATABASE_URL, db_path

if __name__ == "__main__":
    print("[INIT] Initialisation de la base de données...")
    print(f"[INIT] URL: {DATABASE_URL}")
    print(f"[INIT] Fichier: {db_path}")

    # Créer les tables
    init_db()

    # Lister les tables créées
    tables = list(SQLModel.metadata.tables.keys())
    print(f"[INIT] ✅ Tables créées: {tables}")
    print(f"[INIT] ✅ Base initialisée avec succès!")
    print(f"\n[INIT] Vérification: sqlite3 {db_path} \".tables\"")
