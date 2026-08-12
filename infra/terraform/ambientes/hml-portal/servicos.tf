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
    portal-web = {
      # `imagem = null` significa "esta é nossa, o deploy publica no nosso registro".
      # A chave existe nos três porque o `for_each` da costura só aceita o mapa se os
      # valores tiverem atributos idênticos — é o mesmo motivo de `dominio = null`.
      imagem     = null
      argumentos = []
      acesso     = "publico"
      porta      = 3000
      cpu        = "1"
      memoria    = "512Mi"
      min        = 0
      max        = 3
      dominio    = local.host_portal
      variaveis = {
        NODE_ENV = "production"
        # A URL do serviço, não o nome dele: o Cloud Run não tem DNS de nome curto.
        API_BASE_URL    = local.url_interna["portal-api"]
        PORTAL_WEB_URL  = local.url_portal
        KEYCLOAK_ISSUER = local.issuer
        # **A base do realm, não a raiz do servidor** — e a distinção não é preciosismo:
        # o `auth.ts:115` monta `${internal}/protocol/openid-connect/token`, então sem o
        # `/realms/<realm>` a troca do código bate numa URL que não existe e o Keycloak
        # responde `Unable to find matching target resource method`. O Auth.js traduz
        # isso para uma tela genérica de "problema com a configuração do servidor", que
        # não diz qual.
        #
        # **A mesma variável significa outra coisa na `portal-api`**, e o compose já
        # tinha as duas formas: lá é a raiz (`http://keycloak:8080`), porque quem a lê é
        # o cliente de administração, que fala com `/admin/realms/...`. Este Terraform
        # passava o mesmo valor para os dois e acertava só um.
        KEYCLOAK_INTERNAL_URL = "${local.url_keycloak}/realms/${local.realm}"
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
      segredos = {
        AUTH_SECRET          = "AUTH_SECRET"
        AUTH_KEYCLOAK_SECRET = "AUTH_KEYCLOAK_SECRET"
      }
    }


    portal-api = {
      imagem     = null
      argumentos = []
      acesso     = "interno"
      porta      = 8000
      cpu        = "1"
      memoria    = "1Gi"
      min        = 1 # o boot roda `preflight` e abre pool; zero daria 503 no primeiro acesso
      max        = 4
      dominio    = null
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
        STORAGE_BUCKET              = local.fundacao.bucket_documentos
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
      segredos = {
        # **A chave é a variável que o código lê; o valor é o segredo de onde ela vem.**
        # `DATABASE_URL` e `REDIS_URL` divergem porque os dois produtos leem esses dois
        # nomes e precisam de valores diferentes — até aqui havia um segredo só para
        # cada, montado nos dois, de modo que a `portal-api` e o Django do Biahflow
        # recebiam a mesma DSN e o mesmo Redis. Ninguém decidiu isso; era o preço de a
        # lista impor que os dois lados fossem a mesma string.
        DATABASE_URL        = "PORTAL_DATABASE_URL"
        REDIS_URL           = "PORTAL_REDIS_URL"
        DATABASE_SYSTEM_URL = "DATABASE_SYSTEM_URL"
        DATABASE_ADMIN_URL  = "DATABASE_ADMIN_URL"
        # **A API não usa esta DSN, e precisa dela para subir.** O `preflight` varre
        # o `model_dump()` inteiro, e `database_migration_url` tem default com
        # `local_only`: sem entregá-la, o processo reprova por uma credencial que só
        # o job de migração exerce. Entregar o segredo é mais honesto do que abrir
        # exceção no portão — a alternativa seria o portão parar de olhar um campo.
        DATABASE_MIGRATION_URL     = "DATABASE_MIGRATION_URL"
        BIAHFLOW_READ_TOKEN        = "BIAHFLOW_READ_TOKEN"
        BIAHFLOW_WEBHOOK_SECRET    = "BIAHFLOW_WEBHOOK_SECRET"
        AGENT_KEY_PEPPER           = "AGENT_KEY_PEPPER"
        DRIVE_TOKEN_ENCRYPTION_KEY = "DRIVE_TOKEN_ENCRYPTION_KEY"
        STORAGE_ACCESS_KEY         = "STORAGE_ACCESS_KEY"
        STORAGE_SECRET_KEY         = "STORAGE_SECRET_KEY"
        # Está em `_REQUIRED_SECRETS` (`preflight.py:78`): vazio, o cliente de admin
        # do Keycloak falha fechado e em silêncio, e o convite de acesso — que fecha
        # a Fase 1 — para de sair sem nada ficar vermelho.
        KEYCLOAK_ADMIN_CLIENT_SECRET = "KEYCLOAK_ADMIN_CLIENT_SECRET"
        # Sem estas duas o respondedor cai no modo offline e o índice no projetor
        # determinístico: o chat continua respondendo, com outra qualidade e sem
        # avisar. É o silêncio que a ADR 0022 existe para impedir, e elas já eram
        # criadas no Secret Manager sem serem ligadas a serviço nenhum.
        ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
        VOYAGE_API_KEY    = "VOYAGE_API_KEY"
      }
    }


    keycloak = {
      # **A única imagem que não construímos.** Vai pelo espelho do quay.io porque o
      # Cloud Run recusa registro de terceiro; a versão é fixa e explícita, e subir de
      # versão é mudar esta linha — não um `latest` que muda sozinho no dia errado.
      imagem = "${local.fundacao.registro_espelho}/keycloak/keycloak:26.1"
      # `start` e não `start-dev`: o compose usa o modo de desenvolvimento, que é
      # lenient de propósito e não serve a um ambiente com nome público e TLS. A
      # imagem não traz comando padrão — sem esta linha ela imprime a ajuda e sai.
      argumentos = ["start"]
      acesso     = "publico"
      porta      = 8080
      cpu        = "1"
      memoria    = "1Gi"
      # Um só, e nunca zero: o Keycloak leva dezenas de segundos para subir, e um
      # provedor de identidade que dorme faz todo login esperar por ele.
      min     = 1
      max     = 1
      dominio = local.host_keycloak
      variaveis = {
        # **`KC_PROXY` saiu, e `KC_PROXY_HEADERS` entrou.** A opção `proxy` foi removida
        # no Keycloak 25/26; declarada, ela é ignorada em silêncio — e o efeito medido é
        # que o servidor não confia no `X-Forwarded-Proto` da borda e passa a anunciar
        # `"issuer":"http://auth.<base>/realms/..."`. A `portal-api` valida o `iss`
        # contra `https://`, então todo token seria recusado com mensagem sobre
        # assinatura, que é o defeito #6 da ADR 0046 chegando por outra porta.
        KC_PROXY_HEADERS = "xforwarded"
        # URL completa e não só o host: com esquema, o Keycloak fixa o `https` em tudo
        # que ele gera — discovery, redirect e o próprio `issuer`.
        KC_HOSTNAME       = local.url_keycloak
        KC_DB             = "postgres"
        KC_HEALTH_ENABLED = "true"
        KC_HTTP_ENABLED   = "true"
        # **Faltava, e o compose já declarava.** O `roles.sql` cria dois schemas no
        # mesmo banco — `portal` para a aplicação e `keycloak` para o IdP — e sem esta
        # variável o Keycloak migra o próprio schema dentro de `public`: sobe, funciona,
        # e deixa as tabelas dele no lugar onde ninguém as procura no dia do restore.
        # O `pg_dump -n portal` do backup não as levaria, e a ausência só apareceria ao
        # restaurar. Mesma classe do `NUM_PROXIES` da ADR 0050: variável que o compose
        # tem e a infraestrutura esqueceu.
        KC_DB_SCHEMA = "keycloak"
        # **O usuário do admin de bootstrap, que faltava.** O Keycloak 26 só cria o
        # administrador inicial se receber usuário **e** senha; com a senha sozinha ele
        # sobe, não cria ninguém, e a única pista é o `invalid_grant` de quem tenta
        # entrar. Não é segredo — é o nome de login, e o par dele está no cofre.
        KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
      }
      segredos = {
        KC_DB_URL                   = "KC_DB_URL"
        KC_DB_USERNAME              = "KC_DB_USERNAME"
        KC_DB_PASSWORD              = "KC_DB_PASSWORD"
        KC_BOOTSTRAP_ADMIN_PASSWORD = "KC_BOOTSTRAP_ADMIN_PASSWORD"
      }
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
  }

  # Os trabalhos que começam e terminam. Existiam nos workflows de deploy e não
  # existiam em lugar nenhum — um workflow que invoca recurso inexistente falha no
  # primeiro deploy, que é tarde para descobrir.
  trabalhos = {
    portal-migrate = {
      servico = "portal-api"
      comando = ["alembic", "upgrade", "head"]
    }
  }
}
