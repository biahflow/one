"use client";

import { ArrowLeft, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import {
  createAgentKey,
  openAssumption,
  revokeAgentKey,
  rotateAgentKey,
} from "../actions";

export type AgentKey = {
  keyId: string;
  name: string;
  keyPrefix: string;
  expiresAt: string;
  revoked: boolean;
  expired: boolean;
  lastUsedAt: string | null;
  rotatedFromId: string | null;
};

export type Assumption = {
  assumptionId: string;
  effectiveFrom: string;
  effectiveTo: string | null;
  hourlyRate: number;
  monthlyInvestment: number;
  currency: string;
  note: string | null;
};

type ProjectOption = { id: string; name: string; current: boolean };

/**
 * Dinheiro na moeda que a própria premissa declara (ADR 0033).
 *
 * `currency` chega da API desde a Fase 3, era mapeado aqui e ignorado: tudo
 * saía com `R$` fixo. Uma premissa em outra moeda não ficava incompleta na
 * tela, ficava **errada** — e é esta a tela onde alguém digita o número.
 */
function money(value: number, currency: string | null | undefined) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: currency || "BRL",
  }).format(value);
}

function day(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("pt-BR", { timeZone: "UTC" });
}

function keyState(key: AgentKey): { label: string; tone: string } {
  if (key.revoked) return { label: "Revogada", tone: "state--2" };
  if (key.expired) return { label: "Expirada", tone: "state--2" };
  return { label: `Vence em ${day(key.expiresAt)}`, tone: "state--1" };
}

export default function ResultsAdminClient({
  organization,
  projects,
  projectName,
  projectId,
  keys,
  assumptions,
}: {
  organization: string;
  projects: ProjectOption[];
  projectName: string;
  projectId: string;
  keys: AgentKey[];
  assumptions: Assumption[];
}) {
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  // A chave em claro vive só aqui, no estado desta tela, até o próximo refresh.
  // Não há como pedi-la de novo — o banco guarda o HMAC.
  const [revealed, setRevealed] = useState<{ name: string; key: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const current = assumptions.find((item) => item.effectiveTo === null) ?? null;

  function submitKey(formData: FormData) {
    startTransition(async () => {
      const result = await createAgentKey(projectId, formData);
      if (result.ok && result.data) {
        setRevealed({ name: result.data.name, key: result.data.key });
        setMessage(null);
        router.refresh();
      } else if (!result.ok) {
        setMessage({ tone: "error", text: result.error });
      }
    });
  }

  function rotate(key: AgentKey) {
    startTransition(async () => {
      const result = await rotateAgentKey(projectId, key.keyId);
      if (result.ok && result.data) {
        setRevealed({ name: result.data.name, key: result.data.key });
        setMessage(null);
        router.refresh();
      } else if (!result.ok) {
        setMessage({ tone: "error", text: result.error });
      }
    });
  }

  function revoke(key: AgentKey) {
    startTransition(async () => {
      const result = await revokeAgentKey(projectId, key.keyId);
      setMessage(
        result.ok
          ? { tone: "ok", text: `A chave ${key.name} foi revogada.` }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  function submitAssumption(formData: FormData) {
    startTransition(async () => {
      const result = await openAssumption(projectId, formData);
      setMessage(
        result.ok
          ? { tone: "ok", text: "Nova vigência aberta. A anterior foi fechada, não apagada." }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  return (
    // O projeto administrado fica legível na marcação: com um projeto só não há
    // seletor nem `?project=` na URL, e "qual projeto esta tela está mexendo"
    // deixaria de ter resposta observável.
    <main className="admin-shell" data-project-id={projectId}>
      <header className="admin-head">
        <Link className="admin-back" href="/admin">
          <ArrowLeft size={16} /> Administração de acesso
        </Link>
        <p className="eyebrow">RESULTADOS</p>
        <h1>Como {projectName} apura valor</h1>
        <p className="admin-lead">
          {organization} · Os agentes mandam eventos com a chave; a premissa converte esses
          eventos em dinheiro. O cliente vê o número e a premissa que o produziu.
        </p>
      </header>

      {projects.length > 1 && (
        <nav className="admin-projects" aria-label="Escolher projeto">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/admin/resultados?project=${project.id}`}
              className={`state ${project.current ? "state--0" : "state--2"}`}
            >
              {project.name}
            </Link>
          ))}
        </nav>
      )}

      {revealed && (
        <p className="admin-note" role="status">
          <strong>Chave de {revealed.name}:</strong> <code>{revealed.key}</code>
          <br />
          Guarde agora — ela não será mostrada de novo. O portal só armazena o hash; se ela se
          perder, o caminho é rotacionar.
        </p>
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
              <p className="eyebrow">PREMISSA VIGENTE</p>
              <h2>
                {current
                  ? `${money(current.hourlyRate, current.currency)} por hora`
                  : "Nenhuma premissa configurada"}
              </h2>
            </div>
          </div>
          {current ? (
            <div className="field-list">
              <div className="field-row">
                <span className="field-label">Investimento mensal</span>
                <span className="field-value">{money(current.monthlyInvestment, current.currency)}</span>
              </div>
              <div className="field-row">
                <span className="field-label">Vigente desde</span>
                <span className="field-value">{day(current.effectiveFrom)}</span>
              </div>
              {current.note && (
                <div className="field-row">
                  <span className="field-label">Observação</span>
                  <span className="field-value">{current.note}</span>
                </div>
              )}
            </div>
          ) : (
            <p className="empty-state">
              Sem premissa, os eventos ainda contam como volume, mas não viram valor — e o
              cliente vê a lacuna declarada em vez de um número inventado.
            </p>
          )}

          <div className="panel-heading">
            <div>
              <p className="eyebrow">NOVA VIGÊNCIA</p>
              <h2>Mudar valor-hora ou investimento</h2>
            </div>
          </div>
          <p className="admin-lead">
            A premissa atual não é editada: ela é fechada na data que você escolher e uma nova
            começa ali. É o que mantém um indicador antigo explicável pelo valor que valia
            naquele dia.
          </p>
          <form className="admin-form" action={submitAssumption}>
            <label className="auth-field">
              <span>Vigente a partir de</span>
              <input name="effective_from" type="date" required />
            </label>
            <label className="auth-field">
              <span>Valor-hora (R$)</span>
              <input name="hourly_rate" type="number" min="0" step="0.01" required />
            </label>
            <label className="auth-field">
              <span>Investimento mensal (R$)</span>
              <input name="monthly_investment" type="number" min="0" step="0.01" required />
            </label>
            <label className="auth-field">
              <span>Observação</span>
              <input name="note" placeholder="Por que esta premissa é esta" />
            </label>
            <button className="ai-button admin-submit" type="submit" disabled={pending}>
              <Plus size={16} />
              {pending ? "Salvando…" : "Abrir vigência"}
            </button>
          </form>

          {assumptions.length > 1 && (
            <>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">HISTÓRICO</p>
                  <h2>{assumptions.length} vigências</h2>
                </div>
              </div>
              <div className="field-list">
                {assumptions.map((item) => (
                  <div className="field-row" key={item.assumptionId}>
                    <span className="field-label">
                      {day(item.effectiveFrom)} → {item.effectiveTo ? day(item.effectiveTo) : "hoje"}
                    </span>
                    <span className="field-value">
                      {money(item.hourlyRate, item.currency)}/h · {money(item.monthlyInvestment, item.currency)}/mês
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">CHAVES DOS AGENTES</p>
              <h2>{keys.filter((key) => !key.revoked && !key.expired).length} ativas</h2>
            </div>
          </div>
          <p className="admin-lead">
            Cada chave vale para este projeto e só para ele. O agente a envia no cabeçalho
            <code> X-Agent-Key</code> ao publicar um evento.
          </p>
          {keys.length === 0 && (
            <p className="empty-state">Nenhuma chave emitida para este projeto.</p>
          )}
          <div className="field-list">
            {keys.map((key) => {
              const state = keyState(key);
              return (
                <div className="member-row" key={key.keyId}>
                  <span className="avatar avatar--small">
                    <KeyRound size={15} />
                  </span>
                  <div className="member-identity">
                    <strong>{key.name}</strong>
                    <span>
                      {key.keyPrefix}… · {key.lastUsedAt ? `usada em ${day(key.lastUsedAt)}` : "nunca usada"}
                      {/* A cadeia de rotação, pelo prefixo da antecessora — o
                          `runbooks/agent-events-failure.md` manda lê-la, e até
                          a ADR 0033 ela não saía do banco. O id não serve à
                          leitura; o prefixo é o que aparece no log. */}
                      {key.rotatedFromId &&
                        ` · rotacionada de ${
                          keys.find((other) => other.keyId === key.rotatedFromId)?.keyPrefix ??
                          "uma chave já removida"
                        }…`}
                    </span>
                  </div>
                  <span className={`state ${state.tone}`}>{state.label}</span>
                  <button
                    className="icon-button"
                    aria-label={`Rotacionar a chave ${key.name}`}
                    disabled={pending || key.revoked}
                    onClick={() => rotate(key)}
                  >
                    <RefreshCw size={16} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Revogar a chave ${key.name}`}
                    disabled={pending || key.revoked}
                    onClick={() => revoke(key)}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              );
            })}
          </div>

          <div className="panel-heading">
            <div>
              <p className="eyebrow">EMITIR</p>
              <h2>Nova chave</h2>
            </div>
          </div>
          <form className="admin-form" action={submitKey}>
            <label className="auth-field">
              <span>Nome</span>
              <input name="name" required placeholder="Agente Financeiro — produção" />
            </label>
            <button className="ai-button admin-submit" type="submit" disabled={pending}>
              <KeyRound size={16} />
              {pending ? "Emitindo…" : "Emitir chave"}
            </button>
          </form>
        </article>
      </section>
    </main>
  );
}
