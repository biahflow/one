# A costura: liga a camada portátil (`servicos.tf`) aos módulos que sabem GCP.
#
# Nada de negócio mora aqui. Se este arquivo crescer com regra de produto, a
# separação em duas camadas deixou de valer.

module "fundacao" {
  source = "../../modulos/fundacao"

  projeto             = var.projeto
  regiao              = var.regiao
  nomes_de_segredo    = var.nomes_de_segredo
  repositorios_github = var.repositorios_github
}

module "servicos" {
  source   = "../../modulos/servico-cloudrun"
  for_each = local.servicos_http

  projeto  = var.projeto
  regiao   = var.regiao
  nome     = each.key
  imagem   = "${module.fundacao.registro}/${each.key}:${var.tag_imagem}"
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

# O worker e o beat. **A imagem é a da `portal-api`**, e isso é proposital: eles
# executam as tasks que a API enfileira, então precisam do mesmo código, do mesmo
# banco e do mesmo storage. Duas imagens divergiriam no dia em que alguém
# acrescentasse uma task e reconstruísse só uma delas.
module "workers" {
  source   = "../../modulos/worker-pool"
  for_each = local.processos_longos

  projeto    = var.projeto
  regiao     = var.regiao
  nome       = each.key
  imagem     = "${module.fundacao.registro}/portal-api:${var.tag_imagem}"
  comando    = each.value.comando
  instancias = each.value.instancias
  cpu        = each.value.cpu
  memoria    = each.value.memoria
  conta      = module.fundacao.conta_execucao
  rede       = module.fundacao.rede
  sub_rede   = module.fundacao.sub_rede

  variaveis = local.servicos_http["portal-api"].variaveis
  segredos  = local.servicos_http["portal-api"].segredos
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
  imagem   = "${module.fundacao.registro}/${each.value.servico}:${var.tag_imagem}"
  comando  = each.value.comando
  conta    = module.fundacao.conta_execucao
  rede     = module.fundacao.rede
  sub_rede = module.fundacao.sub_rede

  variaveis = local.servicos_http[each.value.servico].variaveis
  # A migração escreve o schema, então ela usa a credencial do **migrator** — que
  # é dona das tabelas e não é a do caminho de requisição (ADR 0010).
  segredos = each.key == "portal-migrate" ? concat(
    local.servicos_http[each.value.servico].segredos, ["DATABASE_MIGRATION_URL"]
  ) : local.servicos_http[each.value.servico].segredos
}

output "urls" {
  value = { for k, m in module.servicos : k => m.url }
}

output "ip_saida" {
  description = "IP fixo de saída — para a allowlist do Neon e do Upstash."
  value       = module.fundacao.ip_saida
}

output "provedor_wif" {
  description = "Vai na variável de repositório WIF_PROVIDER dos dois repos."
  value       = module.fundacao.provedor_wif
}
