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
  MoreHorizontal,
  PanelLeftClose,
  Search,
  Send,
  Settings,
  Sparkles,
  Target,
  TrendingUp,
  User,
  UsersRound,
  Video,
  X,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import { signOutAction } from "./actions";

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  pending?: boolean;
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

const notifications = [
  { title: "Nova pendência atribuída", detail: "Aprovar fluxo de exceções", age: "há 2 dias" },
  { title: "Documento atualizado", detail: "Plano de implantação v3", age: "ontem" },
  { title: "Transcrição pronta", detail: "Comitê de projeto — 28 ago", age: "há 3 dias" },
];

/** Quem está logado, projetado de `GET /api/v1/me` — a membership é a autoridade. */
export type PortalUser = { name: string; initials: string; email: string; role: string; org: string };
/** Um projeto que o usuário alcança. `current` é o que está sendo exibido. */
export type ProjectSummary = { id: string; name: string; status: string; current: boolean };

export type OverviewMilestone = { title: string; owner: string; state: string; date: string };
export type ProjectDocument = { title: string; type: string | null; author: string | null; link: string | null; updated: string };
export type MeetingView = { title: string; date: string; status: string; hasTranscript: boolean; recordingUrl: string | null };
export type PendingItemView = { title: string; description: string | null; owner: string | null; state: string; stateLabel: string; origin: string; age: string };
export type ProjectResults = { milestonesTotal: number; milestonesDone: number; overdue: number; onTimePercent: number };
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

function answerFor(question: string): ChatMessage {
  const normalized = question.toLocaleLowerCase("pt-BR");

  if (normalized.includes("produção") || normalized.includes("producao")) {
    return {
      role: "assistant",
      text: "A entrada em produção está prevista para 30 de setembro, após a validação das integrações e o treinamento da operação. No momento, os dois marcos seguem no cronograma.",
      sources: ["Plano de implantação v3", "Comitê de projeto — 28 ago"],
    };
  }

  if (normalized.includes("financeiro") || normalized.includes("decis")) {
    return {
      role: "assistant",
      text: "Na última reunião, definimos que as exceções financeiras continuarão com aprovação humana na primeira fase. O critério de alçada será validado com o time da Acme antes do piloto.",
      sources: ["Comitê de projeto — 28 ago"],
    };
  }

  if (normalized.includes("pend") || normalized.includes("abert")) {
    return {
      role: "assistant",
      text: "Existem 3 pendências abertas: aprovar o fluxo de exceções, enviar a lista de usuários piloto e validar o cálculo de economia. A mais próxima do prazo é a aprovação do fluxo.",
      sources: ["Pendências do projeto"],
    };
  }

  return {
    role: "assistant",
    text: "Não encontrei evidências suficientes nos materiais deste projeto para responder com segurança. Registrei uma pendência para o time responsável retornar com a informação.",
    sources: ["Busca no contexto do projeto"],
    pending: true,
  };
}

export default function DashboardClient({
  overview,
  user,
  projects,
}: {
  overview: Overview;
  user: PortalUser;
  projects: ProjectSummary[];
}) {
  const router = useRouter();
  const [activeNav, setActiveNav] = useState("Visão geral");
  const [chatOpen, setChatOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(() => greeting(user));
  // Pendências que a IA abriu nesta sessão: já existem no banco, mas a página é renderizada
  // no servidor, então são espelhadas aqui até o próximo carregamento.
  const [aiPendings, setAiPendings] = useState<PendingItemView[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [menu, setMenu] = useState<null | "search" | "notifications" | "profile" | "profile-side">(null);
  const [notifRead, setNotifRead] = useState(false);

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
        body: JSON.stringify({ question: value }),
      });
      if (!response.ok) throw new Error("chat unavailable");
      const data = await response.json();
      pushAnswer({
        role: "assistant",
        text: data.answer,
        sources: data.sources,
        pending: data.pending_created,
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
      // Offline/demo fallback keeps the assistant responsive without the backend. Nenhuma
      // pendência é espelhada aqui: sem API, nada foi realmente registrado.
      pushAnswer(answerFor(value));
    }
  }

  const askAi = () => setChatOpen(true);

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
      case "Meu perfil":
        return <ProfileView onAsk={askAi} user={user} projectName={overview.project} />;
      case "Configurações":
        return <SettingsView onAsk={askAi} />;
      case "Trocar projeto":
        return <ProjectsView projects={projects} onSelect={selectProject} onAsk={askAi} />;
      default:
        return (
          <OverviewView
            user={user}
            onAsk={askAi}
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
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNavOpen(true)} aria-label="Abrir menu"><Menu size={21} /></button>
          <div className="breadcrumb"><span>{user.org}</span><b>/</b><strong>{activeNav}</strong></div>
          <div className="topbar-actions">
            <div className="topbar-menu">
              <button className="icon-button" aria-label="Pesquisar" onClick={() => toggleMenu("search")}><Search size={20} /></button>
              {menu === "search" && (
                <div className="popover popover--search">
                  <input autoFocus placeholder="Buscar documentos, reuniões, pendências..." aria-label="Buscar no projeto" />
                  <p className="popover-hint">Comece a digitar para buscar no contexto do projeto.</p>
                </div>
              )}
            </div>
            <div className="topbar-menu">
              <button className="notification-button" aria-label="Notificações" onClick={() => { toggleMenu("notifications"); setNotifRead(true); }}><Bell size={20} />{!notifRead && <i />}</button>
              {menu === "notifications" && (
                <div className="popover popover--notifications">
                  <div className="popover-head">Notificações</div>
                  {notifications.map((item) => (
                    <div className="popover-row" key={item.title}><strong>{item.title}</strong><span>{item.detail} <b>•</b> {item.age}</span></div>
                  ))}
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
          <header className="chat-header"><div className="ai-avatar"><Sparkles size={16} /></div><div><strong>Assistente do projeto</strong><span><i /> Contexto atualizado</span></div><button className="icon-button" onClick={() => setChatOpen(false)} aria-label="Fechar chat"><X size={19} /></button></header>
          <div className="chat-messages">
            {messages.map((message, index) => (
              <div className={`message message--${message.role}`} key={`${message.role}-${index}`}>
                <p>{message.text}</p>
                {message.sources && <div className="message-sources">{message.sources.map((source) => <span key={source}><FileText size={12} /> {source}</span>)}</div>}
                {message.pending && <small className="pending-created"><Check size={13} /> Pendência criada para Portal Labs</small>}
              </div>
            ))}
          </div>
          <div className="chat-suggestions">{suggestedQuestions.map((item) => <button key={item} onClick={() => sendQuestion(undefined, item)}>{item}</button>)}</div>
          <form className="chat-form" onSubmit={sendQuestion}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Pergunte sobre o projeto..." aria-label="Pergunta para IA" /><button type="submit" aria-label="Enviar pergunta"><Send size={17} /></button></form>
        </section>
      )}
    </main>
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
  if (!roi || roi.ratio == null) return { value: "+142%", note: "↑ 18% desde o último mês", positive: true };
  const pct = Math.round(roi.ratio * 100);
  const note = roi.net != null
    ? `R$ ${roi.net.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} de retorno`
    : "Retorno estimado do projeto";
  return { value: `${pct >= 0 ? "+" : ""}${pct}%`, note, positive: pct >= 0 };
}

function OverviewView({ onAsk, onAnalyze, overview, user }: { onAsk: () => void; onAnalyze: () => void; overview: Overview; user: PortalUser }) {
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
        <div className="status-meta"><span>{overview.completion}% concluído</span><div className="progress"><i style={{ width: `${overview.completion}%` }} /></div><small>{overview.source === "live" ? "Sincronizado com o Biahflow" : "Atualizado há 2 dias"}</small></div>
        <button className="details-link">Ver detalhes <ArrowUpRight size={15} /></button>
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
          <div className="panel-heading"><div><p className="eyebrow">PRÓXIMOS MARCOS</p><h2>Cronograma</h2></div><button className="text-button">Ver cronograma <ArrowUpRight size={14} /></button></div>
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
          <div className="panel-heading"><div><p className="eyebrow">ACOMPANHAMENTO</p><h2>Pendências abertas <span>{open.length}</span></h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
          <div className="pending-list">
            {open.length === 0 && <p className="empty-state">Nenhuma pendência aberta.</p>}
            {open.slice(0, 4).map((item) => <PendingItem key={item.title} item={item} />)}
          </div>
          <button className="text-button full-width">Ver todas as pendências <ArrowUpRight size={14} /></button>
        </article>
      </section>

      <section className="bottom-grid">
        <article className="panel source-panel">
          <div className="panel-heading"><div><p className="eyebrow">CONHECIMENTO DO PROJETO</p><h2>Atualizações recentes</h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
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
        <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Encontros recentes <span>{overview.meetings.length}</span></h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
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
          <div className="panel-heading"><div><p className="eyebrow">ACOMPANHAMENTO</p><h2>Abertas <span>{open.length}</span></h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
          <div className="pending-list">
            {open.length === 0 && <p className="empty-state">Nenhuma pendência aberta.</p>}
            {open.map((item) => <PendingItem key={item.title} item={item} />)}
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2>Resolvidas <span>{resolved.length}</span></h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
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
  const roi = roiValue(overview.roi);
  const hoursSaved = overview.digitalEmployees.reduce((total, employee) => total + (employee.hoursSavedMonth ?? 0), 0);
  const savings = overview.roi?.net ?? null;
  const results = overview.results;

  const cards = [
    { icon: TrendingUp, tone: "green", label: "ROI do projeto", value: roi.value, note: roi.note, positive: roi.positive },
    { icon: Clock3, tone: "purple", label: "Horas economizadas", value: hoursSaved > 0 ? `${hoursSaved}h/mês` : "—", note: hoursSaved > 0 ? "Somadas dos Funcionários Digitais" : "Sem funcionário digital ativo" },
    { icon: TrendingUp, tone: "", label: "Economia estimada", value: savings !== null ? BRL.format(savings) : "—", note: savings !== null ? "Valor líquido do projeto" : "Sem valor apurado" },
    // DEMO — sem fonte até a Fase 3 (eventos dos agentes). Ver ROADMAP.md.
    { icon: Zap, tone: "", label: "Transações automatizadas", value: "12,4k", note: "Últimos 30 dias" },
    { icon: Target, tone: "green", label: "Precisão do fluxo", value: "98,6%", note: "↑ 2,1 p.p. no mês", positive: true },
    { icon: Check, tone: "purple", label: "Exceções tratadas", value: "1.203", note: "87% sem intervenção humana" },
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
        <div className="panel-heading"><div><p className="eyebrow">DADOS PESSOAIS</p><h2>Informações da conta</h2></div><button className="details-link">Editar <ArrowUpRight size={15} /></button></div>
        <div className="profile-head">
          <span className="avatar avatar--lg">{user.initials}</span>
          <div><strong>{user.name}</strong><span>{user.role} <b>•</b> {user.org}</span></div>
        </div>
        <div className="field-list">
          {fields.map((field) => (
            <div className="field-row" key={field.label}><span className="field-label">{field.label}</span><span className="field-value">{field.value}</span></div>
          ))}
        </div>
      </article>
    </>
  );
}

function SettingsView({ onAsk }: { onAsk: () => void }) {
  const toggles = [
    { label: "Notificações por e-mail", detail: "Resumo semanal e avisos de pendências", on: true },
    { label: "Notificações no portal", detail: "Alertas de novas atualizações do projeto", on: true },
    { label: "Resumo de reuniões por IA", detail: "Receber transcrição e decisões extraídas", on: false },
  ];
  const prefs = [
    { label: "Idioma", value: "Português (Brasil)" },
    { label: "Fuso horário", value: "(GMT-3) São Paulo" },
    { label: "Tema", value: "Claro" },
  ];
  return (
    <>
      <ViewHero eyebrow="PREFERÊNCIAS" title="Configurações" subtitle="Ajuste como o portal se comporta para você." onAsk={onAsk} />
      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">NOTIFICAÇÕES</p><h2>Avisos</h2></div></div>
          <div className="setting-list">
            {toggles.map((item) => (
              <div className="setting-row" key={item.label}>
                <div><strong>{item.label}</strong><span>{item.detail}</span></div>
                <span className={`switch ${item.on ? "switch--on" : ""}`} aria-hidden="true"><i /></span>
              </div>
            ))}
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">REGIÃO</p><h2>Preferências</h2></div></div>
          <div className="field-list">
            {prefs.map((pref) => (
              <div className="field-row" key={pref.label}><span className="field-label">{pref.label}</span><span className="field-value">{pref.value}</span></div>
            ))}
          </div>
          <button className="ai-button settings-save"><Check size={16} /> Salvar alterações</button>
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
      <button onClick={() => onNavigate("Configurações")}><Settings size={15} /> Configurações</button>
      <button onClick={() => onNavigate("Trocar projeto")}><Building2 size={15} /> Trocar projeto</button>
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
      <button className="icon-button"><MoreHorizontal size={17} /></button>
    </div>
  );
}
