variable "projeto" {
  description = "Project ID da GCP."
  type        = string
  default     = "biahflow-hml"
}

variable "regiao" {
  description = "Região dos recursos regionais."
  type        = string
  default     = "us-east1"
}

variable "prefixo_da_fundacao" {
  description = <<-TXT
    Onde ler o state da fundação. A direção é sempre esta — fundação → produto —, e
    nunca entre produtos: um produto que precise de valor do outro o deriva do número
    do projeto, que é data source e não recurso nosso.
  TXT
  type        = string
  default     = "ambientes/hml"
}

variable "tag_imagem" {
  description = <<-TXT
    A tag das imagens a implantar. **SHA do commit, nunca `latest`**: é o que permite
    voltar apontando a revisão anterior, e o que faz duas revisões diferentes serem
    distinguíveis.

    Vazio é o caso do **primeiro apply**, e significa `imagem_bootstrap`.
  TXT
  type        = string
  default     = ""
}

variable "imagem_bootstrap" {
  description = <<-TXT
    A imagem com que um serviço **nasce**, antes de o primeiro deploy existir.

    O `lifecycle.ignore_changes` dos módulos protege a tag do último deploy de um
    apply de infraestrutura — mas `ignore_changes` só vale em *update*, nunca em
    *create*. No primeiro apply o Cloud Run receberia a imagem literal, tentaria
    baixá-la de um registro vazio e recusaria a revisão; e o `deploy-hml.yml` só sabe
    fazer `gcloud run services update`, que exige o serviço já criado.

    **Depois da migração da ADR 0051 isto vale como rede de segurança, não como
    caminho:** os serviços já existem e foram importados com a imagem viva. Um serviço
    que precise ser recriado nasceria aqui — e é por isso que todo `plan` deste
    diretório se lê procurando `must be replaced`.
  TXT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}
