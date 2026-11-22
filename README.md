# Archive publique du projet BrainHR

**Built with Meta Llama 3**

État au **22 novembre 2026**. Ce dépôt centralise les documents de travail des auteurs, les données explicitement synthétiques, les jugements A/B sans texte de CV, les inventaires et les liens GitHub et Hugging Face. Ce dépôt est public depuis le 22 novembre 2026. Les réglages des dépôts externes restent inchangés. Les documents V9 décrivent cet accès public et les limites du périmètre partagé.

L’extract local contient **549 718 fichiers ordinaires et 433 liens**, soit **97 221 524 284 octets de fichiers**. Tous leurs chemins d’origine et de copie sont indexés ici. Les contenus de CV réels, les 1 074 exemples qui en sont dérivés, les citations des annotations et les secrets ne sont pas transférés. Les dépendances installées et les bases d’objets Git restent dans la copie locale ; leurs chemins figurent dans l’inventaire.

## Documents à utiliser

- [Manuscrit V9 en Word](documents/BRAINHR_Paper_V9.docx)
- [Questions réponses V9 aux reviewers et annexe statistique en Word](documents/BRAINHR_Reponses_Reviewers_V9.docx)
- [Périmètre exact des contenus transférés](PUBLICATION_SCOPE.json)

## Dépôts et liens

| Ressource | Lien | État observé lors de la préparation |
|---|---|---|
| Code GitHub accessible | [zadbox/BrainRhv0.1](https://github.com/zadbox/BrainRhv0.1) | Privé, accessible avec le compte de publication |
| Ancienne référence du parseur | [SamAI10/brainrh-cv-parser-fix](https://github.com/SamAI10/brainrh-cv-parser-fix) | Non accessible avec les identifiants utilisés pour cette publication ; référence conservée |
| Ancienne référence applicative | [SamAI10/brainrhaws](https://github.com/SamAI10/brainrhaws) | Non accessible avec les identifiants utilisés pour cette publication ; référence conservée |
| Données de recherche existantes | [mounimzad/brainhr-fusion-annotations-20261110](https://huggingface.co/datasets/mounimzad/brainhr-fusion-annotations-20261110) | Privé |
| Compagnon de recherche existant | [mounimzad/brainhr-synthetic-6000-reviewers](https://huggingface.co/datasets/mounimzad/brainhr-synthetic-6000-reviewers) | Privé |
| Modèle QLoRA existant | [mounimzad/Llama-3-BrainHR-QLoRA-Fusion-20261110](https://huggingface.co/mounimzad/Llama-3-BrainHR-QLoRA-Fusion-20261110) | Privé |
| Adaptateur MLX historique | [mounimzad/Llama-3-BrainHR-FT1200](https://huggingface.co/mounimzad/Llama-3-BrainHR-FT1200) | Privé |
| Adaptateur principal à accès contrôlé | [mounimzad/BrainHR-Adapter-Research-Access](https://huggingface.co/mounimzad/BrainHR-Adapter-Research-Access) | Dépôt public, téléchargement soumis à approbation manuelle |
| Échantillon public | [mounimzad/brainhr-plus](https://huggingface.co/datasets/mounimzad/brainhr-plus) | Public, 15 paires illustratives |
| Source synthétique externe référencée | [BrainResearchGroup/candidate-matching-synthetic](https://huggingface.co/datasets/BrainResearchGroup/candidate-matching-synthetic) | Public ; ne constitue pas la totalité du corpus de l’étude |

Les métadonnées datées sont conservées dans [links/GITHUB.json](links/GITHUB.json) et [links/HUGGING_FACE.json](links/HUGGING_FACE.json). La [liste complète des dépôts et copies locales](inventory/DEPOTS_ET_COPIES.txt) conserve aussi les références historiques. Un lien vers un dépôt privé ne donne pas automatiquement accès à celui-ci.

## Fichiers de code

[Onze snapshots de fichiers sources suivis](source/SNAPSHOT_MANIFEST.json) sont inclus dans `source/`. Ils contiennent 1327 fichiers de code, sans les données, fixtures ou environnements installés. Les candidats de configuration sensibles repérés sont exclus. Les dépôts existants restent les références pour leur historique Git ; les autres chemins locaux figurent dans l’inventaire complet.

## Datasets et annotations transférés

- [6 000 exemples de tâches synthétiques](datasets/synthetic_6000/MANIFEST.json), avec leurs partitions d’origine. Le filtrage exige simultanément `fictif: true` et `source_kind: synthetic`. Les 1 074 exemples issus de CV réels sont exclus de cet export.
- [15 paires du compagnon public](datasets/public_companion_15/annotations.jsonl), distinctes du corpus d’entraînement et de la cohorte d’annotation.
- [Tous les jugements A/B sans texte](annotations/AB_LABELS_ONLY.jsonl) : 292 paires, 3 231 unités de critères, 6 462 votes de critères et 584 jugements de pertinence. Les textes, raisons et citations sont exclus.
- [Matrices et coefficients recalculés](annotations/AGREEMENT.json), avec le [manifeste de dérivation](annotations/MANIFEST.json). Ces coefficients décrivent l’accord entre les sorties archivées ; ils ne sont pas présentés comme un accord humain certifié.

Recalculer les coefficients à partir des jugements inclus :

```sh
python3 tools/compute_agreement.py
```

Les fichiers de tâches synthétiques sont compressés avec gzip. Ils contiennent des exemples de tâches et non 6 000 candidats indépendants.

## Modèles et checkpoints

Les **131 références locales de poids** correspondent à **47 objets distincts**, soit **35 058 746 271 octets** après déduplication. Le [manifeste des objets](models/MODEL_OBJECTS.json) relie chaque objet à tous ses chemins locaux d’origine. Les fichiers volumineux sont découpés en parties d’au plus un Gio, chacune avec une empreinte SHA256. Les 64 parties de poids sont publiées et leurs tailles et SHA256 vérifiés côté GitHub. La licence et la notice les accompagnent. Le [reçu de vérification](verification/MODEL_RELEASE_VERIFICATION.json) détaille chaque partie. Leur emplacement est la [release associée](https://github.com/zadbox/brainhr-research-archive-20261122/releases/tag/archive-20261122).

L’adaptateur QLoRA principal commence par `20cfe4592625`, le checkpoint 700 par `f9bbaad0c956`, et l’adaptateur correctif distinct par `171f4c920535`. Le manifeste conserve également les checkpoints intermédiaires, les essais de qualification, les poids de base en quatre fragments et le modèle de base MLX en un fichier. Ces artefacts ne sont pas tous des modèles validés et ne sont pas interchangeables.

Les [configurations et tokenizers](models/CONFIGURATION_OBJECTS.json) sont dédupliqués séparément ; leur table d’alias conserve leurs noms et chemins d’origine. La [licence fournie avec le modèle de base](licenses/META_LLAMA3_LICENSE.txt) est conservée.

Restaurer l’adaptateur principal sans compte GitHub :

```sh
python3 tools/restore_models.py --principal --out restored_models
```

Ou restaurer tous les objets distincts :

```sh
python3 tools/restore_models.py --all --out restored_models
```

Le script télécharge les assets publics, vérifie chaque partie, assemble les objets et contrôle leur SHA256 complet. Les objets sont nommés par leur empreinte ; les noms de chargement d’origine et les configurations correspondantes sont fournis dans les manifestes. Cette restauration de fichiers n’est pas une nouvelle évaluation du modèle.

## Chemins exacts de tous les fichiers

- [Guide local et fichiers principaux](inventory/OUVRIR_ICI.txt)
- [Tous les chemins d’origine](inventory/TOUS_LES_CHEMINS_ORIGINAUX.txt.gz)
- [Tous les chemins dans la copie](inventory/TOUS_LES_CHEMINS_COPIE.txt.gz)
- [Correspondance origine vers copie](inventory/CORRESPONDANCE_SOURCE_COPIE.txt.gz)
- [Inventaire complet avec métadonnées](inventory/INDEX_TOUS_LES_FICHIERS.jsonl.gz)
- [Index des datasets](inventory/INDEX_DATASETS.jsonl.gz)
- [Index des annotations](inventory/INDEX_ANNOTATIONS.jsonl.gz)
- [Les 292 fichiers de la série A](inventory/ANNOTATIONS_A_CHEMINS_EXACTS.txt)
- [Les 292 fichiers de la série B](inventory/ANNOTATIONS_B_CHEMINS_EXACTS.txt)
- [Tous les chemins des poids](inventory/POIDS_MODELES_CHEMINS_EXACTS.txt)
- [Chemins des dépôts distants dans les captures datées](inventory/INDEX_FICHIERS_DEPOTS_DISTANTS.jsonl.gz)

La copie intégrale demeure à `/Users/mac/BrainHR_EXTRACT_INTEGRAL_20261122/COPIE`. Un chemin local dans un inventaire n’est pas un lien de téléchargement distant. Le [reçu de copie](inventory/VERIFICATION_COPIE.json) et le [périmètre des sources](inventory/PERIMETRE.json) distinguent les fichiers effectivement copiés, les liens et les références distantes.

Les limites de stockage Git ordinaires motivent l’utilisation d’assets de release pour les poids : [documentation GitHub sur les gros fichiers](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

## Historique

Les versions V8 conservent l’état documentaire antérieur à l’ouverture de cette archive : [manuscrit V8](documents/BRAINHR_Paper_V8_Sources_Verifiees.docx) et [réponses V8](documents/BRAINHR_Reponses_Reviewers_Sources_Verifiees.docx). Pour l’accès actuel aux artefacts, utiliser les documents V9 ci-dessus.
