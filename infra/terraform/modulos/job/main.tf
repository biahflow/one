# Um Cloud Run Job: trabalho que começa, termina e tem código de saída.
#
# Existe porque os dois workflows de deploy já invocavam `portal-migrate`,
# `biahflow-migrate` e `biahflow-check` — e **ninguém os criava**. Um workflow que
# chama um recurso inexistente falha no primeiro deploy, que é tarde demais para
# descobrir.
#
# `migrate` é o caso em que o código de saída importa de verdade: o deploy para se
# ele falhar, porque subir código novo contra schema velho é a forma mais barata
# de transformar um deploy em incidente.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "nome" { type = string }
variable "imagem" { type = string }
variable "comando" { type = list(string) }
variable "conta" { type = string }
variable "rede" { type = string }
variable "sub_rede" { type = string }
variable "variaveis" { type = map(string) }
# Mapa e não lista: a chave é a variável de ambiente, o valor é o nome do segredo.
# Ver o argumento inteiro em `modulos/servico-cloudrun/main.tf`.
variable "segredos" { type = map(string) }

# Mesma trava, mesmo motivo do `modulos/servico-cloudrun/main.tf`. Os três recursos do
# Cloud Run a têm, e descobrir isso um de cada vez custou três `destroy` reprovados.
variable "protegido" {
  description = "Se o job recusa ser destruído. `false` só ao desmontar um ambiente de propósito."
  type        = bool
  default     = true
}

resource "google_cloud_run_v2_job" "job" {
  name                = var.nome
  location            = var.regiao
  deletion_protection = var.protegido

  template {
    template {
      service_account = var.conta
      # Uma tentativa. Migração que falha precisa de gente olhando, não de
      # retentativa automática — repetir um `alembic upgrade` que morreu no meio
      # é como se piora um problema de schema.
      max_retries = 0

      vpc_access {
        network_interfaces {
          network    = var.rede
          subnetwork = var.sub_rede
        }
        egress = "ALL_TRAFFIC"
      }

      containers {
        image   = var.imagem
        command = var.comando

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
  }

  # O workflow aponta a imagem nova antes de executar.
  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
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

output "nome" { value = google_cloud_run_v2_job.job.name }
