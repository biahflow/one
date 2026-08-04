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
    env: { ...process.env, NODE_ENV: "production" },
  });

  const origin = `http://127.0.0.1:${port}`;
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  const ready = (async () => {
    // `next start` prints "Ready" on stdout, but polling is sturdier than parsing.
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (child.exitCode !== null) {
        throw new Error(`next start exited early (${child.exitCode}):\n${stderr}`);
      }
      try {
        const probe = await fetch(origin, { headers: { accept: "text/html" } });
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

async function render() {
  serverPromise ??= startServer();
  const origin = await serverPromise.ready;
  return fetch(origin, { headers: { accept: "text/html" } });
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

test("server-renders the customer portal dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /<title>Portal Labs \| Portal do Cliente<\/title>/i);
  assert.match(html, /Bom dia, Marina\./);
  assert.match(html, /Automação Financeira/);
  assert.match(html, /ROI do projeto/);
  assert.match(html, /Você está aqui/);
  assert.match(html, /SUA JORNADA/);
  assert.match(html, /No prazo/);
  assert.match(html, /Funcionários Digitais/);
  assert.match(html, /Agente Financeiro/);
  assert.match(html, /Perguntar à IA/);
  // Fase 2: pendências, documentos e reuniões vêm do read model (fallback demo no SSR).
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
