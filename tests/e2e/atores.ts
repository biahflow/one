/**
 * Quem entra, e em qual projeto — num lugar só.
 *
 * O `signIn` existia em **seis cópias**, uma por spec, com duas variações de
 * `waitForURL` que ninguém escolheu de propósito. Isso já era ruim por si, mas o
 * que motivou juntá-las foi o segundo problema, que é de correção e não de
 * repetição: **os specs não diziam em qual projeto trabalhavam.**
 *
 * Uma pessoa interna tem vínculo organizacional (`project_id IS NULL`), e daí
 * `access.default_project` resolve por `created_at DESC` — "o projeto mais
 * recente da organização mais recente". As telas de administração fazem o
 * equivalente com `me.projects[0]`. Nenhuma das duas é errada; as duas são
 * **relativas ao que existe no banco**. Num banco que acumulou uma segunda
 * organização — o passeio de `docs/runbooks/integracao-biahflow.md`, que o
 * próprio runbook manda percorrer — o upload de um spec vai para um tenant e a
 * pergunta do cliente roda em outro, e a suíte reprova quatro vezes por um
 * motivo que não é defeito do produto.
 *
 * `projetoDoSeed` fecha isso resolvendo o id **pela tela**, e não por constante:
 * o uuid é `uuid4()` (`db/base.py`), então não há valor a cravar. Os specs
 * passam a navegar com `?project=<id>`, que as cinco páginas já aceitam.
 */
import { expect, type Page } from "@playwright/test";

export const SENHA = "portal_local_only";

/** Cliente, vínculo **direto** no projeto — para ela `default_project` já é determinístico. */
export const CLIENTE = { username: "marina.farias", password: SENHA, firstName: "Marina" };
/** Interna `internal_admin`: a única que alcança `/admin/*` (`access.ADMIN_ONLY`). */
export const ADMIN = { username: "helena.dias", password: SENHA, firstName: "Helena" };
/**
 * Interno `internal_member`. **Não** alcança `/admin/*` — e isso é contrato, não
 * limitação: `admin.py:_authorized` exige `internal_admin` e responde 404.
 * Serve para o caso negativo, que é onde ele é o ator certo e insubstituível.
 */
export const MEMBRO_INTERNO = { username: "rafael.costa", password: SENHA, firstName: "Rafael" };

/** O projeto que `seed_data/biahflow-snapshot.json` cria. */
export const PROJETO_DO_SEED = "Automação Financeira";

type Ator = { username: string; password: string };

export async function signIn(page: Page, user: Ator) {
  // Limpa **aqui**, coladinho no `goto`. Limpar no chamador deixa uma janela: a
  // navegação anterior pode ter uma requisição em voo que reescreve o cookie de
  // sessão logo depois, e aí `/login` redireciona para `/` (ele faz isso quando
  // há sessão) e o botão nunca aparece. O sintoma é um timeout esperando um
  // botão numa página que é o dashboard.
  //
  // Colar não fecha a janela inteira, só a encolhe — e o que sobra reprova de
  // verdade, uma vez a cada tantas execuções, quando o teste anterior deixou o
  // chat com uma requisição em voo. Daí o laço: se caímos em `/`, o cookie foi
  // reescrito **depois** do `clearCookies`, e a resposta certa é esperar a rede
  // assentar e limpar de novo, não aumentar o timeout de um botão que não vai
  // aparecer.
  //
  // **A condição do laço é o botão, e não a URL, e isso foi medido.** A primeira
  // versão conferia `page.url()` logo depois do `goto` e só então clicava, sem
  // teto: a reescrita do cookie pode chegar **depois** dessa leitura, e aí o laço
  // dava por boa uma página que virou o dashboard no instante seguinte, com o
  // clique esperando os 120 s inteiros do teste por um botão que não existe mais.
  // Foi assim que `search.spec.ts` reprovou no CI — o sintoma que este laço
  // existe para eliminar, sobrevivendo dentro dele. Perguntar pelo botão, com
  // teto curto, é perguntar pelo que de fato se precisa: se ele não veio, o
  // certo é limpar e tentar de novo, não esperar mais.
  for (let tentativa = 0; ; tentativa += 1) {
    await page.context().clearCookies();
    await page.goto("/login");
    try {
      await page.getByRole("button", { name: /Entrar com SSO/ }).click({ timeout: 15_000 });
      break;
    } catch (erro) {
      if (tentativa >= 2) {
        throw new Error(
          `a tela de login não apareceu em ${page.url()} depois de três limpezas — ` +
            `não é a corrida conhecida, e aumentar a espera esconderia o motivo (${erro})`,
        );
      }
      await page.waitForLoadState("networkidle");
    }
  }

  // Tela do Keycloak, no endereço público — se o `iss` estivesse errado, o
  // navegador nem chegaria aqui.
  await page.waitForURL(/\/realms\/portal-local\/protocol\/openid-connect\/auth/);
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await page.locator("#kc-login").click();
  // As duas exclusões: a de `/login` porque é de onde saímos, e a de `/realms`
  // porque o Keycloak pode reexibir o próprio formulário (senha temporária, por
  // exemplo) e sem ela o `waitForURL` daria por concluído um login que não foi.
  await page.waitForURL(
    (url) => !url.pathname.startsWith("/login") && !url.pathname.startsWith("/realms"),
  );
}

/**
 * O uuid do projeto do seed, resolvido pela UI. Requer sessão de {@link ADMIN}.
 *
 * Dois ramos, porque o banco local tem dois estados legítimos e o helper tem de
 * servir aos dois — quem acabou de subir a pilha tem um projeto só, e quem
 * percorreu o runbook de integração tem três:
 *
 * - **Mais de um projeto:** o seletor existe e cada item é um link que já carrega
 *   o `?project=<id>` de destino. É a fonte mais direta que a tela oferece.
 * - **Um projeto só:** não há seletor a ler, e o único projeto é o do seed — mas
 *   isso é conferido pelo título antes de devolver, senão um banco em estado
 *   inesperado devolveria o id errado em silêncio, que é a classe de defeito que
 *   este helper existe para fechar.
 */
export async function projetoDoSeed(page: Page, nome = PROJETO_DO_SEED): Promise<string> {
  await page.goto("/admin/conhecimento");
  await expect(page.getByRole("heading", { name: /O que o assistente pode citar/ })).toBeVisible();

  const seletor = page.getByRole("navigation", { name: "Escolher projeto" });
  if (await seletor.isVisible().catch(() => false)) {
    const href = await seletor.getByRole("link", { name: nome, exact: true }).getAttribute("href");
    // `base` arbitrária: `href` é relativa e o `URLSearchParams` precisa de uma.
    const id = href && new URL(href, "http://localhost").searchParams.get("project");
    if (!id) throw new Error(`o seletor de projetos não trouxe o id de "${nome}" (href: ${href})`);
    return id;
  }

  const id = await page.locator(".admin-shell").getAttribute("data-project-id");
  if (!id) throw new Error("sem seletor de projetos e sem `data-project-id` — tela inesperada");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(nome);
  return id;
}
