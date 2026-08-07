"use client";

import { ArrowLeft, ArrowRight, Mail, ShieldCheck, UserMinus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { inviteMember, revokeMembership } from "./actions";

export type Member = {
  membershipId: string;
  email: string;
  fullName: string;
  role: string;
  roleLabel: string;
  active: boolean;
};

type ProjectOption = { id: string; name: string; current: boolean };

const ROLE_OPTIONS = [
  { value: "client_member", label: "Cliente" },
  { value: "internal_member", label: "Time Portal Labs" },
  { value: "internal_admin", label: "Administrador Portal Labs" },
];

export default function MembersClient({
  organization,
  projects,
  projectName,
  projectId,
  members,
}: {
  organization: string;
  projects: ProjectOption[];
  projectName: string;
  projectId: string;
  members: Member[];
}) {
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function submitInvitation(formData: FormData) {
    const email = String(formData.get("email") ?? "");
    startTransition(async () => {
      const result = await inviteMember(projectId, formData);
      setMessage(
        result.ok
          ? { tone: "ok", text: `Convite enviado para ${email}.` }
          : { tone: "error", text: result.error },
      );
      // A lista veio do Server Component; sem isto ela fica no estado anterior.
      if (result.ok) router.refresh();
    });
  }

  function revoke(member: Member) {
    startTransition(async () => {
      const result = await revokeMembership(projectId, member.membershipId);
      setMessage(
        result.ok
          ? { tone: "ok", text: `Acesso de ${member.fullName} removido.` }
          : { tone: "error", text: result.error },
      );
      if (result.ok) router.refresh();
    });
  }

  return (
    <main className="admin-shell">
      <header className="admin-head">
        <Link className="admin-back" href="/">
          <ArrowLeft size={16} /> Voltar ao portal
        </Link>
        <p className="eyebrow">ADMINISTRAÇÃO DE ACESSO</p>
        <h1>Quem enxerga {projectName}</h1>
        <p className="admin-lead">
          {organization} · Projetos e organizações vêm do Biahflow; aqui você define quem tem
          acesso a eles.
        </p>
        <Link className="text-button" href={`/admin/resultados?project=${projectId}`}>
          Chaves dos agentes e premissas de ROI <ArrowRight size={15} />
        </Link>
        <Link className="text-button" href={`/admin/conhecimento?project=${projectId}`}>
          Documentos que o assistente pode citar <ArrowRight size={15} />
        </Link>
        <Link className="text-button" href={`/admin/assistente?project=${projectId}`}>
          Como o assistente está indo <ArrowRight size={15} />
        </Link>
        {/* Sem `?project=`, e é a diferença que importa: o escopo desta é a
            organização inteira — prazo de retenção, teto de IA e apagamento não
            são perguntas que se façam projeto a projeto (ADR 0027). */}
        <Link className="text-button" href="/admin/organizacao">
          Retenção, gasto de IA e apagamento da organização <ArrowRight size={15} />
        </Link>
        {/* Também sem `?project=`, e por um motivo próprio: o funil pergunta sobre a
            relação do cliente com o produto, e um cliente pode ter mais de um
            projeto (ADR 0039). Esta é a única tela que olha **todas** as
            organizações administradas de uma vez, porque ranquear por gravidade é
            comparar clientes entre si (ADR 0040). */}
        <Link className="text-button" href="/admin/funil">
          Clientes travados no funil de onboarding <ArrowRight size={15} />
        </Link>
      </header>

      {projects.length > 1 && (
        <nav className="admin-projects" aria-label="Escolher projeto">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/admin?project=${project.id}`}
              className={`state ${project.current ? "state--0" : "state--2"}`}
            >
              {project.name}
            </Link>
          ))}
        </nav>
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
              <p className="eyebrow">MEMBROS</p>
              <h2>{members.length} com acesso</h2>
            </div>
          </div>
          {members.length === 0 && (
            <p className="empty-state">Ninguém tem acesso a este projeto ainda.</p>
          )}
          <div className="field-list">
            {members.map((member) => (
              <div className="member-row" key={member.membershipId}>
                <span className="avatar avatar--small">
                  {member.fullName.slice(0, 1).toLocaleUpperCase("pt-BR")}
                </span>
                <div className="member-identity">
                  <strong>{member.fullName}</strong>
                  <span>{member.email}</span>
                </div>
                <span className={`state ${member.active ? "state--1" : "state--2"}`}>
                  {member.active ? member.roleLabel : "Convite pendente"}
                </span>
                <button
                  className="icon-button"
                  aria-label={`Remover acesso de ${member.fullName}`}
                  disabled={pending}
                  onClick={() => revoke(member)}
                >
                  <UserMinus size={17} />
                </button>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">CONVIDAR</p>
              <h2>Dar acesso a alguém</h2>
            </div>
          </div>
          <p className="admin-lead">
            A pessoa recebe um e-mail para definir a senha e confirmar o endereço. Até fazer
            isso, o convite aparece como pendente.
          </p>
          <form className="admin-form" action={submitInvitation}>
            <label className="auth-field">
              <span>Nome</span>
              <input name="full_name" required placeholder="Nome e sobrenome" />
            </label>
            <label className="auth-field">
              <span>E-mail</span>
              <input name="email" type="email" required placeholder="pessoa@empresa.com" />
            </label>
            <label className="auth-field">
              <span>Papel</span>
              <select name="role" defaultValue="client_member">
                {ROLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="ai-button admin-submit" type="submit" disabled={pending}>
              {pending ? <ShieldCheck size={16} /> : <Mail size={16} />}
              {pending ? "Enviando…" : "Enviar convite"}
            </button>
          </form>
        </article>
      </section>
    </main>
  );
}
