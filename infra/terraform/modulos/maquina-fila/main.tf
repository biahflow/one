# A VM que hospeda Redis, o worker e o beat.
#
# **Por que não é Cloud Run.** `celery worker` e `celery beat` não escutam porta
# nenhuma, e um serviço Cloud Run cuja imagem não responde em `$PORT` dentro do
# tempo de boot tem a revisão **recusada**. Só passaria mudando a aplicação para
# subir um servidor HTTP de mentira ao lado do worker — acrescentar um servidor
# que não serve ninguém para satisfazer um verificador é o tipo de contorno que
# fica no código para sempre.
#
# Pôr o Redis aqui também dispensa o Memorystore: um Basic de 1 GB custa mais que
# esta VM inteira, e o conector de VPC seria necessário de qualquer forma.
#
# O que se perde, e fica dito: esta VM é bicho de estimação. Atualização de SO,
# disco e reinício são de quem opera. Em produção isso se troca por outra coisa —
# em HML, o que se quer é a fila funcionando com o mínimo de peças.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "zona" { type = string }
variable "tipo" { type = string }
variable "rede" { type = string }
variable "sub_rede" { type = string }
variable "conta" { type = string }
variable "imagem" { type = string }
variable "processos" { type = map(string) }
variable "variaveis" { type = map(string) }
variable "segredos" { type = list(string) }

locals {
  # Container-Optimized OS: sem gerenciador de pacote, sistema de arquivos raiz
  # somente leitura e atualização automática. É a imagem que menos pede cuidado
  # para uma VM cujo trabalho é rodar contêiner.
  familia_imagem = "cos-cloud/cos-stable"

  inicializacao = templatefile("${path.module}/inicia.sh.tftpl", {
    imagem    = var.imagem
    processos = var.processos
    variaveis = var.variaveis
    segredos  = var.segredos
    projeto   = var.projeto
  })
}

resource "google_compute_instance" "fila" {
  name         = "hml-fila"
  machine_type = var.tipo
  zone         = var.zona

  boot_disk {
    initialize_params {
      image = local.familia_imagem
      size  = 20
    }
  }

  network_interface {
    network    = var.rede
    subnetwork = var.sub_rede
    # **Sem `access_config`, portanto sem IP público.** A saída para a internet
    # vai pelo Cloud NAT da fundação; a entrada não existe. Uma VM de fila não
    # tem por que ser alcançável de fora, e o Redis aqui não tem senha forte
    # justamente porque a rede é a fronteira.
  }

  service_account {
    email  = var.conta
    scopes = ["cloud-platform"]
  }

  metadata = {
    user-data                 = local.inicializacao
    google-logging-enabled    = "true"
    google-monitoring-enabled = "true"
  }

  # A imagem muda a cada deploy, e quem a troca é o Actions (recriando a VM ou
  # reiniciando os contêineres). Sem isto, um apply de infraestrutura reverteria
  # para a tag do último apply.
  lifecycle {
    ignore_changes = [metadata["user-data"]]
  }

  tags = ["hml-fila"]
}

# Só o Cloud Run alcança o Redis, e só na porta dele. Regra por tag e por faixa,
# não por "0.0.0.0/0 na rede interna" — a sub-rede do conector é conhecida, e
# nomeá-la é o que impede a próxima VM de herdar acesso sem ninguém decidir.
resource "google_compute_firewall" "redis" {
  name          = "hml-redis-do-cloudrun"
  network       = var.rede
  direction     = "INGRESS"
  source_ranges = ["10.20.1.0/28"]
  target_tags   = ["hml-fila"]

  allow {
    protocol = "tcp"
    ports    = ["6379"]
  }
}

output "redis_url" {
  value = "redis://${google_compute_instance.fila.network_interface[0].network_ip}:6379/0"
}

output "ip_interno" {
  value = google_compute_instance.fila.network_interface[0].network_ip
}
