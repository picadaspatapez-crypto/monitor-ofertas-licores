# Deploy v5.7.1 — Quality Command & CAV Public Market

Base requerida: **v5.7.0**.

1. Copiar el contenido del hotfix sobre la raíz del repositorio.
2. Commit + push.
3. Railway despliega normalmente.
4. No hay migraciones nuevas: Alembic continúa en `0011_canonical_matching_quality`.
5. Hacer un `Run now` para sincronizar `comparison_enabled=true` de CAV y registrar su precio público actual.
6. Validar en Telegram: `/quality`, `/buscar <producto>` y `/miprecio <producto>`.

CAV es híbrida en v5.7.1:
- Mercado público: solo `PUBLIC` o `SALE` sin requisito de elegibilidad.
- Comparador personal: puede usar `MEMBER / cav_member`.
- Un producto CAV que solo tenga precio MEMBER no entra al mercado público.
