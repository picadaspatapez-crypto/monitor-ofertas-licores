# v5.1.5 — Concurrent Master Product Upsert Fix

Replace only:

- `app/repositories/products.py`
- `app/version.py`

This fixes concurrent `master_products.normalized_key` creation when stores are
persisted in parallel. No database migration, data deletion, or Railway variable
change is required.

Suggested commit:

`Release v5.1.5 concurrent master product upsert fix`
