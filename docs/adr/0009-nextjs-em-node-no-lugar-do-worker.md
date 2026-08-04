# ADR 0009 — Next.js em Node no lugar do Cloudflare Worker

**Status:** Aceito — 04/08/2026

## Contexto

O frontend nasceu de um template (`site-creator-vinext-starter`) e, apesar de ter `next` nas
dependências, `next.config.ts` e a estrutura do App Router, **não era Next.js**: o build era
feito pelo [`vinext`](https://www.npmjs.com/package/vinext) (React 19 RSC sobre Vite) e o
artefato final era um **Cloudflare Worker** (`worker/index.ts`, `vite.config.ts`, wrangler e
miniflare no `npm run dev`). Junto vinha uma segunda camada de dados nunca usada: Drizzle ORM
contra Cloudflare D1, com `db/schema.ts` vazio e os bindings desligados
(`.openai/hosting.json` com `d1: null, r2: null`).

Ao planejar a Fase 1 (identidade e acesso, ADR 0003), o runtime virou o risco dominante — não
o OIDC em si:

- sem `middleware`/`proxy` e sem `cookies()` do `next/headers` com semântica padrão, o fluxo
  Authorization Code + PKCE e o cookie de sessão teriam de ser escritos à mão sobre Web Crypto;
- `cookies().set()` não é permitido em Server Component, o que empurra a renovação de token
  para um desenho próprio;
- sem KV/D1/R2 habilitados, não há onde guardar sessão server-side — o estado teria de caber
  todo em cookie cifrado.

Ou seja: para entregar autenticação, escreveríamos código de segurança artesanal onde o
ecossistema já tem solução madura (Auth.js v5 com provider Keycloak).

## Decisão

Migrar para **Next.js 16 puro**, executado por `next start` em **Node dentro do Docker
Compose** que já orquestra api, worker, Postgres, Redis, MinIO, Keycloak e Mailpit.

Sai do repositório toda a camada Cloudflare e os resíduos do template: `vite.config.ts`,
`worker/`, `build/`, `.openai/`, `dist/`, `.wrangler/`, `drizzle.config.ts`, `drizzle/`,
`db/`, `examples/d1/` e `app/chatgpt-auth.ts` (código morto). Saem as dependências `vinext`,
`vite`, `wrangler`, `@cloudflare/vite-plugin`, `@vitejs/plugin-rsc`, `@vitejs/plugin-react`,
`react-server-dom-webpack`, `drizzle-orm` e `drizzle-kit`.

O `Dockerfile` já fazia `npm ci` → `npm run build` → `npm run start` na porta 3000; só o
`CMD` mudou (o `--host 0.0.0.0` que passávamos não é flag do `next start`, e ele já escuta em
todas as interfaces).

Na mesma mudança, o Tailwind v4 — instalado e importado, mas praticamente sem uso — passou a
ser a camada de estilo de fato, com tokens em `@theme` e os componentes recorrentes em
`@layer components`. A identidade visual (roxo/navy "Portal Labs") foi preservada; a fonte
passou de Arial para Inter.

## Consequências

- **A Fase 1 fica padrão:** Auth.js v5 + provider Keycloak, `proxy.ts` (em Next 16 o
  `middleware.ts` está depreciado) e `cookies()` resolvem sessão, PKCE e refresh.
- **Uma camada de dados só.** O Postgres do FastAPI é a única fonte; o web é stateless. O
  caminho opcional de D1 deixa de existir — se algum dia a Cloudflare voltar, o caminho é
  `@opennextjs/cloudflare` sobre este mesmo código, não um fork do build.
- **Menos superfície:** o `node_modules` caiu para 366 pacotes e o `npm test` deixou de
  depender de um bundle de Worker — passou a subir `next start` e a fazer fetch de verdade.
- **Perde-se o deploy em edge.** Não havia deploy em produção ainda, então o custo é teórico;
  em compensação o ambiente de desenvolvimento passa a ser igual ao de produção.
- `docs/adr/0001-monorepo-e-stack.md` continua válida quanto ao monorepo; a parte de runtime
  do frontend é superada por esta ADR.
