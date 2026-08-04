import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import KnowledgeClient, { type ProjectDocument } from "./KnowledgeClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiMe = {
  is_internal: boolean;
  organization: string | null;
  projects: { id: string; name: string; slug: string; status: string }[];
};

type ApiDocument = {
  document_id: string;
  title: string;
  mime_type: string | null;
  byte_size: number | null;
  ingest_state: "pending" | "indexed" | "failed" | "unsupported";
  ingest_error: string | null;
  chunk_count: number;
  indexed_at: string | null;
  created_at: string;
};

/**
 * O que o assistente pode citar (ADR 0014).
 *
 * A tela existe porque a resposta do chat só é tão boa quanto o que foi
 * indexado — e porque "por que a IA não sabe disso?" precisa ter resposta
 * observável: cada documento mostra o estado da ingestão e, quando falha, o
 * motivo.
 *
 * O `notFound()` para quem não é interno é ergonomia, não segurança — a API
 * responde 404 a quem não tem `internal_admin` no projeto, e é ela a autoridade.
 */
export default async function KnowledgeAdminPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string }>;
}) {
  const base = process.env.API_BASE_URL;
  const session = await auth();
  const authorization = await authorizationHeader();
  if (!base || !session || session.error || !authorization) redirect("/login");

  const meResponse = await fetch(`${base}/api/v1/me`, {
    headers: authorization,
    cache: "no-store",
  });
  if (meResponse.status === 401) redirect("/login");
  if (!meResponse.ok) throw new Error(`GET /api/v1/me respondeu ${meResponse.status}`);

  const me: ApiMe = await meResponse.json();
  if (!me.is_internal || me.projects.length === 0) notFound();

  const { project: requested } = await searchParams;
  const project =
    me.projects.find((candidate) => candidate.id === requested) ?? me.projects[0];

  const response = await fetch(`${base}/api/v1/admin/projects/${project.id}/documents`, {
    headers: authorization,
    cache: "no-store",
  });
  // 404 aqui é "você não é internal_admin neste projeto" — a mesma resposta que
  // um projeto inexistente daria, de propósito.
  if (response.status === 404) notFound();
  if (!response.ok) throw new Error(`GET documents respondeu ${response.status}`);

  const documents: ProjectDocument[] = ((await response.json()) as ApiDocument[]).map(
    (item) => ({
      documentId: item.document_id,
      title: item.title,
      mimeType: item.mime_type,
      byteSize: item.byte_size,
      state: item.ingest_state,
      error: item.ingest_error,
      chunkCount: item.chunk_count,
      indexedAt: item.indexed_at,
      createdAt: item.created_at,
    }),
  );

  return (
    <KnowledgeClient
      organization={me.organization ?? ""}
      projects={me.projects.map((candidate) => ({
        id: candidate.id,
        name: candidate.name,
        current: candidate.id === project.id,
      }))}
      projectName={project.name}
      projectId={project.id}
      documents={documents}
    />
  );
}
