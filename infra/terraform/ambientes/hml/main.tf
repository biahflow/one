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

module "fila" {
  source = "../../modulos/maquina-fila"

  projeto   = var.projeto
  regiao    = var.regiao
  zona      = var.zona
  tipo      = var.maquina_fila
  rede      = module.fundacao.rede
  sub_rede  = module.fundacao.sub_rede
  conta     = module.fundacao.conta_execucao
  imagem    = "${module.fundacao.registro}/portal-api:${var.tag_imagem}"
  processos = local.processos_longos
  # O worker precisa do mesmo ambiente da API: mesmo banco, mesmo storage, mesmo
  # teto de contato. Ele executa as **tasks** que a API enfileira.
  variaveis = local.servicos_http["portal-api"].variaveis
  segredos  = local.servicos_http["portal-api"].segredos
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
  conector = module.fundacao.conector_vpc

  # O `REDIS_URL` só existe depois de a VM existir, e é por isso que ele entra
  # aqui e não em `servicos.tf`: a camada portátil descreve *que* há uma fila, não
  # onde ela mora.
  variaveis = merge(each.value.variaveis, { REDIS_URL = module.fila.redis_url })
  segredos  = each.value.segredos
}
