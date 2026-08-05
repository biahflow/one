"use client";

import {
  ArrowLeft,
  CloudOff,
  FolderOpen,
  FileText,
  Link2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import {
  deleteDocument,
  disconnectDrive,
  listDriveFolders,
  setDriveFolder,
  startDriveAuthorization,
  syncDriveNow,
  uploadDocument,
  type DriveFolder,
} from "../actions";

export type IngestState = "pending" | "indexed" | "failed" | "unsupported" | "rejected";

// O outro eixo (Fase 5, ADR 0017). Fica separado de `IngestState` na tela pelo
// mesmo motivo de estar separado no banco: `skipped` não é `clean`, e a
// administração precisa poder ver a diferença entre "verificado" e "ninguém
// verificou".
export type ScanState = "pending" | "clean" | "infected" | "skipped" | "error";

export type ProjectDocument = {
  documentId: string;
  title: string;
  mimeType: string | null;
  byteSize: number | null;
  state: IngestState;
  error: string | null;
  scanState: ScanState;
  scanError: string | null;
  chunkCount: number;
  indexedAt: string | null;
  createdAt: string;
};

export type DriveConnection = {
  connected: boolean;
  folderId: string | null;
  folderName: string | null;
  account: string | null;
  enabled: boolean;
  syncState: "idle" | "running" | "failed" | null;
  lastSyncAt: string | null;
  lastSyncError: string | null;
  documentCount: number;
};

type ProjectOption = { id: string; name: string; current: boolean };

/** O que a volta do consentimento do Google diz à tela (ADR 0016). */
const DRIVE_RESULT: Record<string, { tone: "ok" | "error"; text: string }> = {
  connected: {
    tone: "ok",
    text: "Drive conectado. Escolha a pasta que o assistente pode ler.",
  },
  denied: { tone: "error", text: "Você recusou o acesso na tela do Google." },
  scope: {
    tone: "error",
    text: "O Google concedeu um acesso diferente do pedido. O portal só aceita somente leitura.",
  },
  error: { tone: "error", text: "Não foi possível concluir a conexão com o Drive." },
};

/** Formatos que a API aceita — a mesma lista que a ingestão sabe ler. */
const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv";

const STATE_LABEL: Record<IngestState, { label: string; tone: string }> = {
  pending: { label: "Na fila", tone: "state--1" },
  indexed: { label: "Indexado", tone: "state--0" },
  failed: { label: "Falhou", tone: "state--2" },
  unsupported: { label: "Não suportado", tone: "state--2" },
  rejected: { label: "Recusado", tone: "state--2" },
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
  drive,
  driveResult,
}: {
  organization: string;
  projects: ProjectOption[];
  projectName: string;
  projectId: string;
  documents: ProjectDocument[];
  drive: DriveConnection;
  driveResult: string | null;
}) {
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    driveResult ? (DRIVE_RESULT[driveResult] ?? null) : null,
  );
  const [folders, setFolders] = useState<DriveFolder[] | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const indexed = documents.filter((item) => item.state === "indexed");
  const waiting = documents.some((item) => item.state === "pending");

  // Acabou de conectar e ainda não escolheu a pasta: a lista já abre, senão a
  // pessoa volta do Google e encontra uma tela que parece não ter mudado nada.
  useEffect(() => {
    if (driveResult === "connected" && drive.connected && !drive.folderId) {
      startTransition(async () => {
        const result = await listDriveFolders(projectId);
        if (result.ok) setFolders(result.data ?? []);
      });
    }
  }, [driveResult, drive.connected, drive.folderId, projectId]);

  function connect() {
    startTransition(async () => {
      const result = await startDriveAuthorization(projectId);
      if (!result.ok) {
        setMessage({ tone: "error", text: result.error });
        return;
      }
      const url = result.data?.authorize_url;
      if (url) window.location.href = url;
    });
  }

  function chooseFolder() {
    startTransition(async () => {
      const result = await listDriveFolders(projectId);
      if (result.ok) setFolders(result.data ?? []);
      else setMessage({ tone: "error", text: result.error });
    });
  }

  function pickFolder(folder: DriveFolder) {
    startTransition(async () => {
      const result = await setDriveFolder(projectId, folder.id);
      setMessage(
        result.ok
          ? { tone: "ok", text: `Pasta ${folder.name} autorizada. Sincronize para indexar.` }
          : { tone: "error", text: result.error },
      );
      if (result.ok) {
        setFolders(null);
        router.refresh();
      }
    });
  }

  function syncNow() {
    startTransition(async () => {
      const result = await syncDriveNow(projectId);
      setMessage(
        result.ok
          ? {
              tone: "ok",
              text: "Sincronização na fila. Atualize em alguns segundos para ver o resultado.",
            }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  function disconnect() {
    startTransition(async () => {
      const result = await disconnectDrive(projectId);
      setMessage(
        result.ok
          ? {
              tone: "ok",
              text: "Drive desconectado. Os documentos já indexados continuam no projeto.",
            }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

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

        <article className="panel" data-drive-panel>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">GOOGLE DRIVE</p>
              <h2>
                {drive.connected ? drive.folderName || "Pasta não escolhida" : "Não conectado"}
              </h2>
            </div>
            {drive.connected && drive.folderId && (
              <button
                className="icon-button"
                aria-label="Sincronizar agora"
                disabled={pending || !drive.enabled}
                onClick={syncNow}
              >
                <RefreshCw size={16} />
              </button>
            )}
          </div>

          <p className="admin-lead">
            {drive.connected
              ? `${drive.account ?? "conta conectada"} · somente leitura, e só a pasta autorizada. Subpastas entram; atalhos, não.`
              : "Conecte uma pasta e o portal indexa o conteúdo dela sozinho. O acesso é somente leitura e vale para uma pasta por projeto."}
          </p>

          {drive.connected && !drive.enabled && (
            <p className="auth-error" role="status">
              {drive.lastSyncError ??
                "A sincronização está pausada. Reconecte a pasta para retomar."}
            </p>
          )}

          {drive.connected && drive.enabled && drive.lastSyncError && (
            <p className="auth-error" role="status">
              {drive.lastSyncError}
            </p>
          )}

          {folders !== null && (
            <div className="field-list">
              {folders.length === 0 && (
                <p className="empty-state">Nenhuma pasta encontrada nesta conta.</p>
              )}
              {folders.map((folder) => (
                <div className="member-row" key={folder.id}>
                  <span className="avatar avatar--small">
                    <FolderOpen size={15} />
                  </span>
                  <div className="member-identity">
                    <strong>{folder.name}</strong>
                  </div>
                  <button
                    className="ai-button"
                    type="button"
                    disabled={pending}
                    onClick={() => pickFolder(folder)}
                  >
                    Autorizar
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="admin-form">
            {!drive.connected && (
              <button
                className="ai-button admin-submit"
                type="button"
                disabled={pending}
                onClick={connect}
              >
                <Link2 size={16} />
                {pending ? "Abrindo…" : "Conectar Google Drive"}
              </button>
            )}
            {drive.connected && folders === null && (
              <button
                className="ai-button admin-submit"
                type="button"
                disabled={pending}
                onClick={chooseFolder}
              >
                <FolderOpen size={16} />
                {drive.folderId ? "Trocar de pasta" : "Escolher a pasta"}
              </button>
            )}
            {drive.connected && (
              <button
                className="icon-button"
                type="button"
                aria-label="Desconectar o Google Drive"
                disabled={pending}
                onClick={disconnect}
              >
                <CloudOff size={16} />
              </button>
            )}
          </div>

          {drive.connected && drive.folderId && (
            <p className="admin-lead">
              {drive.documentCount}{" "}
              {drive.documentCount === 1 ? "documento vindo" : "documentos vindos"} do Drive ·
              última sincronização em {day(drive.lastSyncAt)}
            </p>
          )}
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
                    {/* Dito por extenso, e não só pelo selo: "barrado pela
                        varredura" e "formato não suportado" levam a ações
                        diferentes de quem administra. */}
                    {document.scanState === "infected" && (
                      <span className="scan-note">
                        Barrado pela varredura
                        {document.scanError ? `: ${document.scanError}` : ""} · arquivo
                        removido do storage
                      </span>
                    )}
                    {document.scanState === "skipped" && document.state === "indexed" && (
                      <span className="scan-note scan-note--muted">
                        Indexado sem antivírus configurado
                      </span>
                    )}
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
