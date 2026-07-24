# QAC local acquisition

Quranic Arabic Corpus (QAC) material is an external annotation dataset, not Quran text authority. Tanzil remains the authoritative Quran text source in this project. QAC acquisition is local-only: files in `data/incoming/`, raw annotation copies, manifests, and exports are ignored by Git. The existing committed Tanzil source and manifest remain tracked; a Git ignore rule never removes an already tracked file.

Before registration, capture the source identifier, original and local filenames, acquisition date, license, citation, encoding, line-ending convention, byte count, SHA-256, and optionally SHA-512 in `SourceMetadata`. Local datasets use `user-local-dataset`; test fixtures use the distinct `synthetic-fixture` class. The implemented local workflow explicitly registers, ingests, and aligns a user-provided QAC file; it never acquires or downloads one.
