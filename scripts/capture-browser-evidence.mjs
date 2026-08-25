#!/usr/bin/env node
/**
 * A evidência de navegador da F-025, presa à revisão que a produziu (T05).
 *
 *     node scripts/capture-browser-evidence.mjs
 *
 * Mora em `scripts/` pela razão do `backup.sh`, do `loadtest.py`, do `audit.mjs` e do
 * `pins.mjs`: é **operação**. Não sobe rota, não é importado pela aplicação, e roda
 * quando alguém o chama — com a pilha local de pé (`docker compose up -d --build`).
 *
 * ## Por que existe
 *
 * `BROWSER_REQUIRED` não se satisfaz com suíte unitária verde. O que a F-025 mudou é
 * **o que a pessoa vê**, e um teste que casa string em HTML renderizado não prova que a
 * marca coube, que o anel de foco aparece nem que a pastilha de estado carrega ícone. A
 * prova é a imagem — e uma imagem sem procedência não prova nada, porque não se sabe de
 * qual código ela saiu. Daí o manifesto ao lado, com o SHA, a rota, o ator e o viewport
 * de cada captura.
 *
 * ## As cinco decisões
 *
 * **1. Sem modelo no laço.** O script clica, espera e captura; nenhuma chamada a LLM,
 * nem para escolher recorte nem para descrever imagem. É a regra de FinOps de
 * `workflows/browser-runtime-validation.md`, e é o que torna a captura repetível: rodar
 * de novo na mesma revisão devolve as mesmas imagens.
 *
 * **2. O foco é alcançado por teclado de verdade.** `page.keyboard.press("Tab")` até o
 * controle, contando as tabuladas — nunca `element.focus()` e nunca uma classe injetada.
 * Foco que só existe porque o script o desenhou não prova que o produto é operável por
 * teclado; prova que o script sabe escrever CSS. O manifesto guarda quantas tabuladas
 * foram, qual controle recebeu o foco e **a cor que o anel tinha na hora**.
 *
 * **3. A espera é por condição, nunca por relógio.** E aqui há uma armadilha medida: o
 * `:focus-visible` do `globals.css` pinta o anel com `--color-focus`, mas os controles do
 * shell trazem `transition-colors`, cuja lista inclui `outline-color`. Capturar no
 * instante seguinte ao `Tab` congela o anel **no meio da transição** — a primeira medição
 * devolveu `rgb(98, 116, 142)`, que é o `currentColor` de onde a animação partiu, e não
 * o roxo da marca. Quem lesse aquela captura concluiria que o produto diverge do pacote
 * aprovado. A espera é, portanto, pelo anel ter assentado no valor do token; se ele não
 * assentar, o manifesto registra `settled: false` com a cor observada, em vez de o script
 * fingir que assentou.
 *
 * **4. A árvore precisa estar limpa, e é o script que recusa.** Evidência que aponta para
 * revisão diferente da que está sob revisão é `REVIEW_EVIDENCE_INCOMPLETE`, e o único
 * momento em que dá para saber isso é aqui. Modificação pendente fora do próprio script e
 * do diretório de saída faz a captura **recusar** — o conserto é comitar, não uma flag de
 * exceção, que seria o mecanismo silencioso que o `audit.mjs` recusa ter.
 *
 * **5. O que não existe no produto não é encenado.** A superfície de revisão/decisão do
 * cliente é **reservada** pelo DAP §10 — "ele não é renderizado; não entra na tela do
 * cliente desabilitado, nem só para mostrar" —, então não há tela dela a capturar. O
 * manifesto declara isso em `reserved`, nomeando a captura congelada do pacote de design e
 * a vitrine, que é onde a linguagem daquela superfície pode ser conferida. Inventar a tela
 * para a foto seria o defeito da ADR 0026 com uma câmera junto.
 *
 * ## Códigos de saída
 *
 * `0` capturou · `1` recusou (árvore suja: a evidência apontaria para outra revisão) ·
 * `2` não consegui medir (portal fora do ar, sem git). A distinção entre 1 e 2 é a do
 * `audit.mjs`: achar problema não é a mesma coisa que não ter conseguido olhar.
 */

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { promisify } from "node:util";

import { chromium } from "playwright";

// Os atores vêm de onde eles já moram. `tests/e2e/atores.ts` é "quem entra, e em qual
// projeto — num lugar só", e uma segunda cópia das três contas aqui seria exatamente a
// divergência que aquele módulo foi criado para fechar (o argumento do `textfold.py`).
// Node 24 remove os tipos de um `.ts` importado sem transpilador, então o reúso não custa
// build; e importar não altera spec nenhum, que é o que a T05 põe fora de escopo.
import { ADMIN, CLIENTE, signIn } from "../tests/e2e/atores.ts";

const run = promisify(execFile);

const BASE_URL = process.env.CAPTURE_BASE_URL ?? process.env.E2E_BASE_URL ?? "http://localhost:3000";

/** Os dois viewports que a Issue #46 nomeia. 1× de propósito: o pacote já custou megabytes. */
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const FEATURE = "F-025-o-nome-que-a-tela-ainda-nao-sabia";
const OUT_DIR = `docs/features/${FEATURE}/evidence/browser`;
const SELF = "scripts/capture-browser-evidence.mjs";
const DAP = `docs/features/${FEATURE}/design/one-dap-r4.html`;

/** Fora deste par, arquivo pendente significa que a captura descreveria outro código. */
const WRITE_SCOPE = [SELF, `${OUT_DIR}/`];

async function git(...args) {
  const { stdout } = await run("git", args);
  return stdout.trim();
}

/**
 * A revisão que a captura vai declarar — e a recusa quando ela não descreve o que roda.
 *
 * O diretório de saída e o próprio script ficam de fora da conta porque são o que esta
 * tarefa acrescenta: na primeira execução eles são justamente o que ainda não está
 * comitado, e cobrá-los tornaria a captura impossível de produzir uma primeira vez.
 */
async function revision() {
  const [sha, subject, committedAt, branch] = await Promise.all([
    git("rev-parse", "HEAD"),
    git("log", "-1", "--format=%s"),
    git("log", "-1", "--format=%cI"),
    git("rev-parse", "--abbrev-ref", "HEAD"),
  ]);

  // Duas armadilhas medidas, e as duas mordiam **esta** guarda.
  //
  // `-uall` não é detalhe de formatação: sem ele o git colapsa um diretório inteiramente
  // novo numa linha só — `docs/…/evidence/` —, que é *prefixo* do caminho permitido e não
  // começa por ele, de modo que o diretório de saída desta própria tarefa aparecia como
  // trabalho pendente. Aceitar prefixo curaria o sintoma e abriria o buraco, porque um
  // diretório novo com **outros** arquivos dentro passaria pela mesma frouxidão; listar
  // arquivo por arquivo é perguntar o que se precisa saber.
  //
  // E a saída não pode ser aparada: o formato é `XY caminho`, e num arquivo modificado e
  // não preparado o `X` é **espaço**. Um `trim()` come a primeira coluna da primeira linha
  // e o caminho sai com dois caracteres a menos — a guarda recusava, o que estava certo,
  // nomeando `pp/globals.css`, que não existe.
  const { stdout } = await run("git", ["status", "--porcelain", "-uall"]);
  const pending = stdout
    .split("\n")
    .filter(Boolean)
    // `R  velho -> novo` guarda dois caminhos; o que interessa é onde o arquivo está agora.
    .map((line) => line.slice(3).split(" -> ").pop())
    .filter((path) => !WRITE_SCOPE.some((allowed) => path === allowed || path.startsWith(allowed)));

  return { sha, short: sha.slice(0, 7), subject, committed_at: committedAt, branch, pending };
}

/** O portal responde? Sem isto, o erro sai como um timeout do Playwright dez linhas abaixo. */
async function portalIsUp() {
  try {
    const response = await fetch(`${BASE_URL}/login`, { redirect: "manual" });
    return response.status < 500;
  } catch {
    return false;
  }
}

/**
 * A união de vários elementos, em coordenadas **do documento**.
 *
 * Documento e não viewport porque o recorte que interessa costuma estar abaixo da dobra —
 * os cartões do seed começam em y≈935 numa janela de 900 —, e `clip` com `fullPage`
 * mede a partir do topo da página.
 */
function unionBox(page, selectors, padding = 16) {
  return page.evaluate(
    ([list, pad]) => {
      let box = null;
      for (const selector of list) {
        const element = document.querySelector(selector);
        if (!element) throw new Error(`o recorte pede "${selector}", que não está na tela`);
        const rect = element.getBoundingClientRect();
        const current = {
          left: rect.left + window.scrollX,
          top: rect.top + window.scrollY,
          right: rect.right + window.scrollX,
          bottom: rect.bottom + window.scrollY,
        };
        box = box
          ? {
              left: Math.min(box.left, current.left),
              top: Math.min(box.top, current.top),
              right: Math.max(box.right, current.right),
              bottom: Math.max(box.bottom, current.bottom),
            }
          : current;
      }
      return {
        x: Math.max(0, Math.round(box.left - pad)),
        y: Math.max(0, Math.round(box.top - pad)),
        width: Math.round(box.right - box.left + pad * 2),
        height: Math.round(box.bottom - box.top + pad * 2),
      };
    },
    [selectors, padding],
  );
}

/** O dashboard do cliente carregado de verdade — não o "Buscando seu projeto…" do SSR. */
async function clientDashboardIsReady(page) {
  await page.getByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ }).waitFor();
  await page.waitForLoadState("networkidle");
}

const captured = [];

async function capture(page, { id, requirement, route, actor, viewport, clip, fullPage = false, notes, extra }) {
  const file = `${id}.png`;
  const bytes = await page.screenshot({ path: `${OUT_DIR}/${file}`, clip, fullPage, animations: "disabled" });
  captured.push({
    id,
    requirement,
    file,
    route,
    actor,
    viewport: `${viewport.width}×${viewport.height}`,
    device_scale_factor: 1,
    crop: clip ? { ...clip, unit: "css px, coordenadas do documento" } : null,
    full_page: fullPage,
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    notes,
    ...(extra ?? {}),
  });
  console.log(`  ${file} · ${(bytes.length / 1024).toFixed(0)} KB`);
}

/**
 * Tabula até o controle pedido e devolve o que o navegador diz sobre o foco resultante.
 *
 * O teto existe para o script morrer com uma frase legível em vez de tabular para sempre
 * quando um controle deixa de ser alcançável por teclado — que, se acontecer, é achado de
 * acessibilidade e não defeito do script.
 */
async function tabTo(page, selector, limit = 60) {
  for (let presses = 1; presses <= limit; presses += 1) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((css) => document.activeElement?.matches(css) ?? false, selector)) {
      return presses;
    }
  }
  throw new Error(`"${selector}" não foi alcançado em ${limit} tabuladas — ver decisão 2`);
}

/** O anel como o navegador o pinta, e se ele já é o do token (ver decisão 3). */
async function focusRing(page) {
  const token = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-focus").trim(),
  );
  let settled = true;
  try {
    await page.waitForFunction(
      (expected) => {
        const style = getComputedStyle(document.activeElement);
        const probe = document.createElement("span");
        probe.style.color = expected;
        document.body.append(probe);
        const resolved = getComputedStyle(probe).color;
        probe.remove();
        return style.outlineColor === resolved;
      },
      token,
      { timeout: 5_000 },
    );
  } catch {
    settled = false;
  }
  const observed = await page.evaluate(() => {
    const element = document.activeElement;
    const style = getComputedStyle(element);
    return {
      control: element.className.toString(),
      accessible_name: (element.getAttribute("aria-label") ?? element.textContent ?? "").trim(),
      matches_focus_visible: element.matches(":focus-visible"),
      outline_color: style.outlineColor,
      outline_width: style.outlineWidth,
      outline_offset: style.outlineOffset,
    };
  });
  return { ...observed, focus_token: token, settled };
}

async function main() {
  let head;
  try {
    head = await revision();
  } catch (error) {
    console.error(`não consegui ler a revisão do git: ${error.message}`);
    return 2;
  }

  if (head.pending.length > 0) {
    console.error(
      "recuso capturar: há trabalho pendente fora do escopo desta tarefa, e a evidência " +
        `declararia ${head.short} descrevendo outro código.\n` +
        head.pending.map((path) => `  ${path}`).join("\n") +
        "\nComite antes de capturar (ver decisão 4).",
    );
    return 1;
  }

  if (!(await portalIsUp())) {
    console.error(
      `o portal não respondeu em ${BASE_URL}/login — suba a pilha antes ` +
        "(`docker compose up -d --build`, e espere o Keycloak).",
    );
    return 2;
  }

  await mkdir(OUT_DIR, { recursive: true });
  // Imagem de execução anterior é imagem de outra revisão até prova em contrário, e o
  // manifesto não teria como desmenti-la: ela some antes, não depois.
  for (const stale of await readdir(OUT_DIR)) await rm(`${OUT_DIR}/${stale}`);

  const browser = await chromium.launch();
  const openContext = (viewport) =>
    browser.newContext({ baseURL: BASE_URL, viewport, deviceScaleFactor: 1, locale: "pt-BR" });

  console.log(`Capturando ${BASE_URL} na revisão ${head.short} — ${head.subject}`);

  // ---- /login, nas duas larguras. É a única superfície do produto sem sessão. ----
  for (const [id, viewport] of [
    ["01-login-1440x900", DESKTOP],
    ["02-login-390x844", MOBILE],
  ]) {
    const context = await openContext(viewport);
    const page = await context.newPage();
    await page.goto("/login");
    await page.getByRole("button", { name: /Entrar com SSO/ }).waitFor();
    await capture(page, {
      id,
      requirement: "`/login`",
      route: "/login",
      actor: "sem sessão",
      viewport,
      notes:
        viewport === MOBILE
          ? "Abaixo de 760px o painel de marca sai (`.auth-brand { display: none }`), como o DAP §08 desenhou."
          : "Wordmark `One.` com o ponto em brand-500 sobre claro, e em brand-200 sobre o gradiente escuro (DAP §01 e §08).",
    });
    await context.close();
  }

  // ---- O shell do cliente, o dado do seed e o foco de teclado. Um ator, uma sessão. ----
  const clientDesktop = await openContext(DESKTOP);
  const client = await clientDesktop.newPage();
  await signIn(client, CLIENTE);
  await clientDashboardIsReady(client);

  await capture(client, {
    id: "03-shell-cliente-1440x900",
    requirement: "shell do cliente — desktop",
    route: "/",
    actor: `${CLIENTE.username} (client_member)`,
    viewport: DESKTOP,
    notes:
      "Sidebar, topbar com sino e busca, e a Visão geral. O nome do projeto e o do cliente vêm " +
      "da API e do token — não há caminho na tela que fabrique dado (DAP §06).",
  });

  await capture(client, {
    id: "05-dashboard-do-seed-1440x900",
    requirement: "dashboard/projeto com dado do seed",
    route: "/",
    actor: `${CLIENTE.username} (client_member)`,
    viewport: DESKTOP,
    clip: await unionBox(client, [".status-card", ".metrics-grid"]),
    fullPage: true,
    notes:
      "Recorte por elemento, e não a página inteira: os cartões começam abaixo da dobra. " +
      "São os números de `seed_data/biahflow-snapshot.json` que `docs/runbooks/passeio-local.md` §3.2 " +
      "manda conferir — Em implementação, No prazo, 68%, Treinamento da operação · 18 set, ROI +142%.",
  });

  // O foco vem depois dos recortes de conteúdo porque tabular rola a página.
  await client.goto("/");
  await clientDashboardIsReady(client);
  const presses = await tabTo(client, ".ai-button");
  const ring = await focusRing(client);
  await capture(client, {
    id: "06-foco-de-teclado-1440x900",
    requirement: "foco de teclado visível num controle real",
    route: "/",
    actor: `${CLIENTE.username} (client_member)`,
    viewport: DESKTOP,
    clip: await unionBox(client, [".hero"]),
    fullPage: true,
    notes:
      "O anel apareceu sozinho, por tabulação: nenhuma classe injetada e nenhum `element.focus()`. " +
      "O controle é o botão primário real do produto (DAP §05, anel de 2px na cor da marca com 2px de afastamento).",
    extra: { keyboard_focus: { tab_presses: presses, reached_by: 'page.keyboard.press("Tab")', ...ring } },
  });
  await clientDesktop.close();

  // ---- O mesmo shell em 390×844. ----
  const clientMobile = await openContext(MOBILE);
  const mobile = await clientMobile.newPage();
  await signIn(mobile, CLIENTE);
  await clientDashboardIsReady(mobile);
  await capture(mobile, {
    id: "04-shell-cliente-390x844",
    requirement: "shell do cliente — mobile",
    route: "/",
    actor: `${CLIENTE.username} (client_member)`,
    viewport: MOBILE,
    notes:
      "Abaixo de 760px a sidebar sai da coluna e vira gaveta atrás do botão de menu; o conteúdo " +
      "ocupa a largura inteira (DAP §07).",
  });
  await clientMobile.close();

  // ---- A vitrine. Superfície interna, então o ator muda. ----
  const staffDesktop = await openContext(DESKTOP);
  const staff = await staffDesktop.newPage();
  await signIn(staff, ADMIN);
  await staff.goto("/admin/design");
  await staff.getByRole("heading", { level: 1, name: "A vitrine do One" }).waitFor();
  // A paleta é lida da folha de estilo no cliente; sem esperá-la, a captura pega
  // "Lendo a folha de estilo…" e a evidência do sistema seria a de um spinner.
  await staff.locator(".design-swatch").first().waitFor();
  await staff.waitForLoadState("networkidle");

  await capture(staff, {
    id: "07-estados-semanticos-1440x900",
    requirement: "os quatro estados semânticos com ícone + texto + cor",
    route: "/admin/design",
    actor: `${ADMIN.username} (internal_admin)`,
    viewport: DESKTOP,
    clip: await unionBox(staff, ["article.panel"]),
    fullPage: true,
    notes:
      "sucesso, atenção, falha e informativo — cada um com ícone junto do texto, que é o que faz o " +
      "estado sobreviver a daltonismo e à impressão em cinza (DAP §04, decisão 6).",
  });

  await capture(staff, {
    id: "08-vitrine-1440x900",
    requirement: "a vitrine `/admin/design`",
    route: "/admin/design",
    actor: `${ADMIN.username} (internal_admin)`,
    viewport: DESKTOP,
    fullPage: true,
    notes:
      "A página inteira: estados, as quatro variantes de botão com o desabilitado, o campo em repouso " +
      "e com foco, os três raios, a paleta lida da folha de estilo e as razões de contraste recalculadas " +
      "no navegador. Ela responde 404 para quem não é interno.",
  });
  await staffDesktop.close();

  const version = browser.version();
  await browser.close();

  // Por id, e não pela ordem em que saíram: a sessão do cliente serve três capturas seguidas
  // e a do celular vem depois, o que deixaria o manifesto contando a história do script em
  // vez da lista que a T05 pede conferida.
  const ordered = [...captured].sort((a, b) => a.id.localeCompare(b.id));

  const manifest = {
    feature: "F-025",
    task: "T05",
    generated_at: new Date().toISOString(),
    generated_by: `node ${SELF}`,
    model_in_the_loop: false,
    revision: {
      sha: head.sha,
      short: head.short,
      subject: head.subject,
      committed_at: head.committed_at,
      branch: head.branch,
      pending_outside_this_task: head.pending,
      note:
        "É a revisão do código de produto que produziu as imagens. A T05 não toca código de produto — " +
        `acrescenta ${SELF} e este diretório —, então o commit que congela esta evidência tem ${head.short} ` +
        "como pai e nada entre os dois muda o que foi fotografado.",
    },
    design_approval: {
      package: DAP,
      revision: 4,
      approved_on: "2026-08-25",
      record: `docs/features/${FEATURE}/design-approval.md`,
    },
    runtime: {
      base_url: BASE_URL,
      stack: "docker compose local (web, api, worker, beat, postgres+pgvector, redis, minio, keycloak, mailpit, drive-stub)",
      browser: `chromium ${version}`,
      engine: "playwright",
      device_scale_factor: 1,
      locale: "pt-BR",
      emulation: "apenas viewport — sem emulação de toque, para que a diferença capturada seja a do CSS",
      data: "o seed local (`seed_data/biahflow-snapshot.json`), pelas contas de `docs/runbooks/passeio-local.md`",
    },
    captures: ordered,
    reserved: [
      {
        requirement: "estado de revisão/decisão do cliente",
        product_surface: null,
        status: "reservado — não renderizado",
        why:
          "O DAP §10 desenha a superfície e a declara reservada: ela vira real quando existir contrato de " +
          "projeção com `approvals` chegando de verdade e evento `client.accepted` de volta (ADR 0067). " +
          "Até lá o pacote é explícito — “ele não é renderizado; não entra na tela do cliente desabilitado, " +
          "nem só para mostrar”, porque controle inerte é defeito e não placeholder (ADR 0026). Não há tela " +
          "no produto a fotografar, e encenar uma faria esta evidência afirmar que ela existe.",
        design_evidence: `docs/features/${FEATURE}/design/captures-r4/10-revisao-e-aceite.png`,
        product_evidence: ["07-estados-semanticos-1440x900", "08-vitrine-1440x900"],
        product_evidence_means:
          "o que existe no produto é a linguagem com que aquela superfície será construída — as pastilhas de " +
          "estado e as variantes de botão da vitrine. É isso que estas duas capturas mostram, e nada além.",
      },
    ],
    coverage: {
      total_bytes: captured.reduce((sum, item) => sum + item.bytes, 0),
      requirements: [
        ...ordered.map((item) => ({ requirement: item.requirement, evidence: item.id })),
        { requirement: "estado de revisão/decisão do cliente", evidence: "ver `reserved`" },
      ],
    },
  };

  await writeFile(`${OUT_DIR}/manifest.json`, `${JSON.stringify(manifest, null, 2)}\n`);
  const total = manifest.coverage.total_bytes;
  console.log(`\n${captured.length} capturas · ${(total / 1024).toFixed(0)} KB · manifest.json em ${OUT_DIR}`);
  return 0;
}

process.exitCode = await main();
