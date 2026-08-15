v5.7.1 — Quality Command & CAV Public Market

BASE REQUIRED: v5.7.0

Apply the contents of this ZIP over the repository root, preserving paths and replacing existing files.

WHAT IT FIXES
1) /quality now works directly in Telegram. /calidad is an alias.
2) CAV becomes a hybrid source:
   - PUBLIC comparator: only PUBLIC/SALE prices that do not require eligibility.
   - PERSONAL comparator: MEMBER/cav_member remains available.
3) A CAV member-only price can never leak into the public comparator.
4) No database migration is required.

After deployment, run once manually so the store metadata is synchronized and CAV is marked comparison_enabled=true in PostgreSQL.
