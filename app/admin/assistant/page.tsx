import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import AssistantAdminClient, { type RatedTurn, type Signal } from "./AssistantAdminClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiMe = {
  is_internal: boolean;
  organization: string | null;
  projects: { id: string; name: string; slug: string; status: string }[];
};

type ApiTurn = {
  message_id: string;
  created_at: string;
  confidence: string | null;
  feedback: string;
  feedback_comment: string | null;
  feedback_at: string | null;
  responder: string | null;
  model: string | null;
  prompt_version: string | null;
  opened_pending: boolean;
};

type ApiSignal = {
  project_id: string;
  answers_total: number;
  rated_total: number;
  helpful: number;
  not_helpful: number;
  insufficient_context: number;
  turns: ApiTurn[];
};

/**
 * Como o assistente está indo, para quem o mantém (ADR 0030).
 *
 * O feedback é gravado desde a ADR 0015 e nunca foi lido: aquela ADR adiou a
 * tela dizendo que "sem dado acumulado ela mostraria zero", e o dado acumulou.
 *
 * **O que esta tela não mostra é o ponto dela:** a pergunta do cliente não
 * aparece, e não por escolha do componente — o papel de banco que a rota usa
 * *não consegue* ler `conversation_message.text` nem `conversation.title`
 * (migração 0020). A fronteira está no GRANT de coluna, não numa lembrança de
 * quem escreve a tela.
 */
export default async function AssistantAdminPage({
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

  const response = await fetch(
    `${base}/api/v1/admin/projects/${project.id}/assistant-signal`,
    { headers: authorization, cache: "no-store" },
  );
  if (response.status === 404) notFound();
  if (!response.ok) throw new Error(`GET assistant-signal respondeu ${response.status}`);

  const body: ApiSignal = await response.json();
  const turns: RatedTurn[] = body.turns.map((turn) => ({
    messageId: turn.message_id,
    createdAt: turn.created_at,
    confidence: turn.confidence,
    feedback: turn.feedback,
    comment: turn.feedback_comment,
    ratedAt: turn.feedback_at,
    responder: turn.responder,
    model: turn.model,
    promptVersion: turn.prompt_version,
    openedPending: turn.opened_pending,
  }));

  const signal: Signal = {
    answersTotal: body.answers_total,
    ratedTotal: body.rated_total,
    helpful: body.helpful,
    notHelpful: body.not_helpful,
    insufficientContext: body.insufficient_context,
    turns,
  };

  return (
    <AssistantAdminClient
      projects={me.projects.map((candidate) => ({
        id: candidate.id,
        name: candidate.name,
        current: candidate.id === project.id,
      }))}
      projectName={project.name}
      signal={signal}
    />
  );
}
