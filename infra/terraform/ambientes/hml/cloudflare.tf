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
# **A direção continua fundação → produto.** Este arquivo nomeia `pulse-web`, que é
# recurso do outro state, pela mesma razão que `backends_da_borda` o nomeava: um
# hostname de borda referencia o serviço **por nome**, que é uma string e não um
# recurso. É o que permite declarar a borda inteira sem ler state de produto nenhum, e
# sem ciclo.
#
# **E o preço dessa string está pago desde a ADR 0065.** Uma string não é referência:
# quando os serviços do CRM foram renomeados de `biahflow-*` para `cockpit-*` em
# 19/08/2026 (`b4e0471`), o rename tocou só o `servicos.tf` do outro state e esta linha
# ficou apontando para um serviço que deixara de existir — sem nada ficar vermelho, que
# é o modo de falha que o próprio commit de acerto seguinte (`6a0e45f`) descreve. Quem
# confere agora é `test_every_service_name_the_repository_builds_or_invokes_is_declared`,
# em `apps/api/tests/test_architecture_doc.py`: o primeiro segmento de um hostname
# `run.app` tem de ser chave de algum `servicos.tf`.
#
# **E a guarda foi exercida em 25/08/2026, no rename seguinte.** `cockpit-*` virou
# `pulse-*` junto com o nome do produto, esta linha mudou no mesmo lote — e o que
# garante que mudou não foi lembrança de ninguém: é que deixá-la para trás reprova o
# `api-quality` antes de o PR poder ser mergeado. Da primeira vez o defeito atravessou
# seis dias em silêncio; da segunda ele não passou do CI.

# **A zona entra por id e não por busca, e isso é uma permissão a menos.** O repo do
# site descobre a zona com `data "cloudflare_zone"` filtrando por nome, o que exige
# `Zone → Zone → Read` no token — e um token sem essa permissão não falha com "acesso
# negado", falha com **"0 found"**, que parece nome errado e manda depurar a coisa
# errada. Foi o que aconteceu na primeira tentativa de apply.
#
# O id é identificador, como o `conta_cloudflare`: não é segredo, e fixá-lo troca uma
# chamada de API e uma permissão por uma constante.
#
# **As três permissões que o token daqui precisa**, medidas uma a uma contra a API e
# não deduzidas do nome do recurso:
#
#   Zone → DNS → Edit                        (`cloudflare_dns_record`)
#   Zone → **Origin Rules** → Edit           (`cloudflare_ruleset` de `http_request_origin`)
#   Account → Access: Apps and Policies → Edit  (as duas do Zero Trust)
#
# A do meio se chama **Origin Rules** e não "Config Rules": com a errada, o
# `POST /zones/<id>/rulesets` responde `403 request is not authorized` — que não diz
# qual permissão falta, e manda procurar no lugar errado.

locals {
  # A URL nova do Cloud Run (`<serviço>-<número do projeto>.<região>.run.app`), e não a
  # antiga com hash: é a que o Django do CRM tem em `DJANGO_ALLOWED_HOSTS`. Construída
  # e não lida do serviço pelo mesmo motivo de sempre — o número do projeto torna a URL
  # previsível antes de o serviço existir, e ler o serviço fecharia ciclo entre states.
  origem_do_crm = "pulse-web-${data.google_project.este.number}.${var.regiao}.run.app"
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
  comment = "CRM de homologação — gerenciado pelo Terraform em biahflow/one"
}

# **O que faz o CNAME funcionar, e por que não é uma Origin Rule.** A Cloudflare
# repassa o `Host` original para a origem, e o Cloud Run roteia por `Host`: sem
# reescrever, todo request morre em 404 do Google, sem log nosso e sem pista de que o
# problema é um header.
#
# A ferramenta óbvia para isso é o override de Host das Origin Rules, e ela foi tentada
# primeiro. A API recusa: `400 not entitled to use the HostHeader override`. **É
# entitlement de plano e não permissão de token** — o mesmo erro aparece em relato de
# zona Pro, e nenhum ajuste no token o resolve.
#
# Um Worker consegue o mesmo de graça, e por um caminho diferente: numa subrequisição
# de Worker o `Host` sai da **URL**, não de um header, então trocar o hostname da URL
# já é o override. O free tier são 100 mil requisições por dia, contra um usuário.
resource "cloudflare_workers_script" "proxy_do_crm" {
  account_id  = var.conta_cloudflare
  script_name = "crm-hml-proxy"
  content     = templatefile("${path.module}/worker-do-crm.js.tftpl", { origem = local.origem_do_crm })
  main_module = "worker.js"

  # Sem data de compatibilidade o Worker nasce preso ao runtime do dia em que foi
  # criado, e "o dia em que foi criado" não é uma data que alguém consiga ler no
  # código. Escrita, ela vira decisão datada.
  compatibility_date = "2026-08-13"
}

resource "cloudflare_workers_route" "proxy_do_crm" {
  zone_id = var.zona_cloudflare
  pattern = "${local.host_biahflow}/*"
  script  = cloudflare_workers_script.proxy_do_crm.script_name
}

# --- Access ---------------------------------------------------------------------
# Mesmo padrão já validado em `biahflow-site/infra/terraform/access.tf`.
#
# **E o que ele não resolve, dito por extenso.** O `pulse-web` é `publico` — precisa
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
