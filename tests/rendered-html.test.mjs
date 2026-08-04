import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import test, { after } from "node:test";

import { encode } from "next-auth/jwt";

import { DASHBOARD, ME } from "./fixtures/dashboard.mjs";

const projectRoot = new URL("../", import.meta.url);

const AUTH_SECRET = "portal_auth_test_only";
/** Cookie name on http; it doubles as the salt of the encryption key. */
const SESSION_COOKIE = "authjs.session-token";

/** Boot `next start` once for the whole file and reuse it across tests. */
let serverPromise;
let apiStub;

/**
 * Stands in for the FastAPI. Lets the SSR path be exercised for real — the same
 * fetches, the same projection — without Postgres, Keycloak or Python.
 */
function startApiStub() {
  const server = createServer((request, response) => {
    const body = request.url?.startsWith("/api/v1/me/dashboard")
      ? DASHBOARD
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
  (await serverPromise)?.child.kill("SIGTERM");
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
  assert.doesNotMatch(html, /Your site is taking shape/);
  assert.doesNotMatch(html, /codex-preview/);
});

test("keeps product metadata and avoids disposable starter artifacts", async () => {
  const sources = await readSources();
  const page = sources.get("app/page.tsx");
  const dashboard = sources.get("app/DashboardClient.tsx");
  const layout = sources.get("app/layout.tsx");
  const packageJson = await readFile(new URL("package.json", projectRoot), "utf8");

  // The interactive dashboard (chat logic) lives in the client component; page.tsx is the
  // server component that fetches real data and renders it (ADR 0006, Fase 2).
  assert.match(dashboard, /function answerFor/);
  assert.match(dashboard, /Pendência criada para Portal Labs/);
  assert.match(layout, /Portal Labs \| Portal do Cliente/);
  assert.match(layout, /lang="pt-BR"/);

  // Nada de dado fixo de volta: as abas leem `overview` (Fase 2) e a identidade
  // vem de `GET /api/v1/me` (Fase 1). `projects` e `currentUser` escapavam desta
  // guarda justamente por serem os últimos sobreviventes.
  for (const [path, source] of sources) {
    assert.doesNotMatch(
      source,
      /^const (documents|meetings|pendingItems|resolvedItems|schedule|projects|currentUser) = /m,
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
