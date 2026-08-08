# O que a GCP precisa ter antes de qualquer serviço existir: APIs ligadas, rede,
# registro de imagem, bucket, cofre de segredo e a identidade que o GitHub usa.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "nomes_de_segredo" { type = list(string) }
variable "repositorios_github" { type = list(string) }
variable "repositorio_infra" { type = string }
variable "bucket_estado" { type = string }

locals {
  apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "compute.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "dns.googleapis.com",
    "storage.googleapis.com",
    # As três abaixo não estavam na lista, e são as de que o **próprio Terraform**
    # depende: `serviceusage` para o `google_project_service` acima poder existir,
    # `cloudresourcemanager` para os `google_project_iam_member`, `iam` para o pool
    # de WIF e as contas de serviço. Num projeto novo elas costumam vir desligadas,
    # e o apply falha na primeira dessas linhas — depois de já ter criado rede.
    #
    # Declará-las aqui **não** dispensa habilitá-las à mão antes do primeiro apply:
    # é preciso a API de habilitar APIs para habilitar APIs. Elas estão aqui para
    # que ninguém as desligue depois achando que não são usadas.
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
  ]
}

resource "google_project_service" "api" {
  for_each = toset(local.apis)
  service  = each.value
  # Desligar a API ao destruir deixaria o projeto num estado que o próximo apply
  # tem de consertar antes de fazer qualquer coisa. Não vale a limpeza.
  disable_on_destroy = false
}

# --- Rede -------------------------------------------------------------------
# Sub-rede própria e não a `default`: a `default` vem com regras de firewall que
# ninguém escolheu, e uma delas abre SSH para a internet inteira.

resource "google_compute_network" "rede" {
  name                    = "hml"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "sub_rede" {
  name          = "hml-${var.regiao}"
  ip_cidr_range = "10.20.0.0/24"
  region        = var.regiao
  network       = google_compute_network.rede.id
}

# **Não há conector de VPC**, e a ausência é decisão. O Cloud Run alcança a rede
# por *egress direto* (`network_interfaces`), que dispensa as instâncias pagas do
# conector — e um worker pool nem aceita conector: no schema dele, `vpc_access` só
# tem `network_interfaces`.
#
# A VPC existe por um motivo só: **isolar as duas APIs**. Elas sobem com
# `INGRESS_TRAFFIC_INTERNAL_ONLY`, e é a rede que faz esse "internal" significar
# alguma coisa. Sem ela, a chamada do BFF sairia pela internet e bateria na porta
# que o próprio ingress recusa.

# Saída pela internet com IP estável. Aqui ele é obrigatório e não conveniência:
# com `egress = ALL_TRAFFIC`, **toda** saída passa pela VPC, e sem NAT o Cloud Run
# perderia o Neon, o Upstash e o Anthropic de uma vez. De carona, dá endereço fixo
# para pôr na allowlist daqueles dois.
resource "google_compute_router" "roteador" {
  name    = "hml"
  region  = var.regiao
  network = google_compute_network.rede.id
}

resource "google_compute_address" "saida" {
  name   = "hml-saida"
  region = var.regiao
}

# O endereço de **entrada**, que é outra coisa e mora aqui pelo mesmo motivo que o
# de saída: endereço é o que a nuvem entrega, e este módulo é onde isso é dito.
#
# Ele é global porque o balanceador da borda é global, e nasce **aqui** e não lá por
# causa de um ciclo: sem domínio próprio, o nome de cada frente contém o IP
# (`portal.<ip>.nip.io`), e o certificado da borda precisa dos nomes — um endereço
# criado na borda faria o `servicos.tf` depender de uma saída daquele módulo para
# produzir uma entrada dele.
#
# Confundir os dois foi o defeito que o módulo `borda` conserta: o `nip.io` era
# montado sobre o de saída, que é por onde o Cloud Run *fala* com o Neon e o Upstash
# e onde serviço nenhum escuta.
resource "google_compute_global_address" "entrada" {
  name       = "hml-entrada"
  depends_on = [google_project_service.api]
}

resource "google_compute_router_nat" "nat" {
  name                               = "hml"
  router                             = google_compute_router.roteador.name
  region                             = var.regiao
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.saida.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# --- Imagens ----------------------------------------------------------------

resource "google_artifact_registry_repository" "imagens" {
  location      = var.regiao
  repository_id = "hml"
  format        = "DOCKER"
  description   = "Imagens de homologação dos dois portais"
  depends_on    = [google_project_service.api]
}

# --- Documentos -------------------------------------------------------------
# No lugar do MinIO. O `boto3` do `storage.py` aceita `endpoint_url`, e o GCS tem
# API S3-compatível por chave HMAC — nenhuma linha de código muda.

resource "google_storage_bucket" "documentos" {
  name                        = "${var.projeto}-documentos"
  location                    = var.regiao
  uniform_bucket_level_access = true
  # Público nunca: o download é por URL assinada de vida curta (ADR 0017), e a
  # assinatura é o controle. Um bucket público tornaria a assinatura decorativa.
  public_access_prevention = "enforced"
  force_destroy            = true # HML: derrubar e recriar precisa ser barato
  depends_on               = [google_project_service.api]
}

# --- Segredos ---------------------------------------------------------------
# Criados **vazios**. Os valores entram por `gcloud secrets versions add`, nunca
# pelo Terraform — senão eles ficariam no estado, que é um arquivo num bucket.

resource "google_secret_manager_secret" "segredo" {
  for_each  = toset(var.nomes_de_segredo)
  secret_id = each.value
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}

# --- Identidade de execução -------------------------------------------------

resource "google_service_account" "execucao" {
  account_id   = "hml-execucao"
  display_name = "Execução dos serviços de HML"
}

resource "google_secret_manager_secret_iam_member" "leitura" {
  for_each  = google_secret_manager_secret.segredo
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.execucao.email}"
}

resource "google_storage_bucket_iam_member" "documentos" {
  bucket = google_storage_bucket.documentos.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.execucao.email}"
}

# --- O GitHub, sem chave ----------------------------------------------------
# Workload Identity Federation. A organização proíbe criar chave de conta de
# serviço (a política que a ADR 0016 do Biahflow encontrou), e essa proibição é
# uma boa notícia aqui: o que sobra é o mecanismo que não tem segredo para vazar.

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  # Sem esta condição, **qualquer repositório do GitHub** poderia trocar um token
  # OIDC por credencial deste projeto. É a linha que separa federação de porta
  # aberta, e ela é fácil de esquecer porque nada falha quando falta.
  attribute_condition = "attribute.repository in ${jsonencode(var.repositorios_github)}"

  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

# **Duas contas, e a divisão é a mesma dos dois workflows.** Trocar a imagem de um
# serviço e mudar a forma da infraestrutura têm raios de dano diferentes — é o que
# o cabeçalho do `deploy-hml.yml` argumenta —, e separar os workflows sem separar
# as credenciais deixava o argumento pela metade: um `deploy-hml.yml` comprometido
# usava a mesma conta que pode recriar a rede.
#
# Uma versão anterior tinha só a `hml-deploy`, com as quatro permissões de baixo, e
# era ela que o `infra-hml.yml` usava para rodar `terraform apply`. Não funcionava:
# nenhuma daquelas quatro cria uma sub-rede, uma conta de serviço ou um pool de WIF.

resource "google_service_account" "deploy" {
  account_id   = "hml-deploy"
  display_name = "Deploy de HML pelo GitHub Actions"
}

# O que um deploy precisa e nada além: publicar imagem, trocar revisão, executar
# job, e acrescentar versão de segredo. Não inclui **ler** segredo — quem lê é a
# `hml-execucao`, em tempo de execução.
resource "google_project_iam_member" "deploy" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
    "roles/secretmanager.secretVersionManager",
  ])
  project = var.projeto
  role    = each.value
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account" "infra" {
  account_id   = "hml-infra"
  display_name = "Terraform de HML pelo GitHub Actions"
}

# O que um `apply` precisa. É muito, e é por isso que ela não é a conta do deploy:
# esta lista é praticamente o projeto inteiro, e só o `infra-hml.yml` — que aplica
# sob `workflow_dispatch` com `aplicar=true`, nunca em push — se autentica com ela.
resource "google_project_iam_member" "infra" {
  for_each = toset([
    "roles/compute.networkAdmin",
    "roles/compute.loadBalancerAdmin",
    "roles/compute.securityAdmin",
    "roles/run.admin",
    "roles/artifactregistry.admin",
    "roles/secretmanager.admin",
    "roles/storage.admin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/serviceusage.serviceUsageAdmin",
  ])
  project = var.projeto
  role    = each.value
  member  = "serviceAccount:${google_service_account.infra.email}"
}

# O estado. Sem esta linha o `terraform init` do CI falha antes de planejar
# qualquer coisa, e o erro não menciona o bucket — diz só que a credencial não
# serve. O bucket é criado à mão (ovo e galinha, ver `backend.tf`), então ele entra
# por nome e não por referência.
resource "google_storage_bucket_iam_member" "estado" {
  bucket = var.bucket_estado
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.infra.email}"
}

# A federação, por conta e por repositório. A `hml-deploy` vale para os dois repos,
# porque os dois publicam imagem; a `hml-infra` vale **só para o repo que contém o
# Terraform** — dar a outro a conta que pode recriar a rede seria conceder um poder
# que ele não tem como exercer e não tem por que ter.
locals {
  federacoes = merge(
    { for repo in var.repositorios_github :
      "deploy/${repo}" => { conta = google_service_account.deploy.name, repo = repo }
    },
    { "infra/${var.repositorio_infra}" = {
      conta = google_service_account.infra.name, repo = var.repositorio_infra
    } },
  )
}

resource "google_service_account_iam_member" "federacao" {
  for_each           = local.federacoes
  service_account_id = each.value.conta
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${each.value.repo}"
}

# --- Saídas -----------------------------------------------------------------

output "rede" { value = google_compute_network.rede.id }
output "sub_rede" { value = google_compute_subnetwork.sub_rede.id }
output "conta_execucao" { value = google_service_account.execucao.email }
output "conta_deploy" { value = google_service_account.deploy.email }
output "conta_infra" { value = google_service_account.infra.email }
output "bucket_documentos" { value = google_storage_bucket.documentos.name }
output "ip_saida" { value = google_compute_address.saida.address }
output "ip_entrada" { value = google_compute_global_address.entrada.address }
output "endereco_entrada" { value = google_compute_global_address.entrada.id }
output "registro" {
  value = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.imagens.repository_id}"
}
output "provedor_wif" {
  value = google_iam_workload_identity_pool_provider.github.name
}
