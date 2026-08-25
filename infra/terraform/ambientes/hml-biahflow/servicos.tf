# A camada portátil.
#
# Descreve o que a aplicação precisa **sem citar GCP**: nome, imagem, porta, se é
# público, variáveis, quais segredos, quantas instâncias. É este arquivo que
# sobrevive a uma troca de provedor — o que se reescreve é `modulos/`.
#
# A regra para manter isso verdadeiro: nada aqui pode nomear um recurso de nuvem.
# Onde um valor só existe depois de a nuvem provisionar algo (o endereço do Redis,
# o nome do bucket), ele entra por referência ao módulo, não por literal.


locals {
  # **O endereço interno de um serviço do Cloud Run é a URL dele, não o nome dele.**
  # Isto estava errado desde a primeira versão: `API_BASE_URL = "http://portal-api"`
  # e `API_UPSTREAM = "http://pulse-api"` supunham um DNS de nome curto que o
  # Cloud Run **não tem** — não é Kubernetes, e não existe `portal-api.internal`. A
  # chamada falharia na resolução, e o `INGRESS_TRAFFIC_INTERNAL_ONLY` nem chegaria
  # a ser exercido.
  #
  # A URL é derivada e não lida de `module.servicos[...].url` por causa de um ciclo:
  # aquela saída é produzida a partir deste mapa. O formato é determinístico
  # (`<serviço>-<número do projeto>.<região>.run.app`), e o número vem do data source
  # abaixo — que não depende de recurso nenhum nosso.
  # A lista é literal e curta de propósito: derivá-la de `keys(local.servicos_http)`
  # seria um ciclo, porque é este mapa que alimenta aquele. `portal-api` saiu dela em
  # 13/08/2026, com o produto; sobrou a `pulse-api`, que não tem nome público e é
  # alcançada por dentro da VPC — pelo nginx do SPA e pelo relay do site de marketing.
  url_interna = { for nome in ["pulse-api"] :
    nome => "https://${nome}-${local.numero_projeto}.${var.regiao}.run.app"
  }

  host_interno = { for nome, url in local.url_interna : nome => replace(url, "https://", "") }

  # Os serviços HTTP. `acesso` tem quatro valores e não é um booleano — ver
  # `modulos/servico-cloudrun/`.
  #
  # A `pulse-api` usa `interno-sem-iam` desde que a borda da GCP foi apagada. Antes
  # era `balanceador`, que aceitava tráfego da VPC **e** do balanceador; sem
  # balanceador, o segundo termo é uma porta aberta para ninguém. Não é `interno`
  # porque nenhum dos dois chamadores sabe assinar: o nginx não emite ID token, e o
  # relay do site autentica por `X-Intake-Token` (`backend/server.py` daquele repo).
  servicos_http = {
    pulse-api = {
      # As duas imagens deste produto são nossas: o deploy as publica no registro.
      imagem     = null
      argumentos = []
      acesso     = "interno-sem-iam"
      porta      = 8000
      cpu        = "1"
      memoria    = "1Gi"
      # Zero: em homologação, 1 vCPU + 1 GiB acesos 730h/mês custam mais que todo o
      # resto do ambiente somado, e nada aqui exige processo vivo entre requisições —
      # o cache é o Redis do Upstash (não `LocMemCache`), não há agendador embutido
      # (quem agenda é o worker pool `pulse-scheduler`) e o boot só roda
      # `check --deploy`, sem migração.
      #
      # O preço é cold start no primeiro acesso. **Quem sente é o site**: o relay de
      # `biahflow-site` posta o lead aqui, e a `LeadIntakeView` ainda enriquece e
      # qualifica por IA de forma síncrona. O timeout de lá foi alargado por causa
      # desta linha — mexer numa coisa sem a outra derruba a captação.
      min     = 0
      max     = 4
      dominio = null
      variaveis = {
        # `pulse-api` é o nome pelo qual esta API é alcançada **dentro** da VPC, e
        # sem ele o Django responde 400 a toda chamada do portal — o tropeço já
        # registrado no runbook de integração, onde um `curl` da máquina funcionava
        # porque mandava outro `Host`. O `localhost` é para as sondas do Cloud Run.
        #
        # **Quem exercita cada um mudou de novo em 13/08/2026, e desta vez para trás.**
        # Com a borda da GCP apagada, o caminho do navegador voltou a ser
        # `Cloudflare → pulse-web → nginx → aqui`, e o nginx faz `proxy_pass` com
        # variável sem `proxy_set_header Host`: ele reescreve o Host para
        # `$proxy_host`, que é o `run.app` — o segundo da lista. O primeiro
        # (`app.<domínio>`) fica porque continua sendo o nome que o navegador digita e
        # o que o Django compara em `CSRF_TRUSTED_ORIGINS`; tirá-lo faria o formulário
        # de login reprovar sem o erro falar de Host.
        DJANGO_ALLOWED_HOSTS    = "${local.host_biahflow},${local.host_interno["pulse-api"]},localhost"
        TRUST_X_FORWARDED_PROTO = "true"
        # As cinco abaixo existem porque o `entrypoint.sh` de lá roda
        # `check --deploy --fail-level WARNING --tag security` antes do gunicorn, e
        # esse check **reprova** com `SECURE_SSL_REDIRECT` e `SECURE_HSTS_SECONDS`
        # desligados. Os defaults do `settings.py` os deixam desligados, e o
        # `docs/operacao.md` avisa por extenso: o compose de produção os liga, e quem
        # sobe fora dele precisa ligá-los. Nós subimos fora dele.
        #
        # O redirecionamento é da borda, não do Django — a Cloudflare já manda 80 para
        # 443. Aqui ele existe para o check parar de reprovar e para o caso de alguém
        # alcançar o contêiner por outro caminho.
        DJANGO_SSL_REDIRECT         = "true"
        DJANGO_HSTS_SECONDS         = "31536000"
        DJANGO_CSRF_TRUSTED_ORIGINS = local.url_biahflow
        FRONTEND_ORIGIN             = local.url_biahflow
        # `NUM_PROXIES` é a quinta, e faltava (ADR 0050): o `biahflow.E002` cobra o
        # **par** `TRUST_X_FORWARDED_PROTO` + `NUM_PROXIES`, e sem ela a revisão nem
        # sobe — foi o que reprovou o primeiro deploy real, com `Container called
        # exit(1)` e a sonda de inicialização recusando toda revisão.
        #
        # O valor é a posição, contada do fim, de onde o DRF tira o IP do cliente no
        # `X-Forwarded-For`. Errar para baixo é o defeito que o próprio E002 descreve —
        # todo mundo atrás do mesmo proxy dividindo um balde só; errar para cima faz o
        # DRF ler a ponta esquerda, que o cliente pode forjar.
        #
        # **A cadeia ficou mais longa em 13/08/2026 e este número não foi corrigido de
        # propósito.** Era cliente → balanceador → Cloud Run, e é
        # cliente → Cloudflare → Cloud Run(nginx) → Cloud Run(aqui): há dois saltos
        # novos, mas quantos deles aparecem no header depende de o nginx do SPA usar
        # `$proxy_add_x_forwarded_for` e de o Cloud Run acrescentar o seu — e nenhuma
        # das duas coisas foi medida. `2` já era raciocínio e não medição (ADR 0050);
        # trocá-lo por outro palpite não melhora nada.
        #
        # **Medir é um comando**, e está no runbook `hml-gcp.md`: uma requisição com
        # `X-Forwarded-For` conhecido e conferir o que o DRF lê. Fica aberto.
        NUM_PROXIES = "2"
        # O modo que roda em qualquer lugar (ADR 0016 do Biahflow): credencial de
        # usuário por refresh token, como o n8n. O `adc` exigiria metadata server.
        GOOGLE_AUTH_MODE = "oauth"
        # SMTP do Workspace. O default do `settings.py` de lá é `localhost:1025` — o
        # Mailpit do compose, que dentro do Cloud Run é lugar nenhum —, e a flag
        # `email` nasce ligada **sem exigir credencial**, porque SMTP tem default:
        # não há variável cuja ausência denuncie o problema. Quem denuncia é a sonda
        # do `check_integrations`, e ela vinha reprovando com `Connection refused`.
        #
        # Isso não é cosmético. `POST /invitations/` é transacional com
        # `fail_silently=False`: sem SMTP ele responde **502 e desfaz o convite** —
        # e o convite é o único caminho de onboarding do produto.
        #
        # 587 e não 465: o `settings.py` de lá só expõe `EMAIL_USE_TLS` (STARTTLS),
        # não há `EMAIL_USE_SSL`. E não 25: a GCP bloqueia a saída naquela porta.
        EMAIL_HOST      = "smtp.gmail.com"
        EMAIL_PORT      = "587"
        EMAIL_USE_TLS   = "true"
        EMAIL_HOST_USER = "daniel@biahflow.ai"
        # O Gmail recusa remetente que não seja a conta autenticada ou um alias dela,
        # então os dois são o mesmo endereço. O default do código é
        # `noreply@biahflow.local`, e `.local` não é domínio entregável — o runbook de
        # homologação já registrava que relay sério o recusa.
        DEFAULT_FROM_EMAIL = "daniel@biahflow.ai"
        # Onde os documentos passam a viver. Preenchida, o `settings.py` de lá troca
        # o `STORAGES["default"]` para o GCS; vazia, ele mantém o sistema de
        # arquivos — que é o que o compose continua usando, e é por isso que o teste
        # de mesa do backup segue válido lá.
        #
        # Referência ao módulo e não literal: o nome só existe depois de a nuvem
        # provisionar o bucket, e é a regra do topo deste arquivo.
        GCS_MEDIA_BUCKET = local.fundacao.bucket_midia
      }
      segredos = {
        # Os dois de baixo divergem da chave pela razão explicada na `portal-api`:
        # cada produto tem o seu banco e o seu Redis, e o nome da variável é contrato
        # com o código, não com o cofre.
        DATABASE_URL = "BIAHFLOW_DATABASE_URL"
        REDIS_URL    = "BIAHFLOW_REDIS_URL"

        DJANGO_SECRET_KEY          = "DJANGO_SECRET_KEY"
        PORTAL_READ_TOKEN          = "PORTAL_READ_TOKEN"
        PORTAL_WEBHOOK_SECRET      = "PORTAL_WEBHOOK_SECRET"
        GOOGLE_OAUTH_CLIENT_ID     = "GOOGLE_OAUTH_CLIENT_ID"
        GOOGLE_OAUTH_CLIENT_SECRET = "GOOGLE_OAUTH_CLIENT_SECRET"
        GOOGLE_OAUTH_REFRESH_TOKEN = "GOOGLE_OAUTH_REFRESH_TOKEN"
        EMAIL_HOST_PASSWORD        = "EMAIL_HOST_PASSWORD"
        # Sem esta linha o endpoint público de captação existe e recusa tudo: o
        # `settings.LEAD_INTAKE_TOKEN` nasce vazio e `_valid_intake_token` exige
        # `bool(expected)` antes de comparar. O site recebe 401, traduz para 502, e o
        # visitante lê "tente novamente" — sem nada de anormal no log de lá.
        LEAD_INTAKE_TOKEN = "LEAD_INTAKE_TOKEN"
      }
    }


    pulse-web = {
      # As duas imagens deste produto são nossas: o deploy as publica no registro.
      imagem     = null
      argumentos = []
      acesso     = "publico"
      porta      = 8080
      cpu        = "1"
      memoria    = "256Mi"
      min        = 0
      max        = 3
      dominio    = local.host_biahflow
      variaveis = {
        # **Estas duas ficaram sem cliente e continuam aqui de propósito** (ADR 0048).
        # Desde que a borda roteia `/api|/admin|/static|/healthz|/readyz` de
        # `app.<base>` direto para a `pulse-api`, o navegador nunca mais alcança os
        # blocos `location` do `nginx.conf.template` que as lêem: tirar o `proxy_pass`
        # do caminho era o ponto inteiro da mudança.
        #
        # Removê-las **não** faria o nginx falhar, e é por isso que ficam: o
        # `Dockerfile` do SPA declara `API_UPSTREAM=http://api:8000` e
        # `DNS_RESOLVER=127.0.0.11` como default da imagem, que são os valores do
        # compose. O nginx subiria igual e, no dia em que um `path_rule` estiver
        # errado, responderia 502 dizendo que não conseguiu resolver **`api`** — um
        # nome de rede do Docker, dentro do Cloud Run. Trocaríamos um caminho que
        # funciona por um diagnóstico que mente.
        #
        # Elas saem no mesmo commit em que `biahflow-portal` apagar aqueles dois
        # `location`. Configuração e leitor morrem juntos, e o leitor mora no outro
        # repositório.
        API_UPSTREAM = local.url_interna["pulse-api"]
        # O nginx do SPA usava `resolver 127.0.0.11`, o DNS do Docker, que não existe
        # aqui. `169.254.169.254` é o servidor de metadados, que resolve nome público.
        DNS_RESOLVER = "169.254.169.254"
      }
      segredos = {}
    }
  }

  # Os processos longos que **não falam HTTP**. Vão para **worker pool**, que é a
  # primitiva do Cloud Run feita para isso — o container de um worker pool nem tem
  # bloco `ports`. (Uma versão anterior deste arquivo os mandava para uma VM,
  # sobre a conclusão errada de que o Cloud Run não os aceitava; ver ADR 0045.)
  #
  # `instancias` é contagem **fixa**, e para o `beat` o número é 1 por definição:
  # dois agendadores emitem a mesma tarefa duas vezes.
  # `servico` diz de qual serviço este processo herda imagem, variáveis e segredos —
  # a mesma chave que `trabalhos` usa, e pelo mesmo motivo. Antes a herança era
  # fixa na `portal-api`, o que tornava impossível declarar aqui um processo longo do
  # **outro** produto sem lhe dar o ambiente errado.
  processos_longos = {
    # alerta de backup velho). Ele existe no `docker-compose.prod.yml` daquele repo e
    # **não tinha casa em HML** — de modo que as três rotinas simplesmente não
    # rodariam, incluindo a que avisa que o backup envelheceu. Um alerta de backup
    # que não roda é pior que nenhum: ele faz o silêncio parecer boa notícia.
    pulse-scheduler = {
      servico = "pulse-api"
      comando = ["python", "manage.py", "run_scheduler"]
      # Desligado em homologação (13/08/2026) por custo — 1 vCPU aceso 730h/mês para
      # rotinas que, aqui, rodam sobre dados de teste. **Desligar é diferente de
      # escalar a zero**: worker pool não acorda por requisição, então ele só volta
      # com um apply.
      #
      # O que para junto, e o comentário acima deste bloco não deixa esquecer:
      # digest diário, sincronia de calendário, faturas vencidas, frescor da base —
      # e o aviso de backup envelhecido. Em produção esta linha volta a ser 1, porque
      # lá "um alerta de backup que não roda é pior que nenhum" deixa de ser retórica.
      instancias = 0
      cpu        = "1"
      memoria    = "512Mi"
    }
  }

  # Os trabalhos que começam e terminam. Existiam nos workflows de deploy e não
  # existiam em lugar nenhum — um workflow que invoca recurso inexistente falha no
  # primeiro deploy, que é tarde para descobrir.
  trabalhos = {
    pulse-migrate = {
      servico = "pulse-api"
      comando = ["python", "manage.py", "migrate", "--noinput"]
    }
    pulse-check = {
      servico = "pulse-api"
      comando = ["python", "manage.py", "check_integrations", "--all"]
    }
  }
}

# --- Desmonte dos `cockpit-*` — BLOCO TEMPORÁRIO, SAI NO PR SEGUINTE ------------
#
# O rename da ADR 0070 criou os `pulse-*` e **não** conseguiu destruir os antigos: o
# `deletion_protection` do módulo nasce `true`, e o provider recusa com
# `cannot destroy service without setting deletion_protection=false and running
# `terraform apply``. A trava está certa — o comentário do módulo diz que desmontar
# deve custar uma linha explícita —, e esta é a linha.
#
# **Só que a trava só se abre com o recurso em configuração.** Uma entrada de state
# cuja config sumiu não tem onde receber `protegido = false`, então o desmonte custa
# dois `apply`: este PR devolve as cinco entradas com a trava aberta, e o PR seguinte
# as remove de novo — aí o destroy passa. Não há caminho de um apply só: o Terraform
# não atualiza e destrói o mesmo recurso na mesma passada.
#
# As entradas são **derivadas das vivas**, e não escritas à mão, porque o `pulse-*` é
# cópia exata do `cockpit-*` a menos do nome: derivar garante que o único diff real
# seja a trava. O plano vai mostrar junto alguma deriva de env (`DJANGO_ALLOWED_HOSTS`
# e `API_UPSTREAM` passam a citar `pulse-api`) e a recriação dos dois `invocacao_aberta`
# que o apply de 25/08 chegou a destruir antes de falhar. É ruído em recurso condenado,
# e some no PR seguinte.
locals {
  em_desmonte = { for nome in ["api", "web", "scheduler", "migrate", "check"] :
    "pulse-${nome}" => "cockpit-${nome}"
  }

  desmonte_servicos = {
    for vivo, morto in local.em_desmonte :
    morto => local.servicos_http[vivo] if contains(keys(local.servicos_http), vivo)
  }

  desmonte_processos_longos = {
    for vivo, morto in local.em_desmonte :
    morto => merge(local.processos_longos[vivo], {
      servico = local.em_desmonte[local.processos_longos[vivo].servico]
    }) if contains(keys(local.processos_longos), vivo)
  }

  desmonte_trabalhos = {
    for vivo, morto in local.em_desmonte :
    morto => merge(local.trabalhos[vivo], {
      servico = local.em_desmonte[local.trabalhos[vivo].servico]
    }) if contains(keys(local.trabalhos), vivo)
  }

  # O que os módulos consomem enquanto o desmonte dura.
  servicos_http_com_desmonte    = merge(local.servicos_http, local.desmonte_servicos)
  processos_longos_com_desmonte = merge(local.processos_longos, local.desmonte_processos_longos)
  trabalhos_com_desmonte        = merge(local.trabalhos, local.desmonte_trabalhos)
}
