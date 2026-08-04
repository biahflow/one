# ADR 0001 — Monorepo e stack

**Status:** Aceito

Usaremos Next.js/TypeScript no frontend e FastAPI/Python no backend, no mesmo repositório. PostgreSQL com pgvector é a fonte de verdade; Redis/Celery executam jobs e MinIO/S3 armazena blobs. Isso preserva uma UX web madura e favorece integrações e IA em Python.
