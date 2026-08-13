# A borda, segunda versão: a Cloudflare no lugar do balanceador global da Google.
#
# **Por que trocar.** A borda anterior servia três nomes de dois produtos com um IP e
# um certificado só, e isso a pagava. Com o portal do cliente fora, ela passou a servir
# um produto — e o preço não caiu junto: duas regras de encaminhamento globais (~US$
# 18/mês, o único item que cobrava por hora parado) mais um IP global reservado, que
# fora de uso custa o **dobro** da tarifa de "em uso". A Cloudflare já é a borda do
# site de marketing, já termina TLS para esta zona, e o que se paga por isto é zero.
#
# **O que se perde, declarado.** O `backend_service` da borda antiga tinha
# `log_config` com `sample_rate = 1.0`: uma linha por requisição, que era a única prova
# de "chegou na borda" num 502 ou num timeout — justamente o caso em que a aplicação
# não tem log nenhum. A Cloudflare no plano free dá analytics agregado, não log por
# requisição. Quem for depurar um 502 daqui em diante começa pelo log do Cloud Run.
#
# **A direção continua fundação → produto.** Este arquivo nomeia `biahflow-web`, que é
# recurso do outro state, pela mesma razão que `backends_da_borda` o nomeava: um
# hostname de borda referencia o serviço **por nome**, que é uma string e não um
# recurso. É o que permite declarar a borda inteira sem ler state de produto nenhum, e
# sem ciclo.

# **A zona entra por id e não por busca, e isso é uma permissão a menos.** O repo do
# site descobre a zona com `data "cloudflare_zone"` filtrando por nome, o que exige
# `Zone → Zone → Read` no token — e um token sem essa permissão não falha com "acesso
# negado", falha com **"0 found"**, que parece nome errado e manda depurar a coisa
# errada. Foi o que aconteceu na primeira tentativa de apply.
#
# O id é identificador, como o `conta_cloudflare`: não é segredo, e fixá-lo troca uma
# chamada de API e uma permissão por uma constante. O token daqui precisa só de
# `DNS → Edit`, `Config Rules → Edit` e `Access: Apps and Policies → Edit`.

locals {
  # A URL nova do Cloud Run (`<serviço>-<número do projeto>.<região>.run.app`), e não a
  # antiga com hash: é a que o Django do CRM tem em `DJANGO_ALLOWED_HOSTS`. Construída
  # e não lida do serviço pelo mesmo motivo de sempre — o número do projeto torna a URL
  # previsível antes de o serviço existir, e ler o serviço fecharia ciclo entre states.
  origem_do_crm = "biahflow-web-${data.google_project.este.number}.${var.regiao}.run.app"
}

resource "cloudflare_dns_record" "crm" {
  zone_id = var.zona_cloudflare
  name    = local.host_biahflow
  type    = "CNAME"
  content = local.origem_do_crm

  # `proxied` não é preferência: em "DNS only" o navegador vai direto ao Cloud Run, que
  # recebe `Host: app.biahflow.ai`, não reconhece o nome e responde 404. A regra de
  # origem abaixo só existe porque o tráfego passa por aqui.
  proxied = true
  ttl     = 1 # 1 = automático; obrigatório no schema, ignorado quando proxied
  comment = "CRM de homologação — gerenciado pelo Terraform em biahflow-portal-cliente"
}

# **A regra que faz o CNAME funcionar.** A Cloudflare repassa o `Host` original para a
# origem, e o Cloud Run roteia por `Host`: sem reescrever, todo request morre em 404 do
# Google, sem log nosso e sem pista de que o problema é um header. Override de `Host`
# em Origin Rules existe no plano free.
resource "cloudflare_ruleset" "origem_do_crm" {
  zone_id     = var.zona_cloudflare
  name        = "origem do CRM (hml)"
  description = "Reescreve o Host para o hostname da run.app do biahflow-web."
  kind        = "zone"
  phase       = "http_request_origin"

  rules = [{
    action      = "route"
    description = "Host da run.app do CRM"
    expression  = "http.host eq \"${local.host_biahflow}\""

    action_parameters = {
      host_header = local.origem_do_crm
    }
  }]
}

# --- Access ---------------------------------------------------------------------
# Mesmo padrão já validado em `biahflow-site/infra/terraform/access.tf`.
#
# **E o que ele não resolve, dito por extenso.** O `biahflow-web` é `publico` — precisa
# ser, porque quem o alcança é a Cloudflare, que chega pela internet como qualquer
# outro cliente. Então a `run.app` dele continua aberta, e o Access protege o nome
# bonito, não o serviço. A barreira que vale para quem descobrir a `run.app` continua
# sendo o login do próprio Django. Fechar isso de verdade exigiria mTLS ou um túnel, e
# nenhum dos dois se paga em homologação.

resource "cloudflare_zero_trust_access_policy" "equipe" {
  account_id = var.conta_cloudflare
  name       = "equipe biahflow (crm hml)"
  decision   = "allow"

  # Lista explícita e não `email_domain`, pela mesma razão do repo do site: o acesso
  # inclui uma conta fora de `@biahflow.ai`, e regra por domínio esconderia a exceção.
  include = [for e in var.emails_com_acesso : { email = { email = e } }]
}

resource "cloudflare_zero_trust_access_application" "crm" {
  account_id = var.conta_cloudflare
  name       = "biahflow CRM (hml)"
  type       = "self_hosted"
  domain     = local.host_biahflow

  session_duration = "24h"

  policies = [
    { id = cloudflare_zero_trust_access_policy.equipe.id },
  ]
}

output "url_do_crm" {
  description = "Onde o CRM é acessado desde que a borda virou Cloudflare."
  value       = local.url_biahflow
}
