"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  Bell,
  Bot,
  Building2,
  CalendarClock,
  Check,
  ChevronDown,
  ClipboardCheck,
  Clock3,
  Compass,
  Download,
  FileText,
  FolderOpen,
  HelpCircle,
  Inbox,
  LayoutDashboard,
  Lock,
  LogOut,
  MapPin,
  Menu,
  MessageCircleMore,
  MessageSquare,
  MessageSquarePlus,
  MoreHorizontal,
  PanelLeftClose,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  ThumbsDown,
  ThumbsUp,
  Scale,
  TrendingUp,
  User,
  UsersRound,
  Video,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState, useTransition } from "react";

import { Brand } from "@/components/one/Brand";
import { Button } from "@/components/one/Button";
import { StatePill, type StatePillVariant } from "@/components/one/StatePill";

import {
  addPendingCommentAction,
  listPendingCommentsAction,
  markNotificationsReadAction,
  recordDeliverableDecisionAction,
  type DecisionOutcome,
  type PendingComment,
  type ChannelPreferences,
  setEmailPreferenceAction,
  setPhoneAction,
  setWhatsappPreferenceAction,
  signOutAction,
} from "./actions";

// A citação como ela chega da API (ADR 0017): o rótulo que a pessoa vê e, quando a
// evidência veio de um arquivo, o ponteiro que a torna clicável. `document_id` é
// nulo para evidência do read model — um marco não é um arquivo e não tem o que
// abrir.
// `date` (ADR 0038) é a data da fonte em ISO, ou nula quando a fonte não data o
// fato — marco e status não datam. Ela **também** aparece dentro de `label`, que é
// "o rótulo como foi exibido"; este campo existe para a tela poder tratá-la como
// data em vez de texto, e é o que permite explicar o parêntese a quem o lê.
type Citation = { label: string; document_id?: string | null; dated_at?: string | null };

/** "Versão da fonte em 12 de março de 2026" — o que o parêntese do rótulo quer dizer. */
function citationHint(citation: Citation): string | undefined {
  if (!citation.dated_at) return undefined;
  const parsed = new Date(`${citation.dated_at}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return `Versão da fonte em ${parsed.toLocaleDateString("pt-BR", { dateStyle: "long" })}`;
}

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  citations?: Citation[];
  pending?: boolean;
  // Só existe quando o turno foi gravado pela API (ADR 0015): sem id não há o que
  // avaliar, e é assim que a saudação e o fallback offline ficam sem polegares —
  // avaliar uma resposta que não foi registrada não levaria a lugar nenhum.
  id?: string;
  feedback?: "helpful" | "not_helpful" | null;
  // Como a API classificou o próprio turno: `grounded` quando respondeu sobre
  // evidência, `insufficient_context` quando declarou a lacuna (ADR 0033). Vinha
  // em toda resposta e era descartado aqui — o cliente via "Pendência criada"
  // sem que nada dissesse que a resposta acima dela não tinha lastro.
  confidence?: string | null;
};

const navItems = [
  { label: "Visão geral", icon: LayoutDashboard },
  { label: "Cronograma", icon: CalendarClock },
  { label: "Documentos", icon: FolderOpen },
  { label: "Reuniões", icon: UsersRound },
  // Onde o cliente aprova a entrega ou pede ajuste (FDD 027, ADR 0077). A ordem é a
  // de `portal_api/tabs.py`, e `test_tabs.py` reprova se as duas divergirem.
  { label: "Revisão", icon: ClipboardCheck },
  { label: "Pendências", icon: Inbox },
  { label: "Decisões", icon: Scale },
  { label: "Resultados", icon: TrendingUp },
  // O rótulo em inglês é decisão, e a razão está em `portal_api/tabs.py`: a §1 do
  // Language Map manda não traduzir o termo canônico, e a §2 escreve "Discovery" na
  // coluna do que o cliente vê. Trocar por "Descoberta" aqui reprova em `test_tabs.py`.
  { label: "Discovery", icon: Compass },
];

/** Alta antes de média antes de baixa. Desconhecida vai para o fim, não para o topo. */
const PRIORITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

/**
 * Pendências que ainda pedem ação — resolvidas ficam no histórico —, com as
 * urgentes primeiro (ADR 0029).
 *
 * A ordem importa mais do que parece: a Visão geral mostra as **quatro
 * primeiras**, e sem isto ela mostrava as quatro mais recentes. Um resumo que
 * corta por data é as primeiras linhas de um `ORDER BY created_at` com nome de
 * resumo — foi o que escondeu a pendência semeada quando o e2e rodou num banco
 * usado.
 *
 * Só a prioridade entra na comparação: o `sort` é estável, e a API já devolve
 * por `created_at desc`, então dentro de cada faixa a mais recente continua em
 * cima sem que este arquivo precise repetir o critério dela.
 */
function openPendings(overview: Overview): PendingItemView[] {
  return overview.pendings
    .filter((item) => item.state !== "resolved")
    .slice()
    .sort(
      (a, b) =>
        (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9),
    );
}

/**
 * A escada de aceite (DAP F-027; os cinco rótulos e seus tons são **retidos** da
 * F-025 §10, não novos).
 *
 * Duas coisas separadas de propósito. A escada é a **legenda** — os cinco degraus,
 * na ordem, com o rótulo e o tom que o pacote aprovou. O estado do card é
 * **derivado do dado** por `acceptanceState`, e derivar não é o mesmo que ter
 * produtor: hoje o snapshot traz `pending`/`delivered` e o registro traz
 * `accepted`/`changes_requested`, e nada neste produto emite `client_review` nem
 * `done`. Eles ficam na legenda, que é onde o artefato aprovado os põe, e nenhum
 * card os veste — porque a tela só desenha o que a API entregou.
 *
 * `done` é **cinza** e a decisão é do ADR 0067: quem conclui a entrega é o
 * lifecycle de Delivery. O aceite do cliente autoriza `accepted`, nunca `done`, e
 * um `done` colorido como conquista do cliente diria o contrário.
 */
type AcceptanceState =
  | "ready_for_acceptance"
  | "client_review"
  | "accepted"
  | "changes_requested"
  | "done";

const ACCEPTANCE_LADDER: readonly AcceptanceState[] = [
  "ready_for_acceptance",
  "client_review",
  "accepted",
  "changes_requested",
  "done",
];

const ACCEPTANCE_LABEL: Record<AcceptanceState, string> = {
  ready_for_acceptance: "Pronto para revisão",
  client_review: "Em revisão",
  accepted: "Aprovado",
  changes_requested: "Ajuste pedido",
  done: "Concluído pela operação",
};

/**
 * O tom de cada degrau, e os dois que a primitiva ainda não cobre.
 *
 * `StatePill` tem quatro variantes semânticas (F-025 T02) e nenhuma de marca nem
 * neutra — é a mesma lacuna que o `PILL_VARIANT` acima já declara ao deixar o `"2"`
 * sem entrada. `brand` e `grey` caem no `.state` legado, que tem exatamente os
 * valores do pacote (`.state--0` é `brand-50/brand-700`, `.state--2` é
 * `surface-sunken/muted`). Acrescentar variante à primitiva está fora do escopo
 * desta fatia, e o preço é declarado: os dois saem **sem ícone**. O rótulo carrega
 * o sentido nos dois casos, então o estado não depende só de cor.
 */
const ACCEPTANCE_TONE: Record<AcceptanceState, StatePillVariant | "brand" | "grey"> = {
  ready_for_acceptance: "brand",
  client_review: "info",
  accepted: "success",
  changes_requested: "warning",
  done: "grey",
};

/** O degrau em que a entrega está, ou `null` quando o histórico não carregou. */
function acceptanceState(decisions: DeliverableDecision[] | null): AcceptanceState | null {
  if (decisions === null) return null;
  // A decisão em vigor é a **última**, e as anteriores continuam lá — é o que a
  // ordem da API significa, e é o que torna a supersessão legível sem coluna
  // nenhuma. Sem decisão, a entrega está pronta para a revisão do cliente.
  return decisions.at(-1)?.action ?? "ready_for_acceptance";
}

/** O selo do degrau: a primitiva quando há variante, o `.state` legado quando não há. */
function AcceptancePill({ state }: { state: AcceptanceState }) {
  const tone = ACCEPTANCE_TONE[state];
  const label = ACCEPTANCE_LABEL[state];
  if (tone === "brand") return <span className="state state--0">{label}</span>;
  if (tone === "grey") return <span className="state state--2">{label}</span>;
  return <StatePill variant={tone}>{label}</StatePill>;
}

/** Um entregável que a operação já entregou, com a fase em que ele vive. */
type ReviewItem = { phaseName: string; deliverable: JourneyDeliverable };

/**
 * O que aparece na aba de Revisão.
 *
 * A elegibilidade sai do **estado que o snapshot já traz** (resolução do gate de
 * 27/08/2026): entregue pela operação é o que abre a revisão do cliente. O que a
 * operação ainda não entregou não tem decisão a receber, e listá-lo pediria ao
 * cliente que aprovasse o que não existe.
 */
function reviewItems(overview: Overview): ReviewItem[] {
  return overview.journey.phases.flatMap((phase) =>
    phase.deliverables
      .filter((deliverable) => deliverable.state === "delivered")
      .map((deliverable) => ({ phaseName: phase.name, deliverable })),
  );
}

/**
 * Quantas entregas estão **com o cliente** — o contador da barra lateral.
 *
 * Só conta o que ele pode decidir: entregue, identificado na origem e ainda sem
 * decisão nenhuma. Depois de aprovar ou de pedir ajuste a bola está do outro lado,
 * e um contador que continuasse marcando pediria uma ação que já foi feita. O
 * histórico que não carregou também não conta — não se sabe de quem é a bola.
 */
function awaitingReview(overview: Overview): number {
  return reviewItems(overview).filter(
    ({ deliverable }) =>
      deliverable.externalRef !== null &&
      deliverable.decisions !== null &&
      deliverable.decisions.length === 0,
  ).length;
}

/**
 * Toda âncora que esta tela consegue desenhar, no formato do `?item=` (ADR 0056).
 *
 * Existe para uma pergunta só, e é a que faz a degradação **aparecer**: o rótulo
 * que o aviso apontou ainda está no projeto? Sem ela, "cliquei no aviso do marco X
 * e o marco X não está aqui" seria a pergunta que o suporte receberia — o cliente
 * chega na aba certa e nada acontece, que é exatamente o defeito silencioso que a
 * ADR 0033 nomeou.
 *
 * **É a lista de dados e não o DOM**, ao contrário do efeito que rola até a linha,
 * e a razão é o servidor: um `querySelectorAll` só existe depois da hidratação, e a
 * nota precisa vir no HTML do SSR — senão ela pisca depois da primeira pintura e
 * nenhuma asserção de HTML renderizado a alcança. As duas respostas coincidem
 * porque os quatro filtros de aba nascem em "todos" e a linha ancorada está no
 * primeiro render.
 *
 * Os literais são os mesmos dos `data-item` abaixo, e é `test_item_anchor.py` quem
 * cobra que os espaços de nomes daqui sejam os do Python.
 */
function screenAnchors(overview: Overview): Set<string> {
  const anchors = new Set<string>();
  for (const phase of overview.journey.phases) {
    anchors.add(`phase:${phase.name}`);
    for (const deliverable of phase.deliverables) anchors.add(`deliverable:${deliverable.name}`);
  }
  for (const milestone of overview.milestones) anchors.add(`milestone:${milestone.title}`);
  for (const document of overview.documents) anchors.add(`document:${document.title}`);
  for (const meeting of overview.meetings) anchors.add(`meeting:${meeting.title}`);
  for (const pending of overview.pendings) anchors.add(`pending:${pending.title}`);
  // As quatro do Discovery ancoram pelo **id da origem** e não pelo rótulo (ADR
  // 0087): é o que a API publica como identidade e o que estas listas já usam como
  // chave de React. O `Finding` não tem título — tem `statement`, que é uma frase.
  for (const process of overview.processes) anchors.add(`process:${process.id}`);
  for (const finding of overview.findings) anchors.add(`finding:${finding.id}`);
  for (const pain of overview.painPoints) anchors.add(`pain_point:${pain.id}`);
  for (const improvementOpportunity of overview.improvementOpportunities) {
    anchors.add(`improvement_opportunity:${improvementOpportunity.id}`);
  }
  return anchors;
}

/**
 * O que o `link` de um aviso pede: projeto, aba e linha (ADR 0057).
 *
 * Puro e sem `window` de propósito — o link é **relativo**, e a origem falsa
 * existe só para o `URL` aceitar analisá-lo. Isso é o que permite ao componente
 * abaixo decidir antes de qualquer efeito, e o que faz esta função ser a mesma
 * no servidor e no navegador.
 *
 * **Não re-deriva vocabulário nenhum.** Ele lê a URL que `deep_link` escreveu, e
 * é `test_item_anchor.py` quem cobra que os três nomes de parâmetro sejam os
 * mesmos dos dois lados. O `item` volta já decodificado pelo `URLSearchParams` e
 * é comparado **inteiro** — nunca partido no `:`, porque rótulo de cliente contém
 * dois-pontos e o separador não tem escape, por decisão da ADR 0056.
 */
function anchorTarget(link: string): { project: string | null; tab: string | null; item: string | null } {
  try {
    const url = new URL(link, "https://portal.invalid");
    return {
      project: url.searchParams.get("project"),
      tab: url.searchParams.get("tab"),
      item: url.searchParams.get("item"),
    };
  } catch {
    // Um `link` que o `URL` recusa não é caminho de navegação nenhum. A linha
    // continua sendo `<a href>` e quem decide o que fazer com ela é o navegador.
    return { project: null, tab: null, item: null };
  }
}

/**
 * A linha de um aviso, clicável (FDD 021 critério (4), ADR 0057).
 *
 * Um componente só para as duas superfícies — o popover do sino e a Central —
 * porque "o que o `Notification.link` faz quando clicado" precisa ter **uma**
 * resposta neste repositório. Até esta fatia tinha duas: a Central abria o link
 * numa aba nova, e o popover era um `<div>` que não fazia nada. Aquele `<div>` foi
 * nomeado como ponta aberta na ADR 0043 e de novo na ADR 0056, e sobreviveu às
 * duas porque nenhuma guarda olhava a **forma do controle** (ADR 0026).
 *
 * **O elemento é `<a href>` e a interceptação é o caso feliz, não o mecanismo.**
 * Um `onClick` que só chamasse `goTo(tab, item)` descartaria em silêncio o
 * `?project=` que o link carrega — e há três casos em que ele precisa mesmo cair
 * no href:
 *
 * 1. **modificador ou botão do meio**: abrir em aba nova é do navegador, e
 *    interceptar isso quebraria a única coisa que um `<a>` promete;
 * 2. **o aviso é de outro projeto**: a tela de agora mostra o projeto corrente, e
 *    trocar de aba aqui deixaria o cliente lendo a lista de A achando que é de B.
 *    O href faz carga completa e honra o `?project=`, que é o que troca de
 *    projeto de verdade. Quando esta recusa nasceu ela era também a **defesa**
 *    contra o item F1 da ADR 0057, fechado na ADR 0059 — `GET /me/notifications` não aceitava
 *    `?project=` e respondia pelo projeto mais recente da pessoa. F1 está
 *    fechado e a recusa continua, porque ela nunca foi só sobre isso: a lista
 *    que já está na tela é a do projeto corrente, e nenhum `goTo` a recarrega;
 * 3. **aba que a navegação não conhece**: `onboarding_stuck` traz `/admin/funnel`,
 *    que é outra rota e não uma aba deste componente.
 *
 * A degradação é monotônica, e é o mesmo critério que sustentou o drop do
 * `_MAX_LINK`: recusar a interceptação devolve exatamente o comportamento
 * anterior a esta fatia, nunca um clique morto.
 */
function NotificationLink({
  notification,
  className,
  currentProjectId,
  onNavigate,
  children,
}: {
  notification: NotificationView;
  className: string;
  currentProjectId: string | null;
  onNavigate: (tab: string, item?: string) => void;
  children: ReactNode;
}) {
  const link = notification.link;
  if (!link) return <div className={className}>{children}</div>;

  const target = anchorTarget(link);
  const navigable =
    target.tab !== null &&
    navItems.some((item) => item.label === target.tab) &&
    target.project !== null &&
    target.project === currentProjectId;

  return (
    <a
      className={className}
      href={link}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (!navigable) return;
        event.preventDefault();
        onNavigate(target.tab!, target.item ?? undefined);
      }}
    >
      {children}
    </a>
  );
}

// Mapeia o estado do marco para as classes de cor já existentes no CSS
const stateStyle: Record<string, string> = {
  "Concluído": "done",
  "Em andamento": "0",
  "Próxima entrega": "1",
  "Planejado": "2",
};

/**
 * O tom do selo traduzido para a variante da primitiva (F-026 DAP §3).
 *
 * Este mapa é também **o único lugar que sabe o que a primitiva ainda não
 * cobre**: `"2"` — o neutro — não tem entrada, porque `StatePill` tem quatro
 * variantes semânticas e nenhuma neutra. O pacote de design aprovado mantém o
 * cinza (o `p-grey-d` de `design/one-shell-tokens.html` é
 * `surface-sunken`/`muted`, exatamente o que `.state--2` passou a valer na T03)
 * e o desenha **com ícone** — o que exigiria uma quinta variante, e alterar a
 * primitiva está fora do escopo desta fatia. Enquanto não houver decisão, o
 * neutro cai no `.state` de sempre: mesma geometria, mesma cor, sem ícone.
 */
const PILL_VARIANT: Record<string, StatePillVariant> = {
  "0": "info",
  "1": "success",
  done: "success",
  "3": "danger",
};

/** O selo de estado: a primitiva quando há variante, o `.state` legado quando não há. */
function StateBadge({ tone, children }: { tone: string; children: ReactNode }) {
  const variant = PILL_VARIANT[tone];
  if (!variant) return <span className={`state state--${tone}`}>{children}</span>;
  return <StatePill variant={variant}>{children}</StatePill>;
}

// Tom do selo de pendência por estado (as classes vêm do CSS existente).
const pendingTone: Record<string, string> = {
  open: "amber",
  in_progress: "blue",
  resolved: "green",
};

/** Ícone por tipo de aviso — o `kind` vem da API (ADR 0012). */
const notificationIcon: Record<string, LucideIcon> = {
  milestone_done: Check,
  phase_advanced: MapPin,
  deliverable_delivered: Download,
  document_added: FileText,
  meeting_scheduled: UsersRound,
  transcript_ready: Video,
  pending_opened: Inbox,
  pending_resolved: Check,
  pending_commented: MessageSquare,
  project_status_changed: TrendingUp,
  // O único aviso que o cliente nunca recebe: a audiência é `_INTERNAL_ONLY`
  // (ADR 0040). Está aqui porque quem é interno também abre o portal por este
  // componente, e o `?? Bell` lá embaixo faria o esquecimento degradar em silêncio.
  onboarding_stuck: AlertTriangle,
};

/** Um resultado da busca, como `GET /api/v1/me/search` o devolve (ADR 0024).
 *
 *  `tab` vem pronto da API porque a tela navega por rótulo desde a Fase 2 — um
 *  segundo mapa aqui envelheceria sozinho. `document_id` vazio quer dizer "não
 *  há o que abrir", nunca "abra por sua conta". */
export type SearchHit = {
  kind: string;
  title: string;
  detail: string;
  location: string;
  tab: string;
  document_id: string;
  /** A linha da aba que este resultado aponta, no formato do `?item=` (ADR 0057).
   *
   *  Vem pronta da API pelo motivo do `tab` ao lado, e é o mesmo motivo há três
   *  fatias: um segundo mapa aqui envelheceria sozinho. Vazio quer dizer "não há
   *  o que ancorar" — a decisão, cuja aba não desenha `data-item` —, nunca
   *  "componha a âncora por sua conta". */
  item_anchor: string;
};

/** Rótulo por espécie de resultado. O mesmo vocabulário de `search.py`.
 *
 *  As quatro do Discovery ficam **em inglês**, e não é descuido: são os títulos que
 *  a própria aba desenha nos quatro blocos, e o Language Map §1 diz que o termo
 *  canônico não se traduz — traduz-se o texto em volta dele. Inventar "Processo" e
 *  "Achado" aqui criaria um segundo vocabulário para a mesma lista. */
const searchKindLabel: Record<string, string> = {
  document: "Documento",
  meeting: "Reunião",
  pending: "Pendência",
  decision: "Decisão",
  milestone: "Marco",
  chunk: "Trecho de documento",
  process: "Process",
  finding: "Finding",
  pain_point: "Pain Point",
  improvement_opportunity: "Improvement Opportunity",
};

/** Espelha `search.MIN_QUERY_LENGTH`: abaixo disso a API devolve lista vazia, e
 *  chamar para ouvir isso seria uma ida ao servidor por tecla. */
const SEARCH_MIN_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 250;

/**
 * O que a tela acrescenta ao nome do programa quando o estado dele muda a leitura
 * (ADR 0079). `active` não tem sufixo de propósito — ver `engagementLabel`.
 */
const ENGAGEMENT_STATE_SUFFIX: Record<string, string> = {
  paused: " · pausado",
  closed: " · encerrado",
};

/** Quem está logado, projetado de `GET /api/v1/me` — a membership é a autoridade. */
export type PortalUser = { name: string; initials: string; email: string; role: string; org: string; isInternal: boolean; notifyByEmail: boolean; notifyByWhatsapp: boolean; phoneHint: string };
export type NotificationView = { id: string; kind: string; title: string; detail: string | null; link: string | null; age: string; read: boolean };
/** A caixa do projeto atual, vinda de `GET /api/v1/me/notifications`. */
export type NotificationCenter = { unreadCount: number; items: NotificationView[] };
/** Um projeto que o usuário alcança. `current` é o que está sendo exibido. */
export type ProjectSummary = {
  id: string;
  name: string;
  status: string;
  current: boolean;
  /** O programa a que este projeto pertence, ou `null` (ADR 0079). É por ele que o seletor
   *  agrupa; sem ele o projeto cai no grupo sem cabeçalho, no fim — nunca some da lista. */
  engagementId: string | null;
  engagementName: string | null;
};

export type OverviewMilestone = { title: string; owner: string; state: string; date: string };
export type ProjectDocument = { title: string; type: string | null; author: string | null; link: string | null; updated: string };
export type MeetingView = { title: string; date: string; status: string; hasTranscript: boolean; recordingUrl: string | null };
/** `journeyPhaseName` é a fase da jornada que esta decisão destravou (ADR 0088), ou `null` quando a
 *  origem não a ancorou — e aí ela fica só na aba Decisões, sem nó na timeline. Não há
 *  rótulo de "sem fase": o desenho aprovado não desenha estado para a ausência. */
export type DecisionView = { title: string; rationale: string | null; decidedOn: string | null; ownerLabel: string | null; meetingTitle: string | null; journeyPhaseName: string | null };
export type PendingItemView = { id: string; title: string; description: string | null; owner: string | null; state: string; stateLabel: string; priority: string; priorityLabel: string; origin: string; openedByMessageId: string | null; openedByConversationId: string | null; commentCount: number; age: string };
export type ProjectResults = { milestonesTotal: number; milestonesDone: number; overdue: number; onTimePercent: number };
export type MeasuredAssumption = {
  hourlyRate: number;
  monthlyInvestment: number;
  effectiveFrom: string;
  note: string | null;
  currency: string;
  daysInPeriod: number;
};
/** A conta, como quem a fez a descreve — nunca reescrita aqui (ADR 0033). */
export type MeasuredBasis = { daysPerMonth: number; formula: string };
/** O que os agentes produziram no período, apurado pela API (ADR 0013). Não se
 *  confunde com `roi`, que é o ROI projetado vindo do snapshot do Biahflow. */
export type MeasuredResults = {
  periodDays: number;
  periodFrom: string;
  periodTo: string;
  eventsTotal: number;
  hoursSaved: number;
  benefit: number;
  laborSavings: number;
  avoidedCost: number;
  investment: number;
  net: number;
  roiRatio: number | null;
  accuracy: number | null;
  exceptionsHandled: number;
  unattendedShare: number | null;
  failed: number;
  eventsWithoutAssumption: number;
  assumption: MeasuredAssumption | null;
  basis: MeasuredBasis;
  gaps: string[];
};
/**
 * Uma decisão do cliente sobre um entregável, como o histórico a mostra (ADR 0077).
 *
 * `decidedAt` chega **formatado** de `app/page.tsx`, e não em ISO: este histórico é
 * renderizado no servidor, e formatar no cliente escreveria com o fuso do navegador
 * sobre um HTML que o servidor já escreveu com o dele.
 *
 * Não há campo de "em vigor", e a ausência é a mesma da API: a decisão em vigor é a
 * última da lista, e calculá-la do outro lado inventaria um estado que a tabela não
 * guarda. Também não há nada aqui que **edite** uma decisão — o `GRANT` de
 * `portal_app` é `SELECT, INSERT` e nada mais, e a tela não pode sequer sugerir o
 * contrário.
 */
export type DeliverableDecision = {
  id: string;
  action: "accepted" | "changes_requested";
  actorLabel: string;
  actorIsInternal: boolean;
  comment: string | null;
  decidedAt: string;
};
export type JourneyDeliverable = {
  name: string;
  state: "pending" | "delivered";
  link: string | null;
  /** A identidade do entregável no Biahflow — o caminho da rota de aceite (ADR 0077).
   *  Nula quando a origem não a mandou, e aí não há decisão a registrar. */
  externalRef: string | null;
  /** O histórico, do mais antigo para o mais novo. `null` é "não consegui carregar",
   *  que **não** é a mesma coisa que a lista vazia de "ninguém decidiu ainda". */
  decisions: DeliverableDecision[] | null;
};
export type DigitalEmployeeView = { name: string; area: string | null; description: string | null; status: string; kpiLabel: string | null; kpiValue: string | null; hoursSavedMonth: number | null; roiMonth: number | null; /** Os `KPI.id` da origem que ele move (ADR 0085); vazio é "não referencia nenhum". */ kpiIds: number[] };
/**
 * Uma leitura de KPI — Baseline, Outcome ou um ponto do acompanhamento (Language Map §4).
 *
 * `value` nulo **dentro de um objeto que existe** é "a janela existe e ninguém mediu
 * ainda", e é outra coisa que o objeto inteiro ausente ("não há Baseline definida").
 * Nenhuma das duas é zero, e é a tela que tem de escrever as duas frases diferentes.
 */
export type KpiMeasurementView = {
  value: number | null;
  periodStart: string;
  periodEnd: string | null;
  measuredAt: string | null;
  confidence: number | null;
};
/** Um indicador do projeto, com Baseline e Outcome comparáveis (ADR 0085). */
export type KpiView = {
  /** O id da **origem**, e não um uuid: é por ele que o Value Ledger e os
   *  Funcionários Digitais apontam para este KPI. */
  id: number;
  name: string;
  definition: string | null;
  formula: string | null;
  unit: string | null;
  /** `up` ou `down` — para que lado o indicador melhora. Sem ele a tela não
   *  afirma ganho nem perda, só mostra os dois números. */
  direction: string | null;
  dataSource: string | null;
  cadence: string | null;
  target: number | null;
  baseline: KpiMeasurementView | null;
  /** Nunca vem preenchido com `baseline` nulo — invariante 11 do Language Map. */
  outcome: KpiMeasurementView | null;
  monitoring: KpiMeasurementView[];
};
/**
 * Uma entrada do Value Ledger do mandato (Language Map §2, ADR 0085).
 *
 * É o **valor gerado**, e a §2 diz o que ele nunca é: "ROI projetado" nem "Case".
 */
export type ValueLedgerEntryView = {
  id: number;
  valueType: string;
  amount: number;
  quantity: number | null;
  periodStart: string;
  periodEnd: string;
  /** Como o número foi atribuído — invariante 12. Sem ele a entrada não sai da API. */
  attributionMethod: string;
  /** O KPI de origem. **Pode não casar com nenhum item de `kpis`**: a entrada é do
   *  mandato e o KPI pode viver num projeto irmão que este cliente não alcança. */
  kpiId: number | null;
  outcomeMeasuredAt: string | null;
};
/**
 * O Discovery da **conta** (Language Map v1.1 §2, ADR 0086).
 *
 * Cinco agregados que o Pulse publica por Account: o AS-IS validado
 * (`ProcessView`/`ProcessStepView`), os achados (`FindingView`), as dores
 * (`PainPointView`) e o backlog de melhoria (`ImprovementOpportunityView`) com o
 * Opportunity Score e as hipóteses de solução aninhadas.
 *
 * **Os ids são os da origem**, como em `KpiView`: é por eles que `processId`,
 * `findingIds` e `painPointIds` ligam as quatro listas, sem tabela de tradução aqui.
 */
export type ProcessStepView = {
  id: number;
  position: number;
  name: string;
  /** As seis chaves do formulário P-S-D-T-E-R, nos nomes que o contrato do produtor
   *  fixou em português — elas não são termos da ontologia, são as perguntas da
   *  sessão de Discovery (ADR 0086). */
  pessoas: string | null;
  sistema: string | null;
  dados: string | null;
  tempo: string | null;
  erro: string | null;
  retrabalho: string | null;
};
export type ProcessView = {
  id: number;
  name: string;
  position: number;
  /** Quando a **origem** atualizou o processo, ou `null` quando ela não carimba. */
  updatedAt: string | null;
  steps: ProcessStepView[];
};
export type EvidenceView = {
  id: number;
  kind: string;
  /** O ponteiro para a fonte, como a origem o escreve — nunca o conteúdo dela. */
  reference: string | null;
  capturedAt: string | null;
};
export type FindingView = {
  id: number;
  statement: string;
  /** `fact` · `hypothesis` · `unknown`. É o campo que impede a tela de desenhar
   *  hipótese com cara de fato (§3, regra 1), e por isso ele nunca é opcional. */
  epistemicStatus: string;
  confidence: number | null;
  /** `null` é caso normal: o achado pode apontar para um processo que ninguém
   *  publicou ainda, e a tela o mostra sem a origem em vez de escondê-lo. */
  processId: number | null;
  stepId: number | null;
  evidences: EvidenceView[];
};
export type PainPointView = {
  id: number;
  title: string;
  description: string | null;
  impactType: string | null;
  /** `null` é **não quantificado**, nunca zero: a tela escreve a frase da lacuna. */
  impactEstimate: number | null;
  findingIds: number[];
  status: string;
};
export type PriorityAssessmentView = {
  version: number | null;
  /** O Opportunity Score (Language Map D5) — o rótulo vale só para melhoria
   *  operacional, nunca para uma venda. */
  score: number;
  dimensions: Record<string, number>;
};
export type SolutionHypothesisView = {
  id: number;
  statement: string;
  intervention: string | null;
  /** O efeito **esperado**, não o medido: quem mede é o KPI (ADR 0085). */
  expectedEffect: string | null;
  status: string;
};
export type ImprovementOpportunityView = {
  id: number;
  title: string;
  desiredChange: string | null;
  impactHypothesis: string | null;
  painPointIds: number[];
  status: string;
  /** `null` é "ninguém avaliou ainda", e não a pior nota. A lista já chega ordenada
   *  por score decrescente com estes no fim — quem ordena é a API. */
  priorityAssessment: PriorityAssessmentView | null;
  solutionHypotheses: SolutionHypothesisView[];
};
export type JourneyPhase = {
  name: string;
  description: string;
  state: "locked" | "active" | "done";
  targetDate: string;
  /** O degrau da FDE a que a fase corresponde (Language Map §4, ADR 0081).
   *  `null` é resposta legítima da origem — a fase não tem equivalente na
   *  metodologia —, e **não** um degrau que se possa adivinhar pelo nome. */
  canonicalStage: "discover" | "prioritize" | "feasibility" | "prove" | "scale" | "optimize" | null;
  /** A decisão que fechou o gate (decisão D7 do Language Map). `null` é "ninguém
   *  decidiu ainda", e só vira frase na tela quando `requiresGate` diz que há
   *  decisão a esperar. */
  gateDecision: "go" | "conditional_go" | "redesign" | "no_go" | null;
  /** Se a fase termina em gate. Vem do template da fase na origem, e é o que
   *  separa "aguardando decisão" de "não há decisão a esperar". */
  requiresGate: boolean;
  deliverables: JourneyDeliverable[];
};
/**
 * Por que a tela está em modo de consulta, ou `null` quando não está (ADR 0036/0037).
 *
 * Uma função com as três frases juntas, e não dois booleanos espalhados: os dois motivos fecham as
 * mesmas escritas e mudam o que o cliente lê, então mantê-los num lugar só é o que impede a tela de
 * dizer "encerrado" num canto e "removido" noutro. A exclusão vem primeiro porque é o estado mais
 * forte — um projeto pode ter sido encerrado antes de ser apagado —, e é a mesma ordem de
 * `_refuse_when_read_only` na API, de propósito.
 */
type ReadOnlyReason = {
  pill: string;
  chat: string;
  comments: string;
  /** A mesma recusa na aba de Revisão: a API responde 409 ali também (ADR 0036/0037). */
  decisions: string;
} | null;

function readOnlyReason(overview: Overview): ReadOnlyReason {
  if (overview.sourceDeletedAt !== null) {
    return {
      pill: "Projeto removido na origem",
      chat:
        "Este projeto foi removido no Biahflow. O histórico continua disponível para consulta, " +
        "mas não é possível fazer novas perguntas.",
      comments:
        "O projeto foi removido no Biahflow: os comentários ficam para consulta e não é " +
        "possível escrever novos.",
      decisions:
        "O projeto foi removido no Biahflow: o histórico de decisões fica para consulta e " +
        "não é possível registrar novas.",
    };
  }
  if (overview.archivedAt !== null) {
    return {
      pill: "Projeto encerrado",
      chat:
        "Este projeto foi encerrado. O histórico continua disponível para consulta, mas não é " +
        "possível fazer novas perguntas.",
      comments:
        "O projeto foi encerrado: os comentários ficam para consulta e não é possível escrever " +
        "novos.",
      decisions:
        "O projeto foi encerrado: o histórico de decisões fica para consulta e não é possível " +
        "registrar novas.",
    };
  }
  return null;
}

/**
 * O frescor da projeção, já reduzido ao que a tela desenha (ADR 0076).
 *
 * `kind` **é** o rótulo, e não um adjetivo sobre ele. A API entrega `observed_at` e
 * `synced_at` mutuamente exclusivos: o primeiro é o instante em que a **origem observou**
 * aquele estado, o segundo é o instante em que o **portal copiou**. Chamar o segundo de
 * "atualizado" é a falsa precisão que `results.py` recusa por princípio e que a ADR 0026
 * removeu desta tela — é o defeito que esta fatia inteira existe para negar, e por isso a
 * distinção mora no tipo, onde não dá para esquecê-la.
 *
 * `null` é a terceira resposta e não é o mesmo que velho: sem hora de verdade não há
 * carimbo, e a tela não inventa um.
 */
export type FreshnessView = { kind: "observed" | "synced"; age: string; stale: boolean };

/**
 * O que o carimbo diz, por origem do dado — na forma de `readOnlyReason` e pela mesma
 * razão: as duas frases juntas num lugar só é o que impede a tela de prometer observação
 * da origem num canto e hora da cópia noutro.
 */
const FRESHNESS_LABEL: Record<FreshnessView["kind"], (age: string) => string> = {
  observed: (age) => `Atualizado ${age} · sincronizado com o Biahflow`,
  // A segunda metade não é enfeite: sem ela, "Sincronizado há 3 horas" continua sendo lido
  // como idade do dado, quando é a idade da cópia. É o *Fallback declarado* da ADR 0076
  // dito na tela — uma resposta pior à mesma pergunta, dita honestamente.
  synced: (age) => `Sincronizado ${age} · hora da cópia, não da origem`,
};

/** E acima do limiar, o motivo — o padrão pill + mensagem de `readOnlyReason` reusado. */
const STALE_MESSAGE: Record<FreshnessView["kind"], (age: string) => string> = {
  observed: (age) =>
    `Última observação no Biahflow ${age}. O que você vê pode não refletir o estado atual do projeto.`,
  synced: (age) =>
    `Última sincronização ${age}. O que você vê pode não refletir o estado atual do projeto.`,
};

/**
 * O programa a que o projeto na tela pertence (Language Map v1.1, ADR 0079).
 *
 * **"Engagement" não se traduz.** A regra de idioma do Language Map §1 vale para as
 * quatro superfícies: traduz-se o texto em volta do termo, nunca o termo. Por isso o
 * rótulo é `PROGRAMA (ENGAGEMENT)` na tela e o tipo se chama assim aqui.
 */
export type EngagementView = { id: string; name: string; status: string };

export type Overview = {
  project: string;
  organization: string;
  status: string;
  completion: number;
  source: "live" | "demo";
  /** O programa deste projeto, ou `null` enquanto o Biahflow não mandar a chave (ADR 0079).
   *  Vem do dashboard e não da lista de `/me` de propósito: quando o projeto da tela não
   *  está na lista (ADR 0062), esta é a única fonte que sabe de qual programa ele é. */
  engagement: EngagementView | null;
  /** Quando o Biahflow encerrou o projeto, ou `null` se segue ativo (ADR 0036). Preenchido, a
   *  tela entra em modo de consulta: o histórico continua inteiro e as escritas fecham. */
  archivedAt: string | null;
  /** Quando o Biahflow apagou o projeto de vez, ou `null` (ADR 0037). Mesmo modo de consulta,
   *  motivo diferente — e este não tem volta, porque a fonte não tem mais o que declarar. */
  sourceDeletedAt: string | null;
  /** O carimbo de frescor da projeção, ou `null` quando não há hora de verdade para
   *  carimbar (ADR 0076). A idade já vem derivada: quem a calcula é quem renderiza. */
  freshness: FreshnessView | null;
  nextDelivery: { title: string; detail: string } | null;
  milestones: OverviewMilestone[];
  journey: { currentPhase: string | null; phases: JourneyPhase[] };
  roi: { net: number | null; ratio: number | null } | null;
  nextMeeting: { title: string; detail: string } | null;
  health: { label: string; level: string } | null;
  digitalEmployees: DigitalEmployeeView[];
  /** Os KPIs deste projeto (ADR 0085). Lista vazia é "nenhum definido ainda" — a
   *  API nunca manda `null`, para a tela não ter um terceiro caso a desenhar. */
  kpis: KpiView[];
  /** O Value Ledger do **mandato**, não do projeto: a mesma entrada aparece no
   *  dashboard de todos os projetos do Engagement, porque é o programa que gera o
   *  valor. Vazia quando o projeto ainda não tem programa. */
  valueLedger: ValueLedgerEntryView[];
  /** O Discovery da **conta** (ADR 0086). As quatro listas vêm sempre, e vazias é o
   *  estado normal enquanto o Pulse não tiver tela de publicar — nada atravessa sem
   *  publicação humana. A aba escreve "nada publicado ainda", nunca um erro. */
  processes: ProcessView[];
  findings: FindingView[];
  painPoints: PainPointView[];
  improvementOpportunities: ImprovementOpportunityView[];
  documents: ProjectDocument[];
  meetings: MeetingView[];
  decisions: DecisionView[];
  pendings: PendingItemView[];
  results: ProjectResults | null;
  measured: MeasuredResults | null;
};

function firstName(fullName: string): string {
  return fullName.trim().split(/\s+/)[0] ?? fullName;
}

function greeting(user: PortalUser): ChatMessage[] {
  return [
    {
      role: "assistant",
      text: `Olá, ${firstName(user.name)}. Posso encontrar decisões, entregas e resultados deste projeto para você.`,
    },
  ];
}

// Uma pergunta que a API não respondeu não vira resposta: vira o motivo (ADR 0021).
//
// Até a Fase 5 existia aqui um `answerFor()` que, no `catch` do `sendQuestion`,
// devolvia data inventada, decisão inventada, contagem de pendência inventada e
// **rótulos de citação inventados** — nomes de documento e de reunião que nunca
// existiram — a um cliente autenticado de verdade cuja chamada falhou. E marcava
// `pending: true`, de modo que a tela anunciava uma pendência criada para o
// time — uma pendência que ninguém gravou. O `CLAUDE.md` afirmava que não havia
// mais fallback para dado inventado; era falso justamente aqui, na única tela
// onde a regra 3 do `AGENTS.md` vale por escrito.
const CHAT_UNAVAILABLE: ChatMessage = {
  role: "assistant",
  text:
    "Não consegui falar com o assistente agora, então não tenho resposta para dar. " +
    "Nada foi registrado — tente de novo em instantes.",
};

// A API dá dois 429 diferentes na mesma rota: o ritmo de uma pessoa, em janela de
// um minuto (ADR 0021), e o teto mensal de gasto de IA da organização (ADR 0022).
// A tela os separa pelo `Retry-After` e não pelo texto do erro — o cabeçalho é
// numérico e estável, e o corpo de um 429 é deliberadamente opaco no resto da
// API. Acima de uma hora só pode ser o teto: a janela nunca passa de sessenta
// segundos.
const RATE_WINDOW_CEILING_SECONDS = 3600;

function chatRateLimited(retryAfter: number | null): ChatMessage {
  if (retryAfter !== null && retryAfter > RATE_WINDOW_CEILING_SECONDS) {
    const dias = Math.max(1, Math.ceil(retryAfter / 86_400));
    return {
      role: "assistant",
      text:
        "O limite de uso do assistente para a sua organização foi atingido neste mês, " +
        `então não tenho resposta para dar. A cota é renovada em ${dias} dia(s), e a ` +
        "equipe da Biahflow pode ampliá-la antes disso. Nada foi registrado.",
    };
  }
  const espera = retryAfter && retryAfter > 0 ? ` Tente de novo em ${retryAfter}s.` : "";
  return {
    role: "assistant",
    text: `Você fez muitas perguntas em pouco tempo.${espera}`,
  };
}

export default function DashboardClient({
  overview,
  user,
  projects,
  notifications = { unreadCount: 0, items: [] },
  initialTab,
  initialItem,
}: {
  overview: Overview;
  user: PortalUser;
  projects: ProjectSummary[];
  notifications?: NotificationCenter;
  /**
   * A aba que o `?tab=` da URL pediu (FDD 021, ADR 0043). É o que faz o link de um
   * aviso cair no assunto em vez da home — até aqui a navegação era só estado, e
   * nenhuma URL alcançava uma aba, de modo que `Notification.link` não teria para
   * onde apontar mesmo depois de ganhar escritor.
   *
   * Validada contra `navItems`, e não confiada: o valor vem da barra de endereço.
   * Um rótulo desconhecido cai na visão geral, que é o mesmo desfecho de não
   * mandar nada — nunca uma tela em branco.
   */
  initialTab?: string;
  /**
   * A **linha** que o `?item=` da URL pediu, no formato `<namespace>:<rótulo>`
   * (ADR 0056). O `initialTab` acima abre a tela; este destaca o assunto dentro
   * dela, que é o que o critério de aceite (4) da FDD 021 pede ao exigir "a coisa
   * exata, nunca na home".
   *
   * Também não é confiada, e por um motivo mais forte: o rótulo é texto livre do
   * cliente e chega pela barra de endereço. Nada aqui a interpola em seletor nem
   * em HTML — ela só é **comparada** com o que a tela desenhou, e uma âncora que
   * não casa com nada vira a nota discreta abaixo em vez de sumir em silêncio.
   */
  initialItem?: string;
}) {
  const router = useRouter();
  // Projeto sem escrita no Biahflow: a tela vira consulta (ADR 0036/0037). Derivado do overview e
  // não guardado em estado, porque quem decide isto é a fonte da verdade a cada carregamento.
  const projectReadOnly = readOnlyReason(overview);
  const [activeNav, setActiveNav] = useState(
    navItems.some((item) => item.label === initialTab) ? initialTab! : "Visão geral",
  );
  const [focusedItem, setFocusedItem] = useState<string | null>(initialItem ?? null);
  const [chatOpen, setChatOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(() => greeting(user));
  // A thread corrente. `null` faz o próximo turno abrir uma nova — é o que o
  // botão "Nova conversa" faz, sem precisar de rota própria (ADR 0015).
  const [conversationId, setConversationId] = useState<string | null>(null);
  // O link do documento falhou. Fica fora da mensagem de propósito: o turno
  // gravado é o que a resposta mostrou (ADR 0015), e um erro de rede de agora não
  // pertence ao registro daquele momento.
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const historyLoaded = useRef(false);
  // Pendências que a IA abriu nesta sessão: já existem no banco, mas a página é renderizada
  // no servidor, então são espelhadas aqui até o próximo carregamento.
  const [aiPendings, setAiPendings] = useState<PendingItemView[]>([]);
  /**
   * O turno que a pendência aberta pela IA aponta (ADR 0031). Abre o chat e
   * rola até ele — o histórico já vem da API, então não há nada a buscar.
   */
  const [focusedTurn, setFocusedTurn] = useState<string | null>(null);
  const openTurn = (messageId: string, conversationId: string | null) => {
    setChatOpen(true);
    setFocusedTurn(messageId);
    // Carrega **aquela** thread, não a corrente: o turno que abriu a pendência
    // quase nunca está na conversa mais recente, e sem isto o painel abriria sem
    // ter o que destacar (ADR 0031).
    if (conversationId) setThreadToLoad(conversationId);
  };
  /** Thread pedida por um clique; `null` significa "a corrente". */
  const [threadToLoad, setThreadToLoad] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [menu, setMenu] = useState<null | "search" | "notifications" | "profile" | "profile-side">(null);
  // Otimista só até o servidor responder: `markNotificationsReadAction` revalida
  // a rota, e o próximo render traz a contagem da API. O booleano local de antes
  // fingia leitura — um F5 e o ponto vermelho voltava.
  const [readPending, startReading] = useTransition();
  const [optimisticRead, setOptimisticRead] = useState(false);
  const unreadCount = optimisticRead ? 0 : notifications.unreadCount;

  // Não há mais estado de projeto: quem manda é a URL, porque trocar de projeto
  // significa buscar outro dashboard na API (`/?project=<id>`).
  // **Sem queda no primeiro da lista** (ADR 0061). O `?? projects[0]` que estava aqui era
  // a mesma heurística do casamento por nome com outro nome: se o id que a API serviu não
  // casa com nenhum item de `me.projects`, isso é divergência real entre duas rotas, e
  // escolher o primeiro escoparia o sino, a busca e os comentários por um projeto que
  // ninguém afirmou. Sem casamento, `activeProject` fica `null`, `projectParam` fica vazio,
  // o parâmetro é **omitido** e as nove rotas voltam a `access.default_project` — que é
  // justamente o projeto que o dashboard serviu. A degradação aponta para o lugar certo.
  const activeProject = projects.find((project) => project.current) ?? null;
  /**
   * O programa que está sendo acompanhado (ADR 0079).
   *
   * O dashboard vem primeiro e a lista depois, pela razão que fez `activeProject` poder
   * ser `null`: quando o projeto da tela não está em `me.projects`, a lista não sabe de
   * qual programa ele é e o dashboard sabe — ele projetou justamente aquele projeto.
   */
  const activeEngagementId = overview.engagement?.id ?? activeProject?.engagementId ?? null;
  /**
   * O rótulo do programa no topo, com o estado dele quando ele não está corrente.
   *
   * `active` não vira texto: dizer "ativo" em toda tela seria ruído, e o que muda a
   * leitura é o programa estar **pausado** ou **encerrado** — na mesma regra com que a
   * ADR 0036 marca "Projeto encerrado" e não marca "Projeto ativo".
   */
  const engagementName = overview.engagement?.name ?? activeProject?.engagementName ?? null;
  const engagementLabel = engagementName
    ? `${engagementName}${ENGAGEMENT_STATE_SUFFIX[overview.engagement?.status ?? ""] ?? ""}`
    : null;
  /**
   * O projeto da tela, no formato de query (ADR 0059).
   *
   * As rotas de `/me/` resolviam `access.default_project` do outro lado — a
   * membership **mais recente** —, enquanto o dashboard já vinha do projeto que a
   * URL nomeia. Um cliente com dois projetos, vendo B, tinha o sino, a busca e o
   * histórico de A, e a pendência de B respondia 404 por ser procurada sob o
   * tenant de A.
   *
   * **Omitido quando não há projeto**, nunca mandado vazio: `?project=` sem valor
   * é 422 do outro lado, e ausente é o padrão de sempre.
   */
  const projectParam = activeProject ? `?project=${encodeURIComponent(activeProject.id)}` : "";

  const toggleMenu = (target: typeof menu) => setMenu((current) => (current === target ? null : target));
  // Trocar de aba por vontade própria encerra o destaque, como "Nova conversa"
  // encerra o turno em foco: o cliente saiu do assunto que o aviso abriu, e um
  // realce que sobrevive à navegação passa a apontar para uma pergunta antiga.
  //
  // **E é o único escritor de `activeNav` fora do estado inicial** (ADR 0057). Até
  // aqui a barra lateral chamava `setActiveNav` direto: o comentário acima já
  // prometia isto e o caminho mais óbvio de cumpri-lo não passava por aqui, de
  // modo que a âncora sobrevivia à navegação — a nota "O item deste aviso não está
  // mais nesta lista." seguia o cliente por todas as abas, e o efeito de rolagem,
  // que tem `activeNav` nas dependências, re-destacava uma linha já dispensada.
  //
  // `item` chega de quem **abriu** o assunto (o aviso, a busca) e é ausente em
  // todos os outros chamadores, que é o que faz navegar limpar.
  const goTo = (label: string, item?: string) => { setActiveNav(label); setFocusedItem(item ?? null); setMenu(null); setMobileNavOpen(false); };
  const selectProject = (project: ProjectSummary) => router.push(`/?project=${project.id}`);

  const suggestedQuestions = useMemo(
    () => [
      "Quando entraremos em produção?",
      "Quais decisões tomamos sobre o financeiro?",
      "Mostre todas as pendências.",
    ],
    [],
  );

  function pushAnswer(answer: ChatMessage) {
    setMessages((current) => [...current, answer]);
  }

  // Hidrata o painel com a conversa que a API guardou (ADR 0015). Roda ao abrir o
  // chat, e não no carregamento da página, porque a maioria das visitas não abre
  // o assistente — e o histórico só existe para quem já perguntou algo.
  useEffect(() => {
    // `threadToLoad` sobrepõe a guarda de "já carregou": um clique numa segunda
    // pendência precisa trocar de thread, e a guarda existia só para a abertura
    // do painel não repetir a busca (ADR 0031).
    if (!chatOpen || (historyLoaded.current && !threadToLoad)) return;
    // Ref e não estado: a guarda existe para a busca não repetir, e marcá-la não
    // é informação que a tela precise renderizar.
    historyLoaded.current = true;
    let current = true;
    (async () => {
      try {
        const response = await fetch(
          (threadToLoad ? `/api/chat/history?conversation=${threadToLoad}` : "/api/chat/history") +
            (activeProject ? `${threadToLoad ? "&" : "?"}project=${activeProject.id}` : ""),
          { cache: "no-store" },
        );
        if (!response.ok) return;
        const data = await response.json();
        if (!current || !data.conversation_id || !data.messages?.length) return;
        setConversationId(data.conversation_id);
        const restored = data.messages.map((message: {
            id: string;
            role: "user" | "assistant";
            text: string;
            sources?: string[];
            citations?: Citation[];
            pending_created?: boolean;
            confidence?: string | null;
            feedback?: "helpful" | "not_helpful" | null;
          }) => ({
            id: message.id,
            role: message.role,
            text: message.text,
            sources: message.sources,
            citations: message.citations,
            pending: message.pending_created,
            confidence: message.confidence,
            feedback: message.feedback ?? null,
          }));
        // Só substitui a tela se a pessoa ainda não escreveu nada. O histórico
        // chega **depois** da saudação, e uma pergunta enviada nesse intervalo
        // seria apagada da tela por esta linha — gravada no banco, invisível até
        // o próximo F5. Quem já tem um turno seu na tela não precisa que o
        // histórico o recomponha.
        //
        // `threadToLoad` sobrepõe essa proteção, e é a diferença entre chegada
        // e pedido: o histórico da abertura *chega* e não deve atropelar o que a
        // pessoa digitou; a thread que ela clicou foi *pedida*, e não trocar
        // seria ignorar o clique (ADR 0031).
        setMessages((shown) =>
          !threadToLoad && shown.some((message) => message.role === "user")
            ? shown
            : restored,
        );
      } catch {
        // Sem histórico, o painel abre com a saudação — que é o estado inicial.
      }
    })();
    return () => {
      current = false;
    };
  }, [chatOpen, threadToLoad, activeProject]);

  /** Começa do zero: sem id, a API abre outra thread no próximo turno. */
  function startNewConversation() {
    setConversationId(null);
    setMessages(greeting(user));
  }

  async function rateAnswer(messageId: string, helpful: boolean, comment?: string) {
    // Otimista, e sem desfazer em caso de erro: o polegar é opinião, não estado
    // do projeto — insistir num rollback visível custaria mais do que vale.
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId
          ? { ...message, feedback: helpful ? "helpful" : "not_helpful" }
          : message,
      ),
    );
    try {
      await fetch("/api/chat/feedback" + projectParam, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // O comentário é opcional e é **o campo mais informativo do conjunto**
        // (ADR 0030): o polegar diz que errou, o comentário diz o quê. Ele
        // existia na coluna, na API e na rota do BFF desde a ADR 0015 — e não
        // tinha escritor, então a tela do time interno mostrava um painel
        // intitulado "O que os clientes disseram" sobre um campo sempre nulo.
        body: JSON.stringify({
          message_id: messageId,
          helpful,
          comment: comment?.trim() ? comment.trim() : null,
        }),
      });
    } catch {
      // Silencioso de propósito, pelo mesmo motivo.
    }
  }

  // A visão do projeto = o que veio do servidor + as pendências abertas pela IA nesta sessão.
  const view = useMemo<Overview>(
    () => (aiPendings.length === 0 ? overview : { ...overview, pendings: [...aiPendings, ...overview.pendings] }),
    [overview, aiPendings],
  );
  const openCount = openPendings(view).length;
  // Quantas entregas aguardam a decisão do cliente (FDD 027). Derivado no render e
  // vindo do SSR, como o `openCount` ao lado: um contador que só aparecesse depois
  // da hidratação piscaria, e nenhuma asserção de HTML renderizado o alcançaria.
  const reviewCount = awaitingReview(view);
  // Toda linha que esta tela consegue destacar. Memoizado porque passou a ter dois
  // leitores (a nota do aviso e o clique da busca) e a lista percorre cinco coleções
  // do `overview` — antes era uma chamada por render, dentro do próprio `if`.
  //
  // **Declarado acima de quem o lê**, e não junto da nota como estava: o
  // `openSearchHit` abaixo é uma declaração de função, que sobe, mas o `const` não
  // — e o compilador do React recusa preservar uma memoização usada antes de ser
  // criada. O lint reprova, o que é a resposta certa: o que ele descreve é uma
  // ordem que só funciona porque ninguém chama a função durante o render.
  const anchors = useMemo(() => screenAnchors(view), [view]);

  // Abre o documento por trás da citação (ADR 0017). A URL é assinada e curta, e
  // por isso é pedida no clique e não junto da resposta: uma URL emitida com a
  // mensagem já teria vencido quando alguém rolasse a conversa até ela.
  //
  // `window.open` antes do `await` seria o jeito de escapar do bloqueador de
  // pop-up, mas abriria uma aba em branco quando a API negasse. Navegamos na
  // própria aba, e o que torna isso barato é a Fase 4: a conversa está gravada
  // (ADR 0015), então voltar traz o turno e a citação de volta como estavam.
  //
  // Devolve se conseguiu: quem chama da citação mostra o erro no painel do chat
  // (`downloadError`), e quem chama da busca precisa mostrá-lo em outro lugar —
  // o popover fecharia antes de a falha existir, e o cliente ficaria com um
  // clique que não fez nada.
  async function openDocument(documentId: string): Promise<boolean> {
    setDownloadError(null);
    try {
      const response = await fetch(`/api/documents/${documentId}/download` + projectParam);
      if (!response.ok) throw new Error("download failed");
      const data = await response.json();
      window.location.assign(data.url);
      return true;
    } catch {
      setDownloadError("Não foi possível abrir o documento agora.");
      return false;
    }
  }

  /** O clique num resultado: abrir a fonte, quando há uma, ou ir até a aba. */
  async function openSearchHit(hit: SearchHit): Promise<boolean> {
    if (hit.kind === "chunk" && hit.document_id) {
      // O popover só fecha se a fonte abriu: o `ProjectSearch` é quem diz que
      // não deu, porque ele ainda está na tela.
      const opened = await openDocument(hit.document_id);
      if (opened) setMenu(null);
      return opened;
    }
    // A âncora só entra se a tela **desenha** aquela linha (ADR 0057). A mesma
    // função que responde "o rótulo ainda está no projeto?" para a nota do aviso,
    // reusada aqui — e é o que mantém a copy daquela nota literalmente correta:
    // ela fala de "aviso", e só continua alcançável por âncora vinda de um aviso.
    // Uma âncora sem linha na tela viria da busca e produziria a frase errada.
    goTo(hit.tab, anchors.has(hit.item_anchor) ? hit.item_anchor : undefined);
    return true;
  }

  async function sendQuestion(event?: FormEvent, preset?: string) {
    event?.preventDefault();
    const value = (preset ?? question).trim();
    if (!value) return;

    setQuestion("");
    setMessages((current) => [...current, { role: "user", text: value }]);
    try {
      // BFF proxy injects the client identity server-side and calls the grounded chat API.
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: value,
          conversation_id: conversationId,
          // O campo existia no contrato desde a Fase 3 e esta tela **nunca o
          // mandou** (ADR 0059): entrada publicada sem remetente.
          project_id: activeProject?.id,
        }),
      });
      if (response.status === 429) {
        // Ritmo, não permissão: o único não-ok que a tela sabe explicar (ADR 0021).
        const retryAfter = Number(response.headers.get("Retry-After"));
        pushAnswer(chatRateLimited(Number.isFinite(retryAfter) ? retryAfter : null));
        return;
      }
      if (!response.ok) throw new Error("chat unavailable");
      const data = await response.json();
      setConversationId(data.conversation_id ?? null);
      pushAnswer({
        id: data.message_id,
        role: "assistant",
        text: data.answer,
        sources: data.sources,
        citations: data.citations,
        pending: data.pending_created,
        confidence: data.confidence,
        feedback: null,
      });
      // Espelha a pendência que a API acabou de criar (mesmo título de `ai/service.py`).
      if (data.pending_created) {
        setAiPendings((current) => [
          {
            // Espelho local: a API acabou de gravar a linha e o id real chega no
            // recarregamento. Um id sintético seria endereço para uma rota que
            // responderia 404 — daí a string vazia, que a tela trata como
            // "ainda sem fio".
            id: "",
            title: `Responder dúvida do cliente: ${value.slice(0, 160)}`,
            description: "Pergunta sem evidência suficiente no contexto do projeto (chat).",
            owner: "Biahflow",
            state: "open",
            stateLabel: "Aberta",
            // `medium` é o default da coluna, e é o que `ai/service.py` grava:
            // este espelho tem de dizer o que o banco diz, senão a linha muda
            // de lugar na lista no primeiro recarregamento.
            priority: "medium",
            priorityLabel: "Média",
            origin: "portal",
            // O turno acabou de ser gravado; o id vem no recarregamento (ADR 0031).
            openedByMessageId: null,
            openedByConversationId: null,
            commentCount: 0,
            age: "agora",
          },
          ...current,
        ]);
      }
    } catch {
      // Sem API não há resposta — e dizer isso é a resposta. Inventar uma aqui era
      // o último caminho do portal que devolvia dado fabricado ao cliente.
      pushAnswer(CHAT_UNAVAILABLE);
    }
  }

  const askAi = () => setChatOpen(true);

  /** Abrir a caixa é ler: marca no servidor e some com o ponto vermelho. */
  function markRead() {
    if (unreadCount === 0 || readPending) return;
    setOptimisticRead(true);
    startReading(async () => {
      const ok = await markNotificationsReadAction(activeProject?.id ?? null);
      if (!ok) setOptimisticRead(false); // a API recusou: o ponto volta
    });
  }

  // Derivado no render, e não num efeito: a nota tem de estar no HTML do servidor
  // (ver o efeito de rolagem abaixo).
  const anchorMissing = focusedItem !== null && !anchors.has(focusedItem);

  useEffect(() => {
    if (!focusedTurn || !chatOpen) return;
    // `requestAnimationFrame` porque o painel do chat acabou de montar: sem
    // esperar o layout, `scrollIntoView` roda sobre altura zero e não sai do
    // lugar.
    const frame = requestAnimationFrame(() => {
      document
        .querySelector(`[data-message-id="${focusedTurn}"]`)
        ?.scrollIntoView({ block: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [focusedTurn, chatOpen]);

  /**
   * Rola até a linha que o aviso apontou (ADR 0056). Irmão do efeito acima, com
   * uma diferença deliberada e uma consequência.
   *
   * **A diferença é o seletor, e é o ponto de segurança da fatia.** O efeito do
   * turno interpola o valor dentro de `querySelector` e *pode*, porque ali o valor
   * é um uuid que veio da API. Aqui ele vem da **barra de endereço** e é o título
   * que o cliente digitou no Biahflow: uma aspa no meio dele fecha o seletor cedo
   * e, na melhor das hipóteses, seleciona outra coisa. A varredura compara o
   * atributo em JavaScript, onde aspa é um caractere e não sintaxe.
   *
   * **A consequência é o destaque não morar aqui.** Ele é JSX (`is-anchored`
   * abaixo), como o `message--focused` já é, e não um `classList.add` deste
   * efeito: assim ele existe no HTML do SSR — sem isso haveria um piscar entre a
   * primeira pintura e a hidratação, e a guarda node não teria o que ver.
   */
  useEffect(() => {
    if (!focusedItem) return;
    // `requestAnimationFrame` pelo motivo do efeito acima: a aba pedida pelo
    // `?tab=` acabou de montar, e sem esperar o layout o `scrollIntoView` roda
    // sobre altura zero.
    const frame = requestAnimationFrame(() => {
      Array.from(document.querySelectorAll("[data-item]"))
        .find((node) => node.getAttribute("data-item") === focusedItem)
        ?.scrollIntoView({ block: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [focusedItem, activeNav]);

  function renderActiveView() {
    switch (activeNav) {
      case "Cronograma":
        return <ScheduleView onAsk={askAi} overview={view} focusedItem={focusedItem} />;
      case "Documentos":
        return <DocumentsView onAsk={askAi} overview={view} focusedItem={focusedItem} />;
      case "Reuniões":
        return <MeetingsView onAsk={askAi} overview={view} focusedItem={focusedItem} />;
      // Numa linha, sem parênteses e sem nada entre o `case` e o `return`, como os
      // vizinhos: `test_item_anchor.py` lê este `switch` por regex para saber qual aba
      // desenha qual âncora, e um `return (` — ou um comentário no meio — faz a aba
      // contar como a do `default:`.
      case "Revisão":
        return <ReviewView onAsk={askAi} overview={view} focusedItem={focusedItem} projectId={activeProject?.id ?? null} />;
      case "Pendências":
        return <PendingView onAsk={askAi} overview={view} onOpenTurn={openTurn} focusedItem={focusedItem} projectId={activeProject?.id ?? null} />;
      case "Decisões":
        return <DecisionsView onAsk={askAi} overview={view} />;
      case "Resultados":
        return <ResultsView onAsk={askAi} overview={view} />;
      case "Discovery":
        return <DiscoveryView onAsk={askAi} overview={view} focusedItem={focusedItem} />;
      case "Notificações":
        return (
          <NotificationsView
            currentProjectId={activeProject?.id ?? null}
            notifications={notifications}
            onAsk={askAi}
            onNavigate={goTo}
          />
        );
      case "Meu perfil":
        return <ProfileView onAsk={askAi} user={user} projectName={overview.project} />;
      case "Configurações":
        return <SettingsView onAsk={askAi} user={user} />;
      case "Trocar de contexto":
        return <ProjectsView projects={projects} activeEngagementId={activeEngagementId} onSelect={selectProject} onAsk={askAi} />;
      default:
        return (
          <OverviewView
            user={user}
            onAsk={askAi}
            onNavigate={goTo}
            onOpenTurn={openTurn}
            overview={view}
            focusedItem={focusedItem}
            onAnalyze={() => sendQuestion(undefined, "Mostre todas as pendências.")}
          />
        );
    }
  }

  return (
    <main className={`portal-shell ${collapsed ? "portal-shell--collapsed" : ""}`}>
      <aside className={`sidebar ${mobileNavOpen ? "sidebar--open" : ""} ${menu === "profile-side" ? "sidebar--menu-open" : ""}`}>
        <div className="brand-row">
          <Brand />
          <button
            className="icon-button sidebar-toggle"
            onClick={() => { setCollapsed((value) => !value); setMobileNavOpen(false); }}
            aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        {/*
          Os dois textos desta linha falam do **projeto**, e o fallback do logo dizia
          outra coisa (ADR 0062): ele caía para `user.org` enquanto o `<small>` ao lado
          caía para `overview.project`, de modo que o mesmo estado produzia a inicial da
          organização sobre o nome do projeto. Os dois passam a ler `overview.project`,
          que é factualmente o projeto que a API serviu. O nome segue sendo **rótulo** e
          nunca identidade — a identidade é o `project_id` da ADR 0061, e é por isso que
          unificar o fallback é seguro agora e não era antes.

          Quando não há `activeProject`, a tela **diz**: o cliente vê o dashboard certo e
          um seletor que não o contém, e sem sinal isso é indistinguível de escolha. O que
          se afirma é só o que se sabe — que o projeto da tela não está na lista —, nunca
          qual deveria ser.
        */}
        <button
          className={`project-switcher ${activeProject ? "" : "project-switcher--unlisted"}`}
          aria-label="Trocar de contexto"
          title={activeProject ? undefined : "Este projeto não está na sua lista de projetos."}
          onClick={() => goTo("Trocar de contexto")}
        >
          <span className="project-logo">{(activeProject?.name ?? overview.project).slice(0, 1)}</span>
          <span>
            <strong>{user.org}</strong>
            {/* Conta → Engagement → Project, a hierarquia do Language Map v1.1 na ordem
                em que ela existe (ADR 0079). A linha do programa só aparece quando há
                programa: um projeto sem engagement não ganha rótulo inventado, e é o
                mesmo silêncio com que a tela trata `freshness` nula. */}
            {engagementLabel && <small>{engagementLabel}</small>}
            <small>{activeProject?.name ?? overview.project}</small>
            {!activeProject && <small className="project-unlisted">Fora da sua lista de projetos</small>}
          </span>
          <ChevronDown size={16} />
        </button>

        <nav aria-label="Navegação do projeto">
          <p className="nav-label">PROJETO</p>
          {navItems.map(({ label, icon: Icon }) => (
            <button
              className={`nav-item ${activeNav === label ? "nav-item--active" : ""}`}
              key={label}
              onClick={() => goTo(label)}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span>{label}</span>
              {label === "Pendências" && openCount > 0 && <em>{openCount}</em>}
              {label === "Revisão" && reviewCount > 0 && <em>{reviewCount}</em>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => { setChatOpen(true); setMobileNavOpen(false); }}><HelpCircle size={18} /><span>Central de ajuda</span></button>
          <div className="sidebar-menu">
            <button className="profile-card" onClick={() => toggleMenu("profile-side")} aria-label="Abrir menu do usuário">
              <span className="avatar avatar--small">{user.initials}</span>
              <span><strong>{user.name}</strong><small>{user.org}</small></span>
              <MoreHorizontal size={17} />
            </button>
            {menu === "profile-side" && <ProfileMenu up user={user} onNavigate={goTo} />}
          </div>
        </div>
      </aside>

      {mobileNavOpen && <button className="backdrop" onClick={() => setMobileNavOpen(false)} aria-label="Fechar navegação" />}
      {menu && <button className="menu-backdrop" onClick={() => setMenu(null)} aria-label="Fechar menu" />}

      <section className="content-area">
        <header
          className={`topbar ${menu && menu !== "profile-side" ? "topbar--menu-open" : ""}`}
        >
          <button className="icon-button mobile-menu" onClick={() => setMobileNavOpen(true)} aria-label="Abrir menu"><Menu size={21} /></button>
          <div className="breadcrumb"><span>{user.org}</span><b>/</b><strong>{activeNav}</strong></div>
          <div className="topbar-actions">
            <div className="topbar-menu">
              <button className="icon-button" aria-label="Pesquisar" onClick={() => toggleMenu("search")}><Search size={20} /></button>
              {menu === "search" && (
              <ProjectSearch onOpen={openSearchHit} projectId={activeProject?.id ?? null} />
            )}
            </div>
            <div className="topbar-menu">
              <button
                className="notification-button"
                aria-label={unreadCount > 0 ? `Notificações (${unreadCount} não lidas)` : "Notificações"}
                onClick={() => { toggleMenu("notifications"); markRead(); }}
              >
                <Bell size={20} />
                {unreadCount > 0 && <i />}
              </button>
              {menu === "notifications" && (
                <div className="popover popover--notifications">
                  <div className="popover-head">Notificações</div>
                  {notifications.items.length === 0 && (
                    <p className="popover-hint">Nada novo por aqui. Avisamos quando o projeto andar.</p>
                  )}
                  {notifications.items.slice(0, 5).map((item) => (
                    <NotificationLink
                      className="popover-row"
                      currentProjectId={activeProject?.id ?? null}
                      key={item.id}
                      notification={item}
                      onNavigate={goTo}
                    >
                      <strong>{item.title}</strong>
                      <span>{[item.detail, item.age].filter(Boolean).join(" • ")}</span>
                    </NotificationLink>
                  ))}
                  {notifications.items.length > 0 && (
                    <button className="popover-all" onClick={() => goTo("Notificações")}>
                      Ver todas <ArrowUpRight size={14} />
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="topbar-menu">
              <button className="avatar avatar-button" aria-label="Abrir menu do usuário" onClick={() => toggleMenu("profile")}>{user.initials}</button>
              {menu === "profile" && <ProfileMenu user={user} onNavigate={goTo} />}
            </div>
          </div>
        </header>

        <div className="dashboard">
          {/* A âncora do aviso não existe mais no projeto. Discreta de propósito —
              o cliente veio ver a aba, e ela está inteira aqui —, mas dita: sem
              esta linha o link degradaria de forma invisível. */}
          {anchorMissing && (
            <p className="anchor-missing">O item deste aviso não está mais nesta lista.</p>
          )}
          {renderActiveView()}
        </div>
      </section>

      <button className="chat-fab" onClick={() => setChatOpen(true)} aria-label="Abrir chat com IA"><MessageCircleMore size={22} /><span>Falar com a IA</span></button>

      {chatOpen && (
        <section className="chat-panel" aria-label="Assistente de IA do projeto">
          <header className="chat-header"><div className="ai-avatar"><Sparkles size={16} /></div><div><strong>Assistente do projeto</strong><span><i /> Contexto atualizado</span></div><button className="icon-button" onClick={startNewConversation} aria-label="Iniciar nova conversa" title="Nova conversa"><MessageSquarePlus size={19} /></button><button className="icon-button" onClick={() => setChatOpen(false)} aria-label="Fechar chat"><X size={19} /></button></header>
          <div className="chat-messages">
            {messages.map((message, index) => (
              <div className={`message message--${message.role} ${message.id && message.id === focusedTurn ? "message--focused" : ""}`} data-message-id={message.id} key={message.id ?? `${message.role}-${index}`}>
                <p>{message.text}</p>
                {/* `?.length` e não só `?`: o histórico devolve `[]` para a pergunta
                    do usuário, e um array vazio ainda é verdadeiro — renderizava uma
                    faixa de fontes vazia debaixo de cada pergunta. */}
                {/* `citations` traz o ponteiro do arquivo e é o caminho normal;
                    `sources` continua atendendo quem só tem o rótulo — o
                    fallback offline do chat e a casca de demonstração. */}
                {message.citations?.length ? (
                  <div className="message-sources">
                    {message.citations.map((citation) =>
                      citation.document_id ? (
                        <button
                          className="message-source-link"
                          data-document-id={citation.document_id}
                          key={citation.label}
                          onClick={() => openDocument(citation.document_id!)}
                          title={citationHint(citation)}
                          type="button"
                        >
                          <FileText size={12} /> {citation.label}
                        </button>
                      ) : (
                        <span key={citation.label} title={citationHint(citation)}>
                          <FileText size={12} /> {citation.label}
                        </span>
                      ),
                    )}
                  </div>
                ) : message.sources?.length ? (
                  <div className="message-sources">{message.sources.map((source) => <span key={source}><FileText size={12} /> {source}</span>)}</div>
                ) : null}
                {/* A classificação que a própria API deu ao turno. Só aparece
                    quando ela declarou lacuna: dizer "com evidência" embaixo de
                    toda resposta vira ruído e ensina a ignorar o selo — e é
                    justamente quando **não** houve evidência que o cliente
                    precisa saber, porque a regra 3 do `AGENTS.md` manda declarar
                    a lacuna em vez de inventar (ADR 0033). */}
                {message.confidence === "insufficient_context" && (
                  <small className="answer-gap">
                    Sem evidência suficiente no contexto do projeto
                  </small>
                )}
                {message.pending && <small className="pending-created"><Check size={13} /> Pendência criada para o time Biahflow</small>}
                {/* Só a resposta gravada aceita polegar: sem id não há o que avaliar. */}
                {message.role === "assistant" && message.id && (
                  <AnswerFeedback
                    messageId={message.id}
                    feedback={message.feedback ?? null}
                    onRate={rateAnswer}
                  />
                )}
              </div>
            ))}
          </div>
          {downloadError && <p className="chat-notice" role="status">{downloadError}</p>}
          {/* Projeto encerrado ou removido é consulta, não conversa (ADR 0036/0037). O histórico
              acima continua inteiro — é a evidência das respostas já dadas —, e a API recusaria
              com 409 de qualquer forma: fechar aqui é dizer o motivo antes de a pessoa digitar. */}
          {projectReadOnly ? (
            <p className="chat-notice" role="status">{projectReadOnly.chat}</p>
          ) : (
            <>
              <div className="chat-suggestions">{suggestedQuestions.map((item) => <button key={item} onClick={() => sendQuestion(undefined, item)}>{item}</button>)}</div>
              <form className="chat-form" onSubmit={sendQuestion}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Pergunte sobre o projeto..." aria-label="Pergunta para IA" /><button type="submit" aria-label="Enviar pergunta"><Send size={17} /></button></form>
            </>
          )}
        </section>
      )}
    </main>
  );
}

/** A lupa do topbar, do campo ao resultado (Fase 6, ADR 0024).
 *
 *  Componente próprio, e o motivo não é organização: ele **monta com o popover
 *  e desmonta com ele**, então fechar a lupa esquece o que foi digitado sem
 *  nenhum efeito de limpeza. O termo é a pergunta de alguém — guardá-lo entre
 *  aberturas seria retê-lo sem que ninguém tenha pedido, a mesma razão pela
 *  qual ele não vai para o log.
 *
 *  O resultado é guardado **junto do termo que o produziu**: enquanto a resposta
 *  do termo novo não chega, a lista antiga não é exibida como se fosse dele.
 *  E nenhum caminho aqui fabrica resultado — a lista vem da API ou não existe,
 *  pelo motivo pelo qual o `answerFor()` do chat foi apagado (ADR 0021). */
function ProjectSearch({
  onOpen,
  projectId,
}: {
  onOpen: (hit: SearchHit) => Promise<boolean>;
  /** O projeto da tela (ADR 0059). `null` deixa a API cair no padrão dela. */
  projectId: string | null;
}) {
  const [term, setTerm] = useState("");
  const [found, setFound] = useState<{ query: string; hits: SearchHit[] } | null>(null);
  const [failed, setFailed] = useState("");
  const [openFailed, setOpenFailed] = useState(false);
  const query = term.trim();
  const short = query.length < SEARCH_MIN_LENGTH;
  // O projeto da tela (ADR 0059). Omitido quando não há um conhecido: vazio
  // não é "sem parâmetro", é 422 do outro lado.
  const scope = projectId ? `&project=${encodeURIComponent(projectId)}` : "";

  // Debounce mais `AbortController`: a tecla seguinte cancela a busca da
  // anterior, então a resposta que sobra é sempre a do último termo.
  useEffect(() => {
    if (short) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}` + scope, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("search failed");
        const data = await response.json();
        setFound({ query, hits: data.results ?? [] });
        setFailed("");
      } catch (error) {
        if ((error as Error)?.name === "AbortError") return;
        setFailed(query);
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, short, scope]);

  const hits = found?.query === query ? found.hits : null;

  return (
    <div className="popover popover--search">
      <input
        autoFocus
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        placeholder="Buscar documentos, reuniões, pendências..."
        aria-label="Buscar no projeto"
      />
      {/* Cada estado é uma frase diferente de propósito: "digite mais",
          "buscando", "não consegui" e "nada encontrado" respondem a perguntas
          distintas, e uma frase só faria a tela mentir sobre por que a lista
          está vazia. */}
      {short ? (
        <p className="popover-hint">Comece a digitar para buscar no contexto do projeto.</p>
      ) : failed === query ? (
        <p className="popover-hint" role="status">Não consegui buscar agora.</p>
      ) : hits === null ? (
        <p className="popover-hint" role="status">Buscando...</p>
      ) : hits.length === 0 ? (
        <p className="popover-hint" role="status">Nada encontrado para “{query}”.</p>
      ) : (
        <ul className="search-results" aria-label="Resultados da busca">
          {hits.map((hit, index) => (
            <li key={`${hit.kind}-${hit.title}-${hit.location}-${index}`}>
              <button
                className="search-result"
                onClick={async () => setOpenFailed(!(await onOpen(hit)))}
              >
                <span className="search-result-kind">{searchKindLabel[hit.kind] ?? hit.kind}</span>
                <strong>{hit.title}</strong>
                {(hit.detail || hit.location) && (
                  <span className="search-result-detail">
                    {[hit.location, hit.detail].filter(Boolean).join(" • ")}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* O clique que não abriu a fonte. Fica **aqui**, e não no painel do chat
          onde o erro de download da citação aparece: o popover continua na tela,
          e um clique sem efeito e sem explicação é indistinguível de um botão
          quebrado. */}
      {openFailed && (
        <p className="popover-hint" role="status">Não foi possível abrir o documento agora.</p>
      )}
    </div>
  );
}

function ViewHero({ eyebrow, title, subtitle, onAsk }: { eyebrow: string; title: string; subtitle: string; onAsk: () => void }) {
  return (
    <section className="hero">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="hero-copy">{subtitle}</p>
      </div>
      <Button variant="primary" onClick={onAsk}><Sparkles size={17} /> Perguntar à IA</Button>
    </section>
  );
}

/**
 * O polegar e, depois dele, o comentário (ADR 0033).
 *
 * O campo aparece **depois** de avaliar, e não junto: pedir texto antes torna o
 * polegar caro, e o polegar barato é o que faz existir algum sinal. Depois de
 * dado, "quer contar o que faltou?" é uma pergunta que quem clicou já mostrou
 * disposição de responder.
 *
 * Escrever de novo sobrescreve — é o mesmo `record_feedback`, que é um GRANT de
 * coluna e não um `INSERT`: a pessoa avalia a resposta e nunca reescreve a
 * resposta nem as citações que ela mostrou (ADR 0015).
 */
function AnswerFeedback({
  messageId,
  feedback,
  onRate,
}: {
  messageId: string;
  feedback: "helpful" | "not_helpful" | null;
  onRate: (messageId: string, helpful: boolean, comment?: string) => void;
}) {
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  function submitComment(event: FormEvent) {
    event.preventDefault();
    if (!comment.trim() || !feedback) return;
    onRate(messageId, feedback === "helpful", comment);
    setSent(true);
  }

  return (
    <div className="message-feedback">
      <div className="message-feedback-thumbs">
        <button
          className={feedback === "helpful" ? "is-active" : undefined}
          onClick={() => onRate(messageId, true)}
          aria-pressed={feedback === "helpful"}
          aria-label="Esta resposta ajudou"
        ><ThumbsUp size={13} /></button>
        <button
          className={feedback === "not_helpful" ? "is-active" : undefined}
          onClick={() => onRate(messageId, false)}
          aria-pressed={feedback === "not_helpful"}
          aria-label="Esta resposta não ajudou"
        ><ThumbsDown size={13} /></button>
      </div>
      {feedback && !sent && (
        <form className="message-feedback-comment" onSubmit={submitComment}>
          <input
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={500}
            placeholder={
              feedback === "helpful" ? "O que ajudou? (opcional)" : "O que faltou? (opcional)"
            }
            aria-label="Comentário sobre esta resposta"
          />
          <button type="submit" disabled={!comment.trim()}>Enviar</button>
        </form>
      )}
      {sent && <small className="message-feedback-sent">Obrigado — o time vê isto.</small>}
    </div>
  );
}

const PHASE_STATE_LABEL: Record<JourneyPhase["state"], string> = {
  done: "Concluída",
  active: "Em andamento",
  locked: "A desbloquear",
};

/**
 * O degrau da FDE, no vocabulário canônico (Language Map §2/§4, ADR 0081).
 *
 * Existe porque o **rótulo** da fase é da origem e o **degrau** é da metodologia: um
 * projeto pode chamar sua fase de "Prova de conceito" ou de "Activation", e é o degrau
 * que diz onde aquilo cai na FDE. Fase sem degrau — a `Activation` do exemplo — não
 * ganha selo nenhum: `null` ali quer dizer "não tem equivalente", e inventar um seria
 * derivar do nome, que é exatamente o que a ingestão se recusa a fazer.
 */
const CANONICAL_STAGE_LABEL: Record<NonNullable<JourneyPhase["canonicalStage"]>, string> = {
  discover: "DISCOVER",
  prioritize: "PRIORITIZE",
  feasibility: "FEASIBILITY",
  prove: "PROVE",
  scale: "SCALE",
  optimize: "OPTIMIZE",
};

/**
 * Os quatro rótulos da decisão de gate, **em maiúsculas e em inglês** (Language Map
 * §2, decisão D7).
 *
 * A regra de idioma do mapa é que o termo canônico não se traduz — traduz-se o texto
 * em volta dele. Daí "Decisão da fase: GO", e não "Decisão da fase: Aprovado": o
 * cliente lê a mesma palavra que o time escreve no Pulse e no readout, que é o ponto
 * inteiro de um mapa de linguagem.
 *
 * **Nada aqui é Outcome.** `Outcome` é resultado de negócio medido — um
 * `Measurement(kind=outcome)` com Baseline comparável —, e foi para os dois não
 * disputarem a palavra que a D7 renomeou `GateOutcome` para `GateDecision`. Este selo
 * mora na jornada, ao lado da fase que ele fecha, e nunca na aba Resultados.
 */
const GATE_DECISION_LABEL: Record<NonNullable<JourneyPhase["gateDecision"]>, string> = {
  go: "GO",
  conditional_go: "CONDITIONAL GO",
  redesign: "REDESIGN",
  no_go: "NO-GO",
};

/** A variante da primitiva por decisão; a espera é `info`, porque ainda não é notícia. */
const GATE_DECISION_VARIANT: Record<NonNullable<JourneyPhase["gateDecision"]>, StatePillVariant> = {
  go: "success",
  conditional_go: "warning",
  redesign: "warning",
  no_go: "danger",
};

/**
 * A decisão que fecha a fase, quando a fase termina em gate (ADR 0081).
 *
 * As três respostas possíveis, e a terceira é a que só existe porque `requiresGate`
 * atravessa o contrato:
 *
 * 1. **fase sem gate** → não renderiza nada. Uma caixa vazia dizendo "sem decisão"
 *    afirmaria que há uma decisão faltando numa fase que nunca terá uma;
 * 2. **decidiu** → o rótulo canônico;
 * 3. **exige gate e ninguém decidiu** → "aguardando". Sem `requiresGate` este caso
 *    seria indistinguível do primeiro, e a tela teria de calar sobre os dois.
 *
 * Nunca chame isto de Outcome, resultado ou entrega: é decisão de metodologia sobre
 * uma fase, e o lugar dela é a jornada.
 */
function GateDecisionBadge({ phase }: { phase: JourneyPhase }) {
  if (!phase.requiresGate) return null;
  return (
    // `div` e não `p`: `.journey-detail-head p` já carrega margem e cor próprias, e
    // um seletor de elemento vence a classe — a linha nasceria colada na descrição.
    <div className="journey-gate">
      <span className="journey-gate-label">Decisão da fase</span>
      {phase.gateDecision ? (
        <StatePill variant={GATE_DECISION_VARIANT[phase.gateDecision]}>
          {GATE_DECISION_LABEL[phase.gateDecision]}
        </StatePill>
      ) : (
        <StatePill variant="info">aguardando</StatePill>
      )}
    </div>
  );
}

/**
 * "Decidido em 12 set · reunião de alinhamento" — a linha de data do nó de decisão.
 *
 * Uma função e não um literal interpolado porque as duas metades são independentemente
 * nulas: a origem publica decisão sem data e decisão sem reunião, e as três combinações
 * têm de sair legíveis. Devolve `""` quando não há nenhuma das duas, e aí a linha não é
 * renderizada — um "Decidido em" sem data seria pior que o silêncio.
 */
function decisionWhen(decision: DecisionView): string {
  const when = decision.decidedOn ? `Decidido em ${decision.decidedOn}` : "";
  return [when, decision.meetingTitle].filter(Boolean).join(" · ");
}

// "Você está aqui": a jornada de transformação pela perspectiva do cliente — sem nada
// técnico. Cada fase concluída/ativa revela seus entregáveis; as bloqueadas ficam veladas.
/**
 * O carimbo de frescor e, acima do limiar, o estado *stale* (ADR 0076, DAP r1 §Surfaces).
 *
 * Mora na cabeça da jornada porque é ali que o cliente lê "Você está aqui": a pergunta
 * "aqui **quando**?" é a mesma pergunta, e separá-las deixaria a resposta longe de onde ela
 * é feita. `role="status"` no invólucro, e não uma vez por linha, para o leitor de tela
 * anunciar carimbo e motivo como uma coisa só.
 *
 * Nada aqui decide se o dado está velho: o limiar é de operação e a comparação já foi
 * feita no servidor, no instante da renderização. Esta função só escolhe a frase.
 */
function FreshnessStamp({ freshness }: { freshness: FreshnessView }) {
  return (
    <div className="journey-freshness" role="status">
      <p className="journey-fresh">
        <Clock3 size={13} aria-hidden="true" />
        {FRESHNESS_LABEL[freshness.kind](freshness.age)}
      </p>
      {/* Velho, indisponível e encerrado são três estados distintos, com três cores
          distintas (ADR 0076): aqui é o `warning` — há dado, e ele pode não valer mais. */}
      {freshness.stale && (
        <p className="journey-stale">
          <StatePill variant="warning">Pode estar desatualizado</StatePill>
          <span>{STALE_MESSAGE[freshness.kind](freshness.age)}</span>
        </p>
      )}
    </div>
  );
}

function JourneyPanel({
  journey,
  decisions,
  freshness,
  focusedItem,
  onNavigate,
}: {
  journey: Overview["journey"];
  /** As decisões do projeto, das quais a timeline mostra **só** as que a origem ancorou a
   *  uma fase (ADR 0088). A lista inteira continua na aba Decisões: aqui ela é filtrada,
   *  nunca consumida — a aba é o registro, a timeline é o vínculo. */
  decisions: DecisionView[];
  /** O carimbo de frescor da projeção (ADR 0076); `null` quando nunca houve sync. */
  freshness: FreshnessView | null;
  focusedItem?: string | null;
  /** O atalho `[Revisar]` para a aba de Revisão, na linha do entregável (FDD 027).
   *  É o `goTo` de sempre — troca de aba **e** carrega a âncora —, e não uma URL:
   *  a navegação deste componente é estado, e o `?tab=`/`?item=` existe para quem
   *  chega de fora (ADR 0043/0056). */
  onNavigate?: (label: string, item?: string) => void;
}) {
  const phases = journey.phases;
  const activeIndex = phases.findIndex((phase) => phase.state === "active");
  /**
   * A fase que a âncora do aviso pede, quando há uma (ADR 0056).
   *
   * Este painel só desenha os entregáveis da fase **selecionada**, e o padrão é a
   * fase ativa. Sem isto, um `deliverable_delivered` de fase já concluída
   * produziria uma âncora fora do DOM: link tecnicamente correto e inalcançável,
   * que é o pior desfecho possível — pior que não ter link, porque parece que tem.
   *
   * É também o que dispensa uma âncora composta `fase/entregável`, e com ela o
   * problema de escapar o separador num rótulo que contém dois-pontos. **O preço
   * está escrito**: entregáveis homônimos em fases diferentes se resolvem pela
   * primeira fase que os contiver.
   */
  const anchored = phases.findIndex(
    (phase) =>
      `phase:${phase.name}` === focusedItem ||
      phase.deliverables.some((deliverable) => `deliverable:${deliverable.name}` === focusedItem),
  );
  const initial = anchored >= 0 ? anchored : activeIndex >= 0 ? activeIndex : Math.max(0, phases.length - 1);
  const [selected, setSelected] = useState(initial);
  if (phases.length === 0) return null;
  const phase = phases[Math.min(selected, phases.length - 1)];
  const anchoredDecisions = decisions.filter((decision) => decision.journeyPhaseName === phase.name);

  return (
    <section className="journey-panel" aria-label="Jornada de transformação">
      <div className="journey-head">
        <div>
          <p className="eyebrow">SUA JORNADA</p>
          <h2>Você está aqui</h2>
        </div>
        <div className="journey-status">
          {journey.currentPhase && (
            <span className="journey-here"><MapPin size={15} /> {journey.currentPhase}</span>
          )}
          {freshness && <FreshnessStamp freshness={freshness} />}
        </div>
      </div>

      <ol className="journey-track">
        {phases.map((item, index) => (
          <li
            key={item.name}
            className={`journey-step journey-step--${item.state} ${index === selected ? "is-selected" : ""} ${`phase:${item.name}` === focusedItem ? "is-anchored" : ""}`}
            data-item={`phase:${item.name}`}
          >
            <button type="button" onClick={() => setSelected(index)} aria-current={item.state === "active"}>
              <span className="journey-dot">
                {item.state === "done" ? <Check size={14} /> : item.state === "locked" ? <Lock size={12} /> : <span className="journey-pulse" />}
              </span>
              <span className="journey-name">{item.name}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="journey-detail">
        <div className="journey-detail-head">
          <div>
            <StateBadge tone={phase.state === "done" ? "1" : phase.state === "active" ? "2" : "3"}>{PHASE_STATE_LABEL[phase.state]}</StateBadge>
            {/* O degrau da metodologia, quando a origem o afirma. O `h3` abaixo é o
                rótulo que o projeto deu à fase; este é o degrau da FDE a que ela
                corresponde, e os dois podem divergir sem que nenhum esteja errado. */}
            {phase.canonicalStage && (
              <span className="journey-stage">{CANONICAL_STAGE_LABEL[phase.canonicalStage]}</span>
            )}
            <h3>{phase.name}</h3>
            {phase.description && <p>{phase.description}</p>}
            {/* A decisão da fase fica **aqui**, junto da fase que ela fecha, e nunca
                na aba Resultados: Outcome é resultado medido, e a D7 do Language Map
                renomeou `GateOutcome` justamente para os dois não se confundirem. */}
            <GateDecisionBadge phase={phase} />
          </div>
          {phase.targetDate && <div className="journey-target"><span>Previsão</span><strong>{phase.targetDate}</strong></div>}
        </div>

        {/* As decisões que destravaram **esta** fase (ADR 0088, DAP r1 §Surfaces).
            O casamento é pelo nome porque é a identidade que o servidor publica e a
            que a timeline já usa como âncora; a resolução pela identidade estável (o
            id da fase na origem) aconteceu na ingestão. Homônimas caem na degradação
            benigna que a ADR 0056 já aceitou.

            Nada aqui desenha a decisão **sem** fase: ela não some — continua inteira
            na aba Decisões —, só não ganha nó. Um rótulo de "sem fase" seria estado
            que o gate de design não aprovou. */}
        {anchoredDecisions.length > 0 && (
          <div className="journey-decisions">
            {anchoredDecisions.map((decision) => {
              const when = decisionWhen(decision);
              return (
                <div className="journey-decision" key={decision.title}>
                  <span className="journey-decision-icon"><Check size={14} /></span>
                  <div>
                    <div className="journey-decision-title">{decision.title}</div>
                    {/* Só o que é client-safe: título, racional e data. O dono da decisão
                        fica na aba, onde a pergunta é "quem decidiu"; aqui a pergunta é
                        "o que destravou esta fase". */}
                    {decision.rationale && <div className="journey-decision-why">{decision.rationale}</div>}
                    {when && <div className="journey-decision-when">{when}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <p className="journey-deliverables-label">{phase.state === "locked" ? "Entregáveis a desbloquear" : "Entregáveis desta fase"}</p>
        {phase.deliverables.length === 0 ? (
          <p className="journey-empty">Os entregáveis desta fase aparecerão aqui.</p>
        ) : (
          <ul className="journey-deliverables">
            {phase.deliverables.map((deliverable) => {
              const unlocked = deliverable.state === "delivered";
              return (
                <li
                  key={deliverable.name}
                  className={`${unlocked ? "is-unlocked" : "is-locked"} ${`deliverable:${deliverable.name}` === focusedItem ? "is-anchored" : ""}`}
                  data-item={`deliverable:${deliverable.name}`}
                >
                  <span className="deliverable-icon">{unlocked ? <Check size={13} /> : <Lock size={12} />}</span>
                  {unlocked && deliverable.link ? (
                    <a href={deliverable.link} target="_blank" rel="noreferrer">{deliverable.name} <ArrowUpRight size={13} /></a>
                  ) : (
                    <span>{deliverable.name}</span>
                  )}
                  {/* Só o que a operação entregou e a origem identificou: sem
                      `external_ref` não há rota de aceite, e um atalho para um card
                      que não decide nada é o controle inerte da ADR 0026 com outro
                      nome. */}
                  {unlocked && deliverable.externalRef && onNavigate && (
                    <button
                      className="text-button"
                      onClick={() => onNavigate("Revisão", `deliverable:${deliverable.name}`)}
                    >
                      Revisar
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

function roiValue(roi: Overview["roi"]): { value: string; note: string; positive: boolean } {
  // Sem ROI no snapshot, um travessão. Até a Fase 3 isto devolvia um percentual
  // fixo — o último fallback de demonstração da tela do cliente.
  if (!roi || roi.ratio == null) {
    return { value: "—", note: "Sem projeção no Biahflow", positive: false };
  }
  const pct = Math.round(roi.ratio * 100);
  const note = roi.net != null
    ? `R$ ${roi.net.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} de retorno`
    : "Retorno estimado do projeto";
  return { value: `${pct >= 0 ? "+" : ""}${pct}%`, note, positive: pct >= 0 };
}

function percent(value: number | null, digits = 1): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits).replace(".", ",")}%`;
}

function compact(value: number): string {
  return value.toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
}

function OverviewView({ onAsk, onAnalyze, onNavigate, onOpenTurn, overview, user, focusedItem }: { onAsk: () => void; onAnalyze: () => void; onNavigate: (label: string, item?: string) => void; onOpenTurn: (messageId: string, conversationId: string | null) => void; overview: Overview; user: PortalUser; focusedItem?: string | null }) {
  const timeline = overview.milestones;
  const open = openPendings(overview);
  // A manchete deixou de ser a projeção da origem e passou a ser o **valor
  // gerado** (issue #89, ADR 0085). O ROI projetado não sumiu do produto: ele
  // continua na aba Resultados, ao lado do apurado e rotulado como tal desde a
  // ADR 0084 — o que muda é o primeiro número que o cliente lê ao abrir o portal,
  // que passa a ter período e método de atribuição por trás.
  const generated = valueLedgerTotal(overview.valueLedger);
  const readOnly = readOnlyReason(overview);
  // Conhecimento do projeto: documentos e reuniões mais recentes, na mesma lista.
  const updates = [
    ...overview.documents.map((document) => ({ type: "Documento", title: document.title, detail: document.updated, link: document.link })),
    ...overview.meetings.map((meeting) => ({ type: "Reunião", title: meeting.title, detail: meeting.hasTranscript ? "Transcrição disponível" : meeting.status, link: meeting.recordingUrl })),
  ].slice(0, 5);
  return (
    <>
      <ViewHero eyebrow={overview.project.toLocaleUpperCase("pt-BR")} title={`Bom dia, ${firstName(user.name)}.`} subtitle="Veja o que está acontecendo no seu projeto." onAsk={onAsk} />

      <JourneyPanel journey={overview.journey} decisions={overview.decisions} freshness={overview.freshness} focusedItem={focusedItem} onNavigate={onNavigate} />

      <DigitalEmployees employees={overview.digitalEmployees} />

      <KpiPanel kpis={overview.kpis} employees={overview.digitalEmployees} />

      <ValueLedgerPanel entries={overview.valueLedger} kpis={overview.kpis} />

      <section className="status-card">
        <div className="status-main">
          <div className="status-icon"><Check size={19} /></div>
          <div><p>Status do projeto</p><h2>{overview.status}</h2></div>
          {/* Ao lado da saúde, não no lugar dela: o andamento continua sendo o que era quando
              o projeto foi encerrado, e as duas informações respondem perguntas diferentes. */}
          {readOnly && <span className="health-pill health-pill--archived">{readOnly.pill}</span>}
          {overview.health && <span className={`health-pill health-pill--${overview.health.level}`}>{overview.health.label}</span>}
        </div>
        {/* A casca de demonstração não carimba data: "Atualizado há 2 dias" era
            um frescor inventado no único lugar onde o demo é permitido. */}
        <div className="status-meta"><span>{overview.completion}% concluído</span><div className="progress"><i style={{ width: `${overview.completion}%` }} /></div><small>{overview.source === "live" ? "Sincronizado com o Biahflow" : "Dados de demonstração"}</small></div>
        {/* Não há "Ver detalhes": status, percentual e saúde são o que o portal
            sabe do andamento, e ele não origina status (ADR 0006/0008). */}
      </section>

      <section className="metrics-grid" aria-label="Indicadores do projeto">
        <article className="metric-card metric-card--delivery">
          <div className="metric-icon"><CalendarClock size={19} /></div>
          <p>Próxima entrega</p>
          <h3>{overview.nextDelivery?.title ?? "Sem entrega pendente"}</h3>
          <span>{overview.nextDelivery?.detail ?? "Todos os marcos concluídos"}</span>
        </article>
        <article className="metric-card">
          <div className="metric-icon metric-icon--green"><TrendingUp size={19} /></div>
          <p>Valor gerado</p>
          <h3>{generated.value}</h3>
          <span className={generated.positive ? "positive" : undefined}>{generated.note}</span>
        </article>
        <article className="metric-card">
          <div className="metric-icon metric-icon--purple"><UsersRound size={19} /></div>
          <p>Próxima reunião</p>
          <h3>{overview.nextMeeting?.title ?? "A agendar"}</h3>
          <span>{overview.nextMeeting?.detail ?? "Sem reunião marcada"}</span>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="panel timeline-panel">
          <div className="panel-heading"><div><p className="eyebrow">PRÓXIMOS MARCOS</p><h2>Cronograma</h2></div><button className="text-button" onClick={() => onNavigate("Cronograma")}>Ver cronograma <ArrowUpRight size={14} /></button></div>
          <div className="milestones">
            {timeline.map((milestone) => {
              const tone = stateStyle[milestone.state] ?? "2";
              return (
                <div className="milestone" key={milestone.title}>
                  <div className={`timeline-dot timeline-dot--${tone}`}><span /></div>
                  <div className="milestone-date">{milestone.date}</div>
                  <div className="milestone-title"><strong>{milestone.title}</strong>{milestone.owner && <span>{milestone.owner}</span>}</div>
                  <StateBadge tone={tone}>{milestone.state}</StateBadge>
                </div>
              );
            })}
          </div>
        </article>

        <article className="panel pending-panel">
          <div className="panel-heading"><div><p className="eyebrow">ACOMPANHAMENTO</p><h2>Pendências abertas <span>{open.length}</span></h2></div></div>
          <div className="pending-list">
            {open.length === 0 && <p className="empty-state">Nenhuma pendência aberta.</p>}
            {open.slice(0, 4).map((item) => <PendingItem key={item.title} item={item} onOpenTurn={onOpenTurn} />)}
          </div>
          <button className="text-button full-width" onClick={() => onNavigate("Pendências")}>Ver todas as pendências <ArrowUpRight size={14} /></button>
        </article>
      </section>

      <section className="bottom-grid">
        <article className="panel source-panel">
          <div className="panel-heading"><div><p className="eyebrow">CONHECIMENTO DO PROJETO</p><h2>Atualizações recentes</h2></div></div>
          <div className="source-list">
            {updates.length === 0 && <p className="empty-state">Nenhum documento ou reunião ainda.</p>}
            {updates.map((update) => (
              <div className="source-row" key={`${update.type}-${update.title}`}>
                <span className="file-icon">{update.type === "Reunião" ? <Video size={17} /> : <FileText size={17} />}</span>
                <div><strong>{update.title}</strong><span>{update.type}{update.detail && <> <b>•</b> {update.detail}</>}</span></div>
                {update.link ? <a href={update.link} target="_blank" rel="noreferrer" aria-label={`Abrir ${update.title}`}><ArrowUpRight size={16} /></a> : <ArrowUpRight size={16} />}
              </div>
            ))}
          </div>
        </article>
        <article className="insight-card">
          <div className="insight-orb"><Bot size={24} /></div>
          <p className="eyebrow">INSIGHT DA IA</p>
          <h2>{overview.journey.currentPhase ? `Fase atual: ${overview.journey.currentPhase}.` : "Acompanhe o andamento do projeto."}</h2>
          <p>{open.length === 0 ? "Nenhuma pendência aberta no momento." : `${open.length} ${open.length === 1 ? "pendência aberta" : "pendências abertas"} para avançar.`}</p>
          <button onClick={onAnalyze}>Ver análise <ArrowUpRight size={15} /></button>
        </article>
      </section>
    </>
  );
}

function ScheduleView({ onAsk, overview, focusedItem }: { onAsk: () => void; overview: Overview; focusedItem?: string | null }) {
  const [state, setState] = useState<string | null>(null);
  const counts = countBy(overview.milestones, (item) => item.state);
  const milestones =
    state === null ? overview.milestones : overview.milestones.filter((item) => item.state === state);
  return (
    <>
      <ViewHero eyebrow="CRONOGRAMA" title="Cronograma do projeto" subtitle="Marcos concluídos, em andamento e planejados." onAsk={onAsk} />
      <article className="panel timeline-panel">
        <div className="panel-heading"><div><p className="eyebrow">LINHA DO TEMPO</p><h2>Todos os marcos</h2></div><StateBadge tone="1">{overview.completion}% concluído</StateBadge></div>
        {/* Os estados vêm do que a lista tem, não de uma lista fixa: o rótulo é
            do Biahflow, e enumerá-lo aqui criaria um segundo mapa para envelhecer. */}
        <FilterChips
          label="Filtrar por estado do marco"
          active={state}
          onPick={setState}
          options={[
            { value: null, label: "Todos", count: overview.milestones.length },
            ...Object.keys(counts).map((value) => ({ value, label: value, count: counts[value] })),
          ]}
        />
        <div className="milestones">
          {milestones.length === 0 && (
            <p className="empty-state">
              {overview.milestones.length === 0
                ? "Nenhum marco cadastrado ainda."
                : "Nenhum marco neste estado."}
            </p>
          )}
          {milestones.map((item) => {
            const tone = stateStyle[item.state] ?? "2";
            return (
              <div
                className={`milestone ${`milestone:${item.title}` === focusedItem ? "is-anchored" : ""}`}
                data-item={`milestone:${item.title}`}
                key={item.title}
              >
                <div className={`timeline-dot timeline-dot--${tone}`}><span /></div>
                <div className="milestone-date">{item.date}</div>
                <div className="milestone-title"><strong>{item.title}</strong>{item.owner && <span>{item.owner}</span>}</div>
                <StateBadge tone={tone}>{item.state}</StateBadge>
              </div>
            );
          })}
        </div>
      </article>
    </>
  );
}

function DocumentsView({ onAsk, overview, focusedItem }: { onAsk: () => void; overview: Overview; focusedItem?: string | null }) {
  const [type, setType] = useState<string | null>(null);
  const counts = countBy(overview.documents, (doc) => doc.type || null);
  const documents =
    type === null ? overview.documents : overview.documents.filter((doc) => doc.type === type);
  return (
    <>
      <ViewHero eyebrow="DOCUMENTOS" title="Documentos do projeto" subtitle="Planos, relatórios e materiais compartilhados." onAsk={onAsk} />
      {overview.documents.length === 0 && <p className="empty-state">Nenhum documento compartilhado ainda.</p>}
      {/* Só aparece quando há mais de um tipo: um filtro de uma opção não filtra. */}
      {Object.keys(counts).length > 1 && (
        <FilterChips
          label="Filtrar por tipo de documento"
          active={type}
          onPick={setType}
          options={[
            { value: null, label: "Todos", count: overview.documents.length },
            ...Object.keys(counts).map((value) => ({ value, label: value, count: counts[value] })),
          ]}
        />
      )}
      {overview.documents.length > 0 && documents.length === 0 && (
        <p className="empty-state">Nenhum documento deste tipo.</p>
      )}
      <section className="card-grid" aria-label="Lista de documentos">
        {documents.map((doc) => (
          <article
            className={`panel doc-card ${`document:${doc.title}` === focusedItem ? "is-anchored" : ""}`}
            data-item={`document:${doc.title}`}
            key={doc.title}
          >
            <div className="source-row">
              <span className="file-icon"><FileText size={17} /></span>
              <div>
                <strong>{doc.title}</strong>
                <span>{[doc.type, doc.updated, doc.author].filter(Boolean).join(" • ")}</span>
              </div>
              {/* Sem link não há o que baixar: o arquivo só vira storage próprio na Fase 4. */}
              {doc.link && (
                <a href={doc.link} target="_blank" rel="noreferrer" aria-label={`Abrir ${doc.title}`}>
                  <Download size={16} />
                </a>
              )}
            </div>
          </article>
        ))}
      </section>
    </>
  );
}

function MeetingsView({ onAsk, overview, focusedItem }: { onAsk: () => void; overview: Overview; focusedItem?: string | null }) {
  const [only, setOnly] = useState<string | null>(null);
  const withTranscript = overview.meetings.filter((meeting) => meeting.hasTranscript);
  const meetings = only === "transcript" ? withTranscript : overview.meetings;
  return (
    <>
      <ViewHero eyebrow="REUNIÕES" title="Reuniões do projeto" subtitle="Gravações e transcrições dos encontros." onAsk={onAsk} />
      <article className="panel">
        <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Encontros recentes <span>{meetings.length}</span></h2></div></div>
        {/* Transcrição é o que faz a reunião ser citável pelo assistente
            (ADR 0014), então é o corte que alguém realmente procura aqui. */}
        <FilterChips
          label="Filtrar reuniões"
          active={only}
          onPick={setOnly}
          options={[
            { value: null, label: "Todas", count: overview.meetings.length },
            { value: "transcript", label: "Com transcrição", count: withTranscript.length },
          ]}
        />
        <div className="source-list">
          {meetings.length === 0 && (
            <p className="empty-state">
              {overview.meetings.length === 0
                ? "Nenhuma reunião registrada ainda."
                : "Nenhuma reunião com transcrição ainda."}
            </p>
          )}
          {meetings.map((meeting) => (
            <div
              className={`source-row ${`meeting:${meeting.title}` === focusedItem ? "is-anchored" : ""}`}
              data-item={`meeting:${meeting.title}`}
              key={meeting.title}
            >
              <span className="file-icon"><Video size={17} /></span>
              <div>
                <strong>{meeting.title}</strong>
                <span>{[meeting.date, meeting.hasTranscript ? "Transcrição disponível" : null].filter(Boolean).join(" • ")}</span>
              </div>
              {meeting.recordingUrl && (
                <a href={meeting.recordingUrl} target="_blank" rel="noreferrer" aria-label={`Abrir gravação de ${meeting.title}`}>
                  <ArrowUpRight size={16} />
                </a>
              )}
              <StateBadge tone={meeting.status === "Realizada" ? "done" : "1"}>{meeting.status}</StateBadge>
            </div>
          ))}
        </div>
      </article>
    </>
  );
}

/**
 * A aba de Revisão (FDD 027, DAP r1 aprovado em 26/08/2026).
 *
 * A superfície que a F-025 §10 desenhou como **reservada**, agora viva: o card do
 * entregável elegível, os controles que agem, o histórico imutável e a distinção
 * entre a entrega de engenharia e o aceite do cliente.
 *
 * Aba própria (resolução do gate de 27/08/2026), com contador de "aguardando você"
 * na barra lateral e atalho a partir do card do entregável na jornada.
 */
function ReviewView({
  onAsk,
  overview,
  focusedItem,
  projectId,
}: {
  onAsk: () => void;
  overview: Overview;
  focusedItem?: string | null;
  projectId?: string | null;
}) {
  const items = reviewItems(overview);
  const readOnly = readOnlyReason(overview);
  return (
    <>
      <ViewHero
        eyebrow="REVISÃO"
        title="Revisão e aceite"
        subtitle="Aprove a entrega ou peça ajuste. Sua decisão fica registrada e vai para o time da Biahflow."
        onAsk={onAsk}
      />

      {/* Uma coluna, e não o `dashboard-grid` de duas: a escada é uma faixa larga —
          cinco selos numa linha — e o card de revisão respira. Numa metade de tela os
          selos quebram em duas linhas e o painel ao lado fica com um vazio do tamanho
          da lista. */}
      <section className="dashboard-grid dashboard-grid--single">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">A ESCADA DE ACEITE</p>
              <h2>Como uma entrega anda</h2>
            </div>
          </div>
          {/* Os cinco degraus, na ordem e com os tons do pacote aprovado. É legenda,
              não estado: nenhum card veste um degrau que o produto não emite. */}
          <div className="review-ladder">
            {ACCEPTANCE_LADDER.map((state, index) => (
              <span className="review-step" key={state}>
                {index > 0 && <span className="review-arrow" aria-hidden="true">→</span>}
                <AcceptancePill state={state} />
              </span>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">ENTREGAS</p>
              <h2>Para revisar <span>{items.length}</span></h2>
            </div>
          </div>
          {items.length === 0 ? (
            <p className="empty-state">
              Nada aguardando você. Quando houver uma entrega para revisar, ela aparece aqui.
            </p>
          ) : (
            <div className="review-list">
              {items.map((item) => (
                <ReviewCard
                  focusedItem={focusedItem}
                  item={item}
                  key={`${item.phaseName}/${item.deliverable.name}`}
                  projectId={projectId}
                  readOnly={readOnly}
                />
              ))}
            </div>
          )}
        </article>
      </section>
    </>
  );
}

/**
 * O card de uma entrega, e o único caminho de escrita desta aba.
 *
 * **A separação do meio é o invariante da fatia**, não decoração: "entrega de
 * engenharia concluída" é fato da operação, "seu aceite" é decisão do cliente, e
 * sem as duas metades lado a lado a tela sugeriria que uma é a outra — que é
 * exatamente o que a feature inteira nega.
 *
 * Os dois botões continuam disponíveis **depois** de uma decisão, e isso é o
 * desenho e não descuido: uma segunda decisão **acrescenta** e a primeira aparece
 * superada no histórico. Não há, e não pode haver, controle que edite uma decisão
 * — o `GRANT` de `portal_app` naquela tabela é `SELECT, INSERT`, então o banco
 * recusaria; um botão de editar seria funcionalidade errada, não funcionalidade
 * faltando.
 */
function ReviewCard({
  item,
  readOnly,
  projectId,
  focusedItem,
}: {
  item: ReviewItem;
  readOnly: ReadOnlyReason;
  projectId?: string | null;
  focusedItem?: string | null;
}) {
  const { phaseName, deliverable } = item;
  const [comment, setComment] = useState("");
  const [sending, startSending] = useTransition();
  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null);
  const router = useRouter();

  const decisions = deliverable.decisions;
  const state = acceptanceState(decisions);
  const current = decisions?.at(-1) ?? null;
  const externalRef = deliverable.externalRef;

  function decide(action: "accepted" | "changes_requested") {
    if (!externalRef || sending) return;
    startSending(async () => {
      const result = await recordDeliverableDecisionAction(externalRef, action, comment, projectId);
      setOutcome(result);
      if (!result.ok) return;
      setComment("");
      // O histórico vem do servidor no próximo render, pela razão do fio da
      // pendência: a linha gravada é a fonte, e espelhá-la aqui criaria uma
      // segunda versão do que foi decidido.
      router.refresh();
    });
  }

  return (
    <section
      aria-label={`Revisão de ${deliverable.name}`}
      className={`review-card panel ${`deliverable:${deliverable.name}` === focusedItem ? "is-anchored" : ""}`}
      data-item={`deliverable:${deliverable.name}`}
    >
      <div className="review-head">
        <div>
          <h3>{deliverable.name}</h3>
          <p className="review-phase">Fase: {phaseName}</p>
        </div>
        {state && <AcceptancePill state={state} />}
      </div>

      <div className="review-split">
        <div className="review-half review-half--engineering">
          <p className="review-lab">Entrega de engenharia</p>
          <p className="review-val">Concluída pela operação</p>
          <p className="review-note">o que a Biahflow entregou</p>
        </div>
        <div className="review-half">
          <p className="review-lab">Seu aceite</p>
          {/* O que a API disse, e nada além. Sem histórico carregado a tela não
              afirma "pendente" — ela não sabe. */}
          {decisions === null ? (
            <p className="review-val">Não consegui carregar</p>
          ) : current === null ? (
            <p className="review-val review-val--pending">Pendente — aguardando você</p>
          ) : (
            <p className="review-val">
              {ACCEPTANCE_LABEL[current.action]} · {current.decidedAt}
            </p>
          )}
          <p className="review-note">merge de engenharia ≠ seu aceite</p>
        </div>
      </div>

      {deliverable.link && (
        <>
          <p className="review-lab">Contexto e evidência</p>
          <div className="review-evidence">
            <a href={deliverable.link} target="_blank" rel="noreferrer">
              <FileText size={13} /> {deliverable.name} <ArrowUpRight size={13} />
            </a>
          </div>
        </>
      )}

      {/* Três recusas de escrita, e cada uma diz o motivo que sabe. Nenhuma delas
          inventa um estado: sem `external_ref` não há rota; com o projeto sem
          escrita a API responde 409, então o formulário sai antes de a pessoa
          digitar (ADR 0036/0037). */}
      {!externalRef ? (
        <p className="empty-note">
          Esta entrega ainda não tem identificador na origem, então não é possível registrar
          uma decisão sobre ela aqui.
        </p>
      ) : readOnly ? (
        <p className="empty-note">{readOnly.decisions}</p>
      ) : (
        <>
          <textarea
            aria-label="Comentário da decisão"
            className="review-field"
            maxLength={2000}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Comentário (opcional ao aprovar; esperado ao pedir ajuste)"
            value={comment}
          />
          <div className="review-actions">
            <Button disabled={sending} onClick={() => decide("accepted")} variant="primary">
              {sending ? "Enviando…" : "Aprovar entrega"}
            </Button>
            <Button disabled={sending} onClick={() => decide("changes_requested")} variant="secondary">
              {sending ? "Enviando…" : "Pedir ajuste"}
            </Button>
          </div>
        </>
      )}

      {outcome?.ok && (
        <p className="review-confirm" role="status">
          <Check size={16} /> Enviado ao time da Biahflow
        </p>
      )}
      {outcome && !outcome.ok && (
        <p className="auth-error" role="status">
          {outcome.reason === "read_only"
            ? readOnly?.decisions ??
              "Este projeto não recebe mais decisões. Nada foi enviado."
            : outcome.reason === "rate_limited"
              ? "Muitas ações em pouco tempo. Nada foi enviado — tente de novo em instantes."
              : "Não conseguimos registrar sua decisão. Nada foi enviado. Tente de novo."}
        </p>
      )}

      <DecisionLog decisions={decisions} />
    </section>
  );
}

/**
 * O histórico, e a supersessão visível (DAP F-027, decisão 2).
 *
 * Uma linha por decisão, da mais nova para a mais antiga. Uma segunda decisão
 * **acrescenta**, e a anterior aparece **superada** — riscada, com o rótulo — e
 * nunca apagada. É o reflexo na tela do `GRANT` só de `INSERT`: quem escreve não
 * reescreve.
 *
 * A ordem chega da API do mais antigo para o mais novo, que é o que torna a
 * supersessão legível sem coluna nenhuma; aqui ela é invertida porque a decisão em
 * vigor é a que interessa primeiro.
 */
function DecisionLog({ decisions }: { decisions: DeliverableDecision[] | null }) {
  if (decisions === null) {
    return (
      <p className="auth-error" role="status">
        Não consegui carregar o histórico de decisões agora. Nada foi perdido — tente de novo.
      </p>
    );
  }
  if (decisions.length === 0) {
    return <p className="empty-note">Nenhuma decisão registrada ainda.</p>;
  }
  return (
    <ul className="decision-log">
      {[...decisions].reverse().map((decision, index) => (
        <li className={index > 0 ? "is-superseded" : ""} key={decision.id}>
          <span className={`decision-dot decision-dot--${decision.action}`} />
          <div>
            <span className="decision-who">
              {decision.actorLabel} {decision.action === "accepted" ? "aprovou" : "pediu ajuste"}
            </span>
            {/* Do lado que decidiu, e vindo da **linha** e não do papel de hoje:
                quem deixa de ser interno não muda o lado de quem decidiu naquele
                dia. Mesmo argumento do `.comment-side--internal`. */}
            {decision.actorIsInternal && <span className="decision-internal">Biahflow</span>}
            <span className="decision-when"> · {decision.decidedAt}</span>
            {index > 0 && <span className="decision-superseded">superada</span>}
            {decision.comment && <div className="decision-comment">{decision.comment}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function DecisionsView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  const [only, setOnly] = useState<string | null>(null);
  const fromMeeting = overview.decisions.filter((decision) => decision.meetingTitle !== null);
  const decisions = only === "meeting" ? fromMeeting : overview.decisions;
  return (
    <>
      <ViewHero eyebrow="DECISÕES" title="Decisões do projeto" subtitle="O que foi decidido, por quem e por quê." onAsk={onAsk} />
      <article className="panel">
        <div className="panel-heading"><div><p className="eyebrow">REGISTRO</p><h2>Decisões registradas <span>{decisions.length}</span></h2></div></div>
        {/* A proveniência é o corte que alguém procura aqui: "isso saiu de qual
            reunião?" é a pergunta seguinte a "quem decidiu isso?". */}
        <FilterChips
          label="Filtrar decisões"
          active={only}
          onPick={setOnly}
          options={[
            { value: null, label: "Todas", count: overview.decisions.length },
            { value: "meeting", label: "De uma reunião", count: fromMeeting.length },
          ]}
        />
        <div className="source-list">
          {decisions.length === 0 && (
            <p className="empty-state">
              {overview.decisions.length === 0
                ? "Nenhuma decisão registrada ainda."
                : "Nenhuma decisão veio de uma reunião ainda."}
            </p>
          )}
          {decisions.map((decision) => (
            <div className="source-row" key={decision.title}>
              <span className="file-icon"><Scale size={17} /></span>
              <div>
                <strong>{decision.title}</strong>
                {/* O porquê é o que justifica esta aba existir: sem ele, uma decisão
                    é um título — e é justamente o que o cliente não consegue
                    reconstituir sozinho meses depois. */}
                {decision.rationale && <span>{decision.rationale}</span>}
                <span>{[decision.ownerLabel, decision.decidedOn, decision.meetingTitle].filter(Boolean).join(" • ") || "Sem autoria registrada"}</span>
              </div>
            </div>
          ))}
        </div>
      </article>
    </>
  );
}

/**
 * O filtro das abas longas (ADR 0029).
 *
 * Um componente para as quatro, e do lado do cliente: o dashboard já trouxe a
 * lista inteira, então perguntar ao servidor exigiria parâmetro,
 * `response_model` novo, esquema regenerado e caso negativo de permissão para
 * responder o que o navegador tem em mãos. No dia em que a lista não couber
 * numa resposta, a decisão muda — e aí é paginação, não filtro.
 *
 * `value === null` é "tudo", e é sempre a primeira opção: um filtro sem caminho
 * de volta esconde dado e parece lista vazia.
 */
function FilterChips({
  label,
  options,
  active,
  onPick,
}: {
  label: string;
  options: { value: string | null; label: string; count: number }[];
  active: string | null;
  onPick: (value: string | null) => void;
}) {
  return (
    <div className="filter-bar" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value ?? "todos"}
          className={`filter-chip ${option.value === active ? "filter-chip--on" : ""}`}
          aria-pressed={option.value === active}
          onClick={() => onPick(option.value)}
        >
          {option.label} <em>{option.count}</em>
        </button>
      ))}
    </div>
  );
}

/** Conta quantos itens caem em cada valor, para o chip dizer o tamanho do corte. */
function countBy<T>(items: T[], of: (item: T) => string | null): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const key = of(item);
    if (key !== null) counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

function PendingView({ onAsk, overview, onOpenTurn, focusedItem, projectId }: { onAsk: () => void; overview: Overview; onOpenTurn: (messageId: string, conversationId: string | null) => void; focusedItem?: string | null; projectId?: string | null }) {
  const [priority, setPriority] = useState<string | null>(null);
  const all = openPendings(overview);
  const counts = countBy(all, (item) => item.priority);
  const open = priority === null ? all : all.filter((item) => item.priority === priority);
  const resolved = overview.pendings.filter((item) => item.state === "resolved");
  return (
    <>
      <ViewHero eyebrow="PENDÊNCIAS" title="Pendências do projeto" subtitle="O que precisa de decisão ou ação para avançar." onAsk={onAsk} />
      <section className="dashboard-grid">
        <article className="panel pending-panel">
          <div className="panel-heading"><div><p className="eyebrow">ACOMPANHAMENTO</p><h2>Abertas <span>{open.length}</span></h2></div></div>
          <FilterChips
            label="Filtrar por prioridade"
            active={priority}
            onPick={setPriority}
            options={[
              { value: null, label: "Todas", count: all.length },
              { value: "high", label: "Alta", count: counts.high ?? 0 },
              { value: "medium", label: "Média", count: counts.medium ?? 0 },
              { value: "low", label: "Baixa", count: counts.low ?? 0 },
            ]}
          />
          <div className="pending-list">
            {open.length === 0 && (
              <p className="empty-state">
                {all.length === 0
                  ? "Nenhuma pendência aberta."
                  : "Nenhuma pendência aberta com esta prioridade."}
              </p>
            )}
            {open.map((item) => <PendingItem key={item.id || item.title} item={item} onOpenTurn={onOpenTurn} withThread readOnly={readOnlyReason(overview)} focusedItem={focusedItem} projectId={projectId} />)}
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Resolvidas <span>{resolved.length}</span></h2></div></div>
          <div className="pending-list">
            {resolved.length === 0 && <p className="empty-state">Nenhuma pendência resolvida ainda.</p>}
            {resolved.map((item) => <PendingItem key={item.id || item.title} item={item} withThread readOnly={readOnlyReason(overview)} focusedItem={focusedItem} projectId={projectId} />)}
          </div>
        </article>
      </section>
    </>
  );
}

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

/**
 * Dinheiro na moeda que a **premissa** declara, e não numa constante daqui
 * (ADR 0033).
 *
 * `AssumptionIn.currency` é gravável pela API desde a Fase 3 e a tela formatava
 * tudo com `currency: "BRL"` fixo — uma premissa em outra moeda não aparecia
 * incompleta, aparecia **errada**, com o símbolo de real na frente de um número
 * que não é em reais. Sem premissa não há moeda declarada, e aí o padrão do
 * produto (BRL) é o palpite honesto.
 *
 * Com centavos: uma premissa precisa poder ser conferida na mão, e R$ 150,50
 * arredondado para R$ 151 deixaria a conta do cliente sem fechar.
 */
function money(value: number, currency: string | null | undefined) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: currency || "BRL",
  }).format(value);
}
const EMPLOYEE_STATUS: Record<string, { label: string; cls: string }> = {
  active: { label: "Ativo", cls: "green" },
  paused: { label: "Pausado", cls: "" },
  building: { label: "Em construção", cls: "amber" },
};

function DigitalEmployees({ employees }: { employees: DigitalEmployeeView[] }) {
  if (employees.length === 0) return null;
  return (
    <section className="employees-panel" aria-label="Funcionários Digitais">
      <div className="employees-head"><div><p className="eyebrow">SEU TIME DIGITAL</p><h2>Funcionários Digitais</h2></div><span className="employees-count">{employees.length}</span></div>
      <div className="employees-grid">
        {employees.map((employee) => {
          const status = EMPLOYEE_STATUS[employee.status] ?? EMPLOYEE_STATUS.building;
          return (
            <article className="employee-card" key={employee.name}>
              <div className="employee-top"><span className="employee-avatar"><Bot size={18} /></span><div className="employee-id"><strong>{employee.name}</strong>{employee.area && <span>{employee.area}</span>}</div><span className={`employee-status employee-status--${status.cls || "muted"}`}>{status.label}</span></div>
              {employee.description && <p className="employee-desc">{employee.description}</p>}
              <div className="employee-metrics">
                {employee.kpiLabel && <div><span>{employee.kpiLabel}</span><strong>{employee.kpiValue}</strong></div>}
                {employee.hoursSavedMonth ? <div><span>Horas/mês</span><strong>{employee.hoursSavedMonth}h</strong></div> : null}
                {employee.roiMonth ? <div><span>ROI projetado/mês</span><strong>{BRL.format(employee.roiMonth)}</strong></div> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

/**
 * Rótulos de espécie de valor. Um valor que a origem inventar sai **cru**, no
 * padrão de `STATUS_LABELS` e `MEETING_STATUS_LABELS` em `page.tsx`: aqui o campo
 * é obrigatório e cair para `null` deixaria a entrada sem nome nenhum.
 */
const VALUE_TYPE_LABELS: Record<string, string> = {
  cost_saving: "Economia de custo",
  revenue: "Receita adicional",
  risk_reduction: "Redução de risco",
  productivity: "Ganho de produtividade",
  quality: "Ganho de qualidade",
};

/** Sufixos de unidade de KPI. Unidade desconhecida vira sufixo vazio — o número
 *  sai sozinho, que é honesto, em vez de ganhar uma unidade adivinhada. */
const UNIT_SUFFIX: Record<string, string> = { hours: "h", percent: "%", days: "d" };

/**
 * O número de uma medição, ou **a frase da lacuna** (issue #89, ADR 0085).
 *
 * As duas nulidades chegam distintas até aqui e saem como frases distintas:
 * `null` no lugar do objeto é "Sem baseline definida"/"Ainda não medido", e
 * `value: null` dentro de um objeto que existe é "Ainda não medido" com a janela
 * ao lado. **Nenhuma das duas vira "0"** — foi para isso que a API se deu ao
 * trabalho de manter as duas, e um `?? 0` aqui apagaria o trabalho inteiro.
 */
function measurementValue(reading: KpiMeasurementView | null, unit: string | null): string {
  if (!reading || reading.value === null) return "Ainda não medido";
  return formatMeasure(reading.value, unit);
}

function formatMeasure(value: number, unit: string | null): string {
  if (unit === "brl") return BRL.format(value);
  const suffix = unit ? UNIT_SUFFIX[unit] ?? "" : "";
  return `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}${suffix}`;
}

/** "jul/2026", ou "jul/2026 → em aberto" quando a origem ainda não fechou a janela. */
function measurementPeriod(reading: KpiMeasurementView | null): string {
  if (!reading) return "";
  const from = monthLabel(reading.periodStart);
  const to = reading.periodEnd ? monthLabel(reading.periodEnd) : null;
  if (to === null) return `${from} → janela em aberto`;
  return from === to ? from : `${from} → ${to}`;
}

function monthLabel(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("pt-BR", { month: "short", year: "numeric" });
}

/**
 * Um KPI com **Baseline e Outcome lado a lado**, na mesma unidade.
 *
 * É o critério (3) da issue #89, e a razão de os dois nunca aparecerem separados:
 * um Outcome sozinho é um número sem régua — "21,5h" não diz nada até estar ao
 * lado das 72h de onde se partiu. A API garante o par (invariante 11 do Language
 * Map) e esta tela desenha o par; quando a Baseline falta, o que aparece é a
 * frase da lacuna no lugar dela, nunca a comparação com zero.
 */
function KpiCard({ kpi, movedBy }: { kpi: KpiView; movedBy: string[] }) {
  const baselineMissing = kpi.baseline === null;
  return (
    <article className="kpi-card">
      <div className="kpi-head">
        <div>
          <strong>{kpi.name}</strong>
          {kpi.definition && <p className="kpi-definition">{kpi.definition}</p>}
        </div>
        {kpi.direction === "up" || kpi.direction === "down" ? (
          <span className="kpi-direction" title={kpi.direction === "down" ? "Quanto menor, melhor" : "Quanto maior, melhor"}>
            {kpi.direction === "down" ? "menor é melhor" : "maior é melhor"}
          </span>
        ) : null}
      </div>
      <div className="kpi-pair">
        <div className="kpi-measure">
          <span>Baseline</span>
          <strong className={baselineMissing ? "kpi-gap" : undefined}>
            {baselineMissing ? "Sem baseline definida" : measurementValue(kpi.baseline, kpi.unit)}
          </strong>
          <small>{measurementPeriod(kpi.baseline)}</small>
        </div>
        <div className="kpi-measure">
          <span>Outcome</span>
          <strong className={kpi.outcome === null || kpi.outcome.value === null ? "kpi-gap" : undefined}>
            {measurementValue(kpi.outcome, kpi.unit)}
          </strong>
          <small>{measurementPeriod(kpi.outcome)}</small>
        </div>
        <div className="kpi-measure">
          <span>Meta</span>
          {/* `null` é "ninguém definiu meta" e sai como travessão — não como zero,
              que faria a tela afirmar uma meta que ninguém combinou. */}
          <strong className={kpi.target === null ? "kpi-gap" : undefined}>
            {kpi.target === null ? "Sem meta definida" : formatMeasure(kpi.target, kpi.unit)}
          </strong>
          <small>{kpi.cadence ? `Medido ${CADENCE_LABELS[kpi.cadence] ?? kpi.cadence}` : ""}</small>
        </div>
      </div>
      <dl className="kpi-meta">
        {kpi.formula && <div><dt>Como é calculado</dt><dd>{kpi.formula}</dd></div>}
        {kpi.dataSource && <div><dt>Fonte do dado</dt><dd>{kpi.dataSource}</dd></div>}
        {kpi.monitoring.length > 0 && (
          <div>
            <dt>Acompanhamento</dt>
            <dd>
              {kpi.monitoring.length === 1 ? "1 leitura" : `${kpi.monitoring.length} leituras`}
              {" · última em "}
              {measurementPeriod(kpi.monitoring[kpi.monitoring.length - 1])}
            </dd>
          </div>
        )}
        {movedBy.length > 0 && <div><dt>Movido por</dt><dd>{movedBy.join(", ")}</dd></div>}
      </dl>
    </article>
  );
}

const CADENCE_LABELS: Record<string, string> = {
  monthly: "mensalmente",
  weekly: "semanalmente",
  quarterly: "trimestralmente",
  daily: "diariamente",
};

function KpiPanel({ kpis, employees }: { kpis: KpiView[]; employees: DigitalEmployeeView[] }) {
  if (kpis.length === 0) return null;
  return (
    <section className="panel" aria-label="Indicadores do projeto">
      <div className="panel-heading">
        <div><p className="eyebrow">O QUE ESTAMOS MEDINDO</p><h2>KPIs <span>{kpis.length}</span></h2></div>
      </div>
      <div className="kpi-grid">
        {kpis.map((kpi) => (
          <KpiCard
            key={kpi.id}
            kpi={kpi}
            // O casamento é pelo id **da origem**, o mesmo que os dois lados
            // publicam: é o que dispensa uma tabela de tradução no navegador.
            movedBy={employees.filter((employee) => employee.kpiIds.includes(kpi.id)).map((employee) => employee.name)}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * O **Value Ledger** do mandato (Language Map §2, ADR 0085) — o que substituiu a
 * manchete de projeção na visão geral.
 *
 * A manchete antiga imprimia um percentual projetado pela origem como primeiro
 * número que o cliente lia, sem nada por trás dele que ele pudesse conferir. Aqui
 * cada linha carrega período, espécie, quantia e **método de atribuição**, que é
 * o invariante 12 — e, quando o KPI de origem está nesta resposta, o par
 * Baseline→Outcome que sustenta a conta.
 *
 * **Não casar o KPI é caso normal, e não erro**: a entrada é do Engagement e o
 * indicador pode viver num projeto irmão que este cliente não alcança. A linha
 * aparece igual, sem o vínculo.
 */
function ValueLedgerPanel({ entries, kpis }: { entries: ValueLedgerEntryView[]; kpis: KpiView[] }) {
  if (entries.length === 0) return null;
  const byId = new Map(kpis.map((kpi) => [kpi.id, kpi]));
  return (
    <section className="panel" aria-label="Value Ledger">
      <div className="panel-heading">
        <div><p className="eyebrow">VALOR GERADO</p><h2>Value Ledger <span>{entries.length}</span></h2></div>
      </div>
      <div className="ledger-list">
        {entries.map((entry) => {
          const source = entry.kpiId === null ? undefined : byId.get(entry.kpiId);
          return (
            <article className="ledger-entry" key={entry.id}>
              <div className="ledger-amount">
                <strong>{BRL.format(entry.amount)}</strong>
                <span>{VALUE_TYPE_LABELS[entry.valueType] ?? entry.valueType}</span>
              </div>
              <div className="ledger-body">
                <p className="ledger-period">
                  {measurementPeriod({ value: null, periodStart: entry.periodStart, periodEnd: entry.periodEnd, measuredAt: null, confidence: null })}
                  {entry.quantity !== null && <span> · {entry.quantity.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} {source?.unit ? UNIT_SUFFIX[source.unit] ?? source.unit : "un."}</span>}
                </p>
                <p className="ledger-method">{entry.attributionMethod}</p>
                {source ? (
                  <p className="ledger-source">
                    {source.name}: {measurementValue(source.baseline, source.unit)} → {measurementValue(source.outcome, source.unit)}
                  </p>
                ) : (
                  // Sem inventar rótulo para o indicador que não está aqui: dizer
                  // "sem KPI" seria falso, e nomear um id cru não explicaria nada.
                  <p className="ledger-source ledger-source--absent">Indicador de origem em outro projeto deste Engagement</p>
                )}
                {entry.outcomeMeasuredAt && (
                  <p className="ledger-measured">Outcome medido em {new Date(entry.outcomeMeasuredAt).toLocaleDateString("pt-BR", { dateStyle: "long" })}</p>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

/** O total do razão para a manchete, e a frase quando não há razão nenhum. */
function valueLedgerTotal(entries: ValueLedgerEntryView[]): { value: string; note: string; positive: boolean } {
  if (entries.length === 0) {
    // Zero entradas **não é R$ 0**: é "ainda não há valor apurado no mandato". A
    // manchete diz isso, e não um número que ninguém sustentaria.
    return { value: "—", note: "Nenhum valor registrado ainda", positive: false };
  }
  const total = entries.reduce((sum, entry) => sum + entry.amount, 0);
  const latest = entries.reduce((newest, entry) => (entry.periodEnd > newest ? entry.periodEnd : newest), entries[0].periodEnd);
  return {
    value: BRL.format(total),
    note: `${entries.length} ${entries.length === 1 ? "entrada" : "entradas"} · até ${monthLabel(latest)}`,
    positive: total >= 0,
  };
}

function ResultsView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  const projected = roiValue(overview.roi);
  const results = overview.results;
  const measured = overview.measured;
  const period = measured ? `Últimos ${measured.periodDays} dias` : "Sem período apurado";
  const hasEvents = (measured?.eventsTotal ?? 0) > 0;

  // Cada card diz de onde veio: o projetado é a promessa do Biahflow, o apurado
  // é o que os eventos dos agentes sustentam. Onde falta base vai "—" com o
  // motivo, nunca um número de demonstração (ADR 0013).
  const cards = [
    {
      icon: TrendingUp, tone: "", label: "ROI projetado",
      value: projected.value, note: projected.note, positive: projected.positive,
    },
    {
      icon: TrendingUp, tone: "green", label: "ROI apurado",
      value: percent(measured?.roiRatio ?? null, 0),
      note: measured?.roiRatio != null ? `${BRL.format(measured.net)} líquidos · ${period}` : "Sem investimento configurado",
      positive: (measured?.roiRatio ?? 0) >= 0 && measured?.roiRatio != null,
    },
    {
      icon: Clock3, tone: "purple", label: "Horas economizadas",
      value: hasEvents ? `${measured!.hoursSaved.toLocaleString("pt-BR")}h` : "—",
      note: hasEvents ? `Reportadas pelos agentes · ${period}` : "Nenhum evento no período",
    },
    {
      icon: TrendingUp, tone: "", label: "Economia apurada",
      value: hasEvents ? BRL.format(measured!.benefit) : "—",
      note: hasEvents ? "Horas ao valor-hora vigente + custos evitados" : "Sem evento para converter",
    },
    {
      icon: Zap, tone: "", label: "Transações automatizadas",
      value: hasEvents ? compact(measured!.eventsTotal) : "—",
      note: hasEvents ? period : "Nenhum evento no período",
    },
    {
      icon: Target, tone: "green", label: "Precisão do fluxo",
      value: percent(measured?.accuracy ?? null),
      note: hasEvents ? `${measured!.failed} execuç${measured!.failed === 1 ? "ão" : "ões"} com falha` : "Sem execuções apuradas",
      positive: (measured?.accuracy ?? 0) >= 0.95,
    },
    {
      icon: Check, tone: "purple", label: "Exceções tratadas",
      value: measured ? measured.exceptionsHandled.toLocaleString("pt-BR") : "—",
      note: measured?.unattendedShare != null
        ? `${percent(measured.unattendedShare, 0)} sem intervenção humana`
        : "Nenhuma exceção no período",
    },
  ];

  return (
    <>
      <ViewHero eyebrow="RESULTADOS" title="Resultados do projeto" subtitle="Impacto e indicadores da automação." onAsk={onAsk} />
      <DigitalEmployees employees={overview.digitalEmployees} />
      {results && (
        <section className="results-strip" aria-label="Andamento do projeto">
          <div><span>Conclusão</span><strong>{overview.completion}%</strong></div>
          <div><span>Marcos concluídos</span><strong>{results.milestonesDone}/{results.milestonesTotal}</strong></div>
          <div><span>Atrasados</span><strong>{results.overdue}</strong></div>
          <div><span>No prazo</span><strong>{results.onTimePercent}%</strong></div>
        </section>
      )}
      <section className="results-grid" aria-label="Indicadores de resultado">
        {cards.map(({ icon: Icon, tone, label, value, note, positive }) => (
          <article className="metric-card" key={label}>
            <div className={`metric-icon ${tone === "green" ? "metric-icon--green" : tone === "purple" ? "metric-icon--purple" : ""}`}><Icon size={19} /></div>
            <p>{label}</p>
            <h3>{value}</h3>
            <span className={positive ? "positive" : ""}>{note}</span>
          </article>
        ))}
      </section>
      <MeasurementBasis measured={measured} />
      <section className="section-gap">
        <article className="insight-card">
          <div className="insight-orb"><Bot size={24} /></div>
          <p className="eyebrow">INSIGHT DA IA</p>
          <h2>Pergunte sobre qualquer número desta tela.</h2>
          <p>Os indicadores vêm do andamento real do projeto. A IA responde citando a fonte — e registra uma pendência quando não houver evidência.</p>
          <button onClick={onAsk}>Perguntar sobre os números <ArrowUpRight size={15} /></button>
        </article>
      </section>
    </>
  );
}

const GAP_LABELS: Record<string, string> = {
  no_assumption: "Ainda não há valor-hora nem investimento configurados, então as horas dos agentes não viram dinheiro.",
  events_outside_assumption: "Alguns eventos do período aconteceram antes da premissa vigente e entram no volume, mas não no valor.",
  no_investment: "O investimento configurado é zero, e sem ele não há ROI apurado a calcular.",
  no_events: "Nenhum agente publicou evento neste período.",
};

/**
 * Como cada número foi calculado — a outra metade do aceite da fase.
 *
 * Um indicador sem premissa visível é indistinguível de um chute, e foi
 * exatamente por isso que os três cards de demonstração puderam ficar tanto
 * tempo na tela sem ninguém notar.
 */
function MeasurementBasis({ measured }: { measured: MeasuredResults | null }) {
  if (!measured) return null;
  const { assumption, gaps } = measured;

  return (
    <section className="section-gap">
      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">COMO CALCULAMOS</p>
            <h2>A premissa por trás dos números</h2>
          </div>
        </div>
        <div className="field-list">
          <div className="field-row">
            <span className="field-label">Período</span>
            <span className="field-value">
              {measured.periodFrom} a {measured.periodTo} · {measured.periodDays} dias
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Eventos considerados</span>
            <span className="field-value">
              {measured.eventsTotal.toLocaleString("pt-BR")}
              {measured.eventsWithoutAssumption > 0 &&
                ` · ${measured.eventsWithoutAssumption.toLocaleString("pt-BR")} sem premissa vigente`}
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Economia apurada</span>
            <span className="field-value">
              {money(measured.laborSavings, assumption?.currency)} em horas
              {" + "}
              {money(measured.avoidedCost, assumption?.currency)} em custos evitados
            </span>
          </div>
          {assumption && (
            <>
              <div className="field-row">
                <span className="field-label">Valor-hora vigente</span>
                <span className="field-value">
                  {money(assumption.hourlyRate, assumption.currency)} · desde {assumption.effectiveFrom}
                </span>
              </div>
              <div className="field-row">
                <span className="field-label">Investimento mensal</span>
                <span className="field-value">
                  {money(assumption.monthlyInvestment, assumption.currency)} · rateado por{" "}
                  {measured.basis.daysPerMonth} dias/mês, {assumption.daysInPeriod} dia
                  {assumption.daysInPeriod === 1 ? "" : "s"} neste período
                </span>
              </div>
              {assumption.note && (
                <div className="field-row">
                  <span className="field-label">Observação</span>
                  <span className="field-value">{assumption.note}</span>
                </div>
              )}
            </>
          )}
          <div className="field-row">
            <span className="field-label">Fórmula do ROI apurado</span>
            {/* Vem da API. Até a ADR 0033 esta linha era um literal que nem
                casava com a fórmula que o servidor devolve — a explicação do
                número estava fabricada na única tela feita para conferi-lo. */}
            <span className="field-value">{measured.basis.formula}</span>
          </div>
        </div>
        {gaps.length > 0 && (
          <ul className="empty-note">
            {gaps.map((gap) => (
              <li key={gap}>{GAP_LABELS[gap] ?? gap}</li>
            ))}
          </ul>
        )}
      </article>
    </section>
  );
}

/**
 * Os três estados epistêmicos da §4 do Language Map (D6), como o cliente os lê.
 *
 * `unknown` **não** é "sem informação": é a pergunta que o Discovery abriu e ainda
 * não fechou, e ela aparece na tela de propósito. Um levantamento que só mostrasse
 * o que ficou sabido esconderia do cliente o que ainda não se sabe sobre o próprio
 * processo — que é a regra 3 do `AGENTS.md` na voz do levantamento.
 */
const EPISTEMIC_LABEL: Record<string, string> = {
  fact: "Fato",
  hypothesis: "Hipótese",
  unknown: "Pergunta em aberto",
};

/**
 * E as três **com ícone**, nunca só com cor.
 *
 * É o critério que o `StatePill` já carrega desde a Issue #46, e aqui ele guarda
 * uma coisa específica: a regra 1 da §3 diz que uma hipótese aparece rotulada como
 * hipótese ou não aparece — nunca como fato. Distinguir as duas só pelo tom faria a
 * regra depender de quem enxerga a diferença entre dois cinzas.
 */
const EPISTEMIC_TONE: Record<string, StatePillVariant> = {
  fact: "success",
  hypothesis: "warning",
  unknown: "info",
};

/** As cinco dimensões do Opportunity Score (Language Map D5). Uma chave que a API
 *  não conheça sai crua — a lista branca da ingestão já a teria barrado. */
const DIMENSION_LABELS: Record<string, string> = {
  impact: "Impacto",
  evidence_strength: "Força da evidência",
  feasibility: "Viabilidade",
  time_to_value: "Tempo até o valor",
  economics: "Economia",
};

const IMPACT_TYPE_LABELS: Record<string, string> = {
  cost: "Custo",
  time: "Tempo",
  quality: "Qualidade",
  risk: "Risco",
  volume: "Volume",
};

/** "12 de agosto de 2026", ou vazio quando não há data para escrever. */
function longDate(iso: string | null): string {
  if (!iso) return "";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("pt-BR", { dateStyle: "long" });
}

/**
 * O tamanho da dor, **sem símbolo de moeda** (ADR 0086).
 *
 * `impact_estimate` vem sem unidade declarada e `impact_type` diz coisas que não são
 * dinheiro — `time`, `quality`, `volume`. Formatar tudo como BRL repetiria o defeito
 * que a ADR 0033 achou no `money()` do outro lado: um número que não é em reais
 * aparecendo com "R$" na frente não fica incompleto, fica **errado**.
 *
 * `null` é "não quantificado" e vira frase, nunca zero — a mesma regra da lacuna de
 * medição do KPI (ADR 0085).
 */
function impactLabel(pain: PainPointView): string {
  if (pain.impactEstimate === null) return "Impacto não quantificado";
  const size = pain.impactEstimate.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  const kind = pain.impactType ? IMPACT_TYPE_LABELS[pain.impactType] ?? pain.impactType : null;
  return kind ? `${kind}: ${size}` : size;
}

/**
 * A aba **Discovery** — o AS-IS, os achados, as dores e o backlog de melhoria
 * (Language Map v1.1 §2, ADR 0086).
 *
 * **As quatro seções aparecem sempre, inclusive vazias, e isso é desenho.** Vazio é
 * o estado normal enquanto o Pulse não tiver tela de publicar: nada atravessa sem
 * publicação humana, e hoje a publicação é chamada de API. Uma aba que se escondesse
 * quando não há dado faria o cliente concluir que o produto não tem a superfície; as
 * quatro frases de ausência dizem o que **vai** aparecer ali, e nenhuma delas se
 * parece com erro de carregamento — porque não é um.
 *
 * A ordem do backlog não é decidida aqui: a API já entrega por Opportunity Score
 * decrescente com os não avaliados no fim. Repetir o critério deste lado seria a
 * mesma regra em dois lugares podendo divergir — o argumento do `tabs.py`.
 *
 * **O `data-item` das quatro listas é `<namespace>:<id da origem>`** (ADR 0087), e
 * não o rótulo como nas outras abas: é o id que a API publica como identidade e que
 * estas listas já usam como chave de React, e o `Finding` não tem título para servir
 * de rótulo. `test_item_anchor.py` cobra que os quatro namespaces sejam os do Python.
 */
function DiscoveryView({
  onAsk,
  overview,
  focusedItem,
}: {
  onAsk: () => void;
  overview: Overview;
  focusedItem?: string | null;
}) {
  const { processes, findings, painPoints, improvementOpportunities } = overview;
  const nothingPublished =
    processes.length === 0 &&
    findings.length === 0 &&
    painPoints.length === 0 &&
    improvementOpportunities.length === 0;

  // O casamento entre as quatro listas é pelo id **da origem**, o mesmo que a API
  // publica nas duas pontas — é o que dispensa uma tabela de tradução aqui.
  const processById = new Map(processes.map((item) => [item.id, item]));
  const stepById = new Map(
    processes.flatMap((item) => item.steps.map((step) => [step.id, step] as const)),
  );
  const findingById = new Map(findings.map((finding) => [finding.id, finding]));
  const painById = new Map(painPoints.map((pain) => [pain.id, pain]));

  return (
    <>
      <ViewHero
        eyebrow="DISCOVERY"
        title="O que descobrimos sobre o seu trabalho"
        subtitle={
          nothingPublished
            ? "O time publica cada processo, achado e oportunidade depois de revisar. Enquanto isso não acontece, esta aba fica vazia — e isso é esperado."
            : "O mapa do processo como ele é hoje, os achados que sustentam cada dor e o backlog de melhoria priorizado."
        }
        onAsk={onAsk}
      />

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">COMO O TRABALHO ACONTECE HOJE</p>
            <h2>Process <span>{processes.length}</span></h2>
          </div>
        </div>
        {processes.length === 0 && <p className="empty-state">Nenhum processo mapeado ainda.</p>}
        {processes.map((item) => (
          <section
            className={`discovery-process ${`process:${item.id}` === focusedItem ? "is-anchored" : ""}`}
            data-item={`process:${item.id}`}
            key={item.id}
          >
            <div className="discovery-process-head">
              <strong>{item.name}</strong>
              {item.updatedAt && <span>Atualizado na origem em {longDate(item.updatedAt)}</span>}
            </div>
            {item.steps.length === 0 ? (
              <p className="empty-state">Nenhuma etapa detalhada neste processo.</p>
            ) : (
              <div className="discovery-table">
                <table>
                  <thead>
                    {/* As seis colunas são o formulário P-S-D-T-E-R da sessão de
                        Discovery, e os nomes vêm de lá — ver `ProcessStepView`. */}
                    <tr>
                      <th>Etapa</th>
                      <th>Pessoas</th>
                      <th>Sistema</th>
                      <th>Dados</th>
                      <th>Tempo</th>
                      <th>Erro</th>
                      <th>Retrabalho</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.steps.map((step) => (
                      <tr key={step.id}>
                        <th scope="row">{step.name}</th>
                        {/* Célula vazia é travessão: a origem não respondeu aquela
                            pergunta do formulário, e inventar texto seria pior. */}
                        <td>{step.pessoas ?? "—"}</td>
                        <td>{step.sistema ?? "—"}</td>
                        <td>{step.dados ?? "—"}</td>
                        <td>{step.tempo ?? "—"}</td>
                        <td>{step.erro ?? "—"}</td>
                        <td>{step.retrabalho ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}
      </article>

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">O QUE ENCONTRAMOS</p>
            <h2>Findings <span>{findings.length}</span></h2>
          </div>
        </div>
        {findings.length === 0 && <p className="empty-state">Nenhum achado publicado ainda.</p>}
        <div className="discovery-list">
          {findings.map((finding) => {
            const origin = [
              finding.processId === null ? null : processById.get(finding.processId)?.name,
              finding.stepId === null ? null : stepById.get(finding.stepId)?.name,
            ].filter(Boolean);
            return (
              <article
                className={`discovery-finding ${`finding:${finding.id}` === focusedItem ? "is-anchored" : ""}`}
                data-item={`finding:${finding.id}`}
                key={finding.id}
              >
                <div className="discovery-finding-head">
                  <StatePill variant={EPISTEMIC_TONE[finding.epistemicStatus] ?? "info"}>
                    {EPISTEMIC_LABEL[finding.epistemicStatus] ?? finding.epistemicStatus}
                  </StatePill>
                  {origin.length > 0 && <span className="discovery-origin">{origin.join(" • ")}</span>}
                </div>
                <p className="discovery-statement">{finding.statement}</p>
                {finding.evidences.length > 0 ? (
                  <ul className="discovery-evidences">
                    {finding.evidences.map((evidence) => (
                      <li key={evidence.id}>
                        <span>{evidence.kind}</span>
                        {evidence.reference ?? "Sem referência registrada"}
                        {evidence.capturedAt && ` • ${longDate(evidence.capturedAt)}`}
                      </li>
                    ))}
                  </ul>
                ) : (
                  // Sem evidência a frase diz **o que isso significa**, e não some:
                  // é a lacuna declarada, que é o que a §3 pede que apareça.
                  <p className="discovery-gap">
                    {finding.epistemicStatus === "unknown"
                      ? "Pergunta em aberto: ainda não há evidência que a responda."
                      : "Sem evidência publicada — por isso não está registrado como fato."}
                  </p>
                )}
                {finding.confidence !== null && (
                  <p className="discovery-confidence">Confiança declarada na origem: {finding.confidence}</p>
                )}
              </article>
            );
          })}
        </div>
      </article>

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">O QUE TRAVA O TRABALHO</p>
            <h2>Pain Points <span>{painPoints.length}</span></h2>
          </div>
        </div>
        {painPoints.length === 0 && <p className="empty-state">Nenhuma dor confirmada ainda.</p>}
        <div className="discovery-list">
          {painPoints.map((pain) => (
            <article
              className={`discovery-pain ${`pain_point:${pain.id}` === focusedItem ? "is-anchored" : ""}`}
              data-item={`pain_point:${pain.id}`}
              key={pain.id}
            >
              <div className="discovery-pain-head">
                <strong>{pain.title}</strong>
                <span className={pain.impactEstimate === null ? "discovery-gap" : "discovery-impact"}>
                  {impactLabel(pain)}
                </span>
              </div>
              {pain.description && <p className="discovery-statement">{pain.description}</p>}
              {pain.findingIds.length > 0 && (
                <ul className="discovery-evidences">
                  {pain.findingIds.map((id) => (
                    <li key={id}>
                      <span>Achado</span>
                      {findingById.get(id)?.statement ?? "Achado não publicado nesta lista"}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      </article>

      <article className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">O QUE PODEMOS MELHORAR</p>
            <h2>Improvement Opportunity Backlog <span>{improvementOpportunities.length}</span></h2>
          </div>
        </div>
        {improvementOpportunities.length === 0 && (
          <p className="empty-state">Nenhuma oportunidade de melhoria publicada ainda.</p>
        )}
        <div className="discovery-list">
          {improvementOpportunities.map((opportunity) => (
            <article
              className={`discovery-opportunity ${`improvement_opportunity:${opportunity.id}` === focusedItem ? "is-anchored" : ""}`}
              data-item={`improvement_opportunity:${opportunity.id}`}
              key={opportunity.id}
            >
              <div className="discovery-opportunity-head">
                <strong>{opportunity.title}</strong>
                {opportunity.priorityAssessment ? (
                  <span className="discovery-score">
                    <strong>{opportunity.priorityAssessment.score}</strong>
                    <span>Opportunity Score</span>
                  </span>
                ) : (
                  // Sem nota **não é nota zero**: quem ainda não foi avaliado vai
                  // para o fim da lista com a frase, e não com um número.
                  <span className="discovery-gap">Ainda não priorizada</span>
                )}
              </div>
              {opportunity.desiredChange && <p className="discovery-statement">{opportunity.desiredChange}</p>}
              {opportunity.impactHypothesis && (
                <p className="discovery-hypothesis">
                  <span>Impacto esperado</span> {opportunity.impactHypothesis}
                </p>
              )}
              {opportunity.priorityAssessment &&
                Object.keys(opportunity.priorityAssessment.dimensions).length > 0 && (
                  <dl className="discovery-dimensions">
                    {Object.entries(opportunity.priorityAssessment.dimensions).map(([key, value]) => (
                      <div key={key}>
                        <dt>{DIMENSION_LABELS[key] ?? key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              {opportunity.painPointIds.length > 0 && (
                <ul className="discovery-evidences">
                  {opportunity.painPointIds.map((id) => (
                    <li key={id}>
                      <span>Dor</span>
                      {painById.get(id)?.title ?? "Dor não publicada nesta lista"}
                    </li>
                  ))}
                </ul>
              )}
              {opportunity.solutionHypotheses.length > 0 && (
                <div className="discovery-solutions">
                  {/* "Hipótese" é a palavra do contrato (§2), e o subtítulo diz por
                      quê: o que confirma é o PROVE, não esta tela. */}
                  <p className="eyebrow">HIPÓTESES DE SOLUÇÃO</p>
                  <p className="discovery-gap">Ainda são hipóteses: quem confirma é o PROVE.</p>
                  {opportunity.solutionHypotheses.map((hypothesis) => (
                    <div className="discovery-solution" key={hypothesis.id}>
                      <strong>{hypothesis.statement}</strong>
                      {hypothesis.intervention && <span>{hypothesis.intervention}</span>}
                      {hypothesis.expectedEffect && <span>Efeito esperado: {hypothesis.expectedEffect}</span>}
                    </div>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      </article>
    </>
  );
}

function ProfileView({ onAsk, user, projectName }: { onAsk: () => void; user: PortalUser; projectName: string }) {
  // Só o que a API conhece: telefone não existe no modelo e deixou de ser exibido.
  const fields = [
    { label: "Nome", value: user.name },
    { label: "E-mail", value: user.email },
    { label: "Função", value: user.role },
    { label: "Organização", value: user.org },
    { label: "Projeto atual", value: projectName },
  ];
  return (
    <>
      <ViewHero eyebrow="CONTA" title="Meu perfil" subtitle="Seus dados de acesso ao portal." onAsk={onAsk} />
      <article className="panel">
        {/* Não há "Editar", e não é feature faltando: nome e e-mail vivem no
            Keycloak (ADR 0010/0011), e o GRANT de coluna de `portal_app` em
            `user` é (external_subject, notify_by_email, updated_at) — o banco
            recusa esta edição por desenho. Um botão aqui prometeria o que a
            rota não tem e a policy não deixaria passar. */}
        <div className="panel-heading"><div><p className="eyebrow">DADOS PESSOAIS</p><h2>Informações da conta</h2></div></div>
        <div className="profile-head">
          <span className="avatar avatar--lg">{user.initials}</span>
          <div><strong>{user.name}</strong><span>{user.role} <b>•</b> {user.org}</span></div>
        </div>
        <div className="field-list">
          {fields.map((field) => (
            <div className="field-row" key={field.label}><span className="field-label">{field.label}</span><span className="field-value">{field.value}</span></div>
          ))}
        </div>
        <p className="panel-note">
          Nome e e-mail vêm da sua conta corporativa e mudam lá, não aqui. Função e
          projeto vêm do seu vínculo — fale com quem administra o portal.
        </p>
      </article>
    </>
  );
}

/**
 * A central: o histórico completo do projeto atual, do mais recente ao mais antigo.
 *
 * Perdeu o `target="_blank"` na ADR 0057, e isso é a fatia e não um efeito
 * colateral: o link agora navega **dentro** do portal, na mesma aba, como qualquer
 * outra troca de aba faz desde a Fase 2. Abrir uma segunda aba para chegar a uma
 * lista que já está aberta era o resto de quando o link era só uma URL a copiar. O
 * `<a href>` continua ali inteiro para quem quiser a aba nova — `Ctrl`/`Cmd` e o
 * botão do meio recaem nele, e é por isso que a linha continua sendo uma âncora e
 * não um controle sem href.
 */
function NotificationsView({
  onAsk,
  notifications,
  currentProjectId,
  onNavigate,
}: {
  onAsk: () => void;
  notifications: NotificationCenter;
  currentProjectId: string | null;
  onNavigate: (tab: string, item?: string) => void;
}) {
  return (
    <>
      <ViewHero
        eyebrow="NOTIFICAÇÕES"
        title="Central de notificações"
        subtitle="Tudo o que mudou no projeto, do mais recente ao mais antigo."
        onAsk={onAsk}
      />
      <section className="dashboard-grid dashboard-grid--single">
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Avisos do projeto</h2></div></div>
          {notifications.items.length === 0 ? (
            <p className="empty-note">
              Nada por aqui ainda. Cada marco concluído, documento novo ou pendência
              aberta no projeto aparece nesta lista.
            </p>
          ) : (
            <div className="notification-list">
              {notifications.items.map((item) => {
                const Icon = notificationIcon[item.kind] ?? Bell;
                const body = (
                  <>
                    <span className="notification-icon"><Icon size={16} /></span>
                    <div>
                      <strong>{item.title}</strong>
                      {item.detail && <span>{item.detail}</span>}
                    </div>
                    <small>{item.age}</small>
                  </>
                );
                const className = `notification-row ${item.read ? "" : "notification-row--unread"}`;
                return (
                  <NotificationLink
                    className={className}
                    currentProjectId={currentProjectId}
                    key={item.id}
                    notification={item}
                    onNavigate={onNavigate}
                  >
                    {body}
                  </NotificationLink>
                );
              })}
            </div>
          )}
        </article>
      </section>
    </>
  );
}

function SettingsView({ onAsk, user }: { onAsk: () => void; user: PortalUser }) {
  // Duas preferências, e as duas são reais. As que existiam aqui antes eram
  // decorativas — um interruptor que não liga nada é pior do que não ter.
  const [emailOn, setEmailOn] = useState(user.notifyByEmail);
  const [whatsappOn, setWhatsappOn] = useState(user.notifyByWhatsapp);
  const [phoneHint, setPhoneHint] = useState(user.phoneHint);
  const [phone, setPhone] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  function toggleEmail() {
    const next = !emailOn;
    setEmailOn(next);
    startSaving(async () => {
      const ok = await setEmailPreferenceAction(next);
      if (!ok) setEmailOn(!next);
    });
  }

  // A tela adota o que o servidor **guardou**, e não o que ela mandou: o telefone
  // é normalizado do outro lado e o `phoneHint` é derivado de lá. Calcular o hint
  // aqui reimplementaria `_phone_hint`, e as duas divergiriam no primeiro formato
  // que alguém colasse.
  function adopt(saved: ChannelPreferences) {
    setWhatsappOn(saved.notifyByWhatsapp);
    setPhoneHint(saved.phoneHint);
  }

  function toggleWhatsapp() {
    const next = !whatsappOn;
    setWhatsappOn(next);
    setPhoneError(null);
    startSaving(async () => {
      const saved = await setWhatsappPreferenceAction(next);
      // A API recusa ligar o canal sem número (422). Voltar o interruptor e dizer
      // o motivo é o oposto de deixá-lo ligado sobre coisa nenhuma.
      if (!saved) {
        setWhatsappOn(!next);
        if (next) setPhoneError("Cadastre um telefone antes de ligar o canal.");
        return;
      }
      adopt(saved);
    });
  }

  function savePhone() {
    const value = phone.trim();
    setPhoneError(null);
    startSaving(async () => {
      const saved = await setPhoneAction(value);
      if (!saved) {
        setPhoneError("Número inválido. Use DDI, DDD e o número — 10 a 15 dígitos.");
        return;
      }
      adopt(saved);
      setPhone("");
    });
  }

  return (
    <>
      <ViewHero eyebrow="PREFERÊNCIAS" title="Configurações" subtitle="Ajuste como o portal se comporta para você." onAsk={onAsk} />
      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">NOTIFICAÇÕES</p><h2>Avisos</h2></div></div>
          <div className="setting-list">
            <div className="setting-row">
              <div>
                <strong>Notificações por e-mail</strong>
                <span>Um resumo por atualização do projeto, no seu endereço</span>
              </div>
              <button
                className={`switch ${emailOn ? "switch--on" : ""}`}
                role="switch"
                aria-checked={emailOn}
                aria-label="Notificações por e-mail"
                disabled={saving}
                onClick={toggleEmail}
              >
                <i />
              </button>
            </div>
            <div className="setting-row">
              <div>
                <strong>Avisos por WhatsApp</strong>
                <span>
                  {phoneHint
                    ? `Uma mensagem curta com o link do assunto, no número ${phoneHint}`
                    : "Cadastre um telefone abaixo para poder ligar este canal"}
                </span>
              </div>
              <button
                className={`switch ${whatsappOn ? "switch--on" : ""}`}
                role="switch"
                aria-checked={whatsappOn}
                aria-label="Avisos por WhatsApp"
                disabled={saving}
                onClick={toggleWhatsapp}
              >
                <i />
              </button>
            </div>
            <div className="setting-row">
              <div>
                <strong>Telefone</strong>
                <span>
                  {phoneHint
                    ? `Cadastrado: ${phoneHint}. Envie vazio para apagar.`
                    : "Com DDI e DDD, por exemplo 5511987654321"}
                </span>
                {phoneError && <span role="alert">{phoneError}</span>}
              </div>
              <span className="setting-field">
                <input
                  type="tel"
                  inputMode="tel"
                  aria-label="Telefone para avisos"
                  placeholder={phoneHint || "5511987654321"}
                  value={phone}
                  disabled={saving}
                  onChange={(event) => setPhone(event.target.value)}
                />
                <button type="button" disabled={saving} onClick={savePhone}>
                  Salvar
                </button>
              </span>
            </div>
            <div className="setting-row">
              <div>
                <strong>Notificações no One</strong>
                <span>O sino sempre mostra o que mudou — não há o que desligar</span>
              </div>
            </div>
          </div>
        </article>
        {/* Idioma, fuso e tema são constantes do produto, não preferências: não
            há o que salvar, e o "Salvar alterações" que ficava aqui era o mesmo
            defeito que o comentário acima condena nos dois interruptores.
            Persisti-los custaria migração, policy e GRANT para gravar três
            valores que ninguém pode mudar — então a tela os declara. */}
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">REGIÃO</p><h2>Como o portal se apresenta</h2></div></div>
          <p className="panel-note">
            O portal fala português do Brasil, mostra datas e horas no fuso de São Paulo
            e tem um tema só. Nada disso é ajustável por enquanto.
          </p>
        </article>
      </section>
    </>
  );
}

/**
 * Os projetos agrupados pelo programa a que pertencem (ADR 0079).
 *
 * A ordem é a que a lista já trazia — `/me` abre pelo projeto que o dashboard serviu
 * (ADR 0062) —, e o grupo herda a posição do **primeiro** projeto dele: reordenar por
 * nome de programa jogaria o projeto na tela para o meio da página.
 *
 * O grupo sem programa vai para o **fim** e não ganha cabeçalho. Não é um grupo chamado
 * "sem programa": a ontologia diz que todo projeto pertence a um Engagement, e a
 * ausência aqui é o Biahflow ainda não tendo dito qual — inventar um rótulo afirmaria o
 * contrário. Esconder o projeto seria pior ainda; ele continua clicável.
 */
function groupByEngagement(
  projects: ProjectSummary[],
): { id: string | null; name: string | null; projects: ProjectSummary[] }[] {
  const groups: { id: string | null; name: string | null; projects: ProjectSummary[] }[] = [];
  const loose: ProjectSummary[] = [];
  for (const project of projects) {
    if (!project.engagementId) {
      loose.push(project);
      continue;
    }
    const found = groups.find((group) => group.id === project.engagementId);
    if (found) found.projects.push(project);
    else
      groups.push({
        id: project.engagementId,
        // `null` quando `/me` trouxe o id e não o nome — o grupo existe (os projetos
        // dele são os mesmos) e o cabeçalho fica sem nome em vez de com um inventado.
        name: project.engagementName,
        projects: [project],
      });
  }
  if (loose.length > 0) groups.push({ id: null, name: null, projects: loose });
  return groups;
}

function ProjectsView({
  projects,
  activeEngagementId,
  onSelect,
  onAsk,
}: {
  projects: ProjectSummary[];
  activeEngagementId: string | null;
  onSelect: (project: ProjectSummary) => void;
  onAsk: () => void;
}) {
  const groups = groupByEngagement(projects);
  return (
    <>
      <ViewHero
        eyebrow="ENGAGEMENTS"
        title="Trocar de contexto"
        subtitle="Seus programas, e os projetos dentro de cada um."
        onAsk={onAsk}
      />
      {projects.length === 0 && <p className="empty-state">Nenhum projeto vinculado à sua conta ainda.</p>}
      {groups.map((group) => (
        <div key={group.id ?? "sem-engagement"}>
          {group.name && (
            <div className="panel-heading">
              <div>
                <p className="eyebrow">ENGAGEMENT</p>
                <h2>{group.name}</h2>
              </div>
              {group.id === activeEngagementId && <StateBadge tone="1">Atual</StateBadge>}
            </div>
          )}
          <section className="card-grid" aria-label={group.name ? `Projetos de ${group.name}` : "Lista de projetos"}>
            {group.projects.map((project) => (
              <button
                className={`panel project-card ${project.current ? "project-card--active" : ""}`}
                key={project.id}
                onClick={() => onSelect(project)}
              >
                <div className="project-card-head">
                  <span className="project-logo project-logo--lg">{project.name.slice(0, 1)}</span>
                  {project.current && <StateBadge tone="1">Atual</StateBadge>}
                </div>
                <strong>{project.name}</strong>
                <div className="project-meta"><span>{project.status}</span></div>
              </button>
            ))}
          </section>
        </div>
      ))}
    </>
  );
}

function ProfileMenu({ up, user, onNavigate }: { up?: boolean; user: PortalUser; onNavigate: (label: string) => void }) {
  return (
    <div className={`popover popover-menu ${up ? "popover--up" : ""}`}>
      <div className="popover-user"><span className="avatar avatar--small">{user.initials}</span><div><strong>{user.name}</strong><small>{user.org}</small></div></div>
      <button onClick={() => onNavigate("Meu perfil")}><User size={15} /> Meu perfil</button>
      {/* Também aqui, e não só no "Ver todas" do sino: com a caixa vazia o
          popover não tem o link, e a central ficaria inalcançável. */}
      <button onClick={() => onNavigate("Notificações")}><Bell size={15} /> Notificações</button>
      <button onClick={() => onNavigate("Configurações")}><Settings size={15} /> Configurações</button>
      <button onClick={() => onNavigate("Trocar de contexto")}><Building2 size={15} /> Trocar de contexto</button>
      {/* Só para a equipe interna. A tela existe de qualquer forma; quem manda
          é a API, que responde 404 para quem não é `internal_admin`. */}
      {user.isInternal && <a href="/admin"><ShieldCheck size={15} /> Administração</a>}
      <form action={signOutAction}><button type="submit"><LogOut size={15} /> Sair</button></form>
    </div>
  );
}


/**
 * O fio de uma pendência (ADR 0032), atrás de um clique.
 *
 * Fechado por padrão de propósito: oito pendências com todos os fios abertos
 * viram mural, e a contagem no botão é o que diz se vale abrir. Carrega ao abrir
 * e não no render da aba — a maioria das visitas não comenta nada.
 */
function PendingThread({
  item,
  readOnly,
  projectId,
}: {
  item: PendingItemView;
  readOnly: ReadOnlyReason;
  /** O projeto da tela (ADR 0059): sem ele a pendência de B era procurada
   *  sob o tenant de A, e o fio respondia 404 ao próprio dono. */
  projectId?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState<PendingComment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, startSending] = useTransition();
  const router = useRouter();

  async function load() {
    const items = await listPendingCommentsAction(item.id, projectId);
    if (items === null) setFailed(true);
    else {
      setComments(items);
      setFailed(false);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && comments === null) void load();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    startSending(async () => {
      const ok = await addPendingCommentAction(item.id, text, projectId);
      if (!ok) {
        setFailed(true);
        return;
      }
      setDraft("");
      await load();
      // A contagem no botão vem do servidor; sem isto ela ficaria atrás do fio
      // que a pessoa acabou de ver crescer.
      router.refresh();
    });
  }

  // Sem id não há fio: é o espelho local da pendência que a IA acabou de abrir,
  // cujo id real chega no recarregamento.
  if (!item.id) return null;

  return (
    <div className="pending-thread">
      <button className="text-button" onClick={toggle} aria-expanded={open}>
        <MessageSquare size={14} />
        {item.commentCount === 0
          ? "Comentar"
          : `${item.commentCount} ${item.commentCount === 1 ? "comentário" : "comentários"}`}
      </button>

      {open && (
        <div className="comment-list">
          {failed && (
            <p className="auth-error" role="status">
              Não consegui carregar os comentários agora. Nada foi perdido — tente de novo.
            </p>
          )}
          {comments?.length === 0 && !failed && (
            <p className="empty-note">
              {readOnly ? "Ninguém comentou nesta pendência." : "Ninguém comentou ainda. Escreva o primeiro."}
            </p>
          )}
          {comments?.map((comment) => (
            <div className="comment-row" key={comment.id}>
              <span
                className={`comment-side ${comment.author_is_internal ? "comment-side--internal" : ""}`}
              >
                {comment.author_label}
              </span>
              <p>{comment.body}</p>
              <small>{new Date(comment.created_at).toLocaleString("pt-BR")}</small>
            </div>
          ))}
          {/* Projeto sem escrita mantém a leitura (ADR 0036/0037) — a API responde 409 aqui,
              então o formulário sai em vez de falhar depois de a pessoa digitar. */}
          {readOnly ? (
            <p className="empty-note">{readOnly.comments}</p>
          ) : (
            <form className="comment-form" onSubmit={submit}>
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Escreva um comentário…"
                maxLength={2000}
                aria-label="Novo comentário"
              />
              <button type="submit" disabled={sending || !draft.trim()}>
                {sending ? "Enviando…" : "Enviar"}
              </button>
            </form>
          )}
          <p className="field-hint">
            Comentários ficam no portal e não são editáveis nem removíveis — quem escreve não
            reescreve.
          </p>
        </div>
      )}
    </div>
  );
}

function PendingItem({
  item,
  onOpenTurn,
  withThread = false,
  readOnly = null,
  focusedItem = null,
  projectId = null,
}: {
  item: PendingItemView;
  onOpenTurn?: (messageId: string, conversationId: string | null) => void;
  /** O resumo da Visão geral mostra quatro linhas; abrir fio ali é outra tela. */
  withThread?: boolean;
  /** Projeto encerrado ou removido: o fio abre para leitura, sem campo de escrita (ADR 0036/0037). */
  readOnly?: ReadOnlyReason;
  /** A âncora do `?item=` (ADR 0056). O resumo da Visão geral não a recebe: o link
   *  da pendência abre a aba de Pendências, que é onde a lista está inteira. */
  focusedItem?: string | null;
  /** O projeto da tela, repassado ao fio (ADR 0059). */
  projectId?: string | null;
}) {
  const tone = pendingTone[item.state] ?? "amber";
  const owner = item.owner ?? "Sem responsável definido";
  const detail = [owner, item.age].filter(Boolean).join(" • ");
  return (
    <div
      className={`pending-entry ${`pending:${item.title}` === focusedItem ? "is-anchored" : ""}`}
      data-item={`pending:${item.title}`}
    >
      <div className="pending-row">
      <span className={`pending-avatar pending-avatar--${tone}`}>{owner.slice(0, 1)}</span>
      <div>
        <strong>{item.title}</strong>
        <span>{detail}{item.origin === "portal" && <> <b>•</b> aberta pela IA</>}</span>
      </div>
      {/* O caminho de volta à pergunta que abriu esta pendência (ADR 0031). O FK
          existe desde a ADR 0015 e era lido só como booleano: o cliente via
          "aberta pela IA" sem ter como reler o que perguntou. */}
      {item.openedByMessageId && onOpenTurn && (
        <button
          className="text-button"
          onClick={() =>
            onOpenTurn(item.openedByMessageId as string, item.openedByConversationId)
          }
        >
          Ver a pergunta
        </button>
      )}
      {/* Só a alta e a baixa ganham selo. "Média" é o padrão da coluna, e um
          selo em toda linha deixa de distinguir qualquer coisa (ADR 0029). */}
      {item.priority !== "medium" && (
        <span className={`priority-pill priority-pill--${item.priority}`}>{item.priorityLabel}</span>
      )}
      </div>
      {/* O fio fica **fora** da `.pending-row`, que é um flex de uma linha: pôr
          uma lista dentro dela desalinharia o avatar e o selo (ADR 0032). */}
      {withThread && <PendingThread item={item} readOnly={readOnly} projectId={projectId} />}
    </div>
  );
}
