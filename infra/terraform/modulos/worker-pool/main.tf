# Um processo longo que **não fala HTTP**.
#
# Era uma VM até esta fatia, e a VM existia por um erro meu: eu havia concluído que
# o Celery não cabia no Cloud Run "porque o contêiner precisa escutar em `$PORT`".
# Isso vale para Cloud Run **service** — e worker pool é outra primitiva, feita
# justamente para carga que consome fila e não atende requisição.
#
# A prova está no próprio schema do provider: o container de um worker pool **não
# tem bloco `ports`**. Não é que a porta seja opcional; ela não existe.
#
# Duas diferenças em relação ao service, e as duas mordem quem copia sem olhar:
#
#   1. `scaling` fica na **raiz** do recurso, não dentro de `template`.
#   2. `vpc_access` só aceita `network_interfaces` — worker pool não tem
#      `connector`. Egress direto é o único caminho, e é mais barato.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "nome" { type = string }
variable "imagem" { type = string }
variable "comando" { type = list(string) }
variable "instancias" { type = number }
variable "cpu" { type = string }
variable "memoria" { type = string }
variable "conta" { type = string }
variable "rede" { type = string }
variable "sub_rede" { type = string }
variable "variaveis" { type = map(string) }
# Mapa e não lista: a chave é a variável de ambiente, o valor é o nome do segredo.
# Ver o argumento inteiro em `modulos/servico-cloudrun/main.tf`.
variable "segredos" { type = map(string) }

# Mesma trava, mesmo motivo do `modulos/servico-cloudrun/main.tf`.
variable "protegido" {
  description = "Se o worker pool recusa ser destruído. `false` só ao desmontar um ambiente de propósito."
  type        = bool
  default     = true
}

resource "google_cloud_run_v2_worker_pool" "pool" {
  name                = var.nome
  location            = var.regiao
  deletion_protection = var.protegido

  # `launch_stage = "BETA"` saiu daqui, e não por limpeza: **a API passou a responder
  # `GA`** para estes recursos, de modo que a linha virou uma afirmação falsa que todo
  # `plan` tentava reimpor (`"GA" -> "BETA"`). Era o "fica aberto" da ADR 0045, e quem
  # o fechou foi a separação dos states — o primeiro `plan` de um diretório novo lê o
  # recurso vivo em vez de comparar com o que o state já dizia.

  scaling {
    # **Manual, e não automático.** O `beat` precisa ser exatamente um — dois
    # agendadores emitem a mesma tarefa duas vezes, e o `dedupe_key` do aviso
    # salvaria o sino mas não salvaria um envio de WhatsApp. Para o worker,
    # contagem fixa é o que torna o custo do Upstash previsível: cada instância é
    # um laço de `BRPOP` a mais.
    scaling_mode          = "MANUAL"
    manual_instance_count = var.instancias
  }

  template {
    service_account = var.conta

    vpc_access {
      network_interfaces {
        network    = var.rede
        subnetwork = var.sub_rede
      }
      # `ALL_TRAFFIC` porque o worker precisa alcançar tanto o que está dentro
      # (a API interna, se um dia precisar) quanto o que está fora (Neon, Upstash,
      # Anthropic, Google Drive). O que faz a saída para a internet funcionar é o
      # Cloud NAT da fundação.
      egress = "ALL_TRAFFIC"
    }

    containers {
      image   = var.imagem
      command = var.comando

      resources {
        limits = { cpu = var.cpu, memory = var.memoria }
      }

      dynamic "env" {
        for_each = var.variaveis
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.segredos
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }

  # Quem troca a imagem é o workflow de deploy. Sem isto, um apply de
  # infraestrutura reverteria o worker para a tag do último apply — desfazendo o
  # deploy mais recente sem ninguém pedir.
  #
  # O segundo item é o irmão do que o `servico-cloudrun` ignora, e a assimetria é ao
  # contrário: `scaling_mode` nós **declaramos** (`MANUAL`, e o argumento está acima),
  # e a API não o devolve. Todo `plan` propunha acrescentá-lo, todo `apply` o
  # acrescentava, e o `plan` seguinte propunha de novo. **Só o modo é ignorado** —
  # `manual_instance_count` continua comparado, que é o número que importa: dois `beat`
  # emitem a mesma tarefa duas vezes.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      scaling[0].scaling_mode,
      # `client` e `client_version` são carimbo de **quem tocou por último**, e quem
      # toca a imagem é o `gcloud` do deploy, por desenho. Sem ignorá-los, todo deploy
      # deixa o plano sujo e o `apply` seguinte os remove — para o deploy seguinte
      # recolocar. É o mesmo desvio perpétuo da ADR 0051, pela mesma razão: um plano
      # que nunca fica limpo deixa de distinguir mudança de rotina.
      client,
      client_version,
    ]
  }
}

output "nome" { value = google_cloud_run_v2_worker_pool.pool.name }
