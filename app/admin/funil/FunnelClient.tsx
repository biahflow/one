"use client";

import { ArrowLeft, HelpCircle, PhoneCall, Wrench } from "lucide-react";
import Link from "next/link";

export type ClientRow = {
  organizationId: string;
  organizationName: string;
  currentStep: string | null;
  blockedBy: string | null;
  daysStuck: number | null;
  thresholdDays: number;
  stuck: boolean;
  nextAction: string;
  gaps: string[];
  anchorAt: string;
  anchorSource: string;
};

/**
 * O degrau em português. O mesmo enum tem rótulo do lado do Python (`_STEP_LABEL`, para o
 * título do aviso no sino) — este aqui é a coluna da tabela, e diz o que **falta**, não o
 * que aconteceu.
 */
const STEP_LABELS: Record<string, string> = {
  first_login: "Nunca entrou no portal",
  first_document_opened: "Nunca abriu um documento",
  first_pending_answered: "Nunca respondeu uma pendência",
  first_chat_turn: "Nunca perguntou ao assistente",
  first_roi_seen: "Nunca viu o ROI",
  first_deliverable_delivered: "Nenhum entregável liberado",
};

/**
 * Os códigos de lacuna que a API declara. Traduzidos aqui porque quem lê é quem atende o
 * cliente — e cada um explica **o que não se sabe** sobre a linha, que é a informação que
 * impede alguém de ligar para quem já cumpriu o degrau.
 */
const GAP_LABELS: Record<string, string> = {
  before_instrumentation:
    "anterior à instrumentação (07/08/2026): este degrau pode ter sido cumprido antes de existir medição",
  login_before_instrumentation:
    "o primeiro login é anterior à medição e foi reconhecido pela conta, não pelo carimbo",
  no_client_member: "ninguém do cliente foi convidado, então a contagem é sobre nós",
  steps_may_have_been_purged:
    "os carimbos podem ter saído pela retenção, que é mais velha que esta organização",
};

const ANCHOR_LABELS: Record<string, string> = {
  step: "último degrau alcançado",
  membership: "convite do primeiro cliente",
  organization: "criação da organização",
};

function day(value: string): string {
  return new Date(value).toLocaleDateString("pt-BR");
}

function Row({ row }: { row: ClientRow }) {
  return (
    <div className="field-row">
      <span className="field-label">
        <strong>{row.organizationName}</strong>
        {row.currentStep ? ` · ${STEP_LABELS[row.currentStep] ?? row.currentStep}` : ""}
        <br />
        {row.nextAction}
        <br />
        <small>
          Contando desde {day(row.anchorAt)} (
          {ANCHOR_LABELS[row.anchorSource] ?? row.anchorSource})
          {row.gaps.length > 0
            ? ` · ${row.gaps.map((gap) => GAP_LABELS[gap] ?? gap).join("; ")}`
            : ""}
        </small>
      </span>
      <span className={`state ${row.stuck ? "state--3" : "state--2"}`}>
        {row.daysStuck === null
          ? "— dias"
          : `${row.daysStuck} de ${row.thresholdDays} dias`}
      </span>
    </div>
  );
}

/**
 * Clientes travados no funil de onboarding (RFC 001 passo 3, ADR 0040).
 *
 * **Dois painéis separados, e nenhum total.** A FDD 020 exige que "travou no cliente" e
 * "travou em nós" nunca sejam somados na mesma contagem, e aqui isso é estrutura do
 * componente em vez de convenção de quem escrever a próxima linha: não existe lugar onde os
 * dois números possam ser adicionados.
 *
 * O terceiro painel é o das linhas **sem base para medir** — e ele não é o rodapé dos
 * outros dois. Um cliente cuja organização é anterior à medição não é menos grave que um
 * travado há três dias: é desconhecido, que é outra coisa (o mesmo princípio com que
 * `results.py` declara base ausente em vez de dividir por zero). A contagem de dias
 * aparece nele mesmo assim, porque sai de uma data real — o que a fatia recusa é inventar
 * um zero, não mostrar o que se sabe.
 *
 * Nenhum controle de escrita: esta tela só lê. A ação mora no telefone.
 */
export default function FunnelClient({ rows }: { rows: ClientRow[] }) {
  // A partição é por **certeza** e depois por lado. Uma linha incerta não é uma linha menos
  // grave: é uma linha sobre a qual não se pode ligar para ninguém, e por isso ela não entra
  // em nenhuma das duas contagens.
  const uncertain = rows.filter((row) => row.gaps.includes("before_instrumentation"));
  const certain = rows.filter((row) => !row.gaps.includes("before_instrumentation"));
  const stuckOnClient = certain.filter(
    (row) => row.stuck && row.blockedBy === "client",
  );
  const stuckOnUs = certain.filter((row) => row.stuck && row.blockedBy === "us");
  const moving = certain.filter((row) => !row.stuck);

  return (
    <main className="admin-shell">
      <header className="admin-head">
        <Link className="admin-back" href="/admin">
          <ArrowLeft size={16} /> Voltar à administração
        </Link>
        <p className="eyebrow">FUNIL DE ONBOARDING</p>
        <h1>Clientes travados</h1>
        <p className="admin-lead">
          Onde cada cliente parou de receber valor, e há quantos dias. O caso que esta tela
          existe para tornar visível é uma linha só — <em>ganho há nove dias, convite
          enviado, nunca logou</em> —, e aos nove dias ele ainda se resolve com um
          telefonema. <strong>As duas colunas nunca se somam</strong>: quando o degrau não
          avança porque a entrega não saiu, o alerta é sobre a equipe.
        </p>
        <div className="field-list">
          <div className="field-row">
            <span className="field-label">Travados no cliente</span>
            <span className="field-value">{stuckOnClient.length}</span>
          </div>
          <div className="field-row">
            <span className="field-label">Travados em nós</span>
            <span className="field-value">{stuckOnUs.length}</span>
          </div>
          <div className="field-row">
            <span className="field-label">Sem base para medir</span>
            <span className="field-value">{uncertain.length}</span>
          </div>
        </div>
      </header>

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">TRAVOU NO CLIENTE</p>
            <h2>
              <PhoneCall size={17} /> Ele tem tudo e não veio
            </h2>
          </div>
        </div>
        {stuckOnClient.length === 0 ? (
          <p className="empty-state">
            Nenhum cliente parado além do limiar. Nada a fazer aqui hoje.
          </p>
        ) : (
          <div className="field-list">
            {stuckOnClient.map((row) => (
              <Row key={row.organizationId} row={row} />
            ))}
          </div>
        )}
      </article>

      <article className="panel section-gap">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">TRAVOU EM NÓS</p>
            <h2>
              <Wrench size={17} /> Falta alguma coisa nossa
            </h2>
          </div>
        </div>
        {stuckOnUs.length === 0 ? (
          <p className="empty-state">
            Nenhum cliente esperando por nós. Este é o painel que deve ficar vazio.
          </p>
        ) : (
          <div className="field-list">
            {stuckOnUs.map((row) => (
              <Row key={row.organizationId} row={row} />
            ))}
          </div>
        )}
      </article>

      <article className="panel section-gap">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SEM BASE PARA MEDIR</p>
            <h2>
              <HelpCircle size={17} /> Não dá para dizer
            </h2>
          </div>
        </div>
        {uncertain.length === 0 ? (
          <p className="empty-state">Toda organização listada tem contagem confiável.</p>
        ) : (
          <div className="field-list">
            {uncertain.map((row) => (
              <Row key={row.organizationId} row={row} />
            ))}
          </div>
        )}
        <p className="panel-note">
          Degrau ausente não é degrau zerado. Estas linhas não recebem contagem e não
          disparam alerta — exibir &ldquo;0 dias&rdquo; aqui seria inventar precisão sobre
          uma organização que talvez tenha alcançado o degrau antes de existir medição.
        </p>
      </article>

      {moving.length > 0 && (
        <article className="panel section-gap">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">DENTRO DO PRAZO</p>
              <h2>{moving.length} andando normalmente</h2>
            </div>
          </div>
          <div className="field-list">
            {moving.map((row) => (
              <Row key={row.organizationId} row={row} />
            ))}
          </div>
        </article>
      )}
    </main>
  );
}
