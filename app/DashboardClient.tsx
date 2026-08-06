"use client";

import {
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
  TrendingUp,
  User,
  UsersRound,
  Video,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  markNotificationsReadAction,
  setEmailPreferenceAction,
  signOutAction,
} from "./actions";

// A citação como ela chega da API (ADR 0017): o rótulo que a pessoa vê e, quando a
// evidência veio de um arquivo, o ponteiro que a torna clicável. `document_id` é
// nulo para evidência do read model — um marco não é um arquivo e não tem o que
// abrir.
type Citation = { label: string; document_id?: string | null };

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
};

const navItems = [
  { label: "Visão geral", icon: LayoutDashboard },
  { label: "Cronograma", icon: CalendarClock },
  { label: "Documentos", icon: FolderOpen },
  { label: "Reuniões", icon: UsersRound },
  { label: "Pendências", icon: Inbox },
  { label: "Resultados", icon: TrendingUp },
];

/** Pendências que ainda pedem ação — resolvidas ficam no histórico. */
function openPendings(overview: Overview): PendingItemView[] {
  return overview.pendings.filter((item) => item.state !== "resolved");
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
  project_status_changed: TrendingUp,
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
};

/** Rótulo por espécie de resultado. O mesmo vocabulário de `search.py`. */
const searchKindLabel: Record<string, string> = {
  document: "Documento",
  meeting: "Reunião",
  pending: "Pendência",
  milestone: "Marco",
  chunk: "Trecho de documento",
};

/** Espelha `search.MIN_QUERY_LENGTH`: abaixo disso a API devolve lista vazia, e
 *  chamar para ouvir isso seria uma ida ao servidor por tecla. */
const SEARCH_MIN_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 250;

/** Quem está logado, projetado de `GET /api/v1/me` — a membership é a autoridade. */
export type PortalUser = { name: string; initials: string; email: string; role: string; org: string; isInternal: boolean; notifyByEmail: boolean };
export type NotificationView = { id: string; kind: string; title: string; detail: string | null; link: string | null; age: string; read: boolean };
/** A caixa do projeto atual, vinda de `GET /api/v1/me/notifications`. */
export type NotificationCenter = { unreadCount: number; items: NotificationView[] };
/** Um projeto que o usuário alcança. `current` é o que está sendo exibido. */
export type ProjectSummary = { id: string; name: string; status: string; current: boolean };

export type OverviewMilestone = { title: string; owner: string; state: string; date: string };
export type ProjectDocument = { title: string; type: string | null; author: string | null; link: string | null; updated: string };
export type MeetingView = { title: string; date: string; status: string; hasTranscript: boolean; recordingUrl: string | null };
export type PendingItemView = { title: string; description: string | null; owner: string | null; state: string; stateLabel: string; origin: string; age: string };
export type ProjectResults = { milestonesTotal: number; milestonesDone: number; overdue: number; onTimePercent: number };
export type MeasuredAssumption = { hourlyRate: number; monthlyInvestment: number; effectiveFrom: string; note: string | null };
/** O que os agentes produziram no período, apurado pela API (ADR 0013). Não se
 *  confunde com `roi`, que é o ROI projetado vindo do snapshot do Biahflow. */
export type MeasuredResults = {
  periodDays: number;
  eventsTotal: number;
  hoursSaved: number;
  benefit: number;
  investment: number;
  net: number;
  roiRatio: number | null;
  accuracy: number | null;
  exceptionsHandled: number;
  unattendedShare: number | null;
  failed: number;
  assumption: MeasuredAssumption | null;
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
export type Overview = {
  project: string;
  organization: string;
  status: string;
  completion: number;
  source: "live" | "demo";
  nextDelivery: { title: string; detail: string } | null;
  milestones: OverviewMilestone[];
  journey: { currentPhase: string | null; phases: JourneyPhase[] };
  roi: { net: number | null; ratio: number | null } | null;
  nextMeeting: { title: string; detail: string } | null;
  health: { label: string; level: string } | null;
  digitalEmployees: DigitalEmployeeView[];
  documents: ProjectDocument[];
  meetings: MeetingView[];
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
}: {
  overview: Overview;
  user: PortalUser;
  projects: ProjectSummary[];
  notifications?: NotificationCenter;
}) {
  const router = useRouter();
  const [activeNav, setActiveNav] = useState("Visão geral");
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
  const activeProject = projects.find((project) => project.current) ?? projects[0] ?? null;

  const toggleMenu = (target: typeof menu) => setMenu((current) => (current === target ? null : target));
  const goTo = (label: string) => { setActiveNav(label); setMenu(null); setMobileNavOpen(false); };
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
    if (!chatOpen || historyLoaded.current) return;
    // Ref e não estado: a guarda existe para a busca não repetir, e marcá-la não
    // é informação que a tela precise renderizar.
    historyLoaded.current = true;
    let current = true;
    (async () => {
      try {
        const response = await fetch("/api/chat/history", { cache: "no-store" });
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
            feedback?: "helpful" | "not_helpful" | null;
          }) => ({
            id: message.id,
            role: message.role,
            text: message.text,
            sources: message.sources,
            citations: message.citations,
            pending: message.pending_created,
            feedback: message.feedback ?? null,
          }));
        // Só substitui a tela se a pessoa ainda não escreveu nada. O histórico
        // chega **depois** da saudação, e uma pergunta enviada nesse intervalo
        // seria apagada da tela por esta linha — gravada no banco, invisível até
        // o próximo F5. Quem já tem um turno seu na tela não precisa que o
        // histórico o recomponha.
        setMessages((shown) =>
          shown.some((message) => message.role === "user") ? shown : restored,
        );
      } catch {
        // Sem histórico, o painel abre com a saudação — que é o estado inicial.
      }
    })();
    return () => {
      current = false;
    };
  }, [chatOpen]);

  /** Começa do zero: sem id, a API abre outra thread no próximo turno. */
  function startNewConversation() {
    setConversationId(null);
    setMessages(greeting(user));
  }

  async function rateAnswer(messageId: string, helpful: boolean) {
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
      await fetch("/api/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, helpful }),
      });
    } catch {
      // Silencioso de propósito, pelo mesmo motivo.
    }
  }

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
      const response = await fetch(`/api/documents/${documentId}/download`);
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
    goTo(hit.tab);
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
        body: JSON.stringify({ question: value, conversation_id: conversationId }),
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
        feedback: null,
      });
      // Espelha a pendência que a API acabou de criar (mesmo título de `ai/service.py`).
      if (data.pending_created) {
        setAiPendings((current) => [
          {
            title: `Responder dúvida do cliente: ${value.slice(0, 160)}`,
            description: "Pergunta sem evidência suficiente no contexto do projeto (chat).",
            owner: "Portal Labs",
            state: "open",
            stateLabel: "Aberta",
            origin: "portal",
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
      const ok = await markNotificationsReadAction();
      if (!ok) setOptimisticRead(false); // a API recusou: o ponto volta
    });
  }

  // A visão do projeto = o que veio do servidor + as pendências abertas pela IA nesta sessão.
  const view = useMemo<Overview>(
    () => (aiPendings.length === 0 ? overview : { ...overview, pendings: [...aiPendings, ...overview.pendings] }),
    [overview, aiPendings],
  );
  const openCount = openPendings(view).length;

  function renderActiveView() {
    switch (activeNav) {
      case "Cronograma":
        return <ScheduleView onAsk={askAi} overview={view} />;
      case "Documentos":
        return <DocumentsView onAsk={askAi} overview={view} />;
      case "Reuniões":
        return <MeetingsView onAsk={askAi} overview={view} />;
      case "Pendências":
        return <PendingView onAsk={askAi} overview={view} />;
      case "Resultados":
        return <ResultsView onAsk={askAi} overview={view} />;
      case "Notificações":
        return <NotificationsView onAsk={askAi} notifications={notifications} />;
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
            overview={view}
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
              onClick={() => { setActiveNav(label); setMobileNavOpen(false); }}
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
              {menu === "search" && <ProjectSearch onOpen={openSearchHit} />}
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
                    <div className="popover-row" key={item.id}>
                      <strong>{item.title}</strong>
                      <span>{[item.detail, item.age].filter(Boolean).join(" • ")}</span>
                    </div>
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
          {renderActiveView()}
        </div>
      </section>

      <button className="chat-fab" onClick={() => setChatOpen(true)} aria-label="Abrir chat com IA"><MessageCircleMore size={22} /><span>Falar com a IA</span></button>

      {chatOpen && (
        <section className="chat-panel" aria-label="Assistente de IA do projeto">
          <header className="chat-header"><div className="ai-avatar"><Sparkles size={16} /></div><div><strong>Assistente do projeto</strong><span><i /> Contexto atualizado</span></div><button className="icon-button" onClick={startNewConversation} aria-label="Iniciar nova conversa" title="Nova conversa"><MessageSquarePlus size={19} /></button><button className="icon-button" onClick={() => setChatOpen(false)} aria-label="Fechar chat"><X size={19} /></button></header>
          <div className="chat-messages">
            {messages.map((message, index) => (
              <div className={`message message--${message.role}`} key={message.id ?? `${message.role}-${index}`}>
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
                          type="button"
                        >
                          <FileText size={12} /> {citation.label}
                        </button>
                      ) : (
                        <span key={citation.label}><FileText size={12} /> {citation.label}</span>
                      ),
                    )}
                  </div>
                ) : message.sources?.length ? (
                  <div className="message-sources">{message.sources.map((source) => <span key={source}><FileText size={12} /> {source}</span>)}</div>
                ) : null}
                {message.pending && <small className="pending-created"><Check size={13} /> Pendência criada para Portal Labs</small>}
                {/* Só a resposta gravada aceita polegar: sem id não há o que avaliar. */}
                {message.role === "assistant" && message.id && (
                  <div className="message-feedback">
                    <button
                      className={message.feedback === "helpful" ? "is-active" : undefined}
                      onClick={() => rateAnswer(message.id!, true)}
                      aria-pressed={message.feedback === "helpful"}
                      aria-label="Esta resposta ajudou"
                    ><ThumbsUp size={13} /></button>
                    <button
                      className={message.feedback === "not_helpful" ? "is-active" : undefined}
                      onClick={() => rateAnswer(message.id!, false)}
                      aria-pressed={message.feedback === "not_helpful"}
                      aria-label="Esta resposta não ajudou"
                    ><ThumbsDown size={13} /></button>
                  </div>
                )}
              </div>
            ))}
          </div>
          {downloadError && <p className="chat-notice" role="status">{downloadError}</p>}
          <div className="chat-suggestions">{suggestedQuestions.map((item) => <button key={item} onClick={() => sendQuestion(undefined, item)}>{item}</button>)}</div>
          <form className="chat-form" onSubmit={sendQuestion}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Pergunte sobre o projeto..." aria-label="Pergunta para IA" /><button type="submit" aria-label="Enviar pergunta"><Send size={17} /></button></form>
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
function ProjectSearch({ onOpen }: { onOpen: (hit: SearchHit) => Promise<boolean> }) {
  const [term, setTerm] = useState("");
  const [found, setFound] = useState<{ query: string; hits: SearchHit[] } | null>(null);
  const [failed, setFailed] = useState("");
  const [openFailed, setOpenFailed] = useState(false);
  const query = term.trim();
  const short = query.length < SEARCH_MIN_LENGTH;

  // Debounce mais `AbortController`: a tecla seguinte cancela a busca da
  // anterior, então a resposta que sobra é sempre a do último termo.
  useEffect(() => {
    if (short) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, {
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
  }, [query, short]);

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

const PHASE_STATE_LABEL: Record<JourneyPhase["state"], string> = {
  done: "Concluída",
  active: "Em andamento",
  locked: "A desbloquear",
};

// "Você está aqui": a jornada de transformação pela perspectiva do cliente — sem nada
// técnico. Cada fase concluída/ativa revela seus entregáveis; as bloqueadas ficam veladas.
function JourneyPanel({ journey }: { journey: Overview["journey"] }) {
  const phases = journey.phases;
  const activeIndex = phases.findIndex((phase) => phase.state === "active");
  const initial = activeIndex >= 0 ? activeIndex : Math.max(0, phases.length - 1);
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
          <li key={item.name} className={`journey-step journey-step--${item.state} ${index === selected ? "is-selected" : ""}`}>
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
                <li key={deliverable.name} className={unlocked ? "is-unlocked" : "is-locked"}>
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

function OverviewView({ onAsk, onAnalyze, onNavigate, overview, user }: { onAsk: () => void; onAnalyze: () => void; onNavigate: (label: string) => void; overview: Overview; user: PortalUser }) {
  const timeline = overview.milestones;
  const open = openPendings(overview);
  const roi = roiValue(overview.roi);
  // Conhecimento do projeto: documentos e reuniões mais recentes, na mesma lista.
  const updates = [
    ...overview.documents.map((document) => ({ type: "Documento", title: document.title, detail: document.updated, link: document.link })),
    ...overview.meetings.map((meeting) => ({ type: "Reunião", title: meeting.title, detail: meeting.hasTranscript ? "Transcrição disponível" : meeting.status, link: meeting.recordingUrl })),
  ].slice(0, 5);
  return (
    <>
      <ViewHero eyebrow={overview.project.toLocaleUpperCase("pt-BR")} title={`Bom dia, ${firstName(user.name)}.`} subtitle="Veja o que está acontecendo no seu projeto." onAsk={onAsk} />

      <JourneyPanel journey={overview.journey} />

      <DigitalEmployees employees={overview.digitalEmployees} />

      <section className="status-card">
        <div className="status-main">
          <div className="status-icon"><Check size={19} /></div>
          <div><p>Status do projeto</p><h2>{overview.status}</h2></div>
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
            {open.slice(0, 4).map((item) => <PendingItem key={item.title} item={item} />)}
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

function ScheduleView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  return (
    <>
      <ViewHero eyebrow="CRONOGRAMA" title="Cronograma do projeto" subtitle="Marcos concluídos, em andamento e planejados." onAsk={onAsk} />
      <article className="panel timeline-panel">
        <div className="panel-heading"><div><p className="eyebrow">LINHA DO TEMPO</p><h2>Todos os marcos</h2></div><span className="state state--1">{overview.completion}% concluído</span></div>
        <div className="milestones">
          {overview.milestones.length === 0 && <p className="empty-state">Nenhum marco cadastrado ainda.</p>}
          {overview.milestones.map((item) => {
            const tone = stateStyle[item.state] ?? "2";
            return (
              <div className="milestone" key={item.title}>
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

function DocumentsView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  return (
    <>
      <ViewHero eyebrow="DOCUMENTOS" title="Documentos do projeto" subtitle="Planos, relatórios e materiais compartilhados." onAsk={onAsk} />
      {overview.documents.length === 0 && <p className="empty-state">Nenhum documento compartilhado ainda.</p>}
      <section className="card-grid" aria-label="Lista de documentos">
        {overview.documents.map((doc) => (
          <article className="panel doc-card" key={doc.title}>
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

function MeetingsView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  return (
    <>
      <ViewHero eyebrow="REUNIÕES" title="Reuniões do projeto" subtitle="Gravações e transcrições dos encontros." onAsk={onAsk} />
      <article className="panel">
        <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Encontros recentes <span>{overview.meetings.length}</span></h2></div></div>
        <div className="source-list">
          {overview.meetings.length === 0 && <p className="empty-state">Nenhuma reunião registrada ainda.</p>}
          {overview.meetings.map((meeting) => (
            <div className="source-row" key={meeting.title}>
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

function PendingView({ onAsk, overview }: { onAsk: () => void; overview: Overview }) {
  const open = openPendings(overview);
  const resolved = overview.pendings.filter((item) => item.state === "resolved");
  return (
    <>
      <ViewHero eyebrow="PENDÊNCIAS" title="Pendências do projeto" subtitle="O que precisa de decisão ou ação para avançar." onAsk={onAsk} />
      <section className="dashboard-grid">
        <article className="panel pending-panel">
          <div className="panel-heading"><div><p className="eyebrow">ACOMPANHAMENTO</p><h2>Abertas <span>{open.length}</span></h2></div></div>
          <div className="pending-list">
            {open.length === 0 && <p className="empty-state">Nenhuma pendência aberta.</p>}
            {open.map((item) => <PendingItem key={item.title} item={item} />)}
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Resolvidas <span>{resolved.length}</span></h2></div></div>
          <div className="pending-list">
            {resolved.length === 0 && <p className="empty-state">Nenhuma pendência resolvida ainda.</p>}
            {resolved.map((item) => <PendingItem key={item.title} item={item} />)}
          </div>
        </article>
      </section>
    </>
  );
}

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
/** Com centavos: uma premissa precisa poder ser conferida na mão, e R$ 150,50
 *  arredondado para R$ 151 deixaria a conta do cliente sem fechar. */
const BRL_EXACT = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
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
            <span className="field-value">Últimos {measured.periodDays} dias</span>
          </div>
          <div className="field-row">
            <span className="field-label">Eventos considerados</span>
            <span className="field-value">{measured.eventsTotal.toLocaleString("pt-BR")}</span>
          </div>
          {assumption && (
            <>
              <div className="field-row">
                <span className="field-label">Valor-hora vigente</span>
                <span className="field-value">
                  {BRL_EXACT.format(assumption.hourlyRate)} · desde {assumption.effectiveFrom}
                </span>
              </div>
              <div className="field-row">
                <span className="field-label">Investimento mensal</span>
                <span className="field-value">
                  {BRL_EXACT.format(assumption.monthlyInvestment)} · rateado por dia no período
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
            <span className="field-value">(economia apurada − investimento) ÷ investimento</span>
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

/** A central: o histórico completo do projeto atual, do mais recente ao mais antigo. */
function NotificationsView({ onAsk, notifications }: { onAsk: () => void; notifications: NotificationCenter }) {
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
                return item.link ? (
                  <a className={className} key={item.id} href={item.link} target="_blank" rel="noreferrer">{body}</a>
                ) : (
                  <div className={className} key={item.id}>{body}</div>
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
  // Uma preferência, e ela é real. As outras duas que existiam aqui eram
  // decorativas — um interruptor que não liga nada é pior do que não ter.
  const [emailOn, setEmailOn] = useState(user.notifyByEmail);
  const [saving, startSaving] = useTransition();

  function toggleEmail() {
    const next = !emailOn;
    setEmailOn(next);
    startSaving(async () => {
      const ok = await setEmailPreferenceAction(next);
      if (!ok) setEmailOn(!next);
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

function PendingItem({ item }: { item: PendingItemView }) {
  const tone = pendingTone[item.state] ?? "amber";
  const owner = item.owner ?? "Sem responsável definido";
  const detail = [owner, item.age].filter(Boolean).join(" • ");
  return (
    <div className="pending-row">
      <span className={`pending-avatar pending-avatar--${tone}`}>{owner.slice(0, 1)}</span>
      <div>
        <strong>{item.title}</strong>
        <span>{detail}{item.origin === "portal" && <> <b>•</b> aberta pela IA</>}</span>
      </div>
    </div>
  );
}
