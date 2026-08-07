import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import FunnelClient, { type ClientRow } from "./FunnelClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiOrganization = { organization_id: string; name: string; slug: string };

type ApiFunnel = {
  current_step: string | null;
  blocked_by: string | null;
  days_stuck: number | null;
  threshold_days: number;
  stuck: boolean;
  next_action: string;
  gaps: string[];
  anchor_at: string;
  anchor_source: string;
};

/**
 * A ordem de valor dos degraus, para o desempate da gravidade.
 *
 * Duplica a `LADDER` de `onboarding.py`, e é o único ponto de deriva possível entre os dois
 * lados. A consequência de divergir é cosmética — muda só a ordem de dois clientes empatados
 * em dias — e o preço de evitá-la seria mandar a escada inteira no payload, um campo por
 * degrau que nenhuma coluna da tela lê.
 */
const STEP_ORDER = [
  "artifact_accepted",
  "first_login",
  "first_document_opened",
  "first_pending_answered",
  "first_chat_turn",
  "first_roi_seen",
  "first_deliverable_delivered",
];

/**
 * A lista interna de clientes travados no funil de onboarding (RFC 001 passo 3, ADR 0040).
 *
 * O funil é carimbado desde a ADR 0039 e **nenhuma tela o mostrava** — a ordem foi
 * deliberada, porque a ADR 0033 achou um painel publicado sobre um campo que nunca teve
 * escritor. Esta é a leitura, e o caso que ela existe para tornar visível é uma linha só:
 * "ganho há nove dias, convite enviado, nunca logou".
 *
 * **Fan-out sobre as organizações administradas**, e não um seletor `?org=` como em
 * `/admin/organizacao`: a FDD 020 pede a lista *ordenada por gravidade*, e ranquear é
 * comparar clientes entre si. A rota da API continua escopada por organização — `bind_admin_org`
 * é monotônica, então uma rota cross-org não conseguiria ler sob as policies do papel
 * administrativo — e o ranking acontece aqui, sobre dado que a API já autorizou uma a uma.
 */
export default async function FunnelAdminPage() {
  const base = process.env.API_BASE_URL;
  const session = await auth();
  const authorization = await authorizationHeader();
  if (!base || !session || session.error || !authorization) redirect("/login");

  const organizationsResponse = await fetch(`${base}/api/v1/admin/organizations`, {
    headers: authorization,
    cache: "no-store",
  });
  if (organizationsResponse.status === 401) redirect("/login");
  if (!organizationsResponse.ok) {
    throw new Error(
      `GET /api/v1/admin/organizations respondeu ${organizationsResponse.status}`,
    );
  }

  const listed: ApiOrganization[] = await organizationsResponse.json();
  if (listed.length === 0) notFound();

  const readings = await Promise.all(
    listed.map((organization) =>
      fetch(
        `${base}/api/v1/admin/organizations/${organization.organization_id}/onboarding`,
        { headers: authorization, cache: "no-store" },
      ),
    ),
  );

  const rows: ClientRow[] = [];
  for (const [index, response] of readings.entries()) {
    // 404 aqui **não** é o mesmo que em `/admin/organizacao`, e a diferença é deliberada.
    // Lá o id vem da URL e um 404 responde "você não administra esta", então a página
    // inteira é `notFound()`. Aqui os ids vieram da listagem, que já é derivada dos
    // vínculos deste chamador — um 404 é corrida (vínculo revogado entre as duas chamadas),
    // e um vínculo revogado não pode apagar da tela a lista de todos os outros clientes.
    if (response.status === 404) continue;
    if (response.status === 401) redirect("/login");
    if (!response.ok) {
      throw new Error(`GET .../onboarding respondeu ${response.status}`);
    }
    const funnel: ApiFunnel = await response.json();
    rows.push({
      organizationId: listed[index].organization_id,
      organizationName: listed[index].name,
      currentStep: funnel.current_step,
      blockedBy: funnel.blocked_by,
      daysStuck: funnel.days_stuck,
      thresholdDays: funnel.threshold_days,
      stuck: funnel.stuck,
      nextAction: funnel.next_action,
      gaps: funnel.gaps,
      anchorAt: funnel.anchor_at,
      anchorSource: funnel.anchor_source,
    });
  }
  // Todas negaram: aí sim não há nada que este chamador administre de verdade.
  if (rows.length === 0) notFound();

  // Gravidade: quem estourou mais o próprio limiar primeiro, e o degrau mais baixo
  // desempata — quem nunca logou vale mais que quem não viu ROI, porque o primeiro não
  // recebeu nada. As linhas sem medição não entram nesta ordenação: elas vão para um bloco
  // próprio no cliente, e "não dá para dizer" não é "menos grave".
  rows.sort((a, b) => {
    const excess = (row: ClientRow) =>
      row.daysStuck === null ? -Infinity : row.daysStuck - row.thresholdDays;
    const difference = excess(b) - excess(a);
    if (difference !== 0) return difference;
    return (
      STEP_ORDER.indexOf(a.currentStep ?? "") - STEP_ORDER.indexOf(b.currentStep ?? "")
    );
  });

  return <FunnelClient rows={rows} />;
}
