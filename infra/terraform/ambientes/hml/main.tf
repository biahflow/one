# A fundação: o que é do projeto, e não de um produto.
#
# Rede, saída, entrada, registro de imagens, os buckets, o cofre, as identidades e a
# federação com o GitHub. Mais a borda, pela razão escrita em `borda.tf`.
#
# **Os serviços saíram daqui** (ADR 0051). Cada produto tem o seu diretório e o seu
# state; este declara o que os dois compartilham, e é o único que pode. A ordem de
# leitura é sempre a mesma — fundação → produto —, nunca entre produtos.

data "google_project" "este" {
  project_id = var.projeto
}

module "fundacao" {
  source = "../../modulos/fundacao"

  projeto             = var.projeto
  regiao              = var.regiao
  segredos            = var.segredos
  repositorios_github = var.repositorios_github
  repositorio_infra   = var.repositorio_infra
  bucket_estado       = var.bucket_estado
}

# --- O portão que sobrou aqui ---------------------------------------------------
# Os dois portões de segredo eram uma afirmação **global**: "todo segredo tem leitor"
# só é verificável por quem enxerga todos os serviços, e este state deixou de
# enxergar. Eles não foram apagados — foram divididos, e a divisão custa alguma coisa
# (ADR 0051).
#
# Aqui fica a metade que a fundação ainda pode afirmar: todo segredo declara **de que
# produto é**. Sem isso, os portões dos produtos não teriam contra o que comparar, e
# um segredo novo poderia nascer sem dono — que é como `ANTHROPIC_API_KEY` e
# `VOYAGE_API_KEY` chegaram a existir sem chegar a ninguém (ADR 0046).
locals {
  produtos_conhecidos = toset(["biahflow", "portal"])
  segredos_sem_dono_valido = [
    for nome, produto in var.segredos : nome
    if !contains(local.produtos_conhecidos, produto)
  ]
}

resource "terraform_data" "portao_de_dono" {
  input = "ok"

  lifecycle {
    precondition {
      condition = length(local.segredos_sem_dono_valido) == 0
      error_message = format(
        "Segredo sem produto dono reconhecido: %s. O dono é o que permite ao state daquele produto cobrar que alguém o leia — sem ele, o segredo existe, recebe valor, e nenhum portão pergunta se chega a alguém.",
        join(", ", local.segredos_sem_dono_valido),
      )
    }
  }
}

# --- Saídas ---------------------------------------------------------------------
# É por aqui que os dois produtos leem a fundação, e **só por aqui**. Um produto que
# precise de algo que não está nesta lista está pedindo para acoplar aos recursos, e
# não ao contrato.

output "numero_projeto" {
  description = "O que torna a URL interna de um serviço previsível antes de ele existir."
  value       = data.google_project.este.number
}

output "registro" { value = module.fundacao.registro }
output "registro_espelho" { value = module.fundacao.registro_espelho }
output "conta_execucao" { value = module.fundacao.conta_execucao }
output "rede" { value = module.fundacao.rede }
output "sub_rede" { value = module.fundacao.sub_rede }
output "bucket_documentos" { value = module.fundacao.bucket_documentos }
output "bucket_midia" { value = module.fundacao.bucket_midia }

output "segredos" {
  description = "Nome do segredo => produto dono. Cada produto cobra a sua metade."
  value       = var.segredos
}

output "dominio_base" { value = local.dominio_base }
output "realm" { value = local.realm }
output "issuer" { value = local.issuer }
output "jwks_url" { value = local.jwks_url }

output "ip_saida" {
  description = "IP fixo de saída — para a allowlist do Neon e do Upstash."
  value       = module.fundacao.ip_saida
}

output "ip_entrada" {
  description = "IP do balanceador. É sobre ele que os nomes `nip.io` são montados."
  value       = module.fundacao.ip_entrada
}

output "hosts" {
  description = "Os nomes públicos. O do Keycloak é o `issuer` que o realm tem de declarar."
  value = {
    portal   = local.host_portal
    keycloak = local.host_keycloak
    biahflow = local.host_biahflow
    issuer   = local.issuer
  }
}

output "urls_publicas" {
  value = {
    portal   = local.url_portal
    keycloak = local.url_keycloak
    biahflow = local.url_biahflow
  }
}

output "provedor_wif" {
  description = "Vai na variável de repositório WIF_PROVIDER dos dois repos."
  value       = module.fundacao.provedor_wif
}
