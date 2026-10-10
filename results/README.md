# Validated experiment run

The committed files are the first validated local experiment on 10 October 2026:

- `benchmark-20261010T102604Z.csv` contains every raw query execution.
- `benchmark-20261010T102604Z.json` contains the baseline summary.
- `ablation-20261010T102859Z.json` contains every ablation execution and its summary.

Configuration: PostgreSQL 17, pgvector 0.8.7, 50,000 products, 384-dimensional deterministic hash embeddings, ten queries, five repetitions, and top 10 retrieval. Recall is tie-aware at the exact kth-distance boundary.
