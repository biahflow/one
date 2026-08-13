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
# Os **argumentos** do contêiner, e a palavra importa: no Cloud Run `command` substitui
# o *entrypoint* e `args` é o que se passa a ele. Os módulos de job e de worker usam
# `comando` porque lá a substituição é o ponto (`python manage.py migrate`); aqui não —
# a imagem do Keycloak tem `kc.sh` como entrypoint, e `command = ["start"]` fez o Cloud
# Run procurar um binário chamado `start`. É o `command:` do Docker Compose, que apesar
# do nome vira `args`.
#
# Vazio para as nossas imagens, que trazem entrypoint e argumento próprios
# — e é por isso que esta variável não existia. O primeiro serviço de terceiro do
# ambiente mostrou a falta: a imagem do Keycloak tem `kc.sh` como entrypoint e **nenhum
# comando padrão**, então ela sobe, imprime a ajuda e sai — e o Cloud Run relata
# "failed to start and listen on the port", que fala de porta e não de comando.
variable "argumentos" {
  type    = list(string)
  default = []
}
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

# **A trava de exclusão existia sem estar escrita.** O provider 6.x liga
# `deletion_protection` por default, então todo serviço nasceu protegido sem que
# arquivo nenhum aqui dissesse isso — e a conta veio no `terraform destroy`, que
# reprova inteiro com "cannot destroy service without setting
# deletion_protection=false" depois de já ter derrubado o que não era serviço.
#
# Escrita, ela vira decisão em vez de efeito colateral. O default é `true` porque a
# trava está certa: desmontar um produto é raro e deve custar uma linha explícita.
variable "protegido" {
  description = "Se o serviço recusa ser destruído. `false` só ao desmontar um ambiente de propósito."
  type        = bool
  default     = true
}

resource "google_cloud_run_v2_service" "servico" {
  name                = var.nome
  location            = var.regiao
  deletion_protection = var.protegido

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
      # `null` e não `[]`: lista vazia significaria "sem argumento" para a API, em vez
      # de "não declare".
      args = length(var.argumentos) > 0 ? var.argumentos : null
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
  #
  # O segundo item é de outra espécie e vale a explicação, porque `ignore_changes` é
  # uma forma barata de esconder desvio real. **`scaling` aqui é o de serviço, não o
  # de `template`** — campo que o provider 6.x acrescentou e que a API devolve sempre
  # preenchido com zeros, mesmo para quem nunca o declarou. Como não declaramos, todo
  # `plan` propunha removê-lo, todo `apply` "removia", e o `plan` seguinte propunha de
  # novo: desvio perpétuo, que faz um plano nunca ficar limpo e apaga a diferença entre
  # "este PR não muda nada" e "este PR muda alguma coisa". Quem escalona este serviço é
  # `template[0].scaling`, que continua declarado e continua sendo comparado.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      scaling,
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
