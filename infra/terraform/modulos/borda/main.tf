# A borda: um endereço de entrada, um certificado e um nome por frente pública.
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
variable "servicos" {
  description = <<-TXT
    Os serviços públicos que ganham nome, na forma `{ host = ..., servico = ... }`.
    `servico` é o nome do Cloud Run; `host` é o nome completo já resolvido pelo
    `servicos.tf`, que é quem sabe se o domínio é próprio ou `nip.io`.
  TXT
  type = map(object({
    host    = string
    servico = string
  }))
}
variable "servico_padrao" {
  description = <<-TXT
    Para qual chave de `servicos` vai quem chega por um nome que não mapeamos (ou
    pelo IP cru). Explícito e não `keys(...)[0]`, que seria a ordem alfabética —
    hoje `biahflow-web`, e portanto o portal do *outro* produto.
  TXT
  type        = string
}

# Um NEG por serviço. É o que liga um balanceador a algo que não tem IP nem porta —
# o Cloud Run não é um grupo de instâncias, e o `cloud_run` aqui é o adaptador.
resource "google_compute_region_network_endpoint_group" "neg" {
  for_each = var.servicos

  name                  = "hml-${each.key}"
  region                = var.regiao
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = each.value.servico }
}

resource "google_compute_backend_service" "backend" {
  for_each = var.servicos

  name                  = "hml-${each.key}"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.neg[each.key].id
  }

  # Sem verificação de saúde, e não é esquecimento: um backend sem servidor não
  # aceita `health_checks` — a disponibilidade é do Cloud Run, não do balanceador.
}

# Um certificado para os três nomes. Gerenciado, o que significa que a Google o
# emite e renova sozinha — **desde que** cada `domains` resolva para o IP da
# fundação. É por isso que a primeira emissão leva
# de quinze minutos a uma hora: enquanto ela não termina, o HTTPS responde erro de
# certificado e não erro de rota. `docs/runbooks/hml-gcp.md` diz como conferir.
resource "google_compute_managed_ssl_certificate" "cert" {
  name = "hml"
  managed {
    domains = [for s in var.servicos : s.host]
  }
  # Trocar a lista de nomes recria o certificado, e um certificado em uso não pode
  # ser destruído antes de o novo existir e estar preso ao proxy.
  lifecycle { create_before_destroy = true }
}

# O roteamento por nome. O `default_service` é decisão e não sobra: quem chega pelo
# IP cru cai na frente que sabe pedir login, não no Keycloak nem num 404 do
# balanceador.
resource "google_compute_url_map" "mapa" {
  name            = "hml"
  default_service = google_compute_backend_service.backend[var.servico_padrao].id

  dynamic "host_rule" {
    for_each = var.servicos
    content {
      hosts        = [host_rule.value.host]
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.servicos
    content {
      name            = path_matcher.key
      default_service = google_compute_backend_service.backend[path_matcher.key].id
    }
  }
}

resource "google_compute_target_https_proxy" "proxy" {
  name             = "hml"
  url_map          = google_compute_url_map.mapa.id
  ssl_certificates = [google_compute_managed_ssl_certificate.cert.id]
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "hml-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = var.endereco
  port_range            = "443"
  target                = google_compute_target_https_proxy.proxy.id
}

# --- A porta 80, que existe para não servir nada --------------------------------
# Ela não é conveniência. Sem ela, um `http://` responde conexão recusada, e é isso
# que a validação do certificado gerenciado e o primeiro acesso de qualquer pessoa
# encontram antes de o HTTPS existir. Redirecionar é a única coisa que ela faz.

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
  name                  = "hml-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = var.endereco
  port_range            = "80"
  target                = google_compute_target_http_proxy.proxy_http.id
}

output "certificado" { value = google_compute_managed_ssl_certificate.cert.name }
