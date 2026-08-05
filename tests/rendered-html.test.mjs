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

/**
 * Stands in for the FastAPI. Lets the SSR path be exercised for real — the same
 * fetches, the same projection — without Postgres, Keycloak or Python.
 */
function startApiStub() {
  const server = createServer((request, response) => {
    seenTraceIds.push(request.headers["x-request-id"]);
    const body = request.url?.startsWith("/api/v1/me/dashboard")
      ? DASHBOARD
      : request.url?.startsWith("/api/v1/me/notifications")
        ? NOTIFICATIONS
        : request.url?.startsWith("/api/v1/me/search")
          ? SEARCH
          : request.url?.startsWith("/api/v1/me")
            ? ME
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
  const apiBaseUrl = await apiStub.listening;

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

async function readSources() {
  const paths = await sourceFiles();
  const contents = await Promise.all(
    paths.map(async (path) => [path, await readFile(new URL(path, projectRoot), "utf8")]),
  );
  return new Map(contents);
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

  assert.match(html, /<title>Portal Labs \| Portal do Cliente<\/title>/i);
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
  assert.match(html, /<title>Portal Labs \| Portal do Cliente<\/title>/i);
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
  assert.match(html, /Atualizações recentes/);
  assert.match(html, /Plano de implantação v3\.pdf/);
  assert.match(html, /Comitê de projeto/);
  // O sino conta o que a API disse. Antes da Fase 2 eram três avisos fixos no
  // componente e um booleano de "já li" que um F5 desfazia.
  assert.match(html, /aria-label="Notificações \(2 não lidas\)"/);
  assert.doesNotMatch(html, /Your site is taking shape/);
  assert.doesNotMatch(html, /codex-preview/);
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
  assert.match(dashboard, /Pendência criada para Portal Labs/);
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
  assert.match(layout, /Portal Labs \| Portal do Cliente/);
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
