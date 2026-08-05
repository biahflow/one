-- Só roda em volume novo (docker-entrypoint-initdb.d). O `db-bootstrap` cobre o
-- resto rodando `roles.sql`, que repete estas linhas de propósito: as duas
-- extensões precisam existir antes de qualquer migração e antes de qualquer
-- restore, e uma fonte só, que não roda em volume já existente, seria pior que a
-- duplicação (ADR 0019).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS portal;
CREATE SCHEMA IF NOT EXISTS keycloak;
