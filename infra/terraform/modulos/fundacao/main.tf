# O que a GCP precisa ter antes de qualquer serviço existir: APIs ligadas, rede,
# registro de imagem, bucket, cofre de segredo e a identidade que o GitHub usa.

variable "projeto" { type = string }
variable "regiao" { type = string }
# Nome do segredo => produto dono. O dono não é usado aqui; ele existe para os
# portões de leitor, que moram nos states de produto (ADR 0051).
variable "segredos" { type = map(string) }
variable "repositorios_github" { type = list(string) }
# Quem impersona a `hml-deploy`. Nem todo repositório da condição do provedor
# publica imagem: `biahflow/infra` entra na condição (o CI dele autentica) e **não**
# federa esta conta — ele usa a `infra-deploy`, que é de outro state. Sem esta
# separação, a lista da condição concederia deploy a quem só precisa entrar, e os
# dois states passariam a discordar sobre um mesmo binding (ver `ambientes/hml`).
variable "repositorios_deploy" { type = list(string) }
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

  # Tráfego para APIs e serviços do Google (GCS, OAuth, Drive, e as URLs `run.app`
  # de um serviço para outro) passa a sair por caminho privado, sem atravessar o
  # Cloud NAT — que cobra por GB processado. Não custa nada e é aditivo: o que já
  # ia pelo NAT continua indo.
  #
  # **Isto não torna o NAT dispensável**, e a distinção importa porque a hipótese
  # contrária já foi levantada: PGA cobre destinos *do Google*, e os serviços daqui
  # dependem de cinco que não são — Neon (o banco), Upstash (Redis), Anthropic,
  # Voyage e `smtp.gmail.com:587` (SMTP direto não é API do Google para esse fim).
  # Remover o NAT deixaria os dois produtos sem banco.
  private_ip_google_access = true
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

# **Havia um segundo endereço aqui, o de entrada, e ele saiu em 13/08/2026.** Era o
# IP global do balanceador, e existia neste módulo porque, sem domínio próprio, o nome
# de cada frente continha o IP (`portal.<ip>.nip.io`): o certificado da borda precisava
# dos nomes, e os nomes precisavam do endereço, então criá-lo na borda fecharia ciclo.
#
# Com a borda na Cloudflare e um domínio de verdade, o ciclo deixou de existir e o
# endereço passou a ser só um IP reservado sem nada escutando nele — que é a **tarifa
# mais cara** que a GCP cobra por endereço, o dobro da de "em uso".
#
# O de saída fica, e a distinção entre os dois é o defeito que a ADR 0046 registrou: o
# `nip.io` chegou a ser montado sobre o de saída, que é por onde o Cloud Run *fala* com
# o Neon e o Upstash e onde serviço nenhum escuta. É ele que está nas allowlists deles,
# e é por isso que **este não pode mudar**.

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

# --- O espelho de imagem de terceiro -----------------------------------------
# O Cloud Run **só aceita imagem de `*.pkg.dev`, `gcr.io` ou `docker.io`** — medido,
# e a mensagem de erro dele nomeia a saída: "set up an Artifact Registry remote
# repository". O Keycloak vem do `quay.io`, e sem isto ele não tinha caminho nenhum
# para a imagem real: o Terraform monta a imagem de todo serviço como
# `<registro>/<nome>:<tag>`, e o `deploy-hml.yml` só constrói as duas que são nossas.
# O IdP ficava na `imagem_bootstrap` para sempre, servindo a página do Cloud Run no
# endereço que o `issuer` do realm declara.
#
# Espelho e não passo de mirror no workflow: um `docker pull && push` seria uma cópia
# que alguém precisa lembrar de refazer a cada versão, e que só existe enquanto o
# workflow roda. O repositório remoto é cache sob demanda — pede-se
# `<espelho>/keycloak/keycloak:26.1` e ele busca no upstream na primeira vez.
resource "google_artifact_registry_repository" "espelho" {
  repository_id = "espelho-quay"
  location      = var.regiao
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Espelho do quay.io — o Cloud Run não puxa de registro de terceiro"

  remote_repository_config {
    description = "quay.io"
    docker_repository {
      custom_repository {
        uri = "https://quay.io"
      }
    }
  }

  depends_on = [google_project_service.api]
}

# --- Mídia do Biahflow ------------------------------------------------------
# Bucket **separado** do de documentos, e a separação não é zelo: aquele é do
# portal do cliente e é acessado por API S3 com chave HMAC, com o objeto
# carregando o tenant na chave; este é do Django do Biahflow, escrito pelo
# `FileField` via `django-storages`. Mesmo bucket significaria dois produtos
# escrevendo prefixos no mesmo lugar sem nenhum dos dois saber do outro.
#
# Até aqui a mídia do Biahflow morava no sistema de arquivos do contêiner: com
# `min = 1` e `max = 4`, o arquivo enviado ficava na instância que o recebeu,
# invisível para as outras e perdido na revisão seguinte.

resource "google_storage_bucket" "midia" {
  name                        = "${var.projeto}-midia"
  location                    = var.regiao
  uniform_bucket_level_access = true
  # Mesma razão do bucket ao lado, com um controle diferente: aqui não há URL
  # assinada — o download é servido pela rota autenticada do Django, que passa
  # por `check_object_permissions` (ADR 0002 / FDD 017 de lá). Um bucket público
  # seria um segundo caminho para o arquivo, sem RBAC nenhum.
  public_access_prevention = "enforced"
  force_destroy            = true # HML: derrubar e recriar precisa ser barato

  # O que substitui o `tar` de mídia do sidecar de backup, que não tem casa em
  # HML. Versão anterior sobrevive a um `delete` acidental e ao expurgo de
  # retenção que apagar o objeto errado.
  versioning {
    enabled = true
  }

  depends_on = [google_project_service.api]
}

# --- Segredos ---------------------------------------------------------------
# Criados **vazios**. Os valores entram por `gcloud secrets versions add`, nunca
# pelo Terraform — senão eles ficariam no estado, que é um arquivo num bucket.

resource "google_secret_manager_secret" "segredo" {
  for_each  = var.segredos
  secret_id = each.key
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

# O Django precisa criar, ler e apagar objeto — o expurgo de retenção apaga, e o
# `document.file.delete()` também. `objectAdmin` e não `objectViewer`, pelo mesmo
# motivo do bucket ao lado.
resource "google_storage_bucket_iam_member" "midia" {
  bucket = google_storage_bucket.midia.name
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

# A federação, por conta e por repositório. A `hml-deploy` vale para quem publica
# imagem; a `hml-infra` vale **só para o repo que contém o Terraform** — dar a outro a
# conta que pode recriar a rede seria conceder um poder que ele não tem como exercer e
# não tem por que ter.
locals {
  federacoes = merge(
    { for repo in var.repositorios_deploy :
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
output "bucket_midia" { value = google_storage_bucket.midia.name }
output "ip_saida" { value = google_compute_address.saida.address }
output "registro_espelho" {
  description = "Espelho do quay.io. O Cloud Run não puxa de registro de terceiro."
  value       = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.espelho.repository_id}"
}
output "registro" {
  value = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.imagens.repository_id}"
}
output "provedor_wif" {
  value = google_iam_workload_identity_pool_provider.github.name
}
