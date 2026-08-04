"""Document repositories (project-scoped): a fonte e o índice construído dela."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from portal_api.models import Document, DocumentChunk
from portal_api.repositories.base import TenantScopedRepository


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document


class DocumentChunkRepository(TenantScopedRepository[DocumentChunk]):
    model = DocumentChunk

    def replace_for_document(
        self, document_id: uuid.UUID, chunks: list[DocumentChunk]
    ) -> list[DocumentChunk]:
        """Troca o índice do documento inteiro, de uma vez.

        Reindexar apagando e regravando (em vez de casar chunk a chunk) é o que
        mantém `ordinal` contíguo quando o arquivo muda de tamanho: um documento
        que encolheu não deixa trecho órfão apontando para texto que não existe
        mais. Como roda numa transação só, ninguém vê o índice vazio.
        """
        self.session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id, *self._tenant_filters()
            )
        )
        for chunk in chunks:
            chunk.document_id = document_id
            self.add(chunk)
        return chunks

    def count_for_document(self, document_id: uuid.UUID) -> int:
        stmt = select(DocumentChunk.id).where(
            DocumentChunk.document_id == document_id, *self._tenant_filters()
        )
        return len(list(self.session.execute(stmt).scalars()))

    def search(
        self, embedding: list[float], *, limit: int, max_distance: float
    ) -> list[tuple[DocumentChunk, float]]:
        """Os trechos mais próximos da pergunta, dentro do tenant e do corte.

        O filtro de tenant vem do ``TenantScopedRepository`` e é a primeira
        barreira; a RLS é a segunda. O corte por distância é o que impede a
        recuperação de sempre devolver *alguma coisa*: sem ele, uma pergunta
        sobre um assunto que o projeto não documenta encontraria o chunk menos
        distante e o citaria como se fosse resposta.
        """
        distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance)
            .where(DocumentChunk.embedding.is_not(None), *self._tenant_filters())
            .order_by(distance)
            .limit(limit)
        )
        return [
            (chunk, float(value))
            for chunk, value in self.session.execute(stmt).all()
            if value is not None and float(value) <= max_distance
        ]
