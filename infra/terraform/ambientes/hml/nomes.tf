# O nome público, no singular desde 13/08/2026.
#
# Eram três — `portal.`, `auth.` e `app.` —, montados sobre `nip.io` porque não havia
# domínio e o IP do balanceador precisava caber dentro do hostname. Com o portal do
# cliente fora e a borda da Google apagada, sobrou um produto com nome, e o nome
# passou a sair de um domínio de verdade.
#
# **Este arquivo continua na fundação mesmo servindo um produto só.** Não é inércia:
# quem publica o nome é a borda, a borda agora é a Cloudflare (`cloudflare.tf`), e ela
# é da fundação pela mesma razão que a anterior era — um produto que derivasse o
# próprio hostname precisaria da zona, e a zona não é dele.

locals {
  # Sem fallback. O antigo (`"${ip_entrada}.nip.io"`) existia para dar nome estável ao
  # `issuer` do Keycloak antes de haver domínio; o Keycloak saiu com o portal, e o IP
  # de entrada foi liberado junto com o balanceador. Um fallback que aponta para um
  # recurso destruído não é resiliência, é uma mensagem de erro pior.
  dominio_base = var.dominio

  host_biahflow = "app.${local.dominio_base}"
  url_biahflow  = "https://${local.host_biahflow}"
}
