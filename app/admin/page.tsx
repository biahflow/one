import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import MembersClient, { type Member } from "./MembersClient";

// Administração é por usuário e por requisição, como o dashboard.
export const dynamic = "force-dynamic";

const ROLE_LABELS: Record<string, string> = {
  internal_admin: "Administrador Portal Labs",
  internal_member: "Time Portal Labs",
  client_member: "Cliente",
};

type ApiMe = {
  is_internal: boolean;
  organization: string | null;
  projects: { id: string; name: string; slug: string; status: string }[];
};

type ApiMember = {
  membership_id: string;
  email: string;
  full_name: string;
  role: string;
  active: boolean;
};

/**
 * Administração de **acesso**: quem enxerga qual projeto (ADR 0011).
 *
 * Não há tela para criar organização ou projeto, e não deve haver: o catálogo
 * vem do Biahflow (ADR 0006/0008) e originá-lo aqui dividiria a fonte da
 * verdade.
 *
 * O `notFound()` para quem não é interno é ergonomia, não segurança — a API
 * responde 404 para quem não tem `internal_admin` no projeto, e é ela a
 * autoridade.
 */
export default async function AdminPage({
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

  const membersResponse = await fetch(
    `${base}/api/v1/admin/projects/${project.id}/members`,
    { headers: authorization, cache: "no-store" },
  );
  // 404 aqui significa "você não é internal_admin neste projeto" — a mesma
  // resposta que um projeto inexistente daria, de propósito.
  if (membersResponse.status === 404) notFound();
  if (!membersResponse.ok) {
    throw new Error(`GET members respondeu ${membersResponse.status}`);
  }

  const members: Member[] = ((await membersResponse.json()) as ApiMember[]).map(
    (member) => ({
      membershipId: member.membership_id,
      email: member.email,
      fullName: member.full_name,
      role: member.role,
      roleLabel: ROLE_LABELS[member.role] ?? member.role,
      active: member.active,
    }),
  );

  return (
    <MembersClient
      organization={me.organization ?? ""}
      projects={me.projects.map((candidate) => ({
        id: candidate.id,
        name: candidate.name,
        current: candidate.id === project.id,
      }))}
      projectName={project.name}
      projectId={project.id}
      members={members}
    />
  );
}
