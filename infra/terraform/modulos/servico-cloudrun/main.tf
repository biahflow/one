# Um serviço HTTP no Cloud Run.
#
# O módulo existe para que `servicos.tf` possa dizer "um serviço com esta imagem,
# nesta porta, alcançável por estes" sem saber o que é uma revisão do Cloud Run.

variable "projeto" { type = string }
variable "regiao" { type = string }
variable "nome" { type = string }
variable "imagem" { type = string }
variable "porta" { type = number }
variable "acesso" {
  description = <<-TXT
    Quem alcança este serviço, em três valores e não num booleano:

      `publico`     — qualquer um, pela URL `run.app` e pela borda.
      `interno`     — só de dentro da VPC, e com identidade: ingress **e** IAM.
      `balanceador` — só de dentro da VPC e pelo balanceador de aplicação.

    O terceiro existe porque o segundo não serve a um serviço **cujo cliente é o
    navegador**. A `biahflow-api` é chamada pelo SPA que a `biahflow-web` serve; um
    NEG sem servidor não apresenta ID token ao Cloud Run, e nginx não emite nenhum —
    então sob `interno` o IAM invoker nunca é atravessado e a barreira efetiva é uma
    só, com a aparência de duas. Era o item que a ADR 0046 deixou aberto.

    **Sob `balanceador` o IAM é aberto de propósito, e isso não é descuido.** Como o
    NEG não autentica, exigir IAM ali seria exigir do balanceador uma credencial que
    ele não tem: o serviço responderia 403 a toda requisição legítima. A barreira é
    o ingress — a `run.app` deixa de existir para a internet — e a borda passa a ser
    nossa. Quem quiser a segunda barreira de verdade põe Cloud Armor no backend
    service, não um `iam_member` que ninguém pode apresentar (ADR 0048).
  TXT
  type        = string

  validation {
    condition     = contains(["publico", "interno", "balanceador"], var.acesso)
    error_message = "`acesso` é `publico`, `interno` ou `balanceador`."
  }
}
variable "cpu" { type = string }
variable "memoria" { type = string }
variable "minimo" { type = number }
variable "maximo" { type = number }
variable "conta" { type = string }
variable "rede" { type = string }
variable "sub_rede" { type = string }
variable "variaveis" { type = map(string) }

# **Mapa e não lista: a chave é a variável de ambiente, o valor é o nome do segredo.**
# Era uma lista, e a lista impunha que os dois fossem a mesma string — o que estava
# certo até dois produtos precisarem do mesmo nome de variável apontando para valores
# diferentes. Foi o caso de `DATABASE_URL`: um segredo só, um valor só, montado na
# `portal-api` e na `biahflow-api`, de modo que os dois liam a mesma DSN. Renomear a
# variável não era opção — o nome é contrato com o código de cada aplicação.
#
# Na maioria dos casos os dois lados continuam iguais, e o mapa diz isso por extenso.
variable "segredos" { type = map(string) }

resource "google_cloud_run_v2_service" "servico" {
  name     = var.nome
  location = var.regiao

  # **O ingress é a decisão de segurança deste módulo**, e são três respostas porque
  # há três clientes: a internet, um processo nosso, e o navegador *pela nossa
  # borda*. `INGRESS_TRAFFIC_ALL` é o default do Cloud Run e para as duas APIs
  # estaria errado — o `Caddyfile` do compose decidiu que a `portal-api` não é
  # alcançada pelo navegador, e a `biahflow-api` só é alcançada **através do
  # balanceador**, nunca pela `run.app`. Publicar qualquer uma daria à internet um
  # caminho que o produto não usa.
  #
  # `INTERNAL_LOAD_BALANCER` é **superconjunto** de `INTERNAL_ONLY`: o alcance pela
  # VPC continua, e é por ele que a `portal-api` fala com a `biahflow-api`.
  #
  # Mapa e não ternário aninhado: com três casos, o ternário é onde o quarto valor
  # entra errado sem nada ficar vermelho.
  ingress = {
    publico     = "INGRESS_TRAFFIC_ALL"
    interno     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    balanceador = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  }[var.acesso]

  template {
    service_account = var.conta

    scaling {
      min_instance_count = var.minimo
      max_instance_count = var.maximo
    }

    vpc_access {
      network_interfaces {
        network    = var.rede
        subnetwork = var.sub_rede
      }
      # `ALL_TRAFFIC`, e é ele que faz o ingress interno funcionar. Com
      # `PRIVATE_RANGES_ONLY`, a chamada do BFF para a API sairia pela internet e
      # bateria na porta que o `INGRESS_TRAFFIC_INTERNAL_ONLY` recusa — o serviço
      # subiria, o `terraform plan` ficaria limpo, e a tela daria erro.
      #
      # O preço é que **toda** saída passa pela VPC, inclusive Neon, Upstash e
      # Anthropic. Quem paga esse preço é o Cloud NAT da fundação.
      egress = "ALL_TRAFFIC"
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

  # A tag da imagem muda a cada deploy e é o Actions quem a aplica. Sem isto, um
  # `terraform apply` de infraestrutura reverteria o serviço para a tag do último
  # apply — desfazendo o deploy mais recente sem ninguém pedir.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

# Renomeado na ADR 0048: sob `balanceador` este binding continua sendo `allUsers` e
# o serviço **não** é público. Um label dizendo "publico" faria o `terraform state
# list` afirmar o contrário do que o ingress decide.
moved {
  from = google_cloud_run_v2_service_iam_member.publico
  to   = google_cloud_run_v2_service_iam_member.invocacao_aberta
}

# `allUsers` significa "sem autenticação IAM na frente" — e significa coisas
# diferentes conforme o ingress, que é o par que decide de verdade:
#
#   `publico`     → qualquer um na internet invoca. É o caso do BFF e do Keycloak.
#   `balanceador` → só o balanceador chega, e ele **não tem como** apresentar
#                   identidade: um NEG sem servidor não cunha ID token. Exigir IAM
#                   aqui seria 403 em toda requisição legítima.
#
# Sob `interno` esta permissão não é criada: lá o chamador é um processo nosso, que
# tem conta e sabe apresentá-la.
resource "google_cloud_run_v2_service_iam_member" "invocacao_aberta" {
  count    = contains(["publico", "balanceador"], var.acesso) ? 1 : 0
  name     = google_cloud_run_v2_service.servico.name
  location = var.regiao
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# E a segunda barreira precisa de **alguém que a atravesse**, senão ela é decoração
# que produz 403 antes de a aplicação existir na conversa — e o 403 do Cloud Run não
# aparece em log nosso (ADR 0046). Quem atravessa é a conta de execução, que é a
# mesma dos dois lados: o serviço que chama roda com ela, e é ela que o
# `X-Serverless-Authorization` do BFF apresenta (`app/lib/serviceIdentity.ts`).
#
# **Sobrou uma só sob esta regra, a `portal-api`, e a `biahflow-api` saiu por não ter
# chamador capaz de atravessá-la**: quem a chama é o navegador. O preço, declarado na
# ADR 0048, é que a chamada `portal-api → biahflow-api` deixa de ter IAM e passa a
# ser barrada só pelo `BIAHFLOW_READ_TOKEN` que a aplicação já manda — o que, medido,
# é mais do que ela tinha: `integrations/biahflow.py` nunca cunhou ID token nenhum, e
# aquele caminho respondia 403 em HML sem nada denunciar.
resource "google_cloud_run_v2_service_iam_member" "invocacao_interna" {
  count    = var.acesso == "interno" ? 1 : 0
  name     = google_cloud_run_v2_service.servico.name
  location = var.regiao
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.conta}"
}

output "url" { value = google_cloud_run_v2_service.servico.uri }
