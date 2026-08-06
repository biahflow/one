"use client";

import { ArrowLeft, CalendarClock, Save, ShieldAlert, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { requestErasure, setAiQuota, setRetentionPolicy } from "../actions";

export type Organization = { id: string; name: string; slug: string; current: boolean };

export type RetentionPolicy = {
  /** Nulo é "herdado do padrão" — e a tela precisa dizer isso. */
  notificationDays: number | null;
  agentEventDays: number | null;
  conversationDays: number | null;
  effective: Record<string, number>;
};

export type Quota = {
  monthlyLimit: number | null;
  effectiveLimit: number;
  spent: number;
  inputTokens: number;
  outputTokens: number;
  calls: number;
  gaps: string[];
};

export type ErasureRequest = {
  requestId: string;
  state: string;
  reason: string | null;
  createdAt: string;
  completedAt: string | null;
  removed: Record<string, number> | null;
  error: string | null;
};

type Notice = { tone: "ok" | "error"; text: string };

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const NUMBER = new Intl.NumberFormat("pt-BR");

function moment(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("pt-BR");
}

const ERASURE_STATE: Record<string, { label: string; tone: string }> = {
  pending: { label: "Aguardando o worker", tone: "state--2" },
  running: { label: "Em execução", tone: "state--2" },
  completed: { label: "Cumprido", tone: "state--1" },
  failed: { label: "Falhou", tone: "state--3" },
};

/** Os três prazos, na ordem em que a retenção os aplica. */
const WINDOWS = [
  {
    field: "notification_days",
    label: "Avisos",
    hint: "Notificações do sino e do resumo por e-mail.",
  },
  {
    field: "agent_event_days",
    label: "Eventos dos agentes",
    hint: "A matéria-prima do ROI apurado — por isso o prazo mais longo.",
  },
  {
    field: "conversation_days",
    label: "Conversas",
    hint: "Perguntas, respostas e as citações como foram exibidas.",
  },
] as const;

/**
 * Retenção, teto de IA e apagamento — as três coisas cujo escopo é a
 * organização inteira (ADR 0027).
 *
 * Documento **não** aparece aqui, e a ausência é a decisão: ele é a evidência
 * que sustenta uma citação já dada, e apagá-lo num aniversário tornaria uma
 * resposta antiga impossível de conferir (ADR 0017). Some por decisão de
 * alguém, nunca por idade.
 */
export default function OrganizationAdminClient({
  organizations,
  organizationId,
  organizationName,
  organizationSlug,
  retention,
  quota,
  erasures,
}: {
  organizations: Organization[];
  organizationId: string;
  organizationName: string;
  organizationSlug: string;
  retention: RetentionPolicy;
  quota: Quota;
  erasures: ErasureRequest[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [notice, setNotice] = useState<Notice | null>(null);

  function run(action: () => Promise<{ ok: true } | { ok: false; error: string }>, done: string) {
    setNotice(null);
    startTransition(async () => {
      const result = await action();
      setNotice(result.ok ? { tone: "ok", text: done } : { tone: "error", text: result.error });
      if (result.ok) router.refresh();
    });
  }

  const chosen: Record<string, number | null> = {
    notification_days: retention.notificationDays,
    agent_event_days: retention.agentEventDays,
    conversation_days: retention.conversationDays,
  };

  const openRequest = erasures.find(
    (item) => item.state === "pending" || item.state === "running",
  );

  return (
    <main className="admin-shell">
      <header className="admin-head">
        <Link className="admin-back" href="/">
          <ArrowLeft size={16} /> Voltar ao portal
        </Link>
        <p className="eyebrow">DADOS DA ORGANIZAÇÃO</p>
        <h1>{organizationName}</h1>
        <p className="admin-lead">
          Identificador <code>{organizationSlug}</code> · Por quanto tempo os dados ficam,
          quanto de IA esta organização pode gastar, e o apagamento. São as três perguntas
          que não se fazem projeto a projeto.
        </p>
      </header>

      {organizations.length > 1 && (
        <nav className="admin-projects" aria-label="Escolher organização">
          {organizations.map((item) => (
            <Link
              key={item.id}
              href={`/admin/organizacao?org=${item.id}`}
              className={`state ${item.current ? "state--0" : "state--2"}`}
            >
              {item.name}
            </Link>
          ))}
        </nav>
      )}

      {notice && (
        <p className={notice.tone === "ok" ? "admin-note" : "auth-error"} role="status">
          {notice.text}
        </p>
      )}

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">RETENÇÃO</p>
            <h2>
              <CalendarClock size={17} /> Por quanto tempo os dados ficam
            </h2>
          </div>
        </div>
        <p className="admin-lead">
          Campo vazio significa <strong>usa o padrão do portal</strong>, nunca &ldquo;guarda
          para sempre&rdquo;. Documentos não têm prazo: são a evidência por trás de uma
          citação já dada, e saem por decisão de alguém — não por idade.
        </p>
        <form
          className="admin-form"
          action={(formData) =>
            run(() => setRetentionPolicy(organizationId, formData), "Prazos atualizados.")
          }
        >
          {WINDOWS.map((window) => (
            <label className="auth-field" key={window.field}>
              <span>
                {window.label} — vale hoje: {NUMBER.format(retention.effective[window.field])}{" "}
                dias {chosen[window.field] === null ? "(herdado)" : "(escolhido)"}
              </span>
              <input
                name={window.field}
                type="number"
                min="1"
                max="3650"
                defaultValue={chosen[window.field] ?? ""}
                placeholder="Vazio = padrão do portal"
              />
              <small className="field-hint">{window.hint}</small>
            </label>
          ))}
          <button className="ai-button admin-submit" type="submit" disabled={pending}>
            <Save size={16} />
            {pending ? "Salvando…" : "Salvar prazos"}
          </button>
        </form>
      </article>

      <article className="panel section-gap">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">GASTO DE IA</p>
            <h2>
              <Wallet size={17} /> Teto mensal e consumo
            </h2>
          </div>
          <span className="state state--1">{BRL.format(quota.spent)} este mês</span>
        </div>
        <div className="field-list">
          <div className="field-row">
            <span className="field-label">Teto em vigor</span>
            <span className="field-value">
              {BRL.format(quota.effectiveLimit)}
              {quota.monthlyLimit === null ? " (herdado)" : " (escolhido)"}
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Chamadas no mês</span>
            <span className="field-value">{NUMBER.format(quota.calls)}</span>
          </div>
          <div className="field-row">
            <span className="field-label">Tokens (entrada / saída)</span>
            <span className="field-value">
              {NUMBER.format(quota.inputTokens)} / {NUMBER.format(quota.outputTokens)}
            </span>
          </div>
        </div>
        {quota.gaps.length > 0 && (
          <p className="auth-error" role="status">
            O gasto acima está incompleto: {quota.gaps.join("; ")}. Chamadas cujo modelo não
            tinha preço vigente não entram na soma, então o mês parece mais barato do que foi
            — e o teto fica cego enquanto isso durar.
          </p>
        )}
        <form
          className="admin-form"
          action={(formData) =>
            run(() => setAiQuota(organizationId, formData), "Teto atualizado.")
          }
        >
          <label className="auth-field">
            <span>Teto mensal (R$)</span>
            <input
              name="monthly_limit"
              type="number"
              min="0"
              step="0.01"
              defaultValue={quota.monthlyLimit ?? ""}
              placeholder="Vazio = padrão do portal"
            />
            <small className="field-hint">
              Zero desliga a IA para esta organização, e é uma decisão explícita — que é o que
              a distingue de um esquecimento. Atingido o teto, o chat responde que a cota
              acabou; nada é cobrado e nada é registrado.
            </small>
          </label>
          <button className="ai-button admin-submit" type="submit" disabled={pending}>
            <Save size={16} />
            {pending ? "Salvando…" : "Salvar teto"}
          </button>
        </form>
      </article>

      <article className="panel section-gap">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">APAGAMENTO</p>
            <h2>
              <ShieldAlert size={17} /> Apagar os dados desta organização
            </h2>
          </div>
        </div>
        <p className="admin-lead">
          Isto grava um <strong>pedido</strong>: nenhuma rota do portal apaga dado. Quem
          cumpre é o worker, e o que ele remove é o conteúdo dos projetos e os vínculos —
          ficam a organização, as contas das pessoas (que podem pertencer a outra) e o
          registro deste pedido, porque um apagamento sem registro é indistinguível de um
          acidente. <strong>Não há como desfazer.</strong>
        </p>

        {openRequest ? (
          <p className="admin-note" role="status">
            Já existe um pedido {ERASURE_STATE[openRequest.state]?.label.toLowerCase()} desde{" "}
            {moment(openRequest.createdAt)}. Pedir de novo não enfileira um segundo expurgo.
          </p>
        ) : (
          <form
            className="admin-form"
            action={(formData) =>
              run(
                () => requestErasure(organizationId, formData),
                "Pedido registrado. O worker executa e escreve na linha o que removeu.",
              )
            }
          >
            <label className="auth-field">
              <span>Por que o apagamento foi pedido</span>
              <input name="reason" required placeholder="Encerramento de contrato, pedido do titular…" />
            </label>
            <label className="auth-field">
              <span>
                Digite <code>{organizationSlug}</code> para confirmar
              </span>
              <input name="confirm_slug" required placeholder={organizationSlug} autoComplete="off" />
              <small className="field-hint">
                A confirmação não é cerimônia: ela obriga a olhar <strong>qual</strong>{" "}
                organização está na tela, que é o erro que esta ação pode causar e nenhuma
                outra pode.
              </small>
            </label>
            <button className="ai-button admin-submit admin-submit--danger" type="submit" disabled={pending}>
              <ShieldAlert size={16} />
              {pending ? "Registrando…" : "Pedir apagamento"}
            </button>
          </form>
        )}

        <div className="panel-heading section-gap">
          <div>
            <p className="eyebrow">REGISTRO</p>
            <h2>Pedidos desta organização</h2>
          </div>
        </div>
        {erasures.length === 0 ? (
          <p className="empty-state">Nenhum apagamento pedido até hoje.</p>
        ) : (
          <div className="field-list">
            {erasures.map((item) => {
              const state = ERASURE_STATE[item.state] ?? { label: item.state, tone: "state--2" };
              const removed = item.removed
                ? Object.entries(item.removed)
                    .map(([table, count]) => `${table}: ${NUMBER.format(count)}`)
                    .join(" · ")
                : null;
              return (
                <div className="field-row" key={item.requestId}>
                  <span className="field-label">
                    {moment(item.createdAt)}
                    {item.reason ? ` — ${item.reason}` : ""}
                    {removed ? ` · ${removed}` : ""}
                    {item.error ? ` · ${item.error}` : ""}
                  </span>
                  <span className={`state ${state.tone}`}>{state.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </article>
    </main>
  );
}
