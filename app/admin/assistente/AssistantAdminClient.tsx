"use client";

import { ArrowLeft, MessageSquare, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";

/**
 * Os dois desfechos que `ai/service.py` produz. Ditos em português porque esta
 * linha é lida por quem atende o cliente, não por quem lê o log — e "declarou
 * lacuna" é o comportamento correto da regra 3 do `AGENTS.md`, não uma falha.
 */
const CONFIDENCE_LABELS: Record<string, string> = {
  grounded: "com evidência",
  insufficient_context: "declarou lacuna",
};

export type RatedTurn = {
  messageId: string;
  createdAt: string;
  confidence: string | null;
  feedback: string;
  comment: string | null;
  ratedAt: string | null;
  responder: string | null;
  model: string | null;
  promptVersion: string | null;
  openedPending: boolean;
};

export type Signal = {
  answersTotal: number;
  ratedTotal: number;
  helpful: number;
  notHelpful: number;
  insufficientContext: number;
  turns: RatedTurn[];
};

type ProjectOption = { id: string; name: string; current: boolean };

const NUMBER = new Intl.NumberFormat("pt-BR");

function moment(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("pt-BR");
}

function percent(part: number, whole: number): string {
  if (whole === 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}

/**
 * O sinal do assistente (ADR 0030).
 *
 * Nenhum controle de escrita: esta tela só lê. E não há pergunta nem resposta
 * nela — o papel de banco da rota não alcança essas colunas (migração 0020), e
 * o que o time lê é a avaliação que o cliente endereçou **a ele**.
 */
export default function AssistantAdminClient({
  projects,
  projectName,
  signal,
}: {
  projects: ProjectOption[];
  projectName: string;
  signal: Signal;
}) {
  return (
    <main className="admin-shell">
      <header className="admin-head">
        <Link className="admin-back" href="/">
          <ArrowLeft size={16} /> Voltar ao portal
        </Link>
        <p className="eyebrow">ASSISTENTE</p>
        <h1>Como o assistente está indo em {projectName}</h1>
        <p className="admin-lead">
          A avaliação que os clientes deixaram, a calibragem de cada resposta e quantas
          declararam lacuna. <strong>A pergunta do cliente não aparece aqui</strong>, e não
          por omissão da tela: o papel de banco desta rota não consegue lê-la.
        </p>
      </header>

      {projects.length > 1 && (
        <nav className="admin-projects" aria-label="Escolher projeto">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/admin/assistente?project=${project.id}`}
              className={`state ${project.current ? "state--0" : "state--2"}`}
            >
              {project.name}
            </Link>
          ))}
        </nav>
      )}

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">AGREGADO</p>
            <h2>{NUMBER.format(signal.answersTotal)} respostas</h2>
          </div>
        </div>
        <div className="field-list">
          <div className="field-row">
            <span className="field-label">Avaliadas</span>
            <span className="field-value">
              {NUMBER.format(signal.ratedTotal)} ({percent(signal.ratedTotal, signal.answersTotal)})
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Ajudaram</span>
            <span className="field-value">
              {NUMBER.format(signal.helpful)} ({percent(signal.helpful, signal.ratedTotal)})
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Não ajudaram</span>
            <span className="field-value">
              {NUMBER.format(signal.notHelpful)} ({percent(signal.notHelpful, signal.ratedTotal)})
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Declararam lacuna</span>
            <span className="field-value">
              {NUMBER.format(signal.insufficientContext)} (
              {percent(signal.insufficientContext, signal.answersTotal)})
            </span>
          </div>
        </div>
        <p className="panel-note">
          &ldquo;Declararam lacuna&rdquo; é o sinal mais objetivo dos dois: ninguém precisa
          clicar no polegar para ele contar. Uma taxa alta aqui costuma significar índice
          pobre, não modelo ruim — o caminho é <Link href="/admin/conhecimento">Conhecimento</Link>.
        </p>
      </article>

      <article className="panel section-gap">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">AVALIAÇÕES</p>
            <h2>
              <MessageSquare size={17} /> O que os clientes disseram
            </h2>
          </div>
        </div>
        {signal.turns.length === 0 ? (
          <p className="empty-state">
            Nenhuma resposta avaliada ainda. O polegar aparece no chat, abaixo de cada
            resposta.
          </p>
        ) : (
          <div className="field-list">
            {signal.turns.map((turn) => (
              <div className="field-row" key={turn.messageId}>
                <span className="field-label">
                  {moment(turn.ratedAt ?? turn.createdAt)}
                  {turn.comment ? ` — ${turn.comment}` : ""}
                  {/* A calibragem que o cabeçalho promete. Ela vinha da API,
                      era mapeada em `RatedTurn` e não era renderizada — o
                      campo mais direto para responder "o assistente errou
                      sabendo ou errou achando que sabia" (ADR 0033). */}
                  {turn.confidence ? ` · ${CONFIDENCE_LABELS[turn.confidence] ?? turn.confidence}` : ""}
                  {turn.openedPending ? " · abriu pendência" : ""}
                  {turn.responder ? ` · ${turn.responder}` : ""}
                  {turn.model ? ` · ${turn.model}` : ""}
                  {turn.promptVersion ? ` · ${turn.promptVersion}` : ""}
                </span>
                <span
                  className={`state ${turn.feedback === "helpful" ? "state--1" : "state--3"}`}
                >
                  {turn.feedback === "helpful" ? (
                    <>
                      <ThumbsUp size={12} /> Ajudou
                    </>
                  ) : (
                    <>
                      <ThumbsDown size={12} /> Não ajudou
                    </>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </article>
    </main>
  );
}
