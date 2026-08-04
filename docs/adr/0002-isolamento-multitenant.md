# ADR 0002 — Isolamento multitenant

**Status:** Aceito

Todos os registros recebem organização e, quando aplicável, projeto. Autorização ocorre na API e RLS é a segunda barreira no PostgreSQL. Busca vetorial e jobs carregam obrigatoriamente o mesmo escopo.
