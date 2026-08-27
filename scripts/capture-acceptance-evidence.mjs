#!/usr/bin/env node
/**
 * A evidência de navegador da superfície de aceite (F-027 T08), presa à revisão
 * que a produziu.
 *
 *     npm run build && node scripts/capture-acceptance-evidence.mjs
 *
 * Mora em `scripts/` pela razão do `backup.sh`, do `loadtest.py`, do `audit.mjs`, do
 * `pins.mjs` e do `capture-browser-evidence.mjs`: é **operação**. Não sobe rota, não
 * é importado pela aplicação, e roda quando alguém o chama.
 *
 * ## Por que não é o `capture-browser-evidence.mjs`
 *
 * Aquele script fotografa a pilha local inteira (`docker compose up -d --build`) e é
 * o certo quando ela existe. Aqui ela não existe: **o portal está fora do ar desde
 * 13/08/2026** (ADR 0053), e na máquina em que esta fatia foi construída as portas
 * do Postgres e do MinIO já estão ocupadas por outro ambiente — subir a pilha
 * significaria derrubar o que não é meu. A alternativa honesta não é inventar a
 * foto: é fotografar o **mesmo produto** com a mesma máquina de renderização que o
 * repositório já confia, que é a de `tests/rendered-html.test.mjs` — `next start` de
 * verdade, `proxy.ts` de verdade, `app/page.tsx` de verdade, cookie de sessão
 * cunhado com o `encode()` do próprio Auth.js, e a API servida por um stub.
 *
 * O manifesto **declara isso em `runtime`**, e é o que separa esta evidência de uma
 * afirmação: o que está fotografado é o código desta revisão renderizando as
 * respostas de `tests/fixtures/dashboard.mjs`. O que ela não prova está escrito ao
 * lado, em `does_not_prove`.
 *
 * ## As quatro decisões
 *
 * **1. Sem modelo no laço.** O script clica, espera por condição e captura; nenhuma
 * chamada a LLM. É a regra de FinOps de `workflows/browser-runtime-validation.md`, e
 * é o que torna a captura repetível.
 *
 * **2. O stub guarda estado, e é o que faz o controle provar que age.** O `POST` do
 * aceite **acrescenta** uma linha na lista que o `GET` devolve — nunca reescreve —,
 * do mesmo jeito que o `GRANT` de `portal_app` obriga do outro lado. As capturas de
 * "aprovado" e de "ajuste pedido" saem de um clique de verdade no botão do produto,
 * não de uma fixture pré-cozida: um controle inerte não produziria nenhuma delas.
 *
 * **3. O foco é alcançado por teclado de verdade.** `page.keyboard.press("Tab")` até
 * o controle, contando as tabuladas — nunca `element.focus()`. O manifesto guarda
 * quantas tabuladas foram e a cor que o anel tinha na hora, e diz `settled: false` se
 * ela não assentou no token, em vez de fingir que assentou.
 *
 * **4. A procedência inclui o que ainda não está comitado.** A tarefa entrega a
 * evidência junto do código, então exigir árvore limpa a tornaria impossível de
 * produzir a primeira vez. O manifesto registra o `sha` do `HEAD`, a lista de
 * arquivos pendentes e o **sha256 do `git diff HEAD`** — que é o que permite a quem
 * revisa conferir, com um comando, que a foto descreve exatamente este diff.
 *
 * ## Códigos de saída
 *
 * `0` capturou · `2` não consegui medir (sem build, sem git, servidor não subiu). Não
 * há `1`: este script não julga o produto, só o fotografa.
 */

import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { promisify } from "node:util";

import { encode } from "next-auth/jwt";
import { chromium } from "playwright";

import { DASHBOARD, ME, NOTIFICATIONS, SEARCH } from "../tests/fixtures/dashboard.mjs";

const run = promisify(execFile);
const projectRoot = new URL("../", import.meta.url);

const FEATURE = "F-027-o-aceite-que-a-tela-so-desenhou";
const OUT_DIR = `docs/features/${FEATURE}/evidence/browser`;
const SELF = "scripts/capture-acceptance-evidence.mjs";
const DAP = `docs/features/${FEATURE}/design/one-acceptance.html`;

/** Os dois viewports que o contrato da T08 nomeia. 1× de propósito. */
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const AUTH_SECRET = "portal_auth_test_only";
const SESSION_COOKIE = "authjs.session-token";
/** O entregável entregue e identificado da fixture — o único elegível a revisão. */
const REF = "91";

// --- o stub da API ---------------------------------------------------------

/**
 * As decisões que o stub guarda, por `external_ref`.
 *
 * **Acrescenta e nunca reescreve** (decisão 2). É a mesma regra que a migração 0035
 * impõe por privilégio; aqui ela é convenção, e por isso está escrita.
 */
let decisions = [];
/** Respostas encenadas: `null` é o caminho normal. */
let dashboardOverride = null;
let dashboardStatus = 200;
let acceptanceStatus = 200;

function resetStub() {
  decisions = [];
  dashboardOverride = null;
  dashboardStatus = 200;
  acceptanceStatus = 200;
}

function readBody(request) {
  return new Promise((resolve) => {
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk;
    });
    request.on("end", () => resolve(raw ? JSON.parse(raw) : {}));
  });
}

function startApiStub() {
  const server = createServer(async (request, response) => {
    const url = request.url ?? "";
    const json = (status, body) =>
      response.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(body));

    // O token tem de viajar, e recusar aqui é o que faz a foto provar que ele viajou.
    if (!(request.headers.authorization ?? "").startsWith("Bearer ")) return json(401, {});

    const acceptance = /^\/api\/v1\/me\/deliverables\/([^/?]+)\/acceptance/.exec(url);
    if (acceptance) {
      if (acceptanceStatus !== 200) return json(acceptanceStatus, {});
      if (request.method === "POST") {
        const payload = await readBody(request);
        // Acrescenta. A anterior fica onde estava.
        decisions.push({
          id: `dddddddd-0000-4000-8000-${String(decisions.length + 1).padStart(12, "0")}`,
          deliverable_external_ref: REF,
          phase_name: "Welcome",
          deliverable_name: "Acesso ao portal",
          action: payload.action,
          actor_label: ME.full_name,
          actor_is_internal: false,
          comment: payload.comment ?? null,
          created_at: new Date(Date.now() - (2 - decisions.length) * 86_400_000).toISOString(),
        });
        return json(201, decisions[decisions.length - 1]);
      }
      return json(200, { deliverable_external_ref: REF, items: decisions });
    }

    if (url.startsWith("/api/v1/me/dashboard")) {
      if (dashboardStatus !== 200) return json(dashboardStatus, { detail: "Not found" });
      return json(200, dashboardOverride ?? DASHBOARD);
    }
    if (url.startsWith("/api/v1/me/notifications")) return json(200, NOTIFICATIONS);
    if (url.startsWith("/api/v1/me/search")) return json(200, SEARCH);
    if (url.startsWith("/api/v1/me")) return json(200, ME);
    return json(404, {});
  });

  const listening = new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(`http://127.0.0.1:${server.address().port}`));
  });
  return { server, listening };
}

// --- o portal ---------------------------------------------------------------

async function sessionCookie() {
  const token = await encode({
    token: {
      name: ME.full_name,
      email: ME.email,
      sub: "00000000-0000-4000-8000-000000000001",
      accessToken: "stub-access-token",
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    },
    secret: AUTH_SECRET,
    salt: SESSION_COOKIE,
    maxAge: 3600,
  });
  return { name: SESSION_COOKIE, value: token };
}

async function startPortal(apiBaseUrl) {
  const port = 3900 + Math.floor(Math.random() * 90);
  const child = spawn("npx", ["next", "start", "-p", String(port)], {
    cwd: projectRoot,
    stdio: ["ignore", "pipe", "pipe"],
    // Grupo próprio, para o teardown alcançar o `next-server` que o `npx` lançou.
    detached: true,
    env: { ...process.env, NODE_ENV: "production", AUTH_SECRET, API_BASE_URL: apiBaseUrl, DEMO_MODE: "false" },
  });
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  const origin = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`next start caiu (${child.exitCode}):\n${stderr}`);
    try {
      const probe = await fetch(`${origin}/login`, { headers: { accept: "text/html" } });
      if (probe.ok) return { child, origin };
    } catch {
      // ainda não está ouvindo
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`next start não ficou pronto:\n${stderr}`);
}

// --- procedência ------------------------------------------------------------

async function git(...args) {
  const { stdout } = await run("git", args);
  return stdout;
}

async function revision() {
  const [sha, subject, branch] = await Promise.all([
    git("rev-parse", "HEAD"),
    git("log", "-1", "--format=%s"),
    git("rev-parse", "--abbrev-ref", "HEAD"),
  ]);
  const status = await git("status", "--porcelain", "-uall");
  const pending = status
    .split("\n")
    .filter(Boolean)
    .map((line) => line.slice(3).split(" -> ").pop())
    .filter((path) => !path.startsWith(OUT_DIR));
  const diff = await git("diff", "HEAD");
  return {
    sha: sha.trim(),
    short: sha.trim().slice(0, 7),
    subject: subject.trim(),
    branch: branch.trim(),
    pending,
    // O que torna a procedência conferível apesar da árvore suja (decisão 4):
    // `git diff HEAD | shasum -a 256` na revisão sob revisão devolve este valor.
    diff_sha256: createHash("sha256").update(diff).digest("hex"),
    diff_bytes: Buffer.byteLength(diff),
  };
}

// --- captura ----------------------------------------------------------------

const captured = [];

async function capture(page, { id, requirement, viewport, notes, clip, fullPage = false, extra }) {
  const file = `${id}.png`;
  const bytes = await page.screenshot({ path: `${OUT_DIR}/${file}`, clip, fullPage, animations: "disabled" });
  captured.push({
    id,
    requirement,
    file,
    route: new URL(page.url()).pathname + new URL(page.url()).search,
    actor: `${ME.email} (client_member)`,
    viewport: `${viewport.width}×${viewport.height}`,
    device_scale_factor: 1,
    full_page: fullPage,
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    notes,
    ...(extra ?? {}),
  });
  console.log(`  ${file} · ${(bytes.length / 1024).toFixed(0)} KB`);
}

/** A união de vários elementos, em coordenadas do documento. */
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

async function tabTo(page, selector, limit = 60) {
  for (let presses = 1; presses <= limit; presses += 1) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((css) => document.activeElement?.matches(css) ?? false, selector)) return presses;
  }
  throw new Error(`"${selector}" não foi alcançado em ${limit} tabuladas — ver decisão 3`);
}

/** O anel como o navegador o pinta, e se ele já assentou no token. */
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

/** A aba de Revisão, aberta e hidratada. */
async function openReview(page) {
  await page.goto("/?tab=Revis%C3%A3o");
  await page.getByRole("heading", { level: 1, name: "Revisão e aceite" }).waitFor();
  await page.waitForLoadState("networkidle");
}

async function main() {
  let head;
  try {
    head = await revision();
  } catch (error) {
    console.error(`não consegui ler a revisão do git: ${error.message}`);
    return 2;
  }

  const api = startApiStub();
  const apiBaseUrl = await api.listening;

  let portal;
  try {
    portal = await startPortal(apiBaseUrl);
  } catch (error) {
    console.error(`${error.message}\nRode \`npm run build\` antes de capturar.`);
    api.server.close();
    return 2;
  }

  await mkdir(OUT_DIR, { recursive: true });
  // Imagem de execução anterior é imagem de outra revisão até prova em contrário.
  for (const stale of await readdir(OUT_DIR)) await rm(`${OUT_DIR}/${stale}`);

  const browser = await chromium.launch();
  const cookie = await sessionCookie();
  const openContext = async (viewport) => {
    const context = await browser.newContext({
      baseURL: portal.origin,
      viewport,
      deviceScaleFactor: 1,
      locale: "pt-BR",
    });
    await context.addCookies([{ ...cookie, url: portal.origin }]);
    return context;
  };

  console.log(`Capturando ${portal.origin} na revisão ${head.short} — ${head.subject}`);

  for (const [viewport, largura] of [
    [DESKTOP, "1440x900"],
    [MOBILE, "390x844"],
  ]) {
    resetStub();
    const context = await openContext(viewport);
    const page = await context.newPage();

    // ---- aguardando: entregue pela operação, sem decisão do cliente ----
    await openReview(page);
    await page.getByText("Pendente — aguardando você").waitFor();
    await capture(page, {
      id: `01-aguardando-${largura}`,
      requirement: "card de revisão — `ready_for_acceptance`, aguardando o cliente",
      viewport,
      fullPage: true,
      notes:
        "A entrega de engenharia está concluída e o aceite do cliente está pendente, nas duas " +
        "metades do card. Sem essa separação a tela sugeriria que uma coisa é a outra, que é o " +
        "invariante que a fatia inteira nega (DAP decisão 3).",
    });

    // ---- ajuste pedido: um clique de verdade no botão do produto ----
    await page.getByLabel("Comentário da decisão").fill("Faltou o anexo de custos na seção 4.");
    await page.getByRole("button", { name: "Pedir ajuste" }).click();
    await page.getByText("Enviado ao time da Biahflow").waitFor();
    await page.getByText("pediu ajuste").waitFor();
    await capture(page, {
      id: `02-ajuste-pedido-${largura}`,
      requirement: "controle que age — `changes_requested` e a confirmação",
      viewport,
      fullPage: true,
      notes:
        "O estado saiu de um clique no botão real: o comentário foi digitado, a Server Action " +
        "chamou `POST /api/v1/me/deliverables/{ref}/acceptance`, e a confirmação nomeia o time. " +
        "Um controle inerte (ADR 0026) não produziria esta imagem.",
    });

    // ---- aprovado: a segunda decisão acrescenta, e a primeira fica superada ----
    await page.getByLabel("Comentário da decisão").fill("Aprovado. Pode seguir para produção.");
    await page.getByRole("button", { name: "Aprovar entrega" }).click();
    await page.getByText("superada").waitFor();
    await capture(page, {
      id: `03-aprovado-${largura}`,
      requirement: "`accepted` + histórico imutável com supersessão explícita",
      viewport,
      fullPage: true,
      notes:
        "Duas decisões, duas linhas: a mais nova em vigor e a anterior riscada com o rótulo " +
        "«superada». A primeira **não** foi apagada nem reescrita — é o reflexo na tela do " +
        "`GRANT` só de `INSERT` da migração 0035 (DAP decisão 2).",
    });

    await context.close();
  }

  // ---- foco de teclado, num controle real ----
  resetStub();
  {
    const context = await openContext(DESKTOP);
    const page = await context.newPage();
    await openReview(page);
    const presses = await tabTo(page, ".review-actions .btn--primary");
    const ring = await focusRing(page);
    await capture(page, {
      id: "04-foco-de-teclado-1440x900",
      requirement: "foco de teclado visível no controle de decisão",
      viewport: DESKTOP,
      clip: await unionBox(page, [".review-card"]),
      fullPage: true,
      notes:
        "O anel apareceu sozinho, por tabulação: nenhuma classe injetada e nenhum " +
        "`element.focus()`. O controle é o «Aprovar entrega» real do card.",
      extra: { keyboard_focus: { tab_presses: presses, reached_by: 'page.keyboard.press("Tab")', ...ring } },
    });
    await context.close();
  }

  // ---- vazio: nada aguardando você ----
  resetStub();
  dashboardOverride = {
    ...DASHBOARD,
    journey: {
      ...DASHBOARD.journey,
      phases: DASHBOARD.journey.phases.map((phase) => ({
        ...phase,
        deliverables: phase.deliverables.map((d) => ({ ...d, state: "pending" })),
      })),
    },
  };
  {
    const context = await openContext(DESKTOP);
    const page = await context.newPage();
    await openReview(page);
    await page.getByText("Nada aguardando você").waitFor();
    await capture(page, {
      id: "05-vazio-1440x900",
      requirement: "vazio — nada aguardando revisão",
      viewport: DESKTOP,
      fullPage: true,
      notes: "Nenhuma entrega concluída pela operação: não há decisão a pedir do cliente.",
    });
    await context.close();
  }

  // ---- erro: o histórico não carregou ----
  resetStub();
  acceptanceStatus = 500;
  {
    const context = await openContext(DESKTOP);
    const page = await context.newPage();
    await openReview(page);
    await page.getByText("Não consegui carregar o histórico").waitFor();
    await capture(page, {
      id: "06-erro-1440x900",
      requirement: "erro — serviço indisponível",
      viewport: DESKTOP,
      fullPage: true,
      notes:
        "A tela diz que não conseguiu ler, e **não** diz «pendente»: uma lista vazia afirmaria " +
        "que ninguém decidiu sobre um histórico que ela não leu. É a mesma regra de " +
        "`scan_state=skipped` não ser `clean`.",
    });
    await context.close();
  }

  // ---- não autorizado: 404, nunca 403 ----
  resetStub();
  dashboardStatus = 404;
  {
    const context = await openContext(DESKTOP);
    const page = await context.newPage();
    await page.goto("/?tab=Revis%C3%A3o");
    await page.getByText("Você ainda não tem um projeto atribuído.").waitFor();
    await capture(page, {
      id: "07-nao-autorizado-1440x900",
      requirement: "não autorizado — 404, nunca 403",
      viewport: DESKTOP,
      fullPage: true,
      notes:
        "A API respondeu 404, que é a negação padrão do portal: ela não distingue «não existe» " +
        "de «não é seu», e é isso que impede o 403 de confirmar a existência de um projeto a " +
        "quem não deveria saber dela.",
    });
    await context.close();
  }

  const version = browser.version();
  await browser.close();
  api.server.close();
  if (portal.child.pid) {
    try {
      process.kill(-portal.child.pid, "SIGTERM");
    } catch {
      // já morreu
    }
  }

  const ordered = [...captured].sort((a, b) => a.id.localeCompare(b.id));
  const manifest = {
    feature: "F-027",
    task: "T08",
    generated_at: new Date().toISOString(),
    generated_by: `node ${SELF}`,
    model_in_the_loop: false,
    revision: {
      sha: head.sha,
      short: head.short,
      subject: head.subject,
      branch: head.branch,
      pending_at_capture: head.pending,
      diff_sha256: head.diff_sha256,
      diff_bytes: head.diff_bytes,
      note:
        "A superfície ainda não estava comitada quando foi fotografada — a T08 entrega a " +
        "evidência junto do código. `diff_sha256` é o SHA-256 de `git diff HEAD` no momento da " +
        "captura: `git diff HEAD | shasum -a 256` na revisão sob revisão confere.",
    },
    design_approval: {
      package: DAP,
      revision: 1,
      approved_on: "2026-08-26",
      record: `docs/features/${FEATURE}/design-approval.md`,
      gate_resolutions: "plan.md §Resoluções do gate (27/08/2026)",
    },
    runtime: {
      portal: "`next start` (build de produção) do próprio repositório",
      api: "stub HTTP local servindo `tests/fixtures/dashboard.mjs`, com o aceite **stateful**",
      session: "cookie cunhado com o `encode()` do Auth.js, como em `tests/rendered-html.test.mjs`",
      browser: `chromium ${version}`,
      engine: "playwright",
      device_scale_factor: 1,
      locale: "pt-BR",
      emulation: "apenas viewport — sem emulação de toque, para a diferença capturada ser a do CSS",
      why_not_the_full_stack:
        "o portal está fora do ar desde 13/08/2026 (ADR 0053) e, na máquina desta captura, as " +
        "portas do Postgres e do MinIO pertencem a outro ambiente. Subir a pilha significaria " +
        "derrubar o que não é desta tarefa.",
    },
    proves: [
      "o código desta revisão renderiza a superfície, com os rótulos e tons do pacote aprovado",
      "os controles agem: as capturas 02 e 03 saem de cliques de verdade que atravessaram a Server Action",
      "uma segunda decisão acrescenta e a primeira aparece superada, nunca apagada",
      "o foco de teclado alcança o controle de decisão, por tabulação",
      "a tela não afirma «pendente» quando não conseguiu ler o histórico",
    ],
    does_not_prove: [
      "a integração com o FastAPI real: quem responde aqui é um stub, e é o mesmo mecanismo em que `tests/rendered-html.test.mjs` já se apoia",
      "a imutabilidade no banco — isso é privilégio do Postgres e está provado em `test_rls_isolation.py` (F-027 T02)",
      "o aviso interno de aceite, que não tem superfície de cliente (F-027 T04)",
    ],
    captures: ordered,
    coverage: {
      total_bytes: captured.reduce((sum, item) => sum + item.bytes, 0),
      requirements: ordered.map((item) => ({ requirement: item.requirement, evidence: item.id })),
    },
  };

  await writeFile(`${OUT_DIR}/manifest.json`, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(
    `\n${captured.length} capturas · ${(manifest.coverage.total_bytes / 1024).toFixed(0)} KB · manifest.json em ${OUT_DIR}`,
  );
  return 0;
}

process.exitCode = await main();
