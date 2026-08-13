# A borda: um endereço de entrada, um certificado, um nome por frente pública — e,
# desde a ADR 0048, **um caminho por serviço que não tem nome nenhum**.
#
# **Por que este módulo existe, e por que não é `google_cloud_run_domain_mapping`.**
# O `servicos.tf` declarava uma chave `dominio` por serviço desde o começo, e a
# costura nunca a consumiu: não havia recurso de mapeamento em lugar nenhum. O
# resultado era pior do que "faltou um pedaço" — o `KEYCLOAK_ISSUER` e o
# `PORTAL_WEB_URL` apontavam para nomes que resolviam para o IP de **saída** do
# Cloud NAT, onde nada escuta, e o OIDC não fechava. O README ainda afirmava que
# "o `terraform apply` refaz os mapeamentos".
#
# O mapeamento de domínio do Cloud Run **não serve aqui**: ele exige verificação de
# posse do domínio no Search Console, e `nip.io` não é nosso. O caminho que funciona
# com um domínio de terceiro é o balanceador HTTPS externo com NEGs sem servidor,
# porque o certificado gerenciado pela Google se valida por **resolução DNS até o IP
# do balanceador** — e `<qualquer-coisa>.<ip>.nip.io` resolve para `<ip>` por
# construção. É essa coincidência que torna o `nip.io` viável, e é ela que deixa de
# ser necessária no dia em que houver domínio de verdade: aí o mesmo módulo serve
# trocando `var.dominio`.
#
# O preço é uma regra de encaminhamento global, que é o único item de custo fixo de
# HML. A alternativa de custo zero é abandonar o nome e usar as URLs `*.run.app`,
# que já são estáveis e HTTPS; ela foi considerada e recusada porque o `issuer` do
# Keycloak passaria a conter o nome de um serviço do Cloud Run, e trocar de
# provedor deixaria de ser reescrever `modulos/`.

variable "regiao" { type = string }
variable "endereco" {
  description = <<-TXT
    O `self_link` do endereço global de entrada, criado na **fundação** e não aqui.

    A razão é um ciclo: sem domínio próprio o nome de cada host contém o IP
    (`portal.<ip>.nip.io`), e o certificado deste módulo precisa dos nomes. Se o
    endereço nascesse aqui, o `servicos.tf` dependeria de uma saída deste módulo
    para produzir uma entrada dele. Com o endereço na fundação, a ordem é
    fundação → nomes → borda, e o Terraform consegue resolvê-la.
  TXT
  type        = string
}
variable "backends" {
  description = <<-TXT
    Os serviços que o balanceador alcança, na forma `{ servico = ... }`. A **chave**
    nomeia o NEG e o backend service (`hml-<chave>`) e por isso é estável: trocá-la
    recria os dois.

    Nem todo backend tem nome público: a `biahflow-api` está aqui e **não** está em
    `rotas`, porque quem lhe manda tráfego é um `path_rule` de outro host.
  TXT
  type = map(object({
    servico = string
  }))
}
variable "rotas" {
  description = <<-TXT
    Um nome público e o que fazer com os caminhos dele. A **chave** nomeia o
    `path_matcher` e também é estável.

      `host`   — o nome completo, já resolvido pelo `servicos.tf`, que é quem sabe
                 se o domínio é próprio ou `nip.io`.
      `padrao` — a chave de `backends` que atende tudo que nenhuma regra pegou.
      `regras` — os caminhos que pertencem a **outro** serviço.

    `regras` existe porque a `biahflow-web` é nginx servindo um SPA e o cliente da
    API é o navegador: `/api`, `/admin` e `/static` de `app.<base>` são da
    `biahflow-api`, e atravessá-los pelo `proxy_pass` do nginx tornava impossível
    qualquer barreira além da rede (ADR 0046, ADR 0048).

    **É desta variável, e não de `backends`, que sai o `domains` do certificado.**
    Um backend novo não pode reemitir um certificado em uso.
  TXT
  type = map(object({
    host   = string
    padrao = string
    regras = optional(list(object({
      paths   = list(string)
      destino = string
    })), [])
  }))

  # Dois nomes iguais em `rotas` produzem dois `host_rule` com o mesmo host, e a API
  # responde "Host rule has a duplicate host" — depois de o certificado já ter sido
  # planejado com a lista repetida. Um `distinct()` no `domains` esconderia isto: o
  # certificado sairia bem-formado e o erro apareceria noutro recurso.
  #
  # **Medido, e o alcance é menor do que parece:** com `var.dominio` vazio o host
  # deriva do IP de entrada, que é desconhecido antes de existir, e uma condição
  # sobre valor desconhecido não é avaliada — o `terraform validate` do primeiro dia
  # passa. Ela dispara com host conhecido, que é todo `plan` posterior e todo
  # ambiente com domínio próprio. Escrito aqui para ninguém a ler como se cobrisse o
  # caso em que mais dói.
  validation {
    condition     = length(distinct([for r in var.rotas : r.host])) == length(var.rotas)
    error_message = "Dois hosts iguais em `rotas`: um host pertence a exatamente um `path_matcher`, e a API recusa o `url_map` inteiro."
  }

  # A regra que o próprio provider documenta em `path_rule.paths`: "each must start
  # with / and the only place a * is allowed is at the end following a /". Aqui e não
  # no apply, porque um caminho recusado pela API derruba o `url_map` inteiro — e com
  # ele os três nomes, não só o que estava errado.
  validation {
    condition = alltrue(flatten([
      for r in var.rotas : [
        for regra in r.regras : [
          for p in regra.paths :
          startswith(p, "/") && (!strcontains(p, "*") || endswith(p, "/*")) && length(regexall("\\*", p)) <= 1
        ]
      ]
    ]))
    error_message = "Caminho de `path_rule` inválido: começa com `/`, e o `*` só é aceito no fim, depois de uma `/`."
  }
}
variable "servico_padrao" {
  description = <<-TXT
    Para qual chave de **`backends`** vai quem chega por um nome que não mapeamos (ou
    pelo IP cru). Explícito e não `keys(...)[0]`, que seria a ordem alfabética — hoje
    `biahflow-api`, que é interna e não tem sequer uma tela para responder.
  TXT
  type        = string
}

variable "ligada" {
  description = <<-TXT
    Se as regras de encaminhamento existem. `false` desliga a borda inteira do ponto de
    vista de quem chega — e é a única coisa neste módulo que muda a fatura.

    **Só as regras de encaminhamento são cobradas.** NEG, backend service, url map,
    target proxy e o certificado gerenciado custam zero parados, então desligar é
    destruir dois recursos e reconstruí-los em segundos. É o que torna o custo do único
    item fixo de HML proporcional ao uso, num ambiente com um usuário só.

    **As duas rules caem juntas, e não é simetria estética.** As cinco primeiras regras
    globais custam US$ 0,025/hora **no total** — manter uma só sairia pelo mesmo preço
    de manter as duas, e não economizaria nada.
  TXT
  type        = bool
  default     = true
}

# Um NEG por serviço. É o que liga um balanceador a algo que não tem IP nem porta —
# o Cloud Run não é um grupo de instâncias, e o `cloud_run` aqui é o adaptador.
resource "google_compute_region_network_endpoint_group" "neg" {
  for_each = var.backends

  name                  = "hml-${each.key}"
  region                = var.regiao
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = each.value.servico }
}

resource "google_compute_backend_service" "backend" {
  for_each = var.backends

  name                  = "hml-${each.key}"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.neg[each.key].id
  }

  # Sem verificação de saúde, e não é esquecimento: um backend sem servidor não
  # aceita `health_checks` — a disponibilidade é do Cloud Run, não do balanceador.

  # A borda passou a ser o único caminho do navegador até a `biahflow-api`, e antes
  # havia um registro de acesso ali: o nginx do SPA escrevia uma linha por
  # requisição com o `req=<id>`. O GFE **não** gera `X-Request-ID` — o Django gera o
  # seu quando o header falta, então a correlação *dentro* da aplicação sobrevive
  # (ADR 0018); o que se perdia era a linha que prova "chegou na borda" num 502 ou
  # num timeout, que é justamente o caso em que a aplicação não tem log nenhum.
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

# Um certificado para os três nomes. Gerenciado, o que significa que a Google o
# emite e renova sozinha — **desde que** cada `domains` resolva para o IP da
# fundação. É por isso que a primeira emissão leva
# de quinze minutos a uma hora: enquanto ela não termina, o HTTPS responde erro de
# certificado e não erro de rota. `docs/runbooks/hml-gcp.md` diz como conferir.
#
# **Os nomes saem de `rotas`, e nunca de `backends`.** É a linha mais frágil deste
# arquivo: `backends` ganhou a `biahflow-api`, que não tem host, e derivar `domains`
# dali produziria um `null` na lista ou um nome a mais — e **trocar a lista recria o
# certificado**, o que derruba o HTTPS dos três nomes pelo tempo da emissão nova. A
# ordem também é parte da identidade, porque o provider tipa `domains` como `list` e
# não como `set`: `for` sobre map visita as chaves em ordem lexicográfica, então uma
# rota nova cuja chave ordene antes das existentes é uma **reemissão**, não um
# acréscimo.
resource "google_compute_managed_ssl_certificate" "cert" {
  name = "hml"
  managed {
    domains = [for r in var.rotas : r.host]
  }
  # Trocar a lista de nomes recria o certificado, e um certificado em uso não pode
  # ser destruído antes de o novo existir e estar preso ao proxy.
  lifecycle { create_before_destroy = true }
}

# O roteamento por nome, e dentro de um nome por caminho. O `default_service` é
# decisão e não sobra: quem chega pelo IP cru cai na frente que sabe pedir login,
# não no Keycloak, não numa API interna e não num 404 do balanceador.
#
# **Os `path_rule` são o que tira o `proxy_pass` do nginx do caminho.** Antes,
# `/api/*` de `app.<base>` ia para a `biahflow-web`, que reencaminhava por dentro da
# VPC — e como nginx não emite ID token, o IAM invoker da `biahflow-api` nunca era
# atravessado (ADR 0046). Agora a borda entrega direto à `biahflow-api` e a `run.app`
# dela deixou de existir para a internet. O casamento é por prefixo mais longo, então
# uma regra nova mais específica não conflita com estas.
resource "google_compute_url_map" "mapa" {
  name            = "hml"
  default_service = google_compute_backend_service.backend[var.servico_padrao].id

  dynamic "host_rule" {
    for_each = var.rotas
    content {
      hosts        = [host_rule.value.host]
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.rotas
    content {
      name            = path_matcher.key
      default_service = google_compute_backend_service.backend[path_matcher.value.padrao].id

      dynamic "path_rule" {
        for_each = path_matcher.value.regras
        content {
          paths   = path_rule.value.paths
          service = google_compute_backend_service.backend[path_rule.value.destino].id
        }
      }
    }
  }
}

resource "google_compute_target_https_proxy" "proxy" {
  name             = "hml"
  url_map          = google_compute_url_map.mapa.id
  ssl_certificates = [google_compute_managed_ssl_certificate.cert.id]
}

resource "google_compute_global_forwarding_rule" "https" {
  count = var.ligada ? 1 : 0

  name                  = "hml-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = var.endereco
  port_range            = "443"
  target                = google_compute_target_https_proxy.proxy.id
}

# Sem isto, acrescentar `count` renomeia o recurso de `.https` para `.https[0]` e o
# Terraform lê a mudança de endereço como destruir-e-criar — o que aqui é inofensivo,
# mas em qualquer recurso com estado seria perda de dado. O `moved` diz que é o mesmo
# recurso com outro nome.
moved {
  from = google_compute_global_forwarding_rule.https
  to   = google_compute_global_forwarding_rule.https[0]
}

# --- A porta 80, que existe para não servir nada --------------------------------
# Ela não é conveniência. Sem ela, um `http://` responde conexão recusada, e é isso
# que a validação do certificado gerenciado e o primeiro acesso de qualquer pessoa
# encontram antes de o HTTPS existir. Redirecionar é a única coisa que ela faz.
#
# **E é isso que dá prazo à borda desligada.** O certificado gerenciado se revalida
# sozinho antes de expirar, e a validação chega por aqui: com `ligada = false` não há
# porta 80 no IP, então uma renovação que caia numa janela de sono **falha**, e o
# certificado vai para `FAILED_NOT_VISIBLE`. Não se perde nada além de tempo — a
# próxima subida paga de 15 min a 1h de reemissão —, mas quem não souber vai procurar
# defeito onde não há. Ver o runbook `docs/runbooks/hml-gcp.md`.

resource "google_compute_url_map" "redirecionamento" {
  name = "hml-http"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "proxy_http" {
  name    = "hml-http"
  url_map = google_compute_url_map.redirecionamento.id
}

resource "google_compute_global_forwarding_rule" "http" {
  count = var.ligada ? 1 : 0

  name                  = "hml-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = var.endereco
  port_range            = "80"
  target                = google_compute_target_http_proxy.proxy_http.id
}

moved {
  from = google_compute_global_forwarding_rule.http
  to   = google_compute_global_forwarding_rule.http[0]
}

output "certificado" { value = google_compute_managed_ssl_certificate.cert.name }

output "ligada" {
  description = "Se a borda está servindo. `false` significa desligada por economia, não quebrada."
  value       = var.ligada
}
