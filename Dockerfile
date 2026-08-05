# Imagem do BFF (ADR 0009 escolheu `next start` em Node; a ADR 0022 separou as
# etapas).
#
# Era uma etapa só: `npm ci` com devDependencies, build, e o mesmo
# `node_modules` inteiro seguia para produção — TypeScript, ESLint e Playwright
# incluídos —, tudo rodando como root. Aqui o build acontece numa etapa que é
# descartada, e a imagem final leva só as dependências de runtime.

FROM node:26.5.1-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
# Sem `NODE_ENV=production` nesta etapa, de propósito: ele faria o `npm ci`
# pular as devDependencies, e é com elas que o `next build` acontece.
RUN npm ci
COPY . .
RUN npm run build


FROM node:26.5.1-alpine AS runtime

ENV NODE_ENV=production
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./

# `node` é um usuário que a imagem base já traz, sem privilégio. A 3000 é acima
# de 1024, e o `next start` não escreve no disco.
USER node

EXPOSE 3000
# `next start` já escuta em 0.0.0.0; --host não é flag do Next (seria -H).
CMD ["npm", "run", "start"]
