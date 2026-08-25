import { Building2 } from "lucide-react";
import { redirect } from "next/navigation";

import { auth, signIn } from "@/auth";
import { Brand } from "@/components/one/Brand";

/**
 * A entrada do portal. Server Component: o botão dispara uma Server Action que
 * inicia o Authorization Code + PKCE contra o Keycloak — não há mais formulário
 * de e-mail/senha, porque a senha nunca chegou a este domínio (ADR 0010).
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const session = await auth();
  if (session && !session.error) redirect("/");

  const { error } = await searchParams;

  async function enter() {
    "use server";
    await signIn("keycloak", { redirectTo: "/" });
  }

  return (
    <main className="auth-shell">
      <aside className="auth-brand">
        <div className="brand-row auth-brand-row">
          <Brand />
        </div>
        <div className="auth-brand-copy">
          <h1>Acompanhe seus projetos de IA em um só lugar.</h1>
          <p>Status, resultados, decisões e um assistente que responde só com evidências do seu projeto.</p>
        </div>
        <p className="auth-brand-foot">Portal do Cliente</p>
      </aside>
      <section className="auth-form-wrap">
        <form className="auth-form" action={enter}>
          <p className="eyebrow">BEM-VINDO DE VOLTA</p>
          <h2>Entrar na sua conta</h2>
          <p className="auth-lead">
            O acesso ao portal é feito pelo login corporativo da sua organização.
          </p>
          {error && (
            <p className="auth-error" role="alert">
              Não foi possível entrar. Tente novamente ou fale com o time da Portal Labs.
            </p>
          )}
          <button type="submit" className="auth-sso">
            <Building2 size={16} /> Entrar com SSO da empresa
          </button>
          <p className="auth-hint">Você será redirecionado para autenticar e volta para cá.</p>
        </form>
      </section>
    </main>
  );
}
