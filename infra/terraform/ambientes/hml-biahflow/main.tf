# A costura deste produto.
#
# Liga a camada portátil (`servicos.tf`) aos módulos que sabem GCP, e lê da fundação
# **só pelas saídas dela** — nunca por recurso. A direção é sempre fundação → produto;
# entre produtos não há leitura nenhuma, e é isso que faz um `destroy` daqui não
# alcançar o outro (ADR 0051).

data "terraform_remote_state" "fundacao" {
  backend = "gcs"
  config = {
    bucket = "biahflow-hml-tfstate"
    prefix = var.prefixo_da_fundacao
  }
}

locals {
  fundacao = data.terraform_remote_state.fundacao.outputs

  # Os nomes moram na fundação porque todo nome deste ambiente contém o IP de entrada.
  numero_projeto = local.fundacao.numero_projeto
  dominio_base   = local.fundacao.dominio_base
  host_portal    = local.fundacao.hosts.portal
  host_keycloak  = local.fundacao.hosts.keycloak
  host_biahflow  = local.fundacao.hosts.biahflow
  url_portal     = local.fundacao.urls_publicas.portal
  url_keycloak   = local.fundacao.urls_publicas.keycloak
  url_biahflow   = local.fundacao.urls_publicas.biahflow
  realm          = local.fundacao.realm
  issuer         = local.fundacao.issuer
  jwks_url       = local.fundacao.jwks_url

  primeiro_apply = var.tag_imagem == ""

  imagem = { for nome in keys(local.servicos_http) :
    nome => local.primeiro_apply ? var.imagem_bootstrap : "${local.fundacao.registro}/${nome}:${var.tag_imagem}"
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
  acesso   = each.value.acesso
  cpu      = each.value.cpu
  memoria  = each.value.memoria
  minimo   = each.value.min
  maximo   = each.value.max
  conta    = local.fundacao.conta_execucao
  rede     = local.fundacao.rede
  sub_rede = local.fundacao.sub_rede

  variaveis = each.value.variaveis
  segredos  = each.value.segredos
}

# Os processos longos. **A imagem é a do serviço de que cada um é irmão**, e isso é
# proposital: eles executam as tasks que aquela API enfileira, então precisam do mesmo
# código, do mesmo banco e do mesmo storage.
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
  conta      = local.fundacao.conta_execucao
  rede       = local.fundacao.rede
  sub_rede   = local.fundacao.sub_rede

  variaveis = local.servicos_http[each.value.servico].variaveis
  segredos  = local.servicos_http[each.value.servico].segredos
}

# Os trabalhos que começam e terminam. Cada um herda o ambiente do serviço de que é
# irmão — manter duas listas seria criar uma segunda verdade sobre a mesma configuração.
module "trabalhos" {
  source   = "../../modulos/job"
  for_each = local.trabalhos

  projeto  = var.projeto
  regiao   = var.regiao
  nome     = each.key
  imagem   = local.imagem[each.value.servico]
  comando  = each.value.comando
  conta    = local.fundacao.conta_execucao
  rede     = local.fundacao.rede
  sub_rede = local.fundacao.sub_rede

  variaveis = local.servicos_http[each.value.servico].variaveis
  segredos  = local.servicos_http[each.value.servico].segredos
}

# --- Os dois portões de segredo, agora deste produto ----------------------------
# Eram um par global em `ambientes/hml`, e a divisão custou alcance: nenhum dos dois
# enxerga mais os dois produtos ao mesmo tempo. O que os mantém honestos é a fundação
# declarar **de quem é cada segredo** — sem esse dono, "criado e sem leitor" viraria
# uma pergunta que ninguém faz (ADR 0051).
#
# Continuam `precondition` e não `check`: `check` emite warning, o plano sai 0, e um
# portão que não reprova é decoração.
locals {
  segredos_lidos = toset(flatten([for s in local.servicos_http : values(s.segredos)]))
  segredos_do_produto = toset([
    for nome, dono in local.fundacao.segredos : nome if dono == "biahflow"
  ])

  segredos_sem_dono   = setsubtract(local.segredos_lidos, toset(keys(local.fundacao.segredos)))
  segredos_alheios    = setsubtract(local.segredos_lidos, local.segredos_do_produto)
  segredos_sem_leitor = setsubtract(local.segredos_do_produto, local.segredos_lidos)
}

resource "terraform_data" "portoes_de_segredo" {
  input = "ok"

  lifecycle {
    precondition {
      condition = length(local.segredos_sem_dono) == 0
      error_message = format(
        "Segredo referenciado aqui e ausente do cofre da fundação: %s. Ele não é criado, a revisão do Cloud Run não monta, e a mensagem do erro fala de permissão — não de nome.",
        join(", ", local.segredos_sem_dono),
      )
    }

    precondition {
      condition = length(local.segredos_sem_leitor) == 0
      error_message = format(
        "Segredo do Biahflow que nenhum serviço deste state lê: %s. Alguém põe valor nele, o `gcloud secrets versions add` responde sucesso, e o controle que ele sustenta continua desligado.",
        join(", ", local.segredos_sem_leitor),
      )
    }

    # O portão que a separação **acrescentou**: antes, com um mapa só, ler o segredo do
    # outro produto era invisível. Agora é um erro de plano — e é o que impede o
    # `DATABASE_URL` compartilhado de voltar por descuido.
    precondition {
      condition = length(local.segredos_alheios) == 0
      error_message = format(
        "Segredo de outro produto lido aqui: %s. Se ele é mesmo compartilhado, isso é decisão a registrar — e provavelmente o que se quer são dois segredos com prefixo de dono.",
        join(", ", local.segredos_alheios),
      )
    }
  }
}

output "urls" {
  value = { for k, m in module.servicos : k => m.url }
}
