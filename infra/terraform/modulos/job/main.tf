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
variable "segredos" { type = list(string) }

resource "google_cloud_run_v2_job" "job" {
  name     = var.nome
  location = var.regiao

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
          for_each = toset(var.segredos)
          content {
            name = env.value
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
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}

output "nome" { value = google_cloud_run_v2_job.job.name }
