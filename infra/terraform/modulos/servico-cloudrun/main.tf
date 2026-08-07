# Um serviço HTTP no Cloud Run.
#
# O módulo existe para que `servicos.tf` possa dizer "um serviço com esta imagem,
# nesta porta, público ou não" sem saber o que é uma revisão do Cloud Run.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "nome" { type = string }
variable "imagem" { type = string }
variable "porta" { type = number }
variable "publico" { type = bool }
variable "cpu" { type = string }
variable "memoria" { type = string }
variable "minimo" { type = number }
variable "maximo" { type = number }
variable "conta" { type = string }
variable "conector" { type = string }
variable "variaveis" { type = map(string) }
variable "segredos" { type = list(string) }

resource "google_cloud_run_v2_service" "servico" {
  name     = var.nome
  location = var.regiao

  # **O ingress é a decisão de segurança deste módulo.** `INGRESS_TRAFFIC_ALL` é o
  # default do Cloud Run, e para a `api` ele estaria errado: o `Caddyfile` do
  # compose decidiu que ela não é alcançada pelo navegador — quem fala com ela é o
  # BFF. Publicá-la daria à internet um caminho que o produto não usa.
  ingress = var.publico ? "INGRESS_TRAFFIC_ALL" : "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.conta

    scaling {
      min_instance_count = var.minimo
      max_instance_count = var.maximo
    }

    vpc_access {
      connector = var.conector
      # `PRIVATE_RANGES_ONLY` e não `ALL_TRAFFIC`: só o que vai para a rede
      # privada passa pelo conector. Mandar a saída inteira por ele custaria
      # banda e faria toda chamada a terceiro depender de uma peça a mais.
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.imagem
      ports { container_port = var.porta }

      resources {
        limits = { cpu = var.cpu, memory = var.memoria }
        # Com `min_instance_count > 0`, CPU sempre alocada. É o que mantém um
        # processo vivo entre requisições — sem isso o Keycloak perderia cache e
        # a API perderia o pool a cada janela ociosa.
        cpu_idle = var.minimo == 0
      }

      dynamic "env" {
        for_each = var.variaveis
        content {
          name  = env.key
          value = env.value
        }
      }

      # Segredo entra por referência ao Secret Manager, nunca como valor: assim
      # ele não aparece em `gcloud run services describe`, nem no estado do
      # Terraform, nem no log de deploy.
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

  # A tag da imagem muda a cada deploy e é o Actions quem a aplica. Sem isto, um
  # `terraform apply` de infraestrutura reverteria o serviço para a tag do último
  # apply — desfazendo o deploy mais recente sem ninguém pedir.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

# Público significa "sem autenticação IAM na frente". Para os serviços internos
# esta permissão **não** é criada: além do ingress interno, quem chamar precisa de
# identidade. São duas barreiras, e a segunda é a que sobrevive a alguém trocar o
# ingress por engano.
resource "google_cloud_run_v2_service_iam_member" "publico" {
  count    = var.publico ? 1 : 0
  name     = google_cloud_run_v2_service.servico.name
  location = var.regiao
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" { value = google_cloud_run_v2_service.servico.uri }
