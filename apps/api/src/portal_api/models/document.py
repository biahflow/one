"""Document domain — project knowledge sources and the index built from them.

Duas tabelas do mesmo agregado: ``document`` é a fonte (metadado, arquivo no
storage) e ``document_chunk`` é o que a recuperação enxerga (trecho + embedding).
O chunk existe apenas como derivado do documento — some junto com ele, por
CASCADE, e é reescrito inteiro a cada reindexação (ADR 0014).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin

# O vocabulário do veredito mora no adapter, e a coluna o importa em vez de
# repetir a lista. `scanner.py` é folha — só depende de `config` —, então a seta
# aponta para o lado seguro: quem varre não precisa saber que existe banco.
from portal_api.scanner import ScanState

# Pela mesma razão do import acima: `textfold` é folha e define a expressão que
# o índice de busca usa, então quem consulta e quem indexa leem do mesmo lugar
# (ADR 0024).
from portal_api.textfold import index_expression

#: Dimensão do vetor. Fixa na coluna de propósito: vetores de dimensões
#: diferentes não são comparáveis, então trocar de modelo de embedding é uma
#: migração mais uma reindexação, nunca uma variável de ambiente.
EMBEDDING_DIMENSIONS = 1024


class DocumentSource(str, enum.Enum):
    upload = "upload"
    drive = "drive"
    transcript = "transcript"


class DocumentOrigin(str, enum.Enum):
    """Quem criou a linha — e, por consequência, quem pode apagá-la.

    O sync do Biahflow substitui os documentos do projeto a cada snapshot
    (ADR 0006). Sem esta distinção, um arquivo enviado no portal morreria no
    próximo webhook — o mesmo motivo pelo qual ``PendingItem`` ganhou `origin`
    na Fase 2.

    ``drive`` é um terceiro valor e não um reuso de ``DocumentSource.drive``
    (ADR 0016): aquele já marca o documento que o Biahflow espelha como metadado
    e link, sem arquivo nenhum. Os dois falam do Drive e querem dizer coisas
    opostas — um é "existe lá", o outro é "veio de lá e está indexado aqui".
    """

    biahflow = "biahflow"
    portal = "portal"
    drive = "drive"


class DocumentIngestState(str, enum.Enum):
    """Onde o documento está na fila de virar evidência citável.

    ``unsupported`` é um estado e não uma falha: um `.zip` enviado por engano
    não é erro de sistema, é um formato que o portal não lê — e dizer isso na
    tela é melhor do que deixar a linha parada em `pending` para sempre.

    ``rejected`` (Fase 5, ADR 0017) existe pelo mesmo motivo: a varredura barrou
    o arquivo, ele nunca vai virar índice, e sem um estado para isso a linha
    ficaria parada em ``pending`` para sempre — que é exatamente o defeito que o
    parágrafo acima recusa.
    """

    pending = "pending"
    indexed = "indexed"
    failed = "failed"
    unsupported = "unsupported"
    rejected = "rejected"


class Document(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "document"
    __table_args__ = (
        # Reconciliação idempotente do conector do Drive (ADR 0016): o arquivo do
        # Drive é encontrado pelo par (projeto, id externo), e o banco garante que
        # ele não vira duas linhas.
        #
        # O predicado tem de ser comparação de enum: um predicado de índice só
        # aceita função IMMUTABLE, e o cast de enum para texto é STABLE. O texto
        # aqui tem de ser idêntico ao da migração 0013, senão o `alembic check`
        # passa a ver deriva.
        Index(
            "uq_document_project_id_external_id",
            "project_id",
            "external_id",
            unique=True,
            postgresql_where=text("origin = 'drive'"),
        ),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, name="document_source"), nullable=False
    )
    origin: Mapped[DocumentOrigin] = mapped_column(
        Enum(DocumentOrigin, name="document_origin"),
        nullable=False,
        default=DocumentOrigin.portal,
        server_default=DocumentOrigin.biahflow.value,
    )
    # MinIO/S3 object key; null enquanto o arquivo vive só no Drive/Biahflow.
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Google Drive file id for synced sources.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Link externo (Drive) vindo do snapshot do Biahflow; null quando o arquivo só existe
    # no storage do portal.
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quem subiu o documento, como rótulo exibível — não é um usuário do portal.
    author_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ingestão (ADR 0014).
    ingest_state: Mapped[DocumentIngestState] = mapped_column(
        Enum(DocumentIngestState, name="document_ingest_state"),
        nullable=False,
        default=DocumentIngestState.pending,
        server_default=DocumentIngestState.pending.value,
    )
    #: Motivo da falha, para a tela de administração explicar o que houve. Só a
    #: mensagem do erro — nunca trecho do conteúdo (docs/data-classification.md).
    ingest_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Varredura (Fase 5, ADR 0017). Eixo próprio, e não mais um valor em
    # `ingest_state`: "o arquivo é seguro" e "o arquivo virou texto citável" são
    # perguntas diferentes, e um documento pode ser `clean` e `failed` ao mesmo
    # tempo. `server_default` é `skipped` — a linha que já existia foi indexada
    # antes de haver varredura, e carimbá-la de `clean` seria afirmar o que
    # ninguém verificou; `pending` a mandaria para uma fila de revarredura que
    # esta migração não pede.
    scan_state: Mapped[ScanState] = mapped_column(
        Enum(ScanState, name="document_scan_state"),
        nullable=False,
        default=ScanState.pending,
        server_default=ScanState.skipped.value,
    )
    #: Nome da assinatura encontrada, ou o motivo do erro. Nunca trecho do
    #: arquivo — a mesma regra do `ingest_error`, e aqui ela pesa mais: o que
    #: falhou na varredura é justamente o conteúdo em que não se confia.
    scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: SHA-256 do arquivo indexado. É o que faz reingestão do mesmo objeto ser
    #: no-op em vez de reescrever (e recobrar) todos os embeddings.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentChunk(Base, _ProjectChildMixin, TimestampMixin):
    """Um trecho citável de um documento, com o vetor que o encontra.

    ``location`` é o que aparece na citação ("página 3") e por isso o chunking
    nunca cruza fronteira de página: uma citação que aponta para a página errada
    é pior do que não citar (docs/ai/eval-dataset.md).
    """

    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_document_id"),
        # Declarado aqui, e não só na migração, para o `alembic check` não ver
        # deriva: um índice que existe no banco e não no metadata seria um drop
        # proposto a cada autogenerate.
        Index(
            "ix_document_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Busca lexical dentro do texto do trecho (ADR 0024). A expressão vem de
        # `textfold.index_expression` e **não** está digitada aqui de propósito:
        # ela tem de ser idêntica à da consulta em `search.py`, senão o índice
        # deixa de ser usado sem nada ficar vermelho — e à da migração 0018, pela
        # regra que o índice parcial do Drive acima já escreveu.
        Index(
            "ix_document_chunk_text_fts",
            text(index_expression("text")),
            postgresql_using="gin",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Rótulo humano da posição, exibido na citação. Vazio quando o formato não
    #: tem páginas (um `.md`, por exemplo) — melhor sem localização do que com
    #: uma inventada.
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    #: Qual modelo produziu o vetor. Guardado por linha para uma troca de modelo
    #: ser visível e reindexável, em vez de virar um índice meio velho meio novo.
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
