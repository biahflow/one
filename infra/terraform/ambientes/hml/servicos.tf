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
  dominio_base = var.dominio != "" ? var.dominio : "${module.fundacao.ip_saida}.nip.io"

  host_portal   = "portal.${local.dominio_base}"
  host_keycloak = "auth.${local.dominio_base}"
  host_biahflow = "app.${local.dominio_base}"

  url_portal   = "https://${local.host_portal}"
  url_keycloak = "https://${local.host_keycloak}"
  url_biahflow = "https://${local.host_biahflow}"

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
        NODE_ENV              = "production"
        API_BASE_URL          = "http://portal-api" # resolvido pela rede interna
        PORTAL_WEB_URL        = local.url_portal
        KEYCLOAK_ISSUER       = "${local.url_keycloak}/realms/portal"
        KEYCLOAK_INTERNAL_URL = local.url_keycloak
      }
      segredos = ["AUTH_SECRET", "KEYCLOAK_CLIENT_SECRET"]
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
        OIDC_ISSUER    = "${local.url_keycloak}/realms/portal"
        # TLS termina na borda e acreditar nisso é opt-in (ADR 0011).
        TRUST_X_FORWARDED_PROTO     = "true"
        STORAGE_ENDPOINT_URL        = "https://storage.googleapis.com"
        STORAGE_PUBLIC_ENDPOINT_URL = "https://storage.googleapis.com"
        STORAGE_BUCKET              = module.fundacao.bucket_documentos
        # Sem ClamAV em HML, por decisão registrada: o veredito vira `skipped`,
        # que **autoriza** indexação e download e continua sendo outra coisa que
        # `clean` no banco e na tela. Diferença explícita para produção.
        CLAMAV_HOST            = ""
        WHATSAPP_ENABLED       = "false"
        CONTACT_WINDOW_DAYS    = "7"
        CONTACT_CAP_PER_WINDOW = "3"
      }
      segredos = [
        "DATABASE_URL", "DATABASE_SYSTEM_URL", "DATABASE_ADMIN_URL",
        "BIAHFLOW_READ_TOKEN", "BIAHFLOW_WEBHOOK_SECRET",
        "AGENT_KEY_PEPPER", "DRIVE_TOKEN_ENCRYPTION_KEY",
        "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
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
        DJANGO_ALLOWED_HOSTS    = "${local.host_biahflow},localhost"
        TRUST_X_FORWARDED_PROTO = "true"
        PORTAL_BASE_URL         = local.url_portal
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
      publico   = true
      porta     = 8080
      cpu       = "1"
      memoria   = "256Mi"
      min       = 0
      max       = 3
      dominio   = local.host_biahflow
      variaveis = { API_UPSTREAM = "http://biahflow-api" }
      segredos  = []
    }
  }

  # Os processos longos que **não falam HTTP**, e é por isso que não são Cloud Run:
  # `celery worker` e `celery beat` não escutam porta, e um serviço Cloud Run que
  # não escuta em `$PORT` tem a revisão recusada. Vão para a VM, junto do Redis que
  # eles consomem — o que também dispensa o Memorystore.
  processos_longos = {
    portal-worker = "celery -A portal_api.worker.celery_app worker --loglevel=INFO"
    portal-beat   = "celery -A portal_api.worker.celery_app beat --loglevel=INFO"
  }
}
