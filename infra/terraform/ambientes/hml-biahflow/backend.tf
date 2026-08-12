# Estado remoto. **Mesmo bucket da fundação, prefixo diferente** — o backend GCS
# grava em `<prefix>/<workspace>.tfstate`, então um state novo não custa bucket novo
# nem IAM novo. O que ele custa está escrito na ADR 0051.
terraform {
  backend "gcs" {
    bucket = "biahflow-hml-tfstate"
    prefix = "ambientes/hml-biahflow"
  }
}
