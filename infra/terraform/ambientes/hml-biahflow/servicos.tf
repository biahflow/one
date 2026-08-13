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
  # e `API_UPSTREAM = "http://biahflow-api"` supunham um DNS de nome curto que o
  # Cloud Run **não tem** — não é Kubernetes, e não existe `portal-api.internal`. A
  # chamada falharia na resolução, e o `INGRESS_TRAFFIC_INTERNAL_ONLY` nem chegaria
  # a ser exercido.
  #
  # A URL é derivada e não lida de `module.servicos[...].url` por causa de um ciclo:
  # aquela saída é produzida a partir deste mapa. O formato é determinístico
  # (`<serviço>-<número do projeto>.<região>.run.app`), e o número vem do data source
  # abaixo — que não depende de recurso nenhum nosso.
  # A lista é literal e curta de propósito: derivá-la de `keys(local.servicos_http)`
  # seria um ciclo, porque é este mapa que alimenta aquele. São os dois serviços sem
  # nome público — a `portal-api`, de ingress interno, e a `biahflow-api`, que de fora
  # só a borda alcança e que a `portal-api` continua chamando por dentro da VPC.
  url_interna = { for nome in ["portal-api", "biahflow-api"] :
    nome => "https://${nome}-${local.numero_projeto}.${var.regiao}.run.app"
  }

  host_interno = { for nome, url in local.url_interna : nome => replace(url, "https://", "") }

  # Os serviços HTTP. `acesso` tem três valores e não é um booleano, porque há três
  # clientes possíveis: a internet (`publico`), um processo nosso (`interno`, com
  # ingress **e** IAM) e o navegador **pela nossa borda** (`balanceador`).
  #
  # Para a `portal-api`, `interno` não é preferência: o `Caddyfile` do compose decidiu
  # que ela não é alcançada pelo navegador — quem fala com ela é o BFF, que sabe
  # apresentar identidade. Para a `biahflow-api` a resposta é outra, e é por isso que
  # o terceiro valor existe: quem a chama é o SPA, e nginx não emite ID token. Ver
  # `modulos/servico-cloudrun/`.
  servicos_http = {
    biahflow-api = {
      # As duas imagens deste produto são nossas: o deploy as publica no registro.
      imagem     = null
      argumentos = []
      acesso     = "balanceador"
      porta      = 8000
      cpu        = "1"
      memoria    = "1Gi"
      min        = 1
      max        = 4
      dominio    = null
      variaveis = {
        # `biahflow-api` é o nome pelo qual esta API é alcançada **dentro** da VPC, e
        # sem ele o Django responde 400 a toda chamada do portal — o tropeço já
        # registrado no runbook de integração, onde um `curl` da máquina funcionava
        # porque mandava outro `Host`. O `localhost` é para as sondas do Cloud Run.
        #
        # **Os dois primeiros passaram a ser exercidos por caminhos diferentes**
        # (ADR 0048): `app.<base>` é o Host que o balanceador **preserva** ao entregar
        # `/api|/admin|/static` direto aqui — um NEG sem servidor não reescreve Host —,
        # e o `run.app` é o que a `portal-api` usa por dentro da VPC. Antes só o
        # segundo valia, porque o nginx reescrevia o Host para `$proxy_host`.
        DJANGO_ALLOWED_HOSTS    = "${local.host_biahflow},${local.host_interno["biahflow-api"]},localhost"
        TRUST_X_FORWARDED_PROTO = "true"
        PORTAL_BASE_URL         = local.url_portal
        # As cinco abaixo existem porque o `entrypoint.sh` de lá roda
        # `check --deploy --fail-level WARNING --tag security` antes do gunicorn, e
        # esse check **reprova** com `SECURE_SSL_REDIRECT` e `SECURE_HSTS_SECONDS`
        # desligados. Os defaults do `settings.py` os deixam desligados, e o
        # `docs/operacao.md` avisa por extenso: o compose de produção os liga, e quem
        # sobe fora dele precisa ligá-los. Nós subimos fora dele.
        #
        # O redirecionamento é do balanceador, não do Django — a borda já manda 80
        # para 443. Aqui ele existe para o check parar de reprovar e para o caso de
        # alguém alcançar o contêiner por outro caminho.
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
        # `X-Forwarded-For`. Aqui a cadeia é cliente → balanceador → Cloud Run, e o
        # header chega `<cliente>, <balanceador>`: logo **2**, e não o `1` do compose,
        # onde o nginx é o único salto. Errar para baixo é o defeito que o próprio
        # E002 descreve — todo mundo atrás do mesmo proxy dividindo um balde só; errar
        # para cima faz o DRF ler a ponta esquerda, que o cliente pode forjar.
        # **Fica aberto medir o header como ele chega**; 2 é raciocínio, não medição.
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


    biahflow-web = {
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
        # `app.<base>` direto para a `biahflow-api`, o navegador nunca mais alcança os
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
        API_UPSTREAM = local.url_interna["biahflow-api"]
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
    biahflow-scheduler = {
      servico    = "biahflow-api"
      comando    = ["python", "manage.py", "run_scheduler"]
      instancias = 1
      cpu        = "1"
      memoria    = "512Mi"
    }
  }

  # Os trabalhos que começam e terminam. Existiam nos workflows de deploy e não
  # existiam em lugar nenhum — um workflow que invoca recurso inexistente falha no
  # primeiro deploy, que é tarde para descobrir.
  trabalhos = {
    biahflow-migrate = {
      servico = "biahflow-api"
      comando = ["python", "manage.py", "migrate", "--noinput"]
    }
    biahflow-check = {
      servico = "biahflow-api"
      comando = ["python", "manage.py", "check_integrations", "--all"]
    }
  }
}
