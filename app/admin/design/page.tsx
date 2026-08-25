import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import DesignSystemClient from "./DesignSystemClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiMe = { is_internal: boolean };

/**
 * A vitrine do sistema de design do One (F-025 T04, DAP §§02–05).
 *
 * Ela existe para que `BROWSER_REQUIRED` seja verificável sem encenar estado raro em dado
 * de produção: os quatro estados semânticos, as quatro variantes de botão, o foco, os raios
 * e a paleta ficam a um clique de quem precisa conferir — em vez de dependerem de um
 * cliente que por acaso tenha uma pendência vencida e um documento infectado no mesmo dia.
 *
 * **Nenhuma leitura de dado de projeto.** A única chamada é `GET /api/v1/me`, e ela serve
 * só para decidir se a tela abre. Como em `app/admin/page.tsx`, o `notFound()` para quem
 * não é interno é ergonomia e não segurança: a autoridade é a API, que responde 404. Aqui
 * não há nem isso a proteger — a página não mostra dado de ninguém —, e o portão continua
 * valendo porque uma tela interna que abre para o cliente ensina o vocabulário errado.
 *
 * Ao contrário de `app/admin/page.tsx`, **não** exige projeto: a vitrine mostra o sistema,
 * não o produto, e um interno recém-vinculado sem projeto tem tanto direito a ela quanto
 * qualquer outro.
 */
export default async function DesignSystemPage() {
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
  if (!me.is_internal) notFound();

  return <DesignSystemClient />;
}
