# A borda, e por que ela fica na fundação mesmo servindo os dois produtos.
#
# Um NEG sem servidor referencia o serviço do Cloud Run **por nome** — uma string, não
# um recurso. Então este state declara a borda inteira sem ler o state de produto
# nenhum, e sem ciclo. A alternativa seria uma borda por produto, e o preço estaria em
# três lugares: dobraria as regras de encaminhamento (o único custo fixo de HML),
# exigiria um segundo IP global e, como o nome `nip.io` contém o IP, **mudaria os
# hostnames de um dos dois** — no portal do cliente isso muda o `issuer` do Keycloak,
# que é passo de runbook e não de Terraform.
#
# O preço desta escolha, declarado: mexer numa rota exige `apply` aqui, não no produto.

locals {
  # Quais prefixos de caminho de um host **não** pertencem ao serviço que o serve por
  # padrão. É a mesma afirmação que o `location ~ ^/(api|admin|static)/` do
  # `nginx.conf.template` do outro repositório fazia, deslocada para onde ela pode ser
  # uma barreira em vez de um `proxy_pass` (ADR 0048).
  #
  # **Local irmão e não campo de `servicos_http`**, por duas razões: o `for_each` de
  # `main.tf` só aceita aquele mapa porque os cinco valores têm atributos idênticos, e
  # um campo presente num só quebra a unificação do tipo; e uma lista de regras de
  # caminho é vocabulário de borda, que o topo deste arquivo mantém fora daqui.
  #
  # **Sete caminhos e não os três que a ADR 0046 cita.** `/healthz` e `/readyz` porque
  # a sonda que cai no `try_files` do SPA recebe o `index.html` com **200**, e um
  # balanceador lê isso como "saudável" com a API fora do ar — é o argumento que o
  # bloco próprio das sondas no nginx já trazia. E **com barra no fim**, porque o
  # `HealthProbeMiddleware` do Django faz `rstrip("/")` e responde as duas formas
  # enquanto a regex do nginx (`^/(healthz|readyz)$`) exige a forma sem barra: medido,
  # `app.<base>/healthz/` devolve o SPA com 200 hoje. Replicar só os cinco caminhos
  # óbvios replicaria o defeito.
  rotas_internas = {
    biahflow-web = [
      {
        destino = "biahflow-api"
        paths = [
          "/api/*", "/admin/*", "/static/*",
          "/healthz", "/healthz/", "/readyz", "/readyz/",
        ]
      },
    ]
  }

  # Os quatro serviços que o balanceador alcança. Escrito à mão porque os serviços não
  # moram mais neste state — e o portão abaixo é o que impede esta lista de divergir
  # das rotas.
  backends_da_borda = {
    portal-web   = { servico = "portal-web" }
    keycloak     = { servico = "keycloak" }
    biahflow-web = { servico = "biahflow-web" }
    # Entra como backend e **não** como rota: é destino de `path_rule` e não de
    # `host_rule`, e é essa separação que mantém o `domains` do certificado com os três
    # nomes de sempre (ADR 0048).
    biahflow-api = { servico = "biahflow-api" }
  }

  # As frentes com nome.
  rotas_da_borda = {
    portal-web   = { host = local.host_portal, padrao = "portal-web", regras = [] }
    keycloak     = { host = local.host_keycloak, padrao = "keycloak", regras = [] }
    biahflow-web = { host = local.host_biahflow, padrao = "biahflow-web", regras = local.rotas_internas["biahflow-web"] }
  }
}

module "borda" {
  source = "../../modulos/borda"

  regiao   = var.regiao
  endereco = module.fundacao.endereco_entrada

  backends       = local.backends_da_borda
  rotas          = local.rotas_da_borda
  servico_padrao = "portal-web"
}

# O terceiro portão (ADR 0048). Uma rota cujo `destino` não é backend já reprova
# sozinha, com um `Invalid index` que fala de índice e não de rota; este diz o que é.
locals {
  rotas_sem_backend = setsubtract(
    toset(flatten([for r in values(local.rotas_da_borda) : [for g in r.regras : g.destino]])),
    toset(keys(local.backends_da_borda)),
  )
}

resource "terraform_data" "portao_da_borda" {
  input = "ok"

  lifecycle {
    precondition {
      condition = length(local.rotas_sem_backend) == 0
      error_message = format(
        "Rota da borda apontando para serviço sem backend: %s. Ou o nome está errado, ou o serviço é `interno` — e um serviço `interno` atrás de um `path_rule` responde 404 do balanceador a toda requisição do navegador, sem log nosso.",
        join(", ", local.rotas_sem_backend),
      )
    }
  }
}
