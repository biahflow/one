import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import test, { after } from "node:test";

const projectRoot = new URL("../", import.meta.url);

/** Boot `next start` once for the whole file and reuse it across tests. */
let serverPromise;

function startServer() {
  const port = 3100 + Math.floor(Math.random() * 800);
  const child = spawn("npx", ["next", "start", "-p", String(port)], {
    cwd: projectRoot,
    stdio: ["ignore", "pipe", "pipe"],
    // AUTH_SECRET is what decrypts the session cookie; without it every request
    // to a gated route is a 500 instead of the redirect we are asserting.
    env: {
      ...process.env,
      NODE_ENV: "production",
      AUTH_SECRET: process.env.AUTH_SECRET ?? "portal_auth_test_only",
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

async function render(path = "/", init = {}) {
  serverPromise ??= startServer();
  const origin = await serverPromise.ready;
  return fetch(`${origin}${path}`, { headers: { accept: "text/html" }, ...init });
}

after(() => {
  serverPromise?.child.kill("SIGTERM");
});

/** Every source file we author, so guards survive files being split up. */
async function sourceFiles() {
  const roots = ["app", "components"];
  const found = [];

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

  // As abas do projeto leem `overview` (API), não mais arrays fixos — a guarda vale para
  // todo componente, já que as views vivem em `components/dashboard/`.
  for (const [path, source] of sources) {
    assert.doesNotMatch(
      source,
      /^const (documents|meetings|pendingItems|resolvedItems|schedule) = /m,
      `${path} reintroduziu dados fixos que a Fase 2 removeu`,
    );
    assert.doesNotMatch(source, /_sites-preview|SkeletonPreview/, `${path} tem resíduo do starter`);
  }

  assert.doesNotMatch(page, /_sites-preview|SkeletonPreview/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  // A camada Cloudflare saiu do repositório (ADR 0009).
  assert.doesNotMatch(packageJson, /vinext|wrangler|cloudflare|drizzle/);
  await assert.rejects(readFile(new URL("app/_sites-preview/SkeletonPreview.tsx", projectRoot)));
  await assert.rejects(readFile(new URL("worker/index.ts", projectRoot)));
});
