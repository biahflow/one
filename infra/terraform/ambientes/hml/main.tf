# A costura: liga a camada portátil (`servicos.tf`) aos módulos que sabem GCP.
#
# Nada de negócio mora aqui. Se este arquivo crescer com regra de produto, a
# separação em duas camadas deixou de valer.

# O número do projeto, que é o que torna a URL de um serviço do Cloud Run
# previsível antes de ele existir. Data source e não recurso nosso, então usá-lo em
# `local.url_interna` não cria dependência circular com os módulos.
data "google_project" "este" {
  project_id = var.projeto
}

module "fundacao" {
  source = "../../modulos/fundacao"

  projeto             = var.projeto
  regiao              = var.regiao
  nomes_de_segredo    = var.nomes_de_segredo
  repositorios_github = var.repositorios_github
  repositorio_infra   = var.repositorio_infra
  bucket_estado       = var.bucket_estado
}

locals {
  # `tag_imagem` vazia é o **primeiro apply**: o registro ainda não tem imagem
  # nenhuma, e uma referência a tag inexistente faz o Cloud Run recusar a revisão.
  # O `ignore_changes` dos módulos não salva aqui — ele só age em update. Ver
  # `var.imagem_bootstrap` para o argumento inteiro.
  primeiro_apply = var.tag_imagem == ""

  imagem = { for nome in toset(concat(keys(local.servicos_http), ["portal-api"])) :
    nome => local.primeiro_apply ? var.imagem_bootstrap : "${module.fundacao.registro}/${nome}:${var.tag_imagem}"
  }
}

module "servicos" {
  source   = "../../modulos/servico-cloudrun"
  for_each = local.servicos_http

  projeto  = var.projeto
  regiao   = var.regiao
  nome     = each.key
  imagem   = local.imagem[each.key]
  porta    = each.value.porta
  publico  = each.value.publico
  cpu      = each.value.cpu
  memoria  = each.value.memoria
  minimo   = each.value.min
  maximo   = each.value.max
  conta    = module.fundacao.conta_execucao
  rede     = module.fundacao.rede
  sub_rede = module.fundacao.sub_rede

  variaveis = each.value.variaveis
  segredos  = each.value.segredos
}

# Os processos longos. **A imagem é a do serviço de que cada um é irmão**, e isso é
# proposital: eles executam as tasks que aquela API enfileira, então precisam do
# mesmo código, do mesmo banco e do mesmo storage. Duas imagens divergiriam no dia
# em que alguém acrescentasse uma task e reconstruísse só uma delas.
module "workers" {
  source   = "../../modulos/worker-pool"
  for_each = local.processos_longos

  projeto    = var.projeto
  regiao     = var.regiao
  nome       = each.key
  imagem     = local.imagem[each.value.servico]
  comando    = each.value.comando
  instancias = each.value.instancias
  cpu        = each.value.cpu
  memoria    = each.value.memoria
  conta      = module.fundacao.conta_execucao
  rede       = module.fundacao.rede
  sub_rede   = module.fundacao.sub_rede

  variaveis = local.servicos_http[each.value.servico].variaveis
  segredos  = local.servicos_http[each.value.servico].segredos
}

# A borda. Ela consome a chave `dominio` que `servicos.tf` declarava desde o começo e
# que a costura **nunca lia** — de modo que os nomes existiam nas variáveis de
# ambiente dos serviços e não existiam como rota para lugar nenhum.
module "borda" {
  source = "../../modulos/borda"

  regiao   = var.regiao
  endereco = module.fundacao.endereco_entrada

  # Só as frentes públicas. Um serviço com `dominio = null` é de ingress interno, e
  # dar nome público a ele desfaria a decisão do próprio módulo do Cloud Run.
  servicos = {
    for nome, s in local.servicos_http : nome => { host = s.dominio, servico = nome }
    if s.publico && s.dominio != null
  }
  servico_padrao = "portal-web"
}

# Os trabalhos que começam e terminam. Cada um herda o ambiente do serviço de que
# é irmão — o `migrate` do portal precisa exatamente do que a `portal-api` tem, e
# manter as duas listas separadas seria criar uma segunda verdade sobre a mesma
# configuração.
module "trabalhos" {
  source   = "../../modulos/job"
  for_each = local.trabalhos

  projeto  = var.projeto
  regiao   = var.regiao
  nome     = each.key
  imagem   = local.imagem[each.value.servico]
  comando  = each.value.comando
  conta    = module.fundacao.conta_execucao
  rede     = module.fundacao.rede
  sub_rede = module.fundacao.sub_rede

  variaveis = local.servicos_http[each.value.servico].variaveis
  # A migração escreve o schema com a credencial do **migrator**, que é dona das
  # tabelas e não é a do caminho de requisição (ADR 0010). Ela não precisa mais de
  # tratamento especial aqui: `DATABASE_MIGRATION_URL` passou a ser entregue à
  # `portal-api` também, porque o `preflight` a exige de todo processo — e o job
  # herda a lista dela.
  segredos = local.servicos_http[each.value.servico].segredos
}

# --- Os dois portões deste diretório -------------------------------------------
# Escritos porque as duas direções já falharam de verdade, e nenhuma delas deixava
# nada vermelho: `ANTHROPIC_API_KEY` e `VOYAGE_API_KEY` eram criadas no Secret
# Manager e não chegavam a serviço nenhum (respondedor offline em silêncio, que é o
# que a ADR 0022 existe para impedir), e `KEYCLOAK_CLIENT_SECRET` era entregue com
# um nome que o `auth.ts` não lê. É a forma da guarda de consumo da ADR 0033, um
# nível abaixo: lá é campo publicado sem leitor, aqui é segredo sem leitor.

#
# **`precondition` e não `check`.** A primeira versão usava um bloco `check`, e ele
# está errado para isto: `check` emite *warning*, sempre — o `terraform plan` sai 0,
# o job do CI fica verde, e um portão que não reprova é o `dependency-review` da ADR
# 0023 outra vez. `precondition` faz o plano falhar, que é o que "portão" significa.
locals {
  segredos_lidos    = toset(flatten([for s in local.servicos_http : s.segredos]))
  segredos_sem_dono = setsubtract(local.segredos_lidos, toset(var.nomes_de_segredo))
  segredos_sem_leitor = setsubtract(
    toset(var.nomes_de_segredo), local.segredos_lidos
  )
}

resource "terraform_data" "portoes_de_segredo" {
  input = "ok"

  lifecycle {
    precondition {
      condition = length(local.segredos_sem_dono) == 0
      error_message = format(
        "Segredo referenciado por um serviço e ausente de `nomes_de_segredo`: %s. Ele não é criado, a revisão do Cloud Run não monta, e a mensagem do erro fala de permissão — não de nome.",
        join(", ", local.segredos_sem_dono),
      )
    }

    precondition {
      condition = length(local.segredos_sem_leitor) == 0
      error_message = format(
        "Segredo criado que nenhum serviço lê: %s. Alguém põe valor nele, o `gcloud secrets versions add` responde sucesso, e o controle que ele sustenta continua desligado.",
        join(", ", local.segredos_sem_leitor),
      )
    }
  }
}

output "urls" {
  value = { for k, m in module.servicos : k => m.url }
}

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

output "provedor_wif" {
  description = "Vai na variável de repositório WIF_PROVIDER dos dois repos."
  value       = module.fundacao.provedor_wif
}
