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

resource "google_cloud_run_v2_worker_pool" "pool" {
  name     = var.nome
  location = var.regiao

  # O provider ainda marca worker pool como recurso em preview; sem isto o apply
  # recusa. Sai quando o recurso sair de preview.
  launch_stage = "BETA"

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
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

output "nome" { value = google_cloud_run_v2_worker_pool.pool.name }
