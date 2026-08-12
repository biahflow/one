# Os nomes públicos, e o realm.
#
# Moram na fundação porque **todo nome deste ambiente contém o IP de entrada** — sem
# domínio próprio, `nip.io` o carrega dentro do hostname. Um produto que os derivasse
# sozinho precisaria do IP, e o IP é recurso da fundação: seria dependência de state
# escrita ao contrário.

locals {
  # O nome público de cada frente. Sem domínio próprio, `nip.io` resolve qualquer
  # `<qualquer-coisa>.<ip>.nip.io` para aquele IP — dá nome estável ao OIDC, que é
  # o que o Keycloak precisa para o `issuer` não mudar a cada deploy.
  #
  # **O IP é o de entrada**, do balanceador. Uma versão anterior usava o de saída,
  # do Cloud NAT: o nome resolvia, ninguém escutava lá, e o login não fechava. Ver
  # `modulos/borda/`.
  dominio_base = var.dominio != "" ? var.dominio : "${module.fundacao.ip_entrada}.nip.io"

  host_portal   = "portal.${local.dominio_base}"
  host_keycloak = "auth.${local.dominio_base}"
  host_biahflow = "app.${local.dominio_base}"

  url_portal   = "https://${local.host_portal}"
  url_keycloak = "https://${local.host_keycloak}"
  url_biahflow = "https://${local.host_biahflow}"

  # O realm, num lugar só. Ele estava escrito em três — `/realms/portal` aqui,
  # `portal-local` no default do `config.py` e `portal-homolog` no runbook —, e três
  # nomes para uma coisa é um `issuer` que não casa com o `iss` do token: a API
  # recusa todo acesso e a mensagem fala de assinatura, não de nome.
  realm = "portal-homolog"

  issuer   = "${local.url_keycloak}/realms/${local.realm}"
  jwks_url = "${local.issuer}/protocol/openid-connect/certs"
}
