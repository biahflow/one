# A fundação: o que é do projeto, e não de um produto.
#
# Rede, saída, registro de imagens, os buckets, o cofre, as identidades e a federação
# com o GitHub. Mais a borda — que desde 13/08/2026 é a Cloudflare (`cloudflare.tf`) e
# não mais um balanceador global da Google.
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
  repositorios_deploy = var.repositorios_deploy
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
  # `portal` saiu em 13/08/2026 junto com o state do produto. Deixá-lo aqui manteria
  # aberta a porta de nascer segredo para um dono que não tem mais quem cobre leitor —
  # que é exatamente o defeito que este portão existe para fechar.
  produtos_conhecidos = toset(["biahflow"])
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

# `realm`, `issuer` e `jwks_url` saíram com o Keycloak; `ip_entrada`, com o
# balanceador global. Não viraram `null`: uma saída que existe e não vale nada é uma
# pergunta que alguém vai fazer daqui a seis meses.

output "ip_saida" {
  description = "IP fixo de saída — para a allowlist do Neon e do Upstash. É o único IP que sobrou, e é o que não pode mudar."
  value       = module.fundacao.ip_saida
}

output "hosts" {
  description = "Os nomes públicos. Um só, desde que o portal do cliente saiu."
  value = {
    biahflow = local.host_biahflow
  }
}

output "urls_publicas" {
  value = {
    biahflow = local.url_biahflow
  }
}

output "provedor_wif" {
  description = "Vai na variável de repositório WIF_PROVIDER dos dois repos."
  value       = module.fundacao.provedor_wif
}
