import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import test, { after } from "node:test";

import { encode } from "next-auth/jwt";

import { DASHBOARD, ME, NOTIFICATIONS, SEARCH } from "./fixtures/dashboard.mjs";

const projectRoot = new URL("../", import.meta.url);

const AUTH_SECRET = "portal_auth_test_only";
/** Cookie name on http; it doubles as the salt of the encryption key. */
const SESSION_COOKIE = "authjs.session-token";

/** Boot `next start` once for the whole file and reuse it across tests. */
let serverPromise;
let apiStub;
/** `X-Request-ID` de cada chamada que o BFF fez à API (ADR 0018). */
const seenTraceIds = [];
/** `X-Serverless-Authorization` de cada chamada, e quantas vezes o token foi cunhado (ADR 0046). */
const seenServiceTokens = [];
let metadataStub;
let metadataHits = 0;

/**
 * O servidor de metadados do Cloud Run, de mentira.
 *
 * Ele existe porque a segunda barreira da `portal-api` — IAM invoker, além do
 * ingress interno — não era exercida por chamador nenhum, e um 403 do Cloud Run
 * acontece **antes** da aplicação: não apareceria em log nosso nem em teste que
 * fale só com o stub da API. `GCE_METADATA_HOST` é o nome que as bibliotecas do
 * Google já honram, e é por isso que o módulo o lê em vez de ganhar um parâmetro
 * que só existiria para testar.
 */
function startMetadataStub() {
  const server = createServer((request, response) => {
    if (!request.url?.includes("/identity")) {
      response.writeHead(404).end("");
      return;
    }
    // O Cloud Run recusa a requisição sem este header, e recusar aqui é o que faz
    // a asserção provar que o módulo o manda.
    if (request.headers["metadata-flavor"] !== "Google") {
      response.writeHead(403).end("");
      return;
    }
    metadataHits += 1;
    const exp = Math.floor(Date.now() / 1000) + 3600;
    const parte = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
    response
      .writeHead(200, { "content-type": "text/plain" })
      .end(`${parte({ alg: "RS256" })}.${parte({ exp, aud: "stub" })}.assinatura`);
  });
  const listening = new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(`127.0.0.1:${server.address().port}`));
  });
  return { server, listening };
}

/**
 * Substitui o dashboard servido pelo stub, para o caso em que ele difere do
 * padrão. Hoje só o projeto encerrado (ADR 0036) — `null` volta ao normal.
 */
let dashboardOverride = null;

/**
 * Idem para `GET /api/v1/me`, e existe por um caso só: dois projetos **homônimos**
 * no mesmo tenant (ADR 0061). É a única forma de provar que a tela marca o projeto
 * atual pelo `project_id` que a API serviu, e não pelo nome nem pelo primeiro da
 * lista — com um projeto por pessoa, que é como esta fixture nasceu, os dois
 * critérios dão sempre a mesma resposta.
 */
let meOverride = null;

/**
 * Stands in for the FastAPI. Lets the SSR path be exercised for real — the same
 * fetches, the same projection — without Postgres, Keycloak or Python.
 */
function startApiStub() {
  const server = createServer((request, response) => {
    seenTraceIds.push(request.headers["x-request-id"]);
    seenServiceTokens.push(request.headers["x-serverless-authorization"]);
    const body = request.url?.startsWith("/api/v1/me/dashboard")
      ? (dashboardOverride ?? DASHBOARD)
      : request.url?.startsWith("/api/v1/me/notifications")
        ? NOTIFICATIONS
        : request.url?.startsWith("/api/v1/me/search")
          ? SEARCH
          : request.url?.startsWith("/api/v1/me")
            ? (meOverride ?? ME)
            : null;
    if (!body) {
      response.writeHead(404).end("{}");
      return;
    }
    // The BFF must be sending the access token; answering 401 otherwise is what
    // makes the assertions below prove the token travelled.
    if (!(request.headers.authorization ?? "").startsWith("Bearer ")) {
      response.writeHead(401, { "content-type": "application/json" }).end("{}");
      return;
    }
    // E o `trace_id` (ADR 0018), pela mesma razão e do mesmo jeito: recusar
    // aqui é o que faz a asserção provar que o id **viajou**, em vez de provar
    // que `authorizationHeader()` tem uma chave a mais no objeto.
    if (!request.headers["x-request-id"]) {
      response.writeHead(400, { "content-type": "application/json" }).end("{}");
      return;
    }
    response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(body));
  });

  const listening = new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(`http://127.0.0.1:${server.address().port}`));
  });
  return { server, listening };
}

/** A session cookie built with Auth.js' own primitives — no browser needed. */
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
  return `${SESSION_COOKIE}=${token}`;
}

async function startServer() {
  apiStub ??= startApiStub();
  metadataStub ??= startMetadataStub();
  const apiBaseUrl = await apiStub.listening;
  const metadataHost = await metadataStub.listening;

  const port = 3100 + Math.floor(Math.random() * 800);
  const child = spawn("npx", ["next", "start", "-p", String(port)], {
    cwd: projectRoot,
    stdio: ["ignore", "pipe", "pipe"],
    // Grupo de processos próprio, para o teardown poder derrubar a árvore
    // inteira. `npx` é só um invólucro: ele lança `next`, que por sua vez
    // levanta o `next-server`. Matar o filho direto deixava o neto vivo, e o
    // runner do GitHub espera por processos órfãos — foi assim que o job
    // `web-quality` ficou 6 horas de pé nos merges das Fases 3 e 4, até o teto
    // do runner cancelá-lo. Localmente passava despercebido porque a shell
    // interativa limpa o resto ao sair.
    detached: true,
    // AUTH_SECRET is what decrypts the session cookie; without it every request
    // to a gated route is a 500 instead of the redirect we are asserting.
    env: {
      ...process.env,
      NODE_ENV: "production",
      AUTH_SECRET,
      API_BASE_URL: apiBaseUrl,
      DEMO_MODE: "false",
      // Finge que estamos no Cloud Run: é `K_SERVICE` que liga a identidade de
      // serviço, e sem ele o módulo devolve `null` de propósito — rodar o portal
      // na sua máquina não pode virar erro de servidor por falta de metadados.
      K_SERVICE: "portal-web",
      GCE_METADATA_HOST: metadataHost,
    },
  });

  const origin = `http://127.0.0.1:${port}`;
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  const ready = (async () => {
    // `next start` prints "Ready" on stdout, but polling is sturdier than parsing.
    // `/` now answers 307 to an anonymous request, so `/login` is the probe.
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (child.exitCode !== null) {
        throw new Error(`next start exited early (${child.exitCode}):\n${stderr}`);
      }
      try {
        const probe = await fetch(`${origin}/login`, { headers: { accept: "text/html" } });
        if (probe.ok) return origin;
      } catch {
        // not listening yet
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error(`next start never became ready:\n${stderr}`);
  })();

  return { child, ready };
}

async function server() {
  serverPromise ??= startServer();
  return serverPromise;
}

async function render(path = "/", init = {}) {
  const { ready } = await server();
  const origin = await ready;
  const { headers, ...rest } = init;
  return fetch(`${origin}${path}`, { headers: { accept: "text/html", ...headers }, ...rest });
}

after(async () => {
  const started = await serverPromise;
  const pid = started?.child.pid;
  if (pid) {
    try {
      // O PID negativo é o **grupo**, não o processo — é o que alcança o
      // `next-server` que o `npx` lançou por baixo. Sem isto o `npm test`
      // termina e o servidor continua ouvindo a porta.
      process.kill(-pid, "SIGTERM");
    } catch {
      // Já morreu, ou nunca chegou a subir: nos dois casos não há o que matar.
    }
  }
  apiStub?.server.close();
  metadataStub?.server.close();
});

/** Every source file we author, so guards survive files being split up. */
async function sourceFiles() {
  const roots = ["app", "components"];
  // Auth.js e o portão de sessão moram na raiz e também precisam ser varridos.
  const found = ["auth.ts", "proxy.ts"];

  async function walk(dir) {
    let entries;
    try {
      entries = await readdir(new URL(`${dir}/`, projectRoot), { withFileTypes: true });
    } catch {
      return; // directory does not exist (yet)
    }
    for (const entry of entries) {
      const path = `${dir}/${entry.name}`;
      if (entry.isDirectory()) await walk(path);
      else if (/\.(tsx?|css)$/.test(entry.name)) found.push(path);
    }
  }

  await Promise.all(roots.map(walk));
  return found;
}

/**
 * O HTML sem o payload do RSC — obrigatório para qualquer asserção de **ordem**.
 *
 * Medido, não deduzido (ADR 0029): o Next serializa as props do componente
 * cliente em `<script>self.__next_f.push(...)`, dentro do mesmo documento. Toda
 * string da lista aparece **duas vezes**, e a cópia do payload vem na ordem em
 * que a API a entregou, não na ordem em que a tela a desenhou. Um
 * `html.indexOf(...)` cai na cópia errada, e a asserção passa a medir o
 * `ORDER BY` do Postgres achando que mede a tela.
 *
 * Para asserção de *presença* isso não importa e as outras deste arquivo
 * seguem usando o HTML inteiro.
 */
function renderedMarkup(html) {
  return html.replace(/<script[\s\S]*?<\/script>/g, "");
}

async function readSources() {
  const paths = await sourceFiles();
  const contents = await Promise.all(
    paths.map(async (path) => [path, await readFile(new URL(path, projectRoot), "utf8")]),
  );
  return new Map(contents);
}

/**
 * Botões que não fazem nada (ADR 0026).
 *
 * Toda guarda deste arquivo é sobre **dado**: o fallback fabricado, a citação
 * inventada, o número fixo. Nenhuma delas alcança um controle inerte, e o
 * motivo é que um `<button>` sem `onClick` renderiza HTML byte a byte idêntico
 * a um que funciona — as asserções sobre o HTML do SSR não têm como
 * distingui-los, e nem o Playwright, que clica e não observa nada acontecer.
 * Foi assim que o `<input>` da lupa sobreviveu duas fases (ADR 0024) e que
 * outros onze sobreviveram à afirmação de que ele era o último.
 *
 * O regex ingênuo `<button[^>]*>` **não** serve, e isso foi medido: o sino em
 * `DashboardClient.tsx` tem `aria-label={unreadCount > 0 ? … }`, cujo `>` fecha
 * a tag cedo demais e esconde o `onClick` da linha seguinte. Daí a varredura
 * balancear `{}` e pular strings até o `>` de verdade.
 */
function inertButtons(source) {
  const found = [];
  for (let at = source.indexOf("<button"); at !== -1; at = source.indexOf("<button", at + 1)) {
    if (/[\w-]/.test(source[at + "<button".length] ?? "")) continue; // <buttonish>
    let depth = 0;
    let quote = "";
    let end = at + "<button".length;
    for (; end < source.length; end += 1) {
      const char = source[end];
      if (quote) {
        if (char === quote) quote = "";
      } else if (char === '"' || char === "'" || char === "`") quote = char;
      else if (char === "{") depth += 1;
      else if (char === "}") depth -= 1;
      else if (char === ">" && depth === 0) break;
    }
    const tag = source.slice(at, end + 1);
    // `type="submit"` conta porque o `<form action={…}>` do Server Action é o
    // que o aciona — é handler, só que declarado do outro lado.
    if (/\bonClick=|\btype="submit"/.test(tag)) continue;
    found.push(`linha ${source.slice(0, at).split("\n").length}: ${tag.replace(/\s+/g, " ")}`);
  }
  return found;
}

test("closes the portal to anonymous visitors", async () => {
  const response = await render("/", { redirect: "manual" });

  // The first automated proof that the portal is shut: before Fase 1 this was a
  // 200 with a fabricated dashboard.
  assert.equal(response.status, 307);
  assert.match(response.headers.get("location") ?? "", /\/login$/);
});

test("server-renders the login page", async () => {
  const response = await render("/login");
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /<title>One<\/title>/i);
  assert.match(html, /Acompanhe seus projetos de IA em um só lugar\./);
  assert.match(html, /Entrar com SSO da empresa/);
  // Sem campo de senha: a credencial nunca chega a este domínio (ADR 0010).
  assert.doesNotMatch(html, /type="password"/);
  assert.doesNotMatch(html, /Your site is taking shape/);
  assert.doesNotMatch(html, /codex-preview/);
});

test("server-renders the dashboard for an authenticated session", async () => {
  const response = await render("/", { headers: { cookie: await sessionCookie() } });
  assert.equal(response.status, 200);
  const html = await response.text();

  // Nome e organização vêm de `GET /api/v1/me`; o resto, do dashboard. Antes
  // desta fase eram constantes no componente e um fallback de demonstração.
  assert.match(html, /<title>One<\/title>/i);
  assert.match(html, /Bom dia, Marina\./);
  assert.match(html, /Acme Brasil/);
  assert.match(html, /Automação Financeira/);
  assert.match(html, /ROI do projeto/);
  assert.match(html, /Você está aqui/);
  assert.match(html, /SUA JORNADA/);
  assert.match(html, /No prazo/);
  assert.match(html, /Funcionários Digitais/);
  assert.match(html, /Agente Financeiro/);
  assert.match(html, /Perguntar à IA/);
  assert.match(html, /Pendências abertas/);
  assert.match(html, /Aprovar fluxo de exceções/);
  // A prioridade chega à tela (ADR 0029). Até esta fatia a API a entregava, o
  // `ApiPending` a tipava e o mapeamento a descartava — a aba onde o cliente
  // decide o que fazer primeiro mostrava tudo igual.
  assert.match(html, /priority-pill--high/);
  // E ordena: a fixture tem a alta como a **mais antiga** das três, então
  // encontrá-la antes das outras no HTML só é possível se a ordem não for por
  // data. Sem esta asserção, o selo poderia estar certo e a ordem errada.
  const dom = renderedMarkup(html);
  const highIndex = dom.indexOf("Aprovar fluxo de exceções");
  const lowIndex = dom.indexOf("Renovar o certificado do integrador");
  assert.ok(highIndex > -1 && lowIndex > -1, "as três pendências da fixture têm de aparecer");
  assert.ok(
    highIndex < lowIndex,
    "a pendência de prioridade alta tem de vir antes da baixa (ADR 0029)",
  );
  assert.match(html, /Atualizações recentes/);
  assert.match(html, /Plano de implantação v3\.pdf/);
  assert.match(html, /Comitê de projeto/);
  // O sino conta o que a API disse. Antes da Fase 2 eram três avisos fixos no
  // componente e um booleano de "já li" que um F5 desfazia.
  assert.match(html, /aria-label="Notificações \(2 não lidas\)"/);
  assert.doesNotMatch(html, /Your site is taking shape/);
  assert.doesNotMatch(html, /codex-preview/);
  // Projeto ativo não mostra selo nenhum — sem isto, as asserções dos dois testes
  // seguintes passariam mesmo com o selo aparecendo sempre.
  assert.doesNotMatch(html, /Projeto encerrado/);
  assert.doesNotMatch(html, /Projeto removido na origem/);
});

test("o projeto encerrado é marcado na tela e fecha a pergunta", async () => {
  // Arquivar no Biahflow chega até aqui desde a ADR 0036. Antes, o portal
  // mostrava como ativo um projeto que a fonte da verdade havia encerrado.
  dashboardOverride = { ...DASHBOARD, archived_at: "2026-08-06T22:23:24.171853+00:00" };
  try {
    const response = await render("/", { headers: { cookie: await sessionCookie() } });
    assert.equal(response.status, 200);
    const html = await response.text();

    assert.match(html, /Projeto encerrado/);
    assert.match(html, /health-pill--archived/);
    // A saúde continua ao lado, e não no lugar: um projeto pode terminar no prazo.
    assert.match(html, /No prazo/);
    // O histórico inteiro permanece — é a evidência das respostas já dadas (ADR 0017).
    assert.match(html, /Plano de implantação v3\.pdf/);
    assert.match(html, /Aprovar fluxo de exceções/);
    // O fechamento das escritas não é assertável aqui: o painel de chat só entra no DOM
    // depois de aberto, e o fio de comentário depois de expandido. Quem cobre a forma é a
    // varredura de fonte abaixo; quem cobre o comportamento é o e2e.
  } finally {
    dashboardOverride = null;
  }
});

test("o projeto removido na origem é marcado com o próprio motivo", async () => {
  // Apagar o projeto no Biahflow chega até aqui desde a ADR 0037 — por webhook, porque
  // depois da exclusão não há snapshot que possa declarar coisa alguma. Sem o aviso, o
  // portal mantinha um projeto morto na tela do cliente marcado como ativo, para sempre.
  dashboardOverride = { ...DASHBOARD, source_deleted_at: "2026-08-07T10:11:12.000000+00:00" };
  try {
    const response = await render("/", { headers: { cookie: await sessionCookie() } });
    assert.equal(response.status, 200);
    const html = await response.text();

    assert.match(html, /Projeto removido na origem/);
    assert.match(html, /health-pill--archived/);
    // E **não** diz encerrado: são fatos diferentes, e a tela não pode trocar um pelo outro.
    assert.doesNotMatch(html, /Projeto encerrado/);
    // O histórico continua inteiro, que é a razão de o portal não apagar nada (ADR 0017).
    assert.match(html, /Plano de implantação v3\.pdf/);
  } finally {
    dashboardOverride = null;
  }
});

test("encerrado e removido juntos mostram o motivo mais forte", async () => {
  // O Biahflow permite arquivar e depois apagar, e aí as duas datas existem. A frase útil
  // ao cliente é a segunda — e é a mesma ordem de `_refuse_when_read_only` na API.
  dashboardOverride = {
    ...DASHBOARD,
    archived_at: "2026-08-06T22:23:24.171853+00:00",
    source_deleted_at: "2026-08-07T10:11:12.000000+00:00",
  };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();
    assert.match(html, /Projeto removido na origem/);
    assert.doesNotMatch(html, /Projeto encerrado/);
  } finally {
    dashboardOverride = null;
  }
});

/**
 * O projeto atual é o que a API **disse** que serviu, e não o que tem o mesmo nome
 * (ADR 0061).
 *
 * É a primeira asserção deste repositório sobre a marca `current`, e ela precisou de
 * um mundo que nenhuma fixture tinha: **dois projetos homônimos no mesmo tenant**. Com
 * um projeto por pessoa, "o do nome igual", "o primeiro da lista" e "o que a API
 * serviu" são sempre a mesma linha, e o defeito não tem como aparecer — que é
 * exatamente por que ele atravessou sete fases.
 *
 * A marca não chega ao DOM (a `ProjectsView` só existe depois de o cliente trocar de
 * aba, e os dois cartões teriam o mesmo texto de qualquer forma): o que se lê aqui é o
 * payload de hidratação que o SSR embute, que é onde `projects` viaja para o cliente.
 * As duas direções são exercitadas de propósito — servindo ora o segundo, ora o
 * primeiro —, senão "sempre o último" passaria verde numa delas.
 */
const HOMONYMS = {
  first: "aaaaaaaa-2222-4333-8444-555555555555",
  second: "bbbbbbbb-2222-4333-8444-555555555555",
};

/** A marca `current` que o payload de hidratação carrega para um id. */
function currentFlag(html, id) {
  const at = html.indexOf(id);
  assert.notEqual(at, -1, `o projeto ${id} não chegou ao payload de hidratação`);
  const found = /current\\?":(true|false)/.exec(html.slice(at));
  assert.ok(found, `o payload não declara \`current\` para ${id}`);
  return found[1] === "true";
}

for (const [rotulo, served] of [["o segundo", HOMONYMS.second], ["o primeiro", HOMONYMS.first]]) {
  test(`entre dois projetos homônimos, a tela marca ${rotulo} — o que a API serviu`, async () => {
    meOverride = {
      ...ME,
      projects: [
        { ...ME.projects[0], id: HOMONYMS.first },
        { ...ME.projects[0], id: HOMONYMS.second },
      ],
    };
    dashboardOverride = { ...DASHBOARD, project_id: served };
    try {
      const response = await render("/", { headers: { cookie: await sessionCookie() } });
      assert.equal(response.status, 200);
      const html = await response.text();

      assert.equal(currentFlag(html, served), true);
      const other = served === HOMONYMS.first ? HOMONYMS.second : HOMONYMS.first;
      assert.equal(currentFlag(html, other), false);
    } finally {
      meOverride = null;
      dashboardOverride = null;
    }
  });
}

test("sem casamento de id nenhum projeto é o atual, e a tela não elege o primeiro", async () => {
  // O `?? projects[0]` caiu com a ADR 0061: um id servido que não casa com nenhum item
  // de `/me` é divergência real entre duas rotas, e eleger o primeiro escoparia sino,
  // busca e comentários por um projeto que ninguém afirmou. Sem casamento o parâmetro é
  // **omitido** e as rotas voltam a `access.default_project` — o projeto do dashboard.
  //
  // **E a tela diz** (ADR 0062): até aqui a degradação era muda dos dois lados, e o
  // cliente via o dashboard certo debaixo de um seletor que não o continha — sem nada
  // distinguindo isso de uma escolha. O nome do projeto sai da fixture de propósito:
  // `ME.organization` é "Acme Brasil" e `DASHBOARD.project` é "Automação Financeira",
  // de modo que o fallback errado do logo (a organização) e o certo (o projeto) dão a
  // **mesma inicial**, e a asserção passaria verde com o defeito de volta.
  meOverride = { ...ME, projects: [{ ...ME.projects[0], id: HOMONYMS.first }] };
  dashboardOverride = { ...DASHBOARD, project_id: HOMONYMS.second, project: "Zeta Operações" };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();
    assert.equal(currentFlag(html, HOMONYMS.first), false);

    const markup = renderedMarkup(html);
    assert.match(markup, /project-switcher--unlisted/);
    assert.match(markup, /Fora da sua lista de projetos/);
    // O que se afirma é só o que se sabe: que o projeto da tela não está na lista.
    // Qual deveria ser, ninguém sabe, e inventá-lo é o `answerFor()` da ADR 0021.
    assert.doesNotMatch(markup, /deveria ser|projeto correto/);
    // Os dois textos da mesma linha falam do projeto que a API serviu.
    assert.match(markup, /class="project-logo">Z</);
    assert.match(markup, /<small>Zeta Operações<\/small>/);
  } finally {
    meOverride = null;
    dashboardOverride = null;
  }
});

/**
 * A linha ancorada, com a classe **e** o atributo no mesmo elemento (ADR 0056).
 *
 * Asserção de proximidade e não de presença, e a diferença é o que se prova:
 * `is-anchored` em algum lugar do documento mais `data-item` em outro qualquer
 * passaria verde com o destaque na linha errada — que é justamente o desfecho que
 * esta fatia existe para impedir.
 */
function anchoredRow(markup, anchor) {
  const escaped = anchor.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`<[^>]*class="[^"]*is-anchored[^"]*"[^>]*data-item="${escaped}"`).test(markup);
}

async function anchored(tab, item) {
  const response = await render(
    `/?tab=${encodeURIComponent(tab)}&item=${encodeURIComponent(item)}`,
    { headers: { cookie: await sessionCookie() } },
  );
  assert.equal(response.status, 200);
  return renderedMarkup(await response.text());
}

/**
 * O `?item=` cai na linha, e não só na aba — o critério de aceite (4) da FDD 021.
 *
 * Aqui e não só no Python porque "a âncora é alcançável" é afirmação sobre **HTML
 * renderizado com dados reais**, e só o lado que roda `next start` a produz. Isso
 * funciona pela mesma razão que faz o `?tab=` funcionar: o `useState(initialTab)`
 * roda no SSR, então a aba pedida já vem desenhada do servidor.
 */
test("o link do aviso destaca a linha do assunto em cada aba ancorável", async () => {
  const casos = [
    ["Cronograma", "milestone:Validação de integrações"],
    ["Documentos", "document:Plano de implantação v3.pdf"],
    ["Reuniões", "meeting:Comitê de projeto"],
    ["Pendências", "pending:Renovar o certificado do integrador"],
    ["Visão geral", "phase:Prove"],
  ];

  for (const [tab, item] of casos) {
    const markup = await anchored(tab, item);
    assert.ok(anchoredRow(markup, item), `sem destaque em ${tab} para ${item}`);
  }
});

test("o entregável de uma fase já concluída abre a fase que o contém", async () => {
  // O painel da jornada só desenha os entregáveis da fase **selecionada**, e o
  // padrão é a ativa ("Prove"). Sem derivar a fase da âncora, o link de um
  // `deliverable_delivered` de fase concluída apontaria para um nó fora do DOM:
  // correto e inalcançável, que é pior do que não ter link.
  const semAncora = renderedMarkup(
    await (await render("/", { headers: { cookie: await sessionCookie() } })).text(),
  );
  assert.doesNotMatch(semAncora, /Acesso ao portal/, "a fase concluída não abre sozinha");

  const markup = await anchored("Visão geral", "deliverable:Acesso ao portal");
  assert.ok(anchoredRow(markup, "deliverable:Acesso ao portal"));
});

test("uma âncora que não existe mais mostra a aba inteira e diz o que houve", async () => {
  // Sem esta nota a degradação seria invisível: o cliente chega na aba certa e nada
  // acontece — "cliquei no aviso do marco X e o marco X não está aqui" é a pergunta
  // que o suporte receberia. É o defeito que a ADR 0033 nomeou.
  const markup = await anchored("Cronograma", "milestone:não existe");

  assert.match(markup, /O item deste aviso não está mais nesta lista\./);
  assert.doesNotMatch(markup, /is-anchored/);
  // E a aba continua inteira: a nota é um aviso, não um estado de erro.
  assert.match(markup, /Todos os marcos/);
  assert.match(markup, /Validação de integrações/);
});

test("o link do aviso atravessa o BFF até o componente que o renderiza", async () => {
  // A Central de notificações — o único lugar onde `Notification.link` vira `<a>`
  // — só monta por navegação no cliente, então o HTML do SSR não tem como carregar
  // aquele `href`; quem o prova ponta a ponta é o e2e. O que **este** lado prova é
  // o elo anterior, e ele não tinha nenhuma asserção: a fixture trazia `link: null`
  // nas duas notificações, de modo que aquele ramo era código morto nos testes e um
  // `link` perdido em `toNotifications` passaria verde.
  const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

  assert.ok(
    html.includes("item=milestone%3AValida"),
    "o link com âncora não chegou às props do componente",
  );
});

test("the search route forwards the session and answers from the API", async () => {
  // O campo da lupa prometia "buscar no contexto do projeto" desde a primeira
  // versão da tela, com um `<input>` sem handler nenhum (ADR 0024). O que este
  // teste fixa é a metade do BFF: o termo sai daqui com o token e o `trace_id`
  // — o stub responde 401/400 sem eles —, e a lista que volta é a da API.
  const response = await render("/api/search?q=contrato", {
    headers: { cookie: await sessionCookie(), accept: "application/json" },
  });

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body, SEARCH);
});

test("the search route refuses an anonymous caller before reaching the API", async () => {
  // Sem sessão não há o que repassar, e o 401 sai do BFF em vez de a API decidir
  // por um anônimo — a mesma forma de `app/api/chat/route.ts`.
  const response = await render("/api/search?q=contrato", {
    headers: { accept: "application/json" },
  });

  assert.equal(response.status, 401);
});

test("the search route does not call the API for an empty term", async () => {
  // Uma tecla apagada não vale uma ida ao servidor. A resposta é a mesma lista
  // vazia que a API daria — e o mínimo de verdade continua sendo dela
  // (`search.MIN_QUERY_LENGTH`), não daqui.
  const response = await render("/api/search?q=%20%20", {
    headers: { cookie: await sessionCookie(), accept: "application/json" },
  });

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { results: [] });
});

/**
 * Renderiza e devolve os `X-Request-ID` que a API viu (ADR 0018).
 *
 * O `await response.text()` não é decoração: o SSR do Next é **streaming**, os
 * headers da resposta chegam antes de `app/page.tsx` terminar suas `fetch()`, e
 * medir nesse ponto conta zero chamadas. Ler o corpo até o fim é o que garante
 * que o render acabou.
 */
async function traceIdsSeenWhileRendering(init) {
  seenTraceIds.length = 0;
  const response = await render("/", init);
  assert.equal(response.status, 200);
  await response.text();
  return seenTraceIds.filter(Boolean);
}

test("carries one trace id from the SSR to every API call", async () => {
  // O stub responde 400 sem `X-Request-ID`, então um 200 já prova que o header
  // viajou. O que este teste acrescenta é a **unicidade**: `app/page.tsx` faz
  // três `fetch()` em paralelo, e as três têm que sair com o mesmo id — é para
  // isso que `traceId()` é memoizado com o `cache()` do React. Uma variável de
  // módulo daria o mesmo id a pessoas diferentes; um `randomUUID()` por chamada
  // daria três ids para uma tela só. As duas falham aqui.
  const ids = await traceIdsSeenWhileRendering({ headers: { cookie: await sessionCookie() } });

  assert.ok(ids.length >= 3, `esperava ao menos 3 chamadas, vi ${ids.length}`);
  assert.equal(new Set(ids).size, 1, `esperava um id só, vi ${[...new Set(ids)].join(", ")}`);
});

test("apresenta a identidade do serviço à API, sem tirar a da pessoa", async () => {
  // A `portal-api` sobe com ingress interno **e** sem `allUsers` no `run.invoker`,
  // e o módulo do Cloud Run chama isso de duas barreiras. A segunda não era
  // atravessada por ninguém: o BFF mandava só o token do Keycloak, que não diz nada
  // ao Cloud Run — toda chamada interna levaria 403 **antes** da aplicação, então
  // nem o log da API nem o stub deste arquivo veriam a falha (ADR 0046).
  //
  // O que este teste prende é o par: o header de serviço chega, e o `Authorization`
  // continua sendo o da pessoa. Trocar um pelo outro — que é o erro fácil, porque o
  // Cloud Run aceita ID token em `Authorization` — faria a API perder o principal e
  // responder 401 a uma chamada autorizada.
  seenServiceTokens.length = 0;
  const antes = metadataHits;

  const response = await render("/", { headers: { cookie: await sessionCookie() } });
  assert.equal(response.status, 200);
  // O corpo precisa ser consumido: o SSR é streamed, e as chamadas à API acontecem
  // enquanto ele flui. Sem isto o teste lê os headers antes de haver o que ler — e
  // passaria a medir a ordem em que o Node agenda, não o que o BFF manda.
  await response.text();

  const vistos = seenServiceTokens.filter(Boolean);
  assert.ok(vistos.length >= 3, `esperava ao menos 3 chamadas com o header, vi ${vistos.length}`);
  for (const valor of vistos) {
    assert.match(valor, /^Bearer ey/, "o header de serviço tem que carregar um JWT");
  }

  // E o token é cunhado uma vez, não uma por `fetch`: o servidor de metadados fica
  // no caminho quente de toda renderização, e três chamadas de rede por tela para
  // buscar o mesmo token é custo que não aparece em teste nenhum de correção.
  assert.ok(
    metadataHits - antes <= 1,
    `esperava no máximo uma cunhagem, houve ${metadataHits - antes}`,
  );
});

test("honours a trace id supplied by whoever called the BFF", async () => {
  // Para um gateway ou balanceador poder ser o dono do identificador no dia em
  // que houver um, sem o portal cunhar um segundo para a mesma requisição.
  const ids = await traceIdsSeenWhileRendering({
    headers: { cookie: await sessionCookie(), "x-request-id": "vindo-de-fora" },
  });

  assert.deepEqual([...new Set(ids)], ["vindo-de-fora"]);
});

test("keeps product metadata and avoids disposable starter artifacts", async () => {
  const sources = await readSources();
  const page = sources.get("app/page.tsx");
  const dashboard = sources.get("app/DashboardClient.tsx");
  const layout = sources.get("app/layout.tsx");
  const packageJson = await readFile(new URL("package.json", projectRoot), "utf8");

  // The interactive dashboard (chat logic) lives in the client component; page.tsx is the
  // server component that fetches real data and renders it (ADR 0006, Fase 2).
  //
  // A guarda trocou de lado na ADR 0021, e vale registrar por quê: até a Fase 5
  // esta linha exigia que `function answerFor` **existisse**. Ela era o fallback
  // do `catch` de `sendQuestion` e devolvia data, decisão, contagem de pendência
  // e rótulo de citação inventados a um cliente autenticado cuja chamada falhou —
  // de modo que o teste segurava no lugar exatamente o defeito que o resto da
  // suíte existe para impedir, na forma que a ADR 0020 achou nas asserções de
  // backup que pulavam em silêncio. Um chat que falhou agora diz que falhou.
  assert.doesNotMatch(dashboard, /function answerFor/);
  assert.match(dashboard, /Pendência criada para o time Biahflow/);
  // Projeto sem escrita fecha as duas do cliente (ADR 0036/0037). É guarda de forma, como
  // a de citação abaixo: o formulário de pergunta e o de comentário têm de estar atrás da
  // condição, e não apenas escondidos por CSS ou desabilitados no submit — a API responde
  // 409, e uma tela que só falha depois de a pessoa digitar é pior que nenhuma.
  assert.match(dashboard, /projectReadOnly \? \(/);
  assert.match(dashboard, /readOnly \? \(/);
  assert.match(dashboard, /fazer novas perguntas/);
  // E os dois motivos moram na mesma função, que é o que impede a tela de dizer
  // "encerrado" num canto e "removido" noutro (ADR 0037).
  assert.match(dashboard, /function readOnlyReason/);
  assert.match(dashboard, /overview\.sourceDeletedAt !== null/);
  // A data da citação vem do campo estruturado e não é extraída do rótulo (ADR 0038):
  // quem lê o parêntese precisa saber o que ele significa, e uma cirurgia de string
  // sobre `label` quebraria em silêncio no dia em que o formato mudasse.
  assert.match(dashboard, /function citationHint/);
  assert.match(dashboard, /citation\.dated_at/);
  // E a fabricação não pode voltar por outro caminho. A guarda é sobre a *forma*,
  // não sobre os rótulos: toda citação da tela vem de `data.sources`/`data.citations`
  // da API, então um array de literais atribuído a `sources` no cliente do chat só
  // pode ser rótulo inventado localmente. (Os mesmos nomes aparecem em
  // `app/demo-overview.ts` como dado de dashboard, o que é legítimo e vive atrás
  // do portão de `demoShellEnabled()` — por isso a guarda é do arquivo do chat.)
  assert.doesNotMatch(
    dashboard,
    /sources:\s*\[\s*"/,
    "DashboardClient.tsx voltou a fabricar citação no cliente (ADR 0021)",
  );
  // A busca entra na mesma guarda e pelo mesmo argumento (ADR 0024): todo
  // resultado vem de `GET /api/v1/me/search`, que é onde o filtro de tenant e a
  // RLS valem. Uma lista montada no navegador seria, por construção, uma lista
  // que ninguém escopou — e a tela não teria como saber disso.
  assert.doesNotMatch(
    dashboard,
    /(hits|results):\s*\[\s*\{/,
    "DashboardClient.tsx voltou a fabricar resultado de busca no cliente (ADR 0024)",
  );
  // E o campo tem de continuar ligado: um `<input>` sem `onChange` foi
  // exatamente o estado que esta fatia corrigiu, e ele passaria por qualquer
  // asserção sobre o HTML renderizado.
  assert.match(dashboard, /function ProjectSearch/);
  assert.match(dashboard, /onChange=\{\(event\) => setTerm\(event\.target\.value\)\}/);
  assert.match(dashboard, /fetch\(`\/api\/search\?q=/);
  // O 429 é a única recusa que a tela sabe explicar, e ela precisa explicá-la:
  // sem este ramo, um limite atingido cairia no `catch` e viraria erro genérico.
  assert.match(dashboard, /response\.status === 429/);
  assert.match(dashboard, /muitas perguntas em pouco tempo/);
  assert.match(layout, /title: "One"/);
  assert.match(layout, /lang="pt-BR"/);

  // A aba Resultados não aparece no HTML do SSR (só a ativa é renderizada), então
  // o que se afirma aqui é a fonte: os cards leem a apuração da API e a tela
  // mostra a premissa. Sem isso, um número poderia voltar a ser constante sem
  // bater na guarda de literais abaixo — bastaria escolher outro valor.
  assert.match(dashboard, /overview\.measured/);
  assert.match(dashboard, /COMO CALCULAMOS/);
  assert.match(dashboard, /function MeasurementBasis/);

  // Nada de dado fixo de volta: as abas leem `overview` (Fase 2) e a identidade
  // vem de `GET /api/v1/me` (Fase 1). `projects` e `currentUser` escapavam desta
  // guarda justamente por serem os últimos sobreviventes.
  for (const [path, source] of sources) {
    assert.doesNotMatch(
      source,
      /^const (documents|meetings|pendingItems|resolvedItems|schedule|projects|currentUser|notifications) = /m,
      `${path} reintroduziu dados fixos que a Fase 1/2 removeu`,
    );
    assert.doesNotMatch(source, /_sites-preview|SkeletonPreview/, `${path} tem resíduo do starter`);
    // O header de identidade forjada e o e-mail em variável de ambiente saíram
    // do repositório inteiro quando o token OIDC entrou (ADR 0010).
    assert.doesNotMatch(source, /X-Portal-User|PORTAL_CLIENT_EMAIL/, `${path} ressuscitou a identidade por header`);
    // Dado de demonstração alcançável de um lugar só (ver a asserção abaixo).
    if (path !== "app/demo-overview.ts" && path !== "app/page.tsx") {
      assert.doesNotMatch(source, /DEMO_OVERVIEW/, `${path} alcança o demo fora do gate`);
    }
    // Os três cards que a Fase 3 tirou da demonstração. A guarda acima não os
    // pegava — eles não eram `const` no topo do módulo, e sim um array local
    // dentro de `ResultsView`, o que é justamente por que sobreviveram tanto
    // tempo. Aqui os literais é que ficam proibidos.
    assert.doesNotMatch(
      source,
      /"12,4k"|"98,6%"|"1\.203"|"\+142%"|"↑ 2,1 p\.p\. no mês"|"87% sem intervenção humana"/,
      `${path} ressuscitou um dos números de demonstração da aba Resultados`,
    );
    // Idioma e fuso da aba Configurações, pela mesma razão e com a mesma
    // fuga: eram um array local dentro de `SettingsView`, não um `const` de
    // módulo, e por isso a guarda de cima nunca os viu (ADR 0026). São
    // constantes do produto, e a tela as declara em vez de fingir que são
    // preferências guardadas em algum lugar.
    assert.doesNotMatch(
      source,
      /"Português \(Brasil\)"|"\(GMT-3\) São Paulo"/,
      `${path} ressuscitou as preferências fixas da aba Configurações`,
    );
    // E nenhum controle inerte volta. A guarda é sobre a *forma do controle*,
    // não sobre o HTML que ele produz, que é a única forma de pegá-lo.
    assert.deepEqual(
      inertButtons(source),
      [],
      `${path} tem <button> sem onClick nem type="submit" (ADR 0026)`,
    );
  }

  // O gate é uma condição só, e a única menção ao demo em `page.tsx` está
  // literalmente dentro dele: é isto que torna "nenhum caminho leva a dado
  // inventado" uma afirmação verificável, e não uma promessa.
  assert.match(
    sources.get("app/lib/demo.ts"),
    /!process\.env\.API_BASE_URL && process\.env\.DEMO_MODE === "true"/,
  );
  const gate = page.match(/if \(demoShellEnabled\(\)\) \{[\s\S]*?\n {2}\}/);
  assert.ok(gate, "o gate do demo sumiu de app/page.tsx");
  assert.doesNotMatch(
    page.replace(gate[0], ""),
    /DEMO_OVERVIEW/,
    "app/page.tsx alcança o demo fora do gate",
  );

  assert.doesNotMatch(page, /_sites-preview|SkeletonPreview/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  // A camada Cloudflare saiu do repositório (ADR 0009).
  assert.doesNotMatch(packageJson, /vinext|wrangler|cloudflare|drizzle/);
  await assert.rejects(readFile(new URL("app/_sites-preview/SkeletonPreview.tsx", projectRoot)));
  await assert.rejects(readFile(new URL("worker/index.ts", projectRoot)));
});

/**
 * Do `(` em `at` até o parêntese que o fecha, pulando strings.
 *
 * Irmão do balanceamento de `inertButtons`, e existe pela mesma razão: o corpo
 * de um `.map(…)` tem parênteses dentro de template strings e de JSX, e um
 * `indexOf(")")` cortaria no primeiro deles.
 */
function balancedCall(source, at) {
  let depth = 0;
  let quote = "";
  for (let end = at; end < source.length; end += 1) {
    const char = source[end];
    if (quote) {
      if (char === quote && source[end - 1] !== "\\") quote = "";
    } else if (char === '"' || char === "'" || char === "`") quote = char;
    else if (char === "(") depth += 1;
    else if (char === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(at, end + 1);
    }
  }
  throw new Error("parêntese sem fechamento em app/DashboardClient.tsx");
}

/** Todo `notifications.items…map(…)` cujo corpo não passa por `NotificationLink`. */
function unlinkedNotificationRows(source) {
  const found = [];
  const pattern = /notifications\.items(?:\.[a-zA-Z]+\([^)]*\))*\.map\(/g;
  for (let match; (match = pattern.exec(source)); ) {
    const at = match.index + match[0].length - 1;
    if (balancedCall(source, at).includes("<NotificationLink")) continue;
    found.push(`linha ${source.slice(0, match.index).split("\n").length}`);
  }
  return found;
}

test("toda lista de avisos rende a linha como link, e não como um <div>", async () => {
  // A guarda é sobre a **forma do controle**, como o `inertButtons()` da ADR 0026,
  // e pela mesma razão exata: um `<div className="popover-row">` renderiza HTML
  // indistinguível de um `<a>` para quem só olha strings, e o Playwright clica nele
  // sem observar nada acontecer. Foi assim que o popover do sino atravessou a ADR
  // 0043 e a ADR 0056 inteiras sendo o único lugar do produto onde o
  // `Notification.link` existia e não virava destino — nomeado nas duas, corrigido
  // em nenhuma.
  //
  // Duas listas hoje (o popover e a Central), e a asserção é sobre **toda**
  // ocorrência: uma terceira superfície que renderize avisos nasce coberta, que é
  // o que separa esta guarda da lista escrita à mão da ADR 0033.
  const source = await readFile(new URL("app/DashboardClient.tsx", projectRoot), "utf8");

  assert.deepEqual(
    unlinkedNotificationRows(source),
    [],
    "estas listas de aviso não passam por <NotificationLink>. O `link` existe e a" +
      " tela o descarta — o cliente vê a linha e o clique não leva a lugar nenhum" +
      " (FDD 021 critério (4), ADR 0057).",
  );
});

test("só o goTo troca de aba, e é ele quem apaga a âncora", async () => {
  // O defeito da própria ADR 0056: o comentário do `goTo` declara que "trocar de
  // aba por vontade própria encerra o destaque", e a barra lateral — que é *o*
  // caminho de trocar de aba por vontade própria — chamava `setActiveNav` direto.
  // A âncora sobrevivia à navegação, e o efeito de rolagem tem `activeNav` nas
  // dependências: cada clique na barra re-rolava para uma linha que o cliente já
  // tinha dispensado, com a nota "O item deste aviso não está mais nesta lista."
  // seguindo para todas as abas indefinidamente.
  //
  // A asserção é sobre o **escritor** e não sobre a chamada da barra lateral: um
  // quarto escritor amanhã tem o mesmo defeito, e uma guarda que olhasse só a
  // barra nasceria cega para ele.
  const source = await readFile(new URL("app/DashboardClient.tsx", projectRoot), "utf8");
  const goTo = source.match(/const goTo = \([^)]*\) => \{[^}]*\};/);
  assert.ok(goTo, "não achei a definição de `goTo` em app/DashboardClient.tsx");

  const outside = [...source.matchAll(/setActiveNav\(/g)]
    .filter((match) => match.index < source.indexOf(goTo[0]) || match.index > source.indexOf(goTo[0]) + goTo[0].length)
    .map((match) => `linha ${source.slice(0, match.index).split("\n").length}`);

  assert.deepEqual(
    outside,
    [],
    "estes pontos trocam de aba sem passar pelo `goTo`, e por isso não apagam a" +
      " âncora: a nota do aviso segue para as outras abas e o efeito de rolagem" +
      " re-destaca uma linha que o cliente já dispensou (ADR 0057).",
  );
});
