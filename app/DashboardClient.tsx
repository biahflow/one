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
  Clock3,
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

import {
  addPendingCommentAction,
  listPendingCommentsAction,
  markNotificationsReadAction,
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
  { label: "Pendências", icon: Inbox },
  { label: "Decisões", icon: Scale },
  { label: "Resultados", icon: TrendingUp },
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
 * 3. **aba que a navegação não conhece**: `onboarding_stuck` traz `/admin/funil`,
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

/** Rótulo por espécie de resultado. O mesmo vocabulário de `search.py`. */
const searchKindLabel: Record<string, string> = {
  document: "Documento",
  meeting: "Reunião",
  pending: "Pendência",
  decision: "Decisão",
  milestone: "Marco",
  chunk: "Trecho de documento",
};

/** Espelha `search.MIN_QUERY_LENGTH`: abaixo disso a API devolve lista vazia, e
 *  chamar para ouvir isso seria uma ida ao servidor por tecla. */
const SEARCH_MIN_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 250;

/** Quem está logado, projetado de `GET /api/v1/me` — a membership é a autoridade. */
export type PortalUser = { name: string; initials: string; email: string; role: string; org: string; isInternal: boolean; notifyByEmail: boolean; notifyByWhatsapp: boolean; phoneHint: string };
export type NotificationView = { id: string; kind: string; title: string; detail: string | null; link: string | null; age: string; read: boolean };
/** A caixa do projeto atual, vinda de `GET /api/v1/me/notifications`. */
export type NotificationCenter = { unreadCount: number; items: NotificationView[] };
/** Um projeto que o usuário alcança. `current` é o que está sendo exibido. */
export type ProjectSummary = { id: string; name: string; status: string; current: boolean };

export type OverviewMilestone = { title: string; owner: string; state: string; date: string };
export type ProjectDocument = { title: string; type: string | null; author: string | null; link: string | null; updated: string };
export type MeetingView = { title: string; date: string; status: string; hasTranscript: boolean; recordingUrl: string | null };
export type DecisionView = { title: string; rationale: string | null; decidedOn: string | null; ownerLabel: string | null; meetingTitle: string | null };
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
export type JourneyDeliverable = { name: string; state: "pending" | "delivered"; link: string | null };
export type DigitalEmployeeView = { name: string; area: string | null; description: string | null; status: string; kpiLabel: string | null; kpiValue: string | null; hoursSavedMonth: number | null; roiMonth: number | null };
export type JourneyPhase = {
  name: string;
  description: string;
  state: "locked" | "active" | "done";
  targetDate: string;
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
type ReadOnlyReason = { pill: string; chat: string; comments: string } | null;

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
    };
  }
  return null;
}

export type Overview = {
  project: string;
  organization: string;
  status: string;
  completion: number;
  source: "live" | "demo";
  /** Quando o Biahflow encerrou o projeto, ou `null` se segue ativo (ADR 0036). Preenchido, a
   *  tela entra em modo de consulta: o histórico continua inteiro e as escritas fecham. */
  archivedAt: string | null;
  /** Quando o Biahflow apagou o projeto de vez, ou `null` (ADR 0037). Mesmo modo de consulta,
   *  motivo diferente — e este não tem volta, porque a fonte não tem mais o que declarar. */
  sourceDeletedAt: string | null;
  nextDelivery: { title: string; detail: string } | null;
  milestones: OverviewMilestone[];
  journey: { currentPhase: string | null; phases: JourneyPhase[] };
  roi: { net: number | null; ratio: number | null } | null;
  nextMeeting: { title: string; detail: string } | null;
  health: { label: string; level: string } | null;
  digitalEmployees: DigitalEmployeeView[];
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
// `pending: true`, de modo que a tela dizia "Pendência criada para Portal Labs"
// para uma pendência que ninguém gravou. O `CLAUDE.md` afirmava que não havia
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
        "equipe da Portal Labs pode ampliá-la antes disso. Nada foi registrado.",
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
            owner: "Portal Labs",
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
      case "Pendências":
        return <PendingView onAsk={askAi} overview={view} onOpenTurn={openTurn} focusedItem={focusedItem} projectId={activeProject?.id ?? null} />;
      case "Decisões":
        return <DecisionsView onAsk={askAi} overview={view} />;
      case "Resultados":
        return <ResultsView onAsk={askAi} overview={view} />;
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
      case "Trocar projeto":
        return <ProjectsView projects={projects} onSelect={selectProject} onAsk={askAi} />;
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
          <div className="brand-mark"><Sparkles size={17} /></div>
          <span>portal<span>labs</span></span>
          <button
            className="icon-button sidebar-toggle"
            onClick={() => { setCollapsed((value) => !value); setMobileNavOpen(false); }}
            aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button className="project-switcher" aria-label="Trocar projeto" onClick={() => goTo("Trocar projeto")}>
          <span className="project-logo">{(activeProject?.name ?? user.org).slice(0, 1)}</span>
          <span><strong>{user.org}</strong><small>{activeProject?.name ?? overview.project}</small></span>
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
                {message.pending && <small className="pending-created"><Check size={13} /> Pendência criada para Portal Labs</small>}
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
      <button className="ai-button" onClick={onAsk}><Sparkles size={17} /> Perguntar à IA</button>
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

// "Você está aqui": a jornada de transformação pela perspectiva do cliente — sem nada
// técnico. Cada fase concluída/ativa revela seus entregáveis; as bloqueadas ficam veladas.
function JourneyPanel({ journey, focusedItem }: { journey: Overview["journey"]; focusedItem?: string | null }) {
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

  return (
    <section className="journey-panel" aria-label="Jornada de transformação">
      <div className="journey-head">
        <div>
          <p className="eyebrow">SUA JORNADA</p>
          <h2>Você está aqui</h2>
        </div>
        {journey.currentPhase && (
          <span className="journey-here"><MapPin size={15} /> {journey.currentPhase}</span>
        )}
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
            <span className={`state state--${phase.state === "done" ? "1" : phase.state === "active" ? "2" : "3"}`}>{PHASE_STATE_LABEL[phase.state]}</span>
            <h3>{phase.name}</h3>
            {phase.description && <p>{phase.description}</p>}
          </div>
          {phase.targetDate && <div className="journey-target"><span>Previsão</span><strong>{phase.targetDate}</strong></div>}
        </div>

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

function OverviewView({ onAsk, onAnalyze, onNavigate, onOpenTurn, overview, user, focusedItem }: { onAsk: () => void; onAnalyze: () => void; onNavigate: (label: string) => void; onOpenTurn: (messageId: string, conversationId: string | null) => void; overview: Overview; user: PortalUser; focusedItem?: string | null }) {
  const timeline = overview.milestones;
  const open = openPendings(overview);
  const roi = roiValue(overview.roi);
  const readOnly = readOnlyReason(overview);
  // Conhecimento do projeto: documentos e reuniões mais recentes, na mesma lista.
  const updates = [
    ...overview.documents.map((document) => ({ type: "Documento", title: document.title, detail: document.updated, link: document.link })),
    ...overview.meetings.map((meeting) => ({ type: "Reunião", title: meeting.title, detail: meeting.hasTranscript ? "Transcrição disponível" : meeting.status, link: meeting.recordingUrl })),
  ].slice(0, 5);
  return (
    <>
      <ViewHero eyebrow={overview.project.toLocaleUpperCase("pt-BR")} title={`Bom dia, ${firstName(user.name)}.`} subtitle="Veja o que está acontecendo no seu projeto." onAsk={onAsk} />

      <JourneyPanel journey={overview.journey} focusedItem={focusedItem} />

      <DigitalEmployees employees={overview.digitalEmployees} />

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
          <p>ROI do projeto</p>
          <h3>{roi.value}</h3>
          <span className={roi.positive ? "positive" : undefined}>{roi.note}</span>
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
                  <span className={`state state--${tone}`}>{milestone.state}</span>
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
        <div className="panel-heading"><div><p className="eyebrow">LINHA DO TEMPO</p><h2>Todos os marcos</h2></div><span className="state state--1">{overview.completion}% concluído</span></div>
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
                <span className={`state state--${tone}`}>{item.state}</span>
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
              <span className={`state state--${meeting.status === "Realizada" ? "done" : "1"}`}>{meeting.status}</span>
            </div>
          ))}
        </div>
      </article>
    </>
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
                {employee.roiMonth ? <div><span>ROI/mês</span><strong>{BRL.format(employee.roiMonth)}</strong></div> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
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
  no_investment: "O investimento configurado é zero, e sem ele não há ROI a calcular.",
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
            <span className="field-label">Fórmula do ROI</span>
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
                <strong>Notificações no portal</strong>
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

function ProjectsView({ projects, onSelect, onAsk }: { projects: ProjectSummary[]; onSelect: (project: ProjectSummary) => void; onAsk: () => void }) {
  return (
    <>
      <ViewHero eyebrow="PROJETOS" title="Trocar projeto" subtitle="Escolha qual projeto você quer acompanhar." onAsk={onAsk} />
      {projects.length === 0 && <p className="empty-state">Nenhum projeto vinculado à sua conta ainda.</p>}
      <section className="card-grid" aria-label="Lista de projetos">
        {projects.map((project) => (
          <button
            className={`panel project-card ${project.current ? "project-card--active" : ""}`}
            key={project.id}
            onClick={() => onSelect(project)}
          >
            <div className="project-card-head">
              <span className="project-logo project-logo--lg">{project.name.slice(0, 1)}</span>
              {project.current && <span className="state state--1">Atual</span>}
            </div>
            <strong>{project.name}</strong>
            <div className="project-meta"><span>{project.status}</span></div>
          </button>
        ))}
      </section>
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
      <button onClick={() => onNavigate("Trocar projeto")}><Building2 size={15} /> Trocar projeto</button>
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
