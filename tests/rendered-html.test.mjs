import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import test, { after } from "node:test";

import { encode } from "next-auth/jwt";

import { ACCEPTANCES, DASHBOARD, ME, NOTIFICATIONS, SEARCH } from "./fixtures/dashboard.mjs";

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
 * O status HTTP com que o stub responde ao dashboard, ou `null` para o 200 de sempre.
 *
 * Existe para o estado **indisponível** (ADR 0076): ele é falha de fetch, e não um corpo
 * diferente — não há override de dashboard capaz de produzi-lo, porque o que o produz é a
 * ausência de dashboard.
 */
let dashboardStatus = null;

/**
 * Idem para o histórico de aceite (ADR 0077), e existe por dois casos que só a
 * injeção alcança: o histórico com **duas** decisões, onde a primeira aparece
 * superada, e a falha de leitura, onde a tela não pode afirmar "pendente" — ela
 * não sabe.
 *
 * `null` é o padrão e é o estado comum: entrega elegível sobre a qual ninguém
 * decidiu ainda. `"fail"` faz o stub responder 500.
 */
let acceptanceOverride = null;

/**
 * Stands in for the FastAPI. Lets the SSR path be exercised for real — the same
 * fetches, the same projection — without Postgres, Keycloak or Python.
 */
function startApiStub() {
  const server = createServer((request, response) => {
    seenTraceIds.push(request.headers["x-request-id"]);
    seenServiceTokens.push(request.headers["x-serverless-authorization"]);
    if (dashboardStatus !== null && request.url?.startsWith("/api/v1/me/dashboard")) {
      response.writeHead(dashboardStatus, { "content-type": "application/json" }).end("{}");
      return;
    }
    // O histórico de aceite vem **antes** do `/api/v1/me` genérico: o caminho é
    // `/api/v1/me/deliverables/…`, e o casador solto o serviria com o corpo do
    // `/me`, deixando a tela receber um perfil onde espera uma lista de decisões.
    const acceptance = /^\/api\/v1\/me\/deliverables\/([^/?]+)\/acceptance/.exec(
      request.url ?? "",
    );
    const body = request.url?.startsWith("/api/v1/me/dashboard")
      ? (dashboardOverride ?? DASHBOARD)
      : request.url?.startsWith("/api/v1/me/notifications")
        ? NOTIFICATIONS
        : request.url?.startsWith("/api/v1/me/search")
          ? SEARCH
          : acceptance
            ? (acceptanceOverride ?? {
                deliverable_external_ref: decodeURIComponent(acceptance[1]),
                items: [],
              })
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
    // Depois das duas recusas acima, e não antes: a indisponibilidade encenada não
    // pode encobrir a prova de que o token e o `trace_id` viajaram.
    if (acceptance && acceptanceOverride === "fail") {
      response.writeHead(500, { "content-type": "application/json" }).end("{}");
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
      // O limiar do stale é parâmetro de operação (ADR 0076), e **48 não é o default**:
      // com 24 h, a projeção de 30 h do teste abaixo apareceria velha. É o que faz aquela
      // asserção provar que o número sai da configuração, e não de uma constante no
      // componente.
      PROJECTION_STALE_HOURS: "48",
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

/**
 * Todo `.ai-button` carrega um ícone — e isto é sobre a **forma do controle**,
 * como o `inertButtons()` acima, só que o que some não é o handler: é o nome.
 *
 * A regra móvel de `app/globals.css` colapsa o rótulo abaixo de 760px
 * (`.ai-button { padding: 10px; font-size: 0 }`) e foi escrita para o botão do
 * herói, que tem `<Sparkles />` e vira o ícone dele. Quem não tem ícone não vira
 * nada: vira um círculo roxo vazio, e o HTML continua idêntico ao de um botão
 * correto — nenhuma asserção sobre string o distingue, e o Playwright clica nele
 * normalmente, porque o controle *funciona*; ele só não tem como ser lido.
 *
 * Foi assim que o "Tentar de novo" de `app/error.tsx` atravessou o produto sendo
 * o **único** dos doze `.ai-button` sem ícone — e logo o único caminho de
 * recuperação da tela de erro, sem nome, no celular. Achado ao fotografar a
 * evidência da F-028 (#75), não por leitura de código.
 *
 * A alternativa era restringir a regra ao herói, o que devolveria rótulo aos
 * botões do `/admin` — mudança visual numa superfície fora do escopo de uma
 * correção. Doze controles seguem a mesma convenção; o defeito era a exceção.
 */
function iconlessAiButtons(source) {
  const found = [];
  for (let at = source.indexOf("<button"); at !== -1; at = source.indexOf("<button", at + 1)) {
    if (/[\w-]/.test(source[at + "<button".length] ?? "")) continue;
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
    if (!/className=(?:"[^"]*\bai-button\b|\{`[^`]*\bai-button\b)/.test(tag)) continue;
    const close = source.indexOf("</button>", end);
    if (close === -1) continue;
    // Um componente React (`<Sparkles />`, `<Mail />`) ou um `<svg>` cru. Basta
    // existir: o que a regra móvel preserva é o glifo, não qual é.
    const inner = source.slice(end + 1, close);
    if (/<[A-Z][\w]*[\s/>]|<svg[\s>]/.test(inner)) continue;
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

/**
 * O atalho de tela, que a ADR 0069 deixou aberto e esta fatia fecha.
 *
 * A guarda é de **alcance**, não de aparência: o `apple-touch-icon` e o manifesto
 * são buscados pelo navegador a partir de `/login`, quando ainda não há sessão, e o
 * `proxy.ts` responde a tudo que não está na exceção com um redirect para `/login`.
 * Um manifesto que volta como HTML não dá erro visível — o navegador simplesmente
 * não oferece a instalação —, que é a forma de falha que esta asserção existe para
 * impedir. E cada `src` declarado no manifesto é buscado de verdade: ícone anunciado
 * e ausente é o mesmo silêncio por outro caminho.
 */
test("o manifesto e os ícones da marca resolvem sem sessão", async () => {
  const manifest = await render("/manifest.webmanifest", { redirect: "manual" });
  assert.equal(manifest.status, 200);
  const declared = JSON.parse(await manifest.text());
  assert.equal(declared.name, "One — by Biahflow");
  assert.equal(declared.theme_color, "#6e56cf");

  const sources = [...new Set(declared.icons.map((icon) => icon.src))];
  sources.push("/apple-touch-icon.png");
  for (const src of sources) {
    const asset = await render(src, { redirect: "manual" });
    assert.equal(asset.status, 200, `${src} não é alcançável sem sessão`);
    assert.match(asset.headers.get("content-type") ?? "", /image\/png/, `${src} não voltou PNG`);
  }
});

test("server-renders the login page", async () => {
  const response = await render("/login");
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /<title>One<\/title>/i);
  assert.match(html, /Acompanhe seus projetos de IA em um só lugar\./);
  // As duas tags que fazem o atalho de tela existir. Elas saem de `generateMetadata`,
  // e afirmá-las no HTML — e não no fonte — é o que prova que o Next as emitiu.
  assert.match(html, /rel="manifest"[^>]*href="\/manifest\.webmanifest"|href="\/manifest\.webmanifest"[^>]*rel="manifest"/);
  assert.match(html, /rel="apple-touch-icon"[^>]*href="\/apple-touch-icon\.png"|href="\/apple-touch-icon\.png"[^>]*rel="apple-touch-icon"/);
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
  // A manchete deixou de ser a projeção da origem e passou a ser o **valor
  // gerado** (issue #89, ADR 0085): R$ 48.000 + R$ 12.500 do razão do mandato.
  // O ROI projetado não sumiu do produto — continua na aba Resultados, rotulado
  // desde a ADR 0084 —, e é por isso que a asserção mudou de lugar em vez de sumir.
  assert.match(html, /Valor gerado/);
  assert.match(html, /Value Ledger/);
  // O recorte é o **card de manchete** (`<p>ROI projetado</p>`), e não a palavra:
  // "ROI projetado/mês" continua no card do Funcionário Digital, que é outro
  // número, de outro produtor, e que esta fatia não toca.
  assert.doesNotMatch(html, /<p>ROI projetado<\/p>/);
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
  // O carimbo de frescor, com o rótulo da **origem** (ADR 0076): a fixture traz
  // `observed_at` preenchido, então a frase é "Atualizado há X". A ADR 0026 tinha removido
  // desta tela um "Atualizado há 2 dias" que era frescor inventado; ele volta derivado de
  // uma hora que a origem carimbou.
  assert.match(html, /Atualizado há 2 horas/);
  // E dentro do limiar não há aviso de velho — sem isto, o teste do stale passaria com o
  // aviso aparecendo sempre.
  assert.doesNotMatch(html, /Pode estar desatualizado/);
});

test("o KPI mostra Baseline e Outcome lado a lado, e a lacuna não vira zero", async () => {
  // Os critérios (3) e (4) da issue #89 (ADR 0085), no HTML do servidor.
  //
  // A fixture traz dois KPIs de propósito: o `12` medido dos dois lados, e o `15`
  // com **janela sem número** no Outcome. O segundo é o que importa — é o caso em
  // que um `?? 0` no mapeamento ou no componente faria a tela do cliente afirmar
  // "0" sobre um indicador que ninguém mediu.
  const response = await render("/", { headers: { cookie: await sessionCookie() } });
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /O QUE ESTAMOS MEDINDO/);
  assert.match(html, /Horas de conciliação por mês/);
  // O par, na mesma unidade: 72h de onde se partiu e 21,5h de onde se chegou.
  assert.match(html, /Baseline/);
  assert.match(html, /Outcome/);
  assert.match(html, /72h/);
  assert.match(html, /21,5h/);
  // A lacuna é frase, nunca número.
  assert.match(html, /Divergências reabertas/);
  assert.match(html, /Ainda não medido/);
  assert.match(html, /Sem meta definida/);
  // E o Digital Employee que move os dois indicadores aparece ligado a eles pelo
  // id da origem — é o que `kpi_ids` existe para dizer.
  assert.match(html, /Movido por/);

  // O Value Ledger: quantia, período e **método de atribuição** (invariante 12).
  assert.match(html, /Diferença Baseline→Outcome do KPI 12/);
  // A entrada cujo KPI de origem não está nesta resposta continua aparecendo — é
  // caso normal, não erro, porque o razão é do mandato e o KPI é do projeto.
  assert.match(html, /Receita adicional atribuída ao atendimento/);
  assert.match(html, /Indicador de origem em outro projeto deste Engagement/);
});

test("sem KPI e sem razão, a manchete declara a ausência em vez de imprimir R$ 0", async () => {
  // O outro lado do critério (4): mandato sem entrada nenhuma. "Nenhum valor
  // registrado ainda" e "R$ 0,00" dizem coisas opostas ao cliente, e só a
  // primeira é verdadeira num projeto que acabou de começar.
  dashboardOverride = { ...DASHBOARD, kpis: [], value_ledger: [] };
  try {
    const response = await render("/", { headers: { cookie: await sessionCookie() } });
    assert.equal(response.status, 200);
    const html = await response.text();
    assert.match(html, /Valor gerado/);
    assert.match(html, /Nenhum valor registrado ainda/);
    assert.doesNotMatch(html, /R\$&nbsp;0,00/);
    // Sem KPI não há painel de KPI: o componente devolve `null` em vez de um
    // cabeçalho vazio, como `DigitalEmployees` já fazia.
    assert.doesNotMatch(html, /O QUE ESTAMOS MEDINDO/);
    assert.doesNotMatch(html, /Value Ledger/);
  } finally {
    dashboardOverride = null;
  }
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
 * O rótulo do carimbo é o entregável desta fatia (F-028, ADR 0076).
 *
 * `observed_at` e `synced_at` chegam mutuamente exclusivos, e **qual dos dois veio é o
 * rótulo**: o primeiro é o instante em que a origem observou aquele estado, o segundo é o
 * instante em que o portal copiou. Chamar o segundo de "atualizado" é a falsa precisão que
 * `results.py` recusa e que a ADR 0026 removeu desta tela — os dois testes abaixo existem
 * para que a troca não possa acontecer em silêncio, e é por isso que cada um afirma
 * também a **ausência** da frase do outro.
 */
test("o fallback é rotulado como hora da cópia, e nunca como observação da origem", async () => {
  dashboardOverride = {
    ...DASHBOARD,
    observed_at: null,
    synced_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

    assert.match(html, /Sincronizado há 3 horas/);
    assert.match(html, /hora da cópia, não da origem/);
    // A frase da origem não pode aparecer aqui de jeito nenhum: é o defeito inteiro.
    assert.doesNotMatch(html, /Atualizado há/);
  } finally {
    dashboardOverride = null;
  }
});

test("sem hora nenhuma não há carimbo, e a tela não inventa um", async () => {
  // Projeto que ainda não passou por um sync. É o terceiro estado, e ele **não** é "velho":
  // é a ausência do insumo, que o DAP r1 manda tratar não carimbando.
  dashboardOverride = { ...DASHBOARD, observed_at: null, synced_at: null };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

    assert.match(html, /Você está aqui/);
    assert.doesNotMatch(html, /Atualizado há/);
    assert.doesNotMatch(html, /Sincronizado há/);
    assert.doesNotMatch(html, /Pode estar desatualizado/);
  } finally {
    dashboardOverride = null;
  }
});

test("acima do limiar a jornada diz que o dado pode estar velho", async () => {
  dashboardOverride = {
    ...DASHBOARD,
    observed_at: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
  };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

    assert.match(html, /Atualizado há 5 dias/);
    assert.match(html, /Pode estar desatualizado/);
    // Pill **e** motivo, no padrão de `readOnlyReason`: o selo sozinho não diz o que fazer
    // com ele, e a variante `warning` é o que separa "velho" de "indisponível" (`danger`)
    // e de "encerrado" (cinza).
    assert.match(html, /state-pill--warning/);
    assert.match(html, /Última observação no Biahflow há 5 dias/);
    // E continua sendo dado: o histórico não some porque envelheceu.
    assert.match(html, /Plano de implantação v3\.pdf/);
  } finally {
    dashboardOverride = null;
  }
});

test("o limiar do stale sai da configuração, não de uma constante na tela", async () => {
  // 30 horas: velho pelo default de 24 do BFF, novo pelo `PROJECTION_STALE_HOURS=48` que
  // este servidor de teste declara. É o que prova que o número é de quem opera — o DAP r1
  // o deixa explicitamente fora do que aprova, e uma constante no componente tornaria a
  // decisão nossa sem que nada ficasse vermelho.
  dashboardOverride = {
    ...DASHBOARD,
    observed_at: new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString(),
  };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

    assert.match(html, /Atualizado há 1 dia/);
    assert.doesNotMatch(html, /Pode estar desatualizado/);
  } finally {
    dashboardOverride = null;
  }
});

/**
 * Indisponível é **sem dado**, e não pode virar projeto vazio (ADR 0076, DAP r1 §Surfaces).
 *
 * O estado nasce de uma falha de fetch, que sobe para `app/error.tsx` — a mesma fronteira
 * que a Fase 1 criou para que indisponibilidade parasse de virar dashboard de demonstração.
 *
 * **O que este teste pode afirmar foi medido, e é menos do que parece.** O documento do
 * SSR sai com o `loading.tsx` dentro do limite de Suspense e um `$RX(...)` no fim: o
 * componente de servidor lançou depois de os cabeçalhos terem ido embora, então a resposta
 * é 200 e **quem desenha o cartão de erro é o cliente**, depois da hidratação. Nenhuma
 * asserção sobre HTML renderizado alcança aquele markup — o que o alcança é a captura de
 * navegador da T08, e é lá que ele está.
 *
 * O que sobra aqui é a asserção que importa e é justamente a **negativa**: nenhum pedaço
 * do projeto pode atravessar. Um resto de tela renderizado sobre uma projeção que não
 * chegou é dado velho passado por atual, que é o que a fatia nega no outro extremo com o
 * carimbo. A forma do cartão fica sob guarda de fonte, ao lado dela.
 */
test("a projeção que não chegou não vira projeto vazio, e o erro viaja com código", async () => {
  const cookie = await sessionCookie();
  const saudavel = await (await render("/", { headers: { cookie } })).text();

  dashboardStatus = 503;
  try {
    const response = await render("/", { headers: { cookie } });
    const html = await response.text();

    // Nada do projeto atravessa: nem o nome, nem a jornada, nem o histórico.
    assert.doesNotMatch(html, /Automação Financeira/);
    assert.doesNotMatch(html, /Você está aqui/);
    assert.doesNotMatch(html, /Plano de implantação v3\.pdf/);
    // E nem carimbo: sem projeção não há frescor a declarar. As duas frases, porque as
    // duas mentiriam igual.
    assert.doesNotMatch(html, /Atualizado há/);
    assert.doesNotMatch(html, /Sincronizado há/);
    // O erro viajou com o `digest` que a tela mostra ao cliente e que amarra a linha
    // `web.request_error` (ADR 0018). A render saudável acima é o que torna esta asserção
    // não-vacuosa: o código só aparece quando alguma coisa falhou de verdade.
    assert.match(html, /digest/);
    assert.doesNotMatch(saudavel, /digest/);
  } finally {
    dashboardStatus = null;
  }

  // E a forma do cartão que o cliente desenha, já que o HTML do SSR não a carrega: o selo
  // `danger` é o que separa indisponível (sem dado) de stale (`warning`, há dado velho) e
  // de encerrado (cinza). Colapsar as três cores é colapsar os três estados.
  const errorPage = (await readSources()).get("app/error.tsx");
  assert.match(errorPage, /StatePill variant="danger"/);
  assert.match(errorPage, /Projeção indisponível/);
  assert.match(errorPage, /não um projeto vazio/);
});

test("a espera não desenha projeto nenhum", async () => {
  // O carregando do SSR (`app/loading.tsx`). Ele não é assertável por HTTP — quando a
  // resposta chega, a espera acabou —, então o que se afirma é a **forma**: um esqueleto
  // com número no lugar do dado que ainda não chegou seria dado inventado com outra roupa,
  // e o HTML dele seria indistinguível do verdadeiro.
  const loading = (await readSources()).get("app/loading.tsx");

  assert.ok(loading, "app/loading.tsx sumiu: a espera do SSR voltou a ser tela em branco");
  assert.match(loading, /CARREGANDO/);
  assert.doesNotMatch(loading, /\d+\s*%|R\$|Atualizado há|Sincronizado há/);
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
 * O programa acima do projeto, no topo da barra lateral (ADR 0079).
 *
 * A hierarquia do Language Map v1.1 é Account → Engagement → Project, e o topo passou a
 * desenhá-la nessa ordem. As três asserções abaixo cobrem os três estados que o campo
 * tem, e cada uma nega a frase das outras: sem a negação, um rótulo que aparecesse
 * **sempre** passaria verde nas três.
 *
 * O rótulo sai do **dashboard** e não da lista de `/me`, e é o que a terceira prova: com
 * o projeto fora da lista (ADR 0062) o programa continua nomeado, porque quem o afirma é
 * a resposta que serviu aquele projeto.
 */
test("o topo nomeia o programa acima do projeto", async () => {
  const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();
  const markup = renderedMarkup(html);

  assert.match(markup, /<small>Transformação Financeira<\/small>/);
  assert.match(markup, /<small>Automação Financeira<\/small>/);
  // Programa corrente não ganha sufixo de estado: dizer "ativo" em toda tela é ruído,
  // e é a mesma regra com que a ADR 0036 marca encerrado e não marca ativo.
  assert.doesNotMatch(markup, /Transformação Financeira · /);
});

test("o projeto sem programa não ganha rótulo inventado", async () => {
  // O Biahflow ainda pode não mandar a chave, e a ontologia diz que todo projeto
  // pertence a um Engagement — então "sem programa" seria uma afirmação que ninguém fez.
  // O silêncio é a resposta, na regra do carimbo de frescor ausente (ADR 0026/0076).
  meOverride = {
    ...ME,
    projects: [{ ...ME.projects[0], engagement_id: null, engagement_name: null }],
  };
  dashboardOverride = { ...DASHBOARD, engagement: null };
  try {
    const markup = renderedMarkup(
      await (await render("/", { headers: { cookie: await sessionCookie() } })).text(),
    );

    assert.doesNotMatch(markup, /Transformação Financeira/);
    assert.doesNotMatch(markup, /sem programa|Sem programa|sem engagement/i);
    // E o projeto continua na tela: ausência de programa não esconde projeto.
    assert.match(markup, /<small>Automação Financeira<\/small>/);
  } finally {
    meOverride = null;
    dashboardOverride = null;
  }
});

test("o programa pausado é dito, e o rótulo vem do dashboard mesmo fora da lista", async () => {
  // Duas coisas na mesma renderização, e as duas são sobre a fonte do rótulo. O projeto
  // servido não está em `me.projects`, então `activeProject` é `null` e a lista não sabe
  // de programa nenhum; quem sabe é o dashboard, que projetou aquele projeto.
  meOverride = { ...ME, projects: [{ ...ME.projects[0], id: HOMONYMS.first }] };
  dashboardOverride = {
    ...DASHBOARD,
    project_id: HOMONYMS.second,
    engagement: { ...DASHBOARD.engagement, status: "paused" },
  };
  try {
    const markup = renderedMarkup(
      await (await render("/", { headers: { cookie: await sessionCookie() } })).text(),
    );

    assert.match(markup, /project-switcher--unlisted/);
    assert.match(markup, /Transformação Financeira · pausado/);
  } finally {
    meOverride = null;
    dashboardOverride = null;
  }
});

/**
 * Só os blocos `journey-gate` do HTML — o selo da decisão de fase e o que está
 * dentro dele (ADR 0081/0085).
 *
 * Existe porque a asserção abaixo é sobre **onde** a palavra "Outcome" pode
 * aparecer, e não sobre ela existir: desde a ADR 0085 o Outcome de negócio tem
 * produtor e é renderizado na mesma página, legitimamente.
 */
function gateBlock(html) {
  return [...html.matchAll(/<div class="journey-gate">[\s\S]*?<\/div>\s*<\/div>/g)]
    .map((match) => match[0])
    .join("\n");
}

/**
 * O degrau da FDE e a decisão da fase, na jornada (ADR 0081).
 *
 * A fase servida pela fixture é `Prove`, com `requires_gate: true` e sem decisão — o
 * caso que **só existe porque `requires_gate` atravessa o contrato**: sem ele, "fase
 * sem gate" e "gate ainda por decidir" seriam a mesma coisa aqui, e a tela teria de
 * calar sobre as duas.
 */
test("a fase mostra o degrau da FDE e diz que o gate está por decidir", async () => {
  const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

  assert.match(html, /Você está aqui/);
  // O degrau vem do contrato, e não do nome da fase — a derivação que a ingestão
  // recusa fazer.
  assert.match(html, /PROVE/);
  assert.match(html, /Decisão da fase/);
  assert.match(html, /aguardando/);
  // E não é Outcome: a decisão de gate mora na jornada, e a palavra "Outcome"
  // pertence a `Measurement(kind=outcome)` (decisão D7 do Language Map). Sem esta
  // asserção o selo poderia estar certo e o vocabulário errado.
  //
  // **O recorte deixou de ser a página inteira na ADR 0085, e a mudança é do
  // mundo, não da asserção**: até ali `Outcome` não tinha produtor neste
  // repositório, então "a palavra não aparece em lugar nenhum" e "a palavra não
  // aparece no selo do gate" eram a mesma afirmação. O KPI trouxe o Outcome de
  // verdade para a visão geral, e a asserção larga passaria a proibir justamente o
  // uso **certo** do termo. O que ela sempre quis dizer é o bloco do gate.
  const gate = gateBlock(html);
  // Recorte vazio afirmaria nada, em verde — o defeito que a ADR 0033 nomeia. O
  // rótulo tem de estar dentro do que o recorte devolveu.
  assert.match(gate, /Decisão da fase/);
  assert.doesNotMatch(gate, /Outcome/);
});

test("a fase decidida mostra o rótulo canônico da decisão", async () => {
  // O ramo decidido, por override: uma fixture só desenha um caso, e os dois ramos
  // do gate precisam de exemplo executado — é o mesmo motivo do projeto encerrado.
  dashboardOverride = {
    ...DASHBOARD,
    journey: {
      ...DASHBOARD.journey,
      phases: DASHBOARD.journey.phases.map((phase) =>
        phase.name === "Prove" ? { ...phase, gate_decision: "conditional_go" } : phase,
      ),
    },
  };
  try {
    const html = await (await render("/", { headers: { cookie: await sessionCookie() } })).text();

    assert.match(html, /Decisão da fase/);
    // O rótulo é o canônico do Language Map §2, em inglês e em maiúsculas: traduz-se
    // o texto em volta do termo, nunca o termo.
    assert.match(html, /CONDITIONAL GO/);
    assert.doesNotMatch(html, /aguardando/);
  } finally {
    dashboardOverride = null;
  }
});

test("a fase sem gate não ganha caixa de decisão", async () => {
  // `Welcome` é `requires_gate: false` na fixture. Selecioná-la pela âncora do aviso
  // é o único jeito de olhar uma fase que não é a ativa, e sem esta asserção as duas
  // acima passariam com a caixa aparecendo em toda fase — que seria a tela afirmando
  // uma decisão faltando onde nunca haverá decisão.
  const markup = await anchored("Visão geral", "phase:Welcome");

  assert.match(markup, /DISCOVER/);
  assert.doesNotMatch(markup, /Decisão da fase/);
});

/**
 * O vocabulário banido do Language Map §5, na superfície que esta fatia toca.
 *
 * "POC", "piloto" e "MVP" são o que o PROVE **não** é: ele é a menor implementação
 * real em produção controlada, com critério de sucesso definido antes de construir.
 * A asserção é sobre o HTML renderizado e não sobre o código-fonte, porque o que
 * chega ao cliente é o HTML — um literal numa fixture e um literal num componente
 * produzem a mesma linha na tela.
 *
 * O lint de linguagem completo, sobre todas as superfícies, é a Issue #91. Esta é a
 * asserção pontual da fatia que apagou as ocorrências.
 */
test("a tela do cliente não chama o PROVE de piloto, POC ou MVP", async () => {
  const markup = renderedMarkup(
    await (await render("/", { headers: { cookie: await sessionCookie() } })).text(),
  );

  for (const banido of [/piloto/i, /\bPOC\b/, /\bMVP\b/]) {
    assert.doesNotMatch(markup, banido, `${banido} descreve o PROVE, e o PROVE não é isso`);
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

/** A aba de Revisão, renderizada pelo servidor. */
async function reviewTab() {
  const response = await render("/?tab=Revis%C3%A3o", {
    headers: { cookie: await sessionCookie() },
  });
  assert.equal(response.status, 200);
  return renderedMarkup(await response.text());
}

/**
 * A superfície de aceite deixou de ser reservada (F-027, DAP r1).
 *
 * Até esta fatia a F-025 §10 a desenhava e a declarava **não renderizada** — o
 * manifesto de evidência da F-025 chegou a registrar isso em `reserved`. Estas
 * asserções são o que separa "a superfície existe" de "a superfície foi desenhada".
 */
test("a aba de Revisão desenha o card do entregável entregue", async () => {
  const markup = await reviewTab();

  // O entregável elegível vem do estado que o snapshot já traz: `delivered`.
  assert.match(markup, /Acesso ao portal/);
  // E o que a operação ainda não entregou não pede decisão nenhuma do cliente.
  assert.doesNotMatch(markup, /Funcionário Digital/);

  // A distinção que a fatia inteira existe para afirmar: o merge de engenharia
  // não é o aceite do cliente, e a tela os separa em duas metades.
  assert.match(markup, /Entrega de engenharia/);
  assert.match(markup, /Concluída pela operação/);
  assert.match(markup, /Seu aceite/);
  assert.match(markup, /Pendente — aguardando você/);
  assert.match(markup, /merge de engenharia ≠ seu aceite/);

  // Os controles existem e são os do pacote aprovado.
  assert.match(markup, /Aprovar entrega/);
  assert.match(markup, /Pedir ajuste/);
});

test("a escada de aceite mostra os cinco rótulos, e `done` em cinza", async () => {
  const markup = await reviewTab();

  assert.match(markup, /Pronto para revisão/);
  assert.match(markup, /Em revisão/);
  assert.match(markup, /Aprovado/);
  assert.match(markup, /Ajuste pedido/);
  assert.match(markup, /Concluído pela operação/);

  // O tom de cada um, e não só o texto. `done` é **cinza** (`.state--2`) porque
  // quem conclui a entrega é a operação: o aceite do cliente autoriza `accepted`,
  // nunca `done` (ADR 0067). Pintá-lo de verde diria que o cliente o conquistou.
  assert.match(markup, /class="state state--2"[^>]*>Concluído pela operação/);
  assert.match(markup, /class="state state--0"[^>]*>Pronto para revisão/);
  // A janela é larga porque a primitiva põe um ícone entre a classe e o texto —
  // e o ícone é justamente o que faz o estado não depender só de cor (F-025 §04).
  assert.match(markup, /state-pill--info[^>]*>[\s\S]{0,800}?Em revisão/);
  assert.match(markup, /state-pill--success[^>]*>[\s\S]{0,800}?Aprovado/);
  assert.match(markup, /state-pill--warning[^>]*>[\s\S]{0,800}?Ajuste pedido/);
});

test("uma segunda decisão acrescenta, e a primeira aparece superada", async () => {
  // O reflexo na tela do `GRANT` só de `INSERT` (ADR 0077): quem escreve não
  // reescreve. A asserção que importa é a **negativa** — a decisão anterior
  // continua na tela, com o comentário que ela trazia.
  acceptanceOverride = ACCEPTANCES;
  try {
    const markup = await reviewTab();

    assert.match(markup, /Aprovado\. Pode seguir para produção\./);
    assert.match(markup, /Faltou o anexo de custos na seção 4\./);
    assert.match(markup, /superada/);
    assert.match(markup, /is-superseded/);
    // E o card veste o degrau da decisão em vigor, que é a última da lista.
    assert.doesNotMatch(markup, /Pendente — aguardando você/);
    // Nenhuma affordance de edição de decisão: o banco recusaria, e a tela não
    // pode sequer sugerir que existe.
    assert.doesNotMatch(markup, /Editar decisão|Refazer decisão|Apagar decisão/);
  } finally {
    acceptanceOverride = null;
  }
});

test("o histórico que não carregou não vira 'ninguém decidiu'", async () => {
  // Uma lista vazia diria "existe e ninguém decidiu". Não conseguir ler diz outra
  // coisa, e a tela precisa dizer a que é verdadeira — é a mesma regra do
  // `scan_state=skipped` não ser `clean`.
  acceptanceOverride = "fail";
  try {
    const markup = await reviewTab();

    assert.match(markup, /Não consegui carregar/);
    assert.doesNotMatch(markup, /Pendente — aguardando você/);
    assert.doesNotMatch(markup, /Nenhuma decisão registrada ainda/);
  } finally {
    acceptanceOverride = null;
  }
});

test("o projeto sem escrita mantém o histórico e fecha a decisão", async () => {
  // A API responde 409 aqui (ADR 0036/0037), então o formulário sai antes de a
  // pessoa digitar — em vez de falhar depois.
  dashboardOverride = { ...DASHBOARD, archived_at: "2026-08-06T22:23:24.171853+00:00" };
  try {
    const markup = await reviewTab();

    assert.match(markup, /o histórico de decisões fica para consulta/);
    assert.doesNotMatch(markup, /Aprovar entrega/);
    assert.doesNotMatch(markup, /Pedir ajuste/);
    // E a entrega continua listada: consulta é consulta, não desaparecimento.
    assert.match(markup, /Acesso ao portal/);
  } finally {
    dashboardOverride = null;
  }
});

test("o entregável sem identidade na origem diz por que não recebe decisão", async () => {
  // `external_ref` é nulo quando o Biahflow não mandou a chave, e aí não há rota de
  // aceite a chamar. Esconder a entrega seria a degradação silenciosa de sempre;
  // um botão que não leva a lugar nenhum seria o controle inerte da ADR 0026.
  dashboardOverride = {
    ...DASHBOARD,
    journey: {
      ...DASHBOARD.journey,
      phases: DASHBOARD.journey.phases.map((phase) => ({
        ...phase,
        deliverables: phase.deliverables.map((deliverable) => ({
          ...deliverable,
          external_ref: null,
        })),
      })),
    },
  };
  try {
    const markup = await reviewTab();

    assert.match(markup, /ainda não tem identificador na origem/);
    assert.doesNotMatch(markup, /Aprovar entrega/);
  } finally {
    dashboardOverride = null;
  }
});

test("a jornada oferece o atalho para a revisão da entrega identificada", async () => {
  // O `[Revisar]` do card do entregável, que é a outra metade da resolução do gate
  // ("aba própria **mais** atalho a partir do entregável"). A fase Welcome é aberta
  // pela âncora, como o `deliverable_delivered` a abre.
  const markup = await anchored("Visão geral", "deliverable:Acesso ao portal");
  assert.match(markup, />Revisar</);
});

test("a âncora do entregável destaca o card na aba de Revisão", async () => {
  const markup = await anchored("Revisão", "deliverable:Acesso ao portal");
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
    // E nenhum `.ai-button` fica sem ícone: abaixo de 760px o rótulo é colapsado
    // por CSS, então um botão sem glifo perde o **nome** e não a função.
    assert.deepEqual(
      iconlessAiButtons(source),
      [],
      `${path} tem .ai-button sem ícone — no celular ele vira um círculo sem` +
        ` rótulo, porque a regra móvel zera a fonte (achado em #75)`,
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

/* ==========================================================================
 * A regra de admissão de token, com portão (F-025 T04, PLAN_DEVIATION 01)
 * ==========================================================================
 *
 * `docs/design/one-design-system.md` publica, desde a T01, que "um token só entra no
 * `@theme` se algum seletor de `@layer components` (ou um utilitário do Tailwind) o
 * consumir". No mesmo commit em que a frase foi publicada, **sete tokens não tinham
 * consumidor nenhum** — `--color-info-50/600`, `--color-surface`, `--color-surface-sunken`
 * e os três raios. É o defeito da ADR 0033 dentro da própria fatia que o descreve: um
 * documento publicado sobre o que não existe.
 *
 * A T02 deu consumidor aos sete. Isto aqui é o que impede o oitavo: regra publicada sem
 * portão volta a divergir, e esse é o argumento inteiro da ADR 0034 — lá o `alerts.md`
 * tinha sido corrigido à mão e divergiu de novo pelo outro lado em dois dias.
 *
 * Três decisões, todas com precedente medido neste repositório:
 *
 * 1. **O corpus é derivado, não digitado.** Ele sai do próprio bloco `@theme`. Um `for`
 *    sobre nomes escritos à mão é o que a ADR 0033 achou e generalizou: a guarda anterior
 *    de consumo de contrato era um laço sobre oito nomes num contrato de 56 esquemas, e a
 *    allowlist dela seguia vazia porque nada a consultava.
 *
 * 2. **Fail-closed.** `@theme` ilegível ou vazio reprova. Verde por não ter conseguido
 *    olhar é a forma do `dependency-review` da ADR 0023, que passou meses parecendo
 *    varredura enquanto olhava só o diff de um PR.
 *
 * 3. **O elo é medido, não argumentado.** Um token é consumido por `var(--token)` no CSS
 *    **ou** pelo utilitário que o Tailwind v4 gera a partir dele — `--color-info-600` vira
 *    `text-info-600`/`bg-info-600`/`border-info-600`, `--radius-card` vira `rounded-card`,
 *    `--shadow-pop` vira `shadow-pop`. O casador é estreito nas duas pontas de propósito:
 *    exige prefixo de utilitário na frente e recusa continuação de palavra atrás. Sem a
 *    segunda metade, `--color-brand-5` passaria verde por causa de `bg-brand-500` — que é
 *    o `.priority` da ADR 0033 e o `date` da ADR 0038, os dois casos em que um nome casou
 *    por substring e a guarda deu por consumido o que ninguém consumia.
 */

/**
 * O bloco `@theme` inteiro, com as chaves balanceadas. `null` quando não existe.
 *
 * A âncora é `^@theme` em início de linha, e isso foi medido: a busca solta casava a
 * menção a `@theme` **dentro de um comentário** de `@layer components`, e daí em diante a
 * varredura balanceava as chaves de outro bloco e devolvia zero token. Renomear o bloco
 * de verdade continuaria reprovando — mas pela asserção errada, dizendo "o `@theme`
 * existe e está vazio" sobre um arquivo onde ele não existe mais.
 */
function themeBlock(css) {
  const at = css.search(/^@theme\b/m);
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  if (open === -1) return null;
  let depth = 0;
  for (let end = open; end < css.length; end += 1) {
    if (css[end] === "{") depth += 1;
    else if (css[end] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(at, end + 1);
    }
  }
  return null;
}

/**
 * O texto sem comentário.
 *
 * Um token citado em prosa não é um token consumido — é justamente como um documento
 * afirma o que o código não faz. O erro possível aqui é só numa direção: apagar demais
 * derruba um consumidor de verdade e a guarda fica **vermelha**, nunca verde por engano.
 * O `[^:\w]` antes de `//` é o que preserva `https://` dentro de string.
 */
function withoutComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|[^:\w])\/\/[^\n]*/g, "$1 ");
}

/** Os utilitários que o Tailwind v4 gera a partir de um token, por família. */
function utilityPattern(family, value) {
  const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const side = "(?:x-|y-|t-|r-|b-|l-|s-|e-)?";
  const corner = "(?:t-|r-|b-|l-|s-|e-|tl-|tr-|br-|bl-|ss-|se-|es-|ee-)?";
  if (family === "color") {
    return (
      `(?:text|bg|fill|stroke|from|via|to|accent|caret|decoration|placeholder|ring|` +
      `outline|shadow|ring-offset)-${escaped}|(?:border|divide)-${side}${escaped}`
    );
  }
  if (family === "radius") return `rounded-${corner}${escaped}`;
  if (family === "shadow") return `(?:shadow|inset-shadow|drop-shadow)-${escaped}`;
  if (family === "font") return `font-${escaped}`;
  return null;
}

/** Os arquivos que consomem um token, por `var(--token)` ou pelo utilitário dele. */
function consumersOf(token, sources) {
  const [, family, value] = /^--([a-z]+)-(.+)$/.exec(token);
  // As duas pontas são fechadas por asserção de largura zero, para que o trecho relatado
  // seja exatamente o utilitário: `(?<![\w-])` recusa continuação de palavra na frente e
  // `(?![\w-])` atrás — é o segundo que separa `brand-50` de `brand-500`.
  const utility = new RegExp(`(?<![\\w-])(?:${utilityPattern(family, value)})(?![\\w-])`);
  const variable = new RegExp(`var\\(\\s*${token}\\s*[,)]`);
  const found = [];
  for (const [path, source] of sources) {
    const hit = source.match(variable) ?? source.match(utility);
    if (hit) found.push(`${path} (${hit[0].trim()})`);
  }
  return found;
}

/**
 * Token que o `@theme` declara e que ninguém consome, com o motivo por extenso.
 *
 * A isenção **não tem prazo**, no precedente do `PINNED_BY_EXCEPTION` de
 * `test_supply_chain_pins.py` e pelo argumento que ele já escreveu: token não caduca por
 * calendário. O vencimento dela é a asserção de obsolescência abaixo, que reprova no dia
 * em que o token ganhar consumidor ou sair do `@theme`.
 *
 * Nasce **vazia**, e isso é medição e não sorte: os 32 tokens de hoje têm consumidor, os
 * sete órfãos que a T01 deixou foram fechados pela T02, e o valor da linha vazia é a
 * asserção que a mantém assim.
 */
const TOKEN_WITHOUT_A_CONSUMER = {};

/** O `@theme`, os tokens dele e o corpus onde se procura consumidor. */
async function themeAndCorpus() {
  const sources = await readSources();
  const css = sources.get("app/globals.css");
  assert.ok(css, "app/globals.css sumiu do corpus varrido");

  const block = themeBlock(css);
  assert.ok(
    block,
    "não achei o bloco `@theme` em app/globals.css. A guarda de consumo de token" +
      " depende dele para existir, e um corpus que não deu para ler reprova em vez de" +
      " passar (ADR 0023).",
  );

  const tokens = [...block.matchAll(/^\s*(--(?:color|radius|shadow|font)-[\w-]+)\s*:/gm)].map(
    (match) => match[1],
  );

  // O consumidor tem de ser **fora** do `@theme`: um token que só aparece na própria
  // declaração não é consumido, e `--color-focus: var(--color-brand-500)` provaria o
  // contrário se o bloco entrasse no corpus.
  const corpus = new Map();
  for (const [path, source] of sources) {
    corpus.set(
      path,
      withoutComments(path === "app/globals.css" ? source.replace(block, " ") : source),
    );
  }
  return { tokens, corpus };
}

test("todo token do @theme tem consumidor, e o corpus sai do próprio @theme", async () => {
  const { tokens, corpus } = await themeAndCorpus();

  // Fail-closed nas duas pontas: um `@theme` que a varredura não conseguiu ler e um
  // corpus vazio produzem exatamente o mesmo verde de "nenhum token sem consumidor".
  assert.ok(
    tokens.length > 0,
    "o bloco `@theme` existe e a varredura não extraiu token nenhum dele. Isto é a" +
      " guarda cega, não um `@theme` limpo.",
  );
  assert.ok(corpus.size > 0, "o corpus de `app/` e `components/` voltou vazio");

  const orphans = tokens.filter(
    (token) => !(token in TOKEN_WITHOUT_A_CONSUMER) && consumersOf(token, corpus).length === 0,
  );

  assert.deepEqual(
    orphans,
    [],
    "estes tokens do `@theme` não têm consumidor em `app/` nem em `components/`: " +
      orphans.join(", ") +
      ". `docs/design/one-design-system.md` publica que um token só entra no `@theme` se" +
      " algum seletor o consumir — dê consumidor ao token, tire-o do `@theme`, ou" +
      " declare a isenção em `TOKEN_WITHOUT_A_CONSUMER` com o motivo por extenso" +
      " (F-025 T04, PLAN_DEVIATION 01).",
  );
});

test("a isenção de token não guarda linha que deixou de ser necessária", async () => {
  const { tokens, corpus } = await themeAndCorpus();

  const obsolete = [];
  for (const token of Object.keys(TOKEN_WITHOUT_A_CONSUMER).sort()) {
    if (!tokens.includes(token)) {
      obsolete.push(`${token}: não está mais no @theme`);
      continue;
    }
    const consumers = consumersOf(token, corpus);
    if (consumers.length > 0) obsolete.push(`${token}: já é consumido em ${consumers[0]}`);
  }

  assert.deepEqual(
    obsolete,
    [],
    "estas linhas de `TOKEN_WITHOUT_A_CONSUMER` deixaram de ser necessárias: " +
      obsolete.join("; ") +
      ". Apague-as. A isenção não tem prazo de propósito — token não caduca por" +
      " calendário —, então esta asserção é o único vencimento que ela tem" +
      " (precedente do `PINNED_BY_EXCEPTION`, ADR 0063).",
  );
});

test("o casador de consumo separa um token do irmão mais longo", async () => {
  // A medição que sustenta a guarda acima, e ela mora no arquivo porque um casador
  // frouxo é o defeito de que a ADR 0033 e a ADR 0038 são feitas: lá `.priority` e
  // `date` passaram verdes por substring, sem consumidor nenhum. Aqui o caso é
  // `--color-brand-5`, que não existe e cujo nome é prefixo de dois tokens que existem e
  // são usados o tempo todo.
  const corpus = new Map([["falso.css", ".x { @apply bg-brand-50 text-brand-500; }"]]);

  assert.deepEqual(consumersOf("--color-brand-5", corpus), []);
  assert.deepEqual(consumersOf("--color-brand-50", corpus), ["falso.css (bg-brand-50)"]);
  assert.deepEqual(consumersOf("--color-brand-500", corpus), ["falso.css (text-brand-500)"]);
  // E o utilitário tem de estar mesmo escrito: o nome do token solto na prosa não conta.
  assert.deepEqual(
    consumersOf("--radius-card", new Map([["prosa.tsx", "o raio de cartão é radius-card"]])),
    [],
  );
  assert.deepEqual(
    consumersOf("--radius-card", new Map([["uso.tsx", '<div className="rounded-card" />']])),
    ["uso.tsx (rounded-card)"],
  );
});
