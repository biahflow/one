# Runbook — Backup e restore

Testar backup criptografado de PostgreSQL e objetos do MinIO em ambiente isolado. Validar RLS, integridade de fontes e ausência de cruzamento de tenant após restore.

**Rode `infra/postgres/bootstrap/roles.sql` antes do restore.** Papéis são objetos de
*cluster* e **não vêm num `pg_dump` do banco**: sem eles, os `GRANT` e as policies do dump
apontam para papéis inexistentes e o restore falha — ou pior, a aplicação acaba conectando com
uma credencial privilegiada e a RLS vira decoração. É o item de restore mais fácil de esquecer
(ADR 0010).

Depois do restore, a verificação de uma linha que prova o resto:

```sql
SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'portal_app';  -- → (f, f)
```
