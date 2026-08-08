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
  # O nome público de cada frente. Sem domínio próprio, `nip.io` resolve qualquer
  # `<qualquer-coisa>.<ip>.nip.io` para aquele IP — dá nome estável ao OIDC, que é
  # o que o Keycloak precisa para o `issuer` não mudar a cada deploy.
  #
  # **O IP é o de entrada**, do balanceador. Uma versão anterior usava o de saída,
  # do Cloud NAT: o nome resolvia, ninguém escutava lá, e o login não fechava. Ver
  # `modulos/borda/`.
  dominio_base = var.dominio != "" ? var.dominio : "${module.fundacao.ip_entrada}.nip.io"

  host_portal   = "portal.${local.dominio_base}"
  host_keycloak = "auth.${local.dominio_base}"
  host_biahflow = "app.${local.dominio_base}"

  url_portal   = "https://${local.host_portal}"
  url_keycloak = "https://${local.host_keycloak}"
  url_biahflow = "https://${local.host_biahflow}"

  # O realm, num lugar só. Ele estava escrito em três — `/realms/portal` aqui,
  # `portal-local` no default do `config.py` e `portal-homolog` no runbook —, e três
  # nomes para uma coisa é um `issuer` que não casa com o `iss` do token: a API
  # recusa todo acesso e a mensagem fala de assinatura, não de nome.
  realm = "portal-homolog"

  issuer   = "${local.url_keycloak}/realms/${local.realm}"
  jwks_url = "${local.issuer}/protocol/openid-connect/certs"

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
  # seria um ciclo, porque é este mapa que alimenta aquele. São os dois serviços de
  # ingress interno — os únicos que alguém chama por dentro.
  url_interna = { for nome in ["portal-api", "biahflow-api"] :
    nome => "https://${nome}-${data.google_project.este.number}.${var.regiao}.run.app"
  }

  host_interno = { for nome, url in local.url_interna : nome => replace(url, "https://", "") }

  # Os serviços HTTP. `publico = false` é o ingress interno — e para a `api` isso
  # não é preferência: o `Caddyfile` do compose decidiu que ela não é alcançada
  # pelo navegador, e publicá-la daria à internet um caminho que o produto não usa.
  servicos_http = {
    portal-web = {
      publico = true
      porta   = 3000
      cpu     = "1"
      memoria = "512Mi"
      min     = 0
      max     = 3
      dominio = local.host_portal
      variaveis = {
        NODE_ENV = "production"
        # A URL do serviço, não o nome dele: o Cloud Run não tem DNS de nome curto.
        API_BASE_URL          = local.url_interna["portal-api"]
        PORTAL_WEB_URL        = local.url_portal
        KEYCLOAK_ISSUER       = local.issuer
        KEYCLOAK_INTERNAL_URL = local.url_keycloak
        # `AUTH_URL` decide o prefixo `__Secure-` do cookie de sessão
        # (`app/lib/session.ts`). Ausente, o cookie sai sem o prefixo num ambiente
        # que **é** https, o que é exatamente o contrário do que o esquema indica.
        AUTH_URL = local.url_portal
        # O client id não é segredo — é o mesmo string público que aparece na URL de
        # autorização. Ele estava faltando, e o `auth.ts` caía no default
        # `"portal-web"`, que por acaso é o certo: funcionava por coincidência.
        AUTH_KEYCLOAK_ID = "portal-web"
      }
      # `AUTH_KEYCLOAK_SECRET` e não `KEYCLOAK_CLIENT_SECRET`: o nome do segredo **é**
      # o nome da variável de ambiente (o módulo usa a mesma string dos dois lados), e
      # quem lê é o `auth.ts:58`. Com o nome antigo o BFF subia com `clientSecret`
      # vazio e o login morria na troca do código, sem nada ficar vermelho no apply.
      segredos = ["AUTH_SECRET", "AUTH_KEYCLOAK_SECRET"]
    }

    portal-api = {
      publico = false
      porta   = 8000
      cpu     = "1"
      memoria = "1Gi"
      min     = 1 # o boot roda `preflight` e abre pool; zero daria 503 no primeiro acesso
      max     = 4
      dominio = null
      variaveis = {
        ENVIRONMENT    = "homolog"
        PORTAL_WEB_URL = local.url_portal
        OIDC_ISSUER    = local.issuer
        # As seis abaixo não estavam aqui, e a ausência **impedia a subida**: o
        # `preflight.py` varre toda setting string em busca de `localhost`,
        # `127.0.0.1`, `local_only` e `changeme`, e uma variável que ninguém fornece
        # cai no default local — que é justamente o que ele recusa. Fora de `local`
        # não existe "não configurei ainda"; existe processo que não sobe (ADR 0022).
        OIDC_JWKS_URL         = local.jwks_url
        KEYCLOAK_INTERNAL_URL = local.url_keycloak
        KEYCLOAK_REALM        = local.realm
        # `web_origin` é cobrada duas vezes: pela sentinela e por `_MUST_BE_HTTPS`.
        WEB_ORIGIN = local.url_portal
        # O Biahflow é interno e o BFF não fala com ele — quem fala é esta API, pela
        # rede da VPC, no nome do serviço do Cloud Run.
        BIAHFLOW_BASE_URL = "${local.url_interna["biahflow-api"]}/api/v1"
        # O callback do Drive é uma URL de navegador, então é o host público.
        GOOGLE_DRIVE_REDIRECT_URI = "${local.url_portal}/admin/conhecimento/drive-callback"
        # TLS termina na borda e acreditar nisso é opt-in (ADR 0011).
        TRUST_X_FORWARDED_PROTO     = "true"
        STORAGE_ENDPOINT_URL        = "https://storage.googleapis.com"
        STORAGE_PUBLIC_ENDPOINT_URL = "https://storage.googleapis.com"
        STORAGE_BUCKET              = module.fundacao.bucket_documentos
        # Sem ClamAV em HML, por decisão registrada: o veredito vira `skipped`,
        # que **autoriza** indexação e download e continua sendo outra coisa que
        # `clean` no banco e na tela. Diferença explícita para produção.
        CLAMAV_HOST = ""
        # Sem SMTP em HML, e o **vazio é a forma de dizer isso**: o `mailer.py:42`
        # já trata host vazio como desligado, e o `preflight` salta valor vazio — de
        # modo que a ausência não precisa de um host falso para passar o portão. Um
        # host inventado passaria igual e mentiria. O convite de acesso continua
        # saindo, porque quem o manda é o SMTP **do realm** do Keycloak, que é
        # configuração de lá e passo de runbook.
        SMTP_HOST                   = ""
        NOTIFICATIONS_EMAIL_ENABLED = "false"
        WHATSAPP_ENABLED            = "false"
        CONTACT_WINDOW_DAYS         = "7"
        CONTACT_CAP_PER_WINDOW      = "3"
      }
      segredos = [
        "DATABASE_URL", "DATABASE_SYSTEM_URL", "DATABASE_ADMIN_URL",
        # **A API não usa esta DSN, e precisa dela para subir.** O `preflight` varre
        # o `model_dump()` inteiro, e `database_migration_url` tem default com
        # `local_only`: sem entregá-la, o processo reprova por uma credencial que só
        # o job de migração exerce. Entregar o segredo é mais honesto do que abrir
        # exceção no portão — a alternativa seria o portão parar de olhar um campo.
        "DATABASE_MIGRATION_URL",
        "BIAHFLOW_READ_TOKEN", "BIAHFLOW_WEBHOOK_SECRET",
        "AGENT_KEY_PEPPER", "DRIVE_TOKEN_ENCRYPTION_KEY",
        "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
        # Está em `_REQUIRED_SECRETS` (`preflight.py:78`): vazio, o cliente de admin
        # do Keycloak falha fechado e em silêncio, e o convite de acesso — que fecha
        # a Fase 1 — para de sair sem nada ficar vermelho.
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
        # Sem estas duas o respondedor cai no modo offline e o índice no projetor
        # determinístico: o chat continua respondendo, com outra qualidade e sem
        # avisar. É o silêncio que a ADR 0022 existe para impedir, e elas já eram
        # criadas no Secret Manager sem serem ligadas a serviço nenhum.
        "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
        # Upstash, `rediss://`. Externo e por segredo — não há Redis nosso para
        # apontar, e é isso que dispensou a VM e o Memorystore.
        "REDIS_URL",
      ]
    }

    keycloak = {
      publico = true
      porta   = 8080
      cpu     = "1"
      memoria = "1Gi"
      # Um só, e nunca zero: o Keycloak leva dezenas de segundos para subir, e um
      # provedor de identidade que dorme faz todo login esperar por ele.
      min     = 1
      max     = 1
      dominio = local.host_keycloak
      variaveis = {
        KC_PROXY          = "edge"
        KC_HOSTNAME       = local.host_keycloak
        KC_DB             = "postgres"
        KC_HEALTH_ENABLED = "true"
        KC_HTTP_ENABLED   = "true"
      }
      segredos = ["KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD"]
    }

    biahflow-api = {
      publico = false
      porta   = 8000
      cpu     = "1"
      memoria = "1Gi"
      min     = 1
      max     = 4
      dominio = null
      variaveis = {
        # `biahflow-api` é o nome pelo qual esta API é alcançada **dentro** da VPC, e
        # sem ele o Django responde 400 a toda chamada do portal — o tropeço já
        # registrado no runbook de integração, onde um `curl` da máquina funcionava
        # porque mandava outro `Host`. O `localhost` é para as sondas do Cloud Run.
        DJANGO_ALLOWED_HOSTS    = "${local.host_biahflow},${local.host_interno["biahflow-api"]},localhost"
        TRUST_X_FORWARDED_PROTO = "true"
        PORTAL_BASE_URL         = local.url_portal
        # As quatro abaixo existem porque o `entrypoint.sh` de lá roda
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
        # O modo que roda em qualquer lugar (ADR 0016 do Biahflow): credencial de
        # usuário por refresh token, como o n8n. O `adc` exigiria metadata server.
        GOOGLE_AUTH_MODE = "oauth"
      }
      segredos = [
        "DJANGO_SECRET_KEY", "DATABASE_URL", "REDIS_URL",
        "PORTAL_READ_TOKEN", "PORTAL_WEBHOOK_SECRET",
        "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
      ]
    }

    biahflow-web = {
      publico = true
      porta   = 8080
      cpu     = "1"
      memoria = "256Mi"
      min     = 0
      max     = 3
      dominio = local.host_biahflow
      variaveis = {
        API_UPSTREAM = local.url_interna["biahflow-api"]
        # O nginx do SPA usava `resolver 127.0.0.11`, o DNS do Docker, que não existe
        # aqui. `169.254.169.254` é o servidor de metadados, que resolve nome público.
        DNS_RESOLVER = "169.254.169.254"
      }
      segredos = []
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
    portal-worker = {
      servico    = "portal-api"
      comando    = ["celery", "-A", "portal_api.worker.celery_app", "worker", "--loglevel=INFO"]
      instancias = 1
      cpu        = "1"
      memoria    = "1Gi"
    }
    portal-beat = {
      servico    = "portal-api"
      comando    = ["celery", "-A", "portal_api.worker.celery_app", "beat", "--loglevel=INFO"]
      instancias = 1
      cpu        = "1"
      memoria    = "512Mi"
    }
    # O agendador do Biahflow (FDD 023 de lá: digest diário, sincronia de calendário,
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
    portal-migrate = {
      servico = "portal-api"
      comando = ["alembic", "upgrade", "head"]
    }
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
