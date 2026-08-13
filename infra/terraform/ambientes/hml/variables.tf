variable "projeto" {
  description = "Project ID da GCP."
  type        = string
  default     = "biahflow-hml"
}

variable "regiao" {
  description = "Região dos recursos regionais (Cloud Run, VM, bucket)."
  type        = string
  default     = "us-east1"
}

variable "dominio" {
  description = <<-TXT
    A zona registrada na Cloudflare. **Obrigatória desde 13/08/2026**, e é a mudança
    que tornou a borda gratuita.

    Antes ela podia ser vazia, e vazio caía em `nip.io` sobre o IP de entrada do
    balanceador — o único jeito de dar nome estável ao `issuer` do Keycloak sem
    domínio. Com o Keycloak fora e a borda na Cloudflare, o fallback deixou de ter
    para o que apontar: o IP global foi liberado, e um default que constrói hostname
    a partir de um recurso destruído produz erro pior do que exigir o valor.

    `var.borda_ligada` sumiu junto. Ela desligava as duas regras de encaminhamento
    para não pagá-las paradas; hoje não há regra de encaminhamento para desligar.
  TXT
  type        = string
  default     = "biahflow.ai"

  validation {
    condition     = var.dominio != ""
    error_message = "`dominio` não é mais opcional: sem ele não há de onde derivar `app.<domínio>`, e o `nip.io` que preenchia essa lacuna dependia de um IP que não existe mais."
  }
}

variable "conta_cloudflare" {
  description = "Account ID da Cloudflare. Identificador, não segredo — o segredo é o token, que vem por `CLOUDFLARE_API_TOKEN` no ambiente. Mesmo valor do repo do site."
  type        = string
  default     = "81d31bb1b024f9759bbd374d13370976"
}

variable "zona_cloudflare" {
  description = <<-TXT
    Zone ID de `biahflow.ai`. Fixo, e não descoberto por `data "cloudflare_zone"`
    filtrando por nome — a busca exige `Zone → Zone → Read` no token, e um token sem
    essa permissão não responde "acesso negado": responde **`0 found`**, que parece
    nome de zona errado e manda depurar a coisa errada.

    Identificador, como o account id. O valor confere com o que o state do
    `biahflow-site` já resolveu para a mesma zona.
  TXT
  type        = string
  default     = "fd52b4e75ea808250a902949f7a494e2"
}

variable "emails_com_acesso" {
  description = <<-TXT
    Quem atravessa o Cloudflare Access na frente do CRM. Lista explícita, e não regra
    por domínio, porque o acesso inclui uma conta fora de `@biahflow.ai` — uma regra
    por domínio esconderia essa exceção em vez de declará-la.
  TXT
  type        = list(string)
  default     = ["daniel@biahflow.ai", "danielcamppos@gmail.com"]
}

variable "bucket_estado" {
  description = <<-TXT
    O bucket do estado remoto, criado **à mão** antes de tudo (o comando está em
    `backend.tf`). Aparece aqui como variável porque o Terraform precisa conceder
    acesso a ele à conta que roda o próprio Terraform, e um recurso não pode
    referenciar o bucket que guarda o estado dele.

    Precisa bater com o `bucket` do `backend.tf`, que não aceita variável —
    `terraform init` acontece antes de haver valores.
  TXT
  type        = string
  default     = "biahflow-hml-tfstate"
}

variable "repositorios_github" {
  description = <<-TXT
    Os repositórios que podem se autenticar por Workload Identity Federation, no
    formato `dono/repo`. **Sem chave de conta de serviço** — é a mesma postura que a
    ADR 0016 do Biahflow adotou por política da organização.
  TXT
  type        = list(string)
  # `biahflow-site` entrou em 13/08/2026: o site de marketing passou a ter backend
  # próprio no Cloud Run (`biahflow-site-api-hml`), e o workflow que publica a imagem
  # dele precisa da mesma federação — sem chave, como os outros dois. O Terraform
  # daquele produto mora no repo dele, então ele **não** entra em `repositorio_infra`:
  # federa só a conta de deploy.
  #
  # Os dois do OikOS entraram **fora do Terraform** e foram descobertos por um plano
  # que queria removê-los. Estão escritos aqui porque a condição do provedor é um
  # atributo único e não um conjunto de bindings: quem a reescrever a partir de uma
  # lista incompleta **revoga** o que não está nela — o `oikos-proto-web` pararia de
  # ser publicado, e o sintoma seria um token recusado no CI de outro repositório.
  # Federam só a conta de deploy, como o site.
  default = [
    "dcamppos83/biahflow-portal-cliente",
    "dcamppos83/biahflow-portal",
    "dcamppos83/biahflow-site",
    "dcamppos83/OikOS",
    "dcamppos83/plataforma-oikos",
  ]
}

variable "repositorio_infra" {
  description = <<-TXT
    O único repositório autorizado a rodar `terraform apply` — o que **contém** o
    Terraform. Os dois repos publicam imagem e por isso ambos federam a conta de
    deploy; só um muda a forma da infraestrutura, e conceder ao outro a conta que
    recria a rede seria poder sem uso e sem motivo.

    Precisa estar contido em `repositorios_github`, senão a condição do provedor
    de WIF recusa o token antes de a federação ser consultada.
  TXT
  type        = string
  default     = "dcamppos83/biahflow-portal-cliente"
}

variable "segredos" {
  description = <<-TXT
    Os segredos que o Terraform **cria vazios** no Secret Manager, e de que produto é
    cada um. Os valores entram por fora (`gcloud secrets versions add`) e nunca por
    aqui — o repositório documenta os nomes e jamais os valores.

    **A chave é o nome do segredo; o valor é o produto dono.** O dono existe porque os
    dois portões de leitor moram nos states de produto desde a ADR 0051: cada um cobra
    que todo segredo atribuído a ele seja lido por algum serviço seu. Sem o dono
    declarado aqui, um segredo poderia nascer sem que portão nenhum perguntasse se ele
    chega a alguém — que é exatamente como `ANTHROPIC_API_KEY` e `VOYAGE_API_KEY`
    passaram meses no cofre sem leitor.

    Na maioria dos casos o nome do segredo é o nome da variável de ambiente que a
    aplicação lê. A exceção são as quatro DSNs: quando dois produtos leem a mesma
    variável e precisam de valores diferentes, o segredo ganha o prefixo do dono e o
    mapa `segredos` de cada produto faz a ligação.
  TXT
  type        = map(string)
  # **Os vinte segredos do portal do cliente saíram em 13/08/2026**, com o produto.
  # Eram `AUTH_SECRET`, `AUTH_KEYCLOAK_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`, as
  # quatro DSNs do portal, os quatro `KC_*` do Keycloak, os dois tokens de leitura e
  # webhook em direção ao Biahflow, `AGENT_KEY_PEPPER`, `DRIVE_TOKEN_ENCRYPTION_KEY`,
  # o par `STORAGE_*` e as chaves da Anthropic e da Voyage.
  #
  # **Apagar o segredo apaga o valor**, e os valores das DSNs continuam válidos do
  # outro lado: o Postgres do portal e o do Keycloak seguem na Neon, o Redis na
  # Upstash. Quem religar o portal um dia recria os segredos aqui e põe os valores de
  # lá — o que se perdeu foi a cópia, não a fonte.
  #
  # `PORTAL_READ_TOKEN` e `PORTAL_WEBHOOK_SECRET` **ficam**, e não é esquecimento: o
  # dono deles é `biahflow`, quem os lê é a `biahflow-api`, e removê-los quebraria o
  # `secret_key_ref` daquele serviço para economizar centavos. O webhook em direção ao
  # portal se desliga sozinho — `apps/core/flags.py` exige as duas variáveis
  # preenchidas, e `settings.py` as lê com default vazio.
  default = {
    DJANGO_SECRET_KEY          = "biahflow"
    BIAHFLOW_DATABASE_URL      = "biahflow"
    BIAHFLOW_REDIS_URL         = "biahflow"
    PORTAL_READ_TOKEN          = "biahflow"
    PORTAL_WEBHOOK_SECRET      = "biahflow"
    GOOGLE_OAUTH_CLIENT_ID     = "biahflow"
    GOOGLE_OAUTH_CLIENT_SECRET = "biahflow"
    GOOGLE_OAUTH_REFRESH_TOKEN = "biahflow"
    EMAIL_HOST_PASSWORD        = "biahflow"
    # Token compartilhado da captação de leads: quem o apresenta em `X-Intake-Token`
    # pode postar em `/api/v1/leads/intake/`. O leitor é a `biahflow-api`; o emissor
    # é o relay do site de marketing (repo `biahflow-site`), que o guarda do lado
    # servidor para ele nunca chegar ao navegador.
    #
    # Sem ele o intake não fica aberto — fica **fechado**: `_valid_intake_token`
    # exige `bool(expected)` antes de comparar, então token vazio recusa todo lead
    # com 401 e o visitante vê erro. É o mesmo segredo que o site guarda em
    # `site-crm-intake-token-hml`, e os dois valores têm de ser idênticos.
    LEAD_INTAKE_TOKEN = "biahflow"
  }
}
