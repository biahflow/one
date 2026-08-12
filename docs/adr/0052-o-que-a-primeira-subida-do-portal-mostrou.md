# ADR 0052 — O que a primeira subida do portal mostrou

**Status:** aceito
**Data:** 12/08/2026
**Fecha:** os passos 8 e 11 do `hml-gcp.md`, que nunca tinham sido percorridos
**Relacionadas:** ADR 0022 (preflight), ADR 0045 (worker no Cloud Run), ADR 0046 (o
Terraform de HML), ADR 0048 (a borda), ADR 0050 (o primeiro apply), ADR 0051 (três states)

## Contexto

O portal do cliente estava declarado em Terraform desde a ADR 0046 e **nunca tinha subido**:
os três serviços viviam na `imagem_bootstrap`, e `portal.<base>` respondia a página
"Congratulations | Cloud Run". Não era descuido — era o escopo escolhido quando a HML
subiu só para o Biahflow, e o `WIF_PROVIDER` deste repositório ficou desligado de
propósito enquanto `DATABASE_URL` era um segredo compartilhado (ADR 0051 fechou isso).

Subi-lo achou **sete defeitos**, e seis são da mesma família: uma variável que o
`docker-compose.yml` declara e o Terraform não reproduzia. Vale nomear a família, porque
ela já tinha aparecido duas vezes — `NUM_PROXIES` na ADR 0050, e antes dela o
`API_UPSTREAM` que o nginx não lia. **O compose é a especificação de fato do que cada
processo precisa, e ninguém estava comparando os dois.**

## Os sete

**1. `KC_DB_SCHEMA` ausente.** O `roles.sql` cria dois schemas no mesmo banco — `portal`
e `keycloak` — e sem a variável o Keycloak migra o próprio schema dentro de `public`.
Sobe, funciona, e deixa as tabelas fora do `pg_dump -n portal` do backup: a ausência só
apareceria no dia do restore.

**2. O Keycloak não tinha caminho para a imagem real.** A costura monta a imagem de todo
serviço como `<registro>/<nome>:<tag>`, e o `deploy-hml.yml` só constrói as duas que são
nossas. O IdP ficaria na `imagem_bootstrap` **para sempre**, servindo a página do Cloud
Run no endereço que o `issuer` do realm declara. Medido: o Cloud Run **recusa** imagem de
`quay.io`, e a mensagem de erro dele nomeia a saída — um repositório remoto no Artifact
Registry. É cache sob demanda, e não um `docker pull && push` que alguém precisa lembrar
de refazer.

**3. O módulo de serviço não aceitava argumentos.** A imagem do Keycloak tem `kc.sh` como
entrypoint e nenhum comando padrão: subia, imprimia a ajuda e saía, e o Cloud Run relatava
*"failed to start and listen on the port"* — que fala de porta e não de comando. A
primeira tentativa ensinou a distinção que virou comentário no módulo: **no Cloud Run
`command` substitui o entrypoint e `args` é o que se passa a ele**; o `command:` do
Docker Compose, apesar do nome, é `args`. Os módulos de job e worker usam `comando`
porque lá a substituição é o ponto; aqui a variável se chama `argumentos`.

**4. `KC_PROXY` foi removido no Keycloak 26.** Declarado, é ignorado em silêncio — e o
efeito medido é o servidor anunciar `"issuer":"http://auth.<base>/..."`. A `portal-api`
valida o `iss` contra `https://`, então **todo token seria recusado com mensagem sobre
assinatura**: o defeito #6 da ADR 0046 chegando por outra porta. Agora é
`KC_PROXY_HEADERS=xforwarded`, e `KC_HOSTNAME` passou a ser URL completa.

**5. `KC_BOOTSTRAP_ADMIN_USERNAME` ausente.** O Keycloak 26 só cria o administrador
inicial se receber usuário **e** senha. Com a senha sozinha ele sobe, não cria ninguém, e
a única pista é o `invalid_grant` de quem tenta entrar. Pior: o bootstrap só roda com o
banco vazio, então quando a variável chegou ele já se considerava inicializado — foi
preciso zerar o schema (87 tabelas, nenhum dado) para o admin nascer.

**6. `KEYCLOAK_INTERNAL_URL` significa coisas diferentes em dois serviços.** No
`portal-web` o `auth.ts` monta `${internal}/protocol/openid-connect/token`, então ela é a
**base do realm**; na `portal-api` quem a lê é o cliente de administração, que fala com
`/admin/realms/...`, então ela é a **raiz do servidor**. O compose tinha as duas formas —
linha 416 com o realm, linha 161 sem — e o Terraform passava o mesmo valor aos dois,
acertando um. O sintoma foi a tela genérica do Auth.js *"problema com a configuração do
servidor"*, que não diz qual.

**7. O primeiro login de um usuário desconhecido é uma corrida.** Este não é de
configuração, é de produto, e continua **aberto**. `identity.resolve_user` seleciona e
depois insere, sem tratar inserção concorrente; o BFF busca `/me` e o dashboard **em
paralelo** (é o desenho, e está no `CLAUDE.md`). No primeiro login as duas requisições
tentam provisionar o mesmo usuário: uma ganha, a outra estoura em `uq_user_email` e a tela
mostra "não conseguimos carregar seu projeto". Recarregar resolve, porque a linha já
existe — e é por isso que passa por instabilidade em vez de defeito.

Nunca tinha aparecido porque **no compose o seed já criou os usuários**: ninguém havia
exercitado "primeiro login de quem o banco não conhece". Ele acerta todo usuário novo, que
é exatamente o caminho de onboarding que a Fase 1 existe para entregar. A forma do
conserto já existe no repositório: a ADR 0041 resolveu esta mesma classe em
`onboarding.stamp_within` com `SAVEPOINT` — insere, e se a chave já existir, volta ao
savepoint e relê.

## Decisões

- **Um serviço pode declarar a própria imagem** (`imagem = null` significa "é nossa, o
  deploy publica"). A chave existe em todos os serviços do mapa porque o `for_each` só
  aceita valores de atributos idênticos — o mesmo motivo de `dominio = null`.
- **O espelho do `quay.io` mora na fundação**, como o registro: é infraestrutura
  compartilhada, e a versão do Keycloak fica explícita no `servicos.tf` — subir de versão
  é mudar uma linha, não um `latest` que muda sozinho no dia errado.
- **`client` e `client_version` entraram no `ignore_changes`.** São carimbo de quem tocou
  por último, e quem toca a imagem é o `gcloud` do deploy, por desenho. Sem isso todo
  deploy deixa o plano sujo e o `apply` seguinte os remove — para o deploy seguinte
  recolocar. É o desvio perpétuo da ADR 0051 outra vez, pela mesma razão.
- **O realm é criado pela API de administração, não pelo console.** O `hml-gcp.md`
  tratava isso como trabalho manual porque não há provider de Terraform para Keycloak — mas
  a API REST é roteirizável, e o que se ganha é reprodutibilidade: realm, os dois clients,
  o **mapper de audiência** (`aud = portal-api`, sem o qual todo token do BFF é recusado) e
  os papéis `manage-users`/`view-users` do service account.
- **O Celery do portal ganhou `global_keyprefix`.** Em HML o Redis é dividido com o outro
  produto, e não por gosto: medido, o Upstash contratado responde
  `Only 0th database is supported!` a um `SELECT 1`. Sem prefixo, a fronteira entre os dois
  seria a sorte de os nomes não se cruzarem.

## Consequências

- **O portal do cliente está no ar e o login fecha ponta a ponta**: navegador → BFF →
  Keycloak → troca de código no servidor → cookie do Auth.js → `portal-api` por dentro da
  VPC → Neon com RLS. Verificado, inclusive os claims do token (`iss` do realm,
  `aud: ["portal-api", "account"]`).
- **A conta entra e vê "nenhum projeto atribuído", e isso é o comportamento certo.** O
  portal não origina projeto — ele recebe por `sync_snapshot` (ADR 0006/0008), e esse sync
  ainda não rodou nesta HML.
- **Fica aberto o defeito 7**, e ele merece teste de regressão antes do conserto: o teste
  precisa disparar duas resoluções concorrentes do mesmo `sub` e afirmar que as duas
  devolvem a mesma linha.
- **Fica aberto o SMTP do realm.** Sem ele o convite de acesso pelo `/admin` falha em
  silêncio, porque quem manda aquele e-mail é o Keycloak e não a aplicação — o
  `SMTP_HOST` vazio da `portal-api` é decisão registrada e não a causa.
- **Fica aberta a integração Biahflow → portal.** Os quatro segredos pareados já estão nos
  dois lados; falta `PORTAL_WEBHOOK_URL` no Biahflow e um snapshot.
- **A família de defeitos merece uma guarda.** Sete achados em duas subidas, todos
  "variável que o compose declara e a infra não", pedem algo que compare as duas listas —
  não este ADR pela terceira vez. Fica nomeado, sem dono.
