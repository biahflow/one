"use client";

import { ArrowLeft, FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { deleteDocument, uploadDocument } from "../actions";

export type IngestState = "pending" | "indexed" | "failed" | "unsupported";

export type ProjectDocument = {
  documentId: string;
  title: string;
  mimeType: string | null;
  byteSize: number | null;
  state: IngestState;
  error: string | null;
  chunkCount: number;
  indexedAt: string | null;
  createdAt: string;
};

type ProjectOption = { id: string; name: string; current: boolean };

/** Formatos que a API aceita — a mesma lista que a ingestão sabe ler. */
const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv";

const STATE_LABEL: Record<IngestState, { label: string; tone: string }> = {
  pending: { label: "Na fila", tone: "state--1" },
  indexed: { label: "Indexado", tone: "state--0" },
  failed: { label: "Falhou", tone: "state--2" },
  unsupported: { label: "Não suportado", tone: "state--2" },
};

function day(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("pt-BR", { timeZone: "UTC" });
}

function size(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function KnowledgeClient({
  organization,
  projects,
  projectName,
  projectId,
  documents,
}: {
  organization: string;
  projects: ProjectOption[];
  projectName: string;
  projectId: string;
  documents: ProjectDocument[];
}) {
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const indexed = documents.filter((item) => item.state === "indexed");
  const waiting = documents.some((item) => item.state === "pending");

  function submit(formData: FormData) {
    startTransition(async () => {
      const result = await uploadDocument(projectId, formData);
      setMessage(
        result.ok
          ? {
              tone: "ok",
              text: "Documento recebido. A indexação roda em segundo plano — atualize para ver o estado.",
            }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  function remove(document: ProjectDocument) {
    startTransition(async () => {
      const result = await deleteDocument(projectId, document.documentId);
      setMessage(
        result.ok
          ? { tone: "ok", text: `${document.title} saiu do projeto — arquivo e índice.` }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  return (
    <main className="admin-shell" data-project-id={projectId}>
      <header className="admin-head">
        <Link className="admin-back" href="/admin">
          <ArrowLeft size={16} /> Administração de acesso
        </Link>
        <p className="eyebrow">CONHECIMENTO</p>
        <h1>O que o assistente pode citar sobre {projectName}</h1>
        <p className="admin-lead">
          {organization} · Cada documento vira trechos com a página de origem. O assistente só
          afirma o que estiver aqui — sem evidência, ele declara a lacuna e abre uma pendência.
        </p>
      </header>

      {projects.length > 1 && (
        <nav className="admin-projects" aria-label="Escolher projeto">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/admin/conhecimento?project=${project.id}`}
              className={`state ${project.current ? "state--0" : "state--2"}`}
            >
              {project.name}
            </Link>
          ))}
        </nav>
      )}

      {message && (
        <p className={message.tone === "ok" ? "admin-note" : "auth-error"} role="status">
          {message.text}
        </p>
      )}

      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">ENVIAR</p>
              <h2>Novo documento</h2>
            </div>
          </div>
          <p className="admin-lead">
            PDF, DOCX, TXT, Markdown ou CSV. O texto é extraído no servidor e dividido em
            trechos que nunca cruzam a virada de página — é o que faz a citação apontar para o
            lugar certo.
          </p>
          <form className="admin-form" action={submit}>
            <label className="auth-field">
              <span>Arquivo</span>
              <input name="file" type="file" accept={ACCEPT} required />
            </label>
            <label className="auth-field">
              <span>Título</span>
              <input name="title" placeholder="Como o cliente reconhece este documento" />
            </label>
            <button className="ai-button admin-submit" type="submit" disabled={pending}>
              <Upload size={16} />
              {pending ? "Enviando…" : "Enviar e indexar"}
            </button>
          </form>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">ÍNDICE DO PROJETO</p>
              <h2>
                {indexed.length} de {documents.length} indexados
              </h2>
            </div>
            {waiting && (
              <button
                className="icon-button"
                aria-label="Atualizar o estado da indexação"
                disabled={pending}
                onClick={() => router.refresh()}
              >
                <RefreshCw size={16} />
              </button>
            )}
          </div>

          {documents.length === 0 && (
            <p className="empty-state">
              Nenhum documento enviado. Sem índice, o assistente responde apenas pelo que o
              Biahflow espelha — status, marcos e pendências.
            </p>
          )}

          <div className="field-list">
            {documents.map((document) => {
              const state = STATE_LABEL[document.state];
              return (
                <div className="member-row" key={document.documentId}>
                  <span className="avatar avatar--small">
                    <FileText size={15} />
                  </span>
                  <div className="member-identity">
                    <strong>{document.title}</strong>
                    <span>
                      {size(document.byteSize)} ·{" "}
                      {document.state === "indexed"
                        ? `${document.chunkCount} ${
                            document.chunkCount === 1 ? "trecho" : "trechos"
                          } · indexado em ${day(document.indexedAt)}`
                        : document.error || `enviado em ${day(document.createdAt)}`}
                    </span>
                  </div>
                  <span className={`state ${state.tone}`}>{state.label}</span>
                  <button
                    className="icon-button"
                    aria-label={`Remover ${document.title}`}
                    disabled={pending}
                    onClick={() => remove(document)}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              );
            })}
          </div>
        </article>
      </section>
    </main>
  );
}
