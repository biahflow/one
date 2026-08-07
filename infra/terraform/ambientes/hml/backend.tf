# Estado remoto. O bucket **não** é criado por este Terraform — ovo e galinha.
# Uma vez, à mão:
#
#   gcloud storage buckets create gs://biahflow-hml-tfstate \
#     --project=biahflow-hml --location=us-east1 --uniform-bucket-level-access
#   gcloud storage buckets update gs://biahflow-hml-tfstate --versioning
#
# Versionamento ligado de propósito: o estado é o único artefato deste diretório
# que não dá para reconstruir a partir do repositório.
terraform {
  backend "gcs" {
    bucket = "biahflow-hml-tfstate"
    prefix = "ambientes/hml"
  }
}
