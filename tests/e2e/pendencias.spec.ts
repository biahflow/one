import { expect, test } from "@playwright/test";

import { CLIENTE, MEMBRO_INTERNO, signIn } from "./atores";
import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * Prioridade e filtro na aba onde o cliente decide o que fazer (ADR 0029).
 *
 * O que só este nível prova: que o dado atravessa a corrente inteira até um
 * navegador de verdade. A prioridade é coluna no Postgres desde a Fase 1, o
 * sync a projeta, o contrato a declara — e o mapeamento do BFF a descartava,
 * de modo que toda pendência aparecia igual. `api-contract.test.mjs` pega o
 * descarte no código-fonte; aqui se vê o selo e o filtro funcionando com a
 * sessão real e o read model semeado.
 *
 * O `signIn` daqui era a cópia **antiga**, anterior ao laço de re-limpeza que a
 * ADR 0047 criou para a corrida do `clearCookies` — este spec era o único que
 * ainda a carregava depois de a corrida ter sido diagnosticada.
 */

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
});

test("o filtro de prioridade encolhe a lista e o caminho de volta existe", async ({ page }) => {
  await signIn(page, CLIENTE);
  // Sem `exact`: o item da navegação carrega a contagem de abertas num `<em>`,
  // então o nome acessível é "Pendências 3", não "Pendências".
  await page.getByRole("button", { name: /^Pendências/ }).click();
  await expect(page.getByRole("heading", { name: "Pendências do projeto" })).toBeVisible();

  // Escopado ao painel de abertas: a aba tem dois, e o de resolvidas também usa
  // `.pending-row` — sem o escopo, a contagem inclui o que o filtro não toca.
  const rows = page.locator(".pending-panel .pending-row");
  const total = await rows.count();
  expect(total).toBeGreaterThan(0);

  // O chip diz quantas são antes de clicar — sem o número, escolher é adivinhar.
  const alta = page.getByRole("button", { name: /^Alta/ });
  const declared = Number((await alta.textContent())?.match(/\d+/)?.[0] ?? "-1");
  await alta.click();

  await expect(rows).toHaveCount(declared);
  expect(declared).toBeLessThan(total);

  // "Todas" é sempre a primeira opção: um filtro sem volta esconde dado e
  // parece lista vazia.
  await page.getByRole("button", { name: /^Todas/ }).click();
  await expect(rows).toHaveCount(total);
});

test("a pendência aberta pela IA leva de volta à pergunta que a gerou", async ({ page }) => {
  // **Este teste cria a pendência de que precisa, e é por isso que ele existe assim.**
  // Pendência com `origin='portal'` não vem do snapshot — o seed traz só as do
  // Biahflow —, ela nasce quando o chat não acha evidência e declara a lacuna
  // (`ai/service.py`). Num banco acumulado sempre há uma sobrando de execução
  // anterior, e era nela que este teste se apoiava; num banco novo, que é o do
  // CI, não há nenhuma, e ele reprovava sem nada estar quebrado.
  //
  // Criar em vez de semear é o caminho honesto: o que o teste afirma é que **a
  // lacuna vira pendência com caminho de volta ao turno**, e semear a linha
  // pronta afirmaria sobre o efeito sem passar pela corrente que o produz.
  const termo = `abrolhado${Date.now().toString(36)}`;

  await signIn(page, CLIENTE);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  // Uma pergunta sem token de quatro letras que case com evidência alguma: o
  // `OfflineResponder` só declara lacuna quando **nada** é selecionado, e
  // `_query_tokens` descarta o que tem menos de quatro caracteres — por isso "o
  // que é o", que sozinho não casa nada, e um termo inventado como única palavra
  // com sinal.
  await page.getByLabel("Pergunta para IA").fill(`O que é o ${termo}?`);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  await expect(page.locator(".chat-messages")).toContainText(/Registrei uma pendência/, {
    timeout: 30_000,
  });

  // A aba lê o read model do servidor; o turno acabou de escrever nele.
  await page.reload();
  await page.getByRole("button", { name: /^Pendências/ }).click();

  // Casada pelo termo, e não por "aberta pela IA": o selo é o que se **afirma**,
  // e usá-lo para escolher a linha faria o teste passar apontando para a
  // pendência de outra execução.
  const row = page.locator(".pending-row", { hasText: termo }).first();
  await expect(row).toBeVisible();
  // As do Biahflow não vieram de conversa nenhuma; a da IA veio, e o FK que diz
  // qual turno era lido só como booleano até a ADR 0031.
  await expect(row).toContainText("aberta pela IA");
  await row.getByRole("button", { name: "Ver a pergunta" }).click();

  // O chat abre e o turno apontado é o que fica em destaque — não o último.
  await expect(page.locator(".chat-panel")).toBeVisible();
  await expect(page.locator(".message--focused")).toHaveCount(1);
});

/**
 * O "outro lado" é o `internal_member` (`MEMBRO_INTERNO`), e não a
 * administradora: `helena.dias` tem vínculo org-wide, e numa máquina com uma
 * segunda organização — o passeio da ADR 0025 — o `default_project` dela é o
 * outro projeto e a caixa dela é a de outro tenant. `rafael.costa` pertence só à
 * organização semeada, e é ele quem, no produto, acompanha o projeto.
 */
test("o comentário do cliente chega ao time, com aviso no sino", async ({ page }) => {
  const mark = `combinado-${Date.now().toString(36)}`;

  await signIn(page, CLIENTE);

  /** A contagem do sino, ou 0 quando não há badge. */
  async function unread(): Promise<number> {
    const bell = page.getByRole("button", { name: /^Notificações/ });
    const label = (await bell.getAttribute("aria-label")) ?? "";
    return Number(label.match(/\((\d+)/)?.[1] ?? "0");
  }

  // Medido antes, e não comparado com zero: este banco acumula avisos de sync
  // anteriores, e exigir zero confundiria "não recebeu pelo próprio comentário"
  // com "não tem aviso nenhum".
  const before = await unread();

  await page.getByRole("button", { name: /^Pendências/ }).click();
  const row = page.locator(".pending-entry", { hasText: "Aprovar fluxo de exceções" }).first();
  // O fio abre por clique: oito pendências com todos abertos viram mural.
  await row.getByRole("button", { name: /Comentar|comentário/ }).click();
  await row.getByLabel("Novo comentário").fill(`Já enviei, ${mark}`);
  await row.getByRole("button", { name: "Enviar" }).click();
  await expect(row.getByText(new RegExp(mark))).toBeVisible();

  // Quem escreveu não é avisado do próprio comentário — é o que
  // `exclude_user_id` garante (ADR 0032).
  await page.reload();
  expect(await unread()).toBe(before);

  // E o outro lado vê o comentário e recebe o aviso.
  await signIn(page, MEMBRO_INTERNO);
  await expect(
    page.getByRole("button", { name: /Notificações \(\d+ não lidas\)/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Pendências/ }).click();
  const sameRow = page
    .locator(".pending-entry", { hasText: "Aprovar fluxo de exceções" })
    .first();
  await sameRow.getByRole("button", { name: /comentário/ }).click();
  await expect(sameRow.getByText(new RegExp(mark))).toBeVisible();
});
