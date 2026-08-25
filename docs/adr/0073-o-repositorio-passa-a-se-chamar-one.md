# ADR 0073 — O repositório passa a se chamar one

**Status:** aceito
**Data:** 25/08/2026
**Fase:** 7 — o repositório alcança o nome que a ADR 0067 deu ao produto
**Contexto:** ADR 0067 e ADR 0070 · ADRs 0030 e 0035 do `biahflow/pulse`

## Contexto

A ADR 0067 renomeou o produto para **One** em 24/08/2026, a ADR 0069 levou o nome à tela —
e o repositório continuou se chamando `biahflow/portal-cliente`. É a mesma situação que a
ADR 0070 encontrou nos recursos `cockpit-*` de HML: o nome do meio, sobrevivendo depois de o
produto seguir adiante.

O rename de repositório tem um precedente medido duas vezes no `biahflow/pulse`
(`portal → cockpit` em 19/08, `cockpit → pulse` em 24/08), e o que ele ensina está escrito
no comentário de `infra/terraform/ambientes/hml/variables.tf`: **o redirect do GitHub cobre
clone, push, issues e PRs; a claim `assertion.repository` do token OIDC não** — ela carrega
o nome novo no push seguinte, e toda condição de WIF que nomeia o caminho antigo passa a
recusar o token. No `cockpit → pulse` a lista daqui ficou um dia para trás e o `plan` de
25/08 mostrou a condição do provedor revertendo para um repositório que não existia mais.

Este repositório tem três referências **vivas** ao próprio caminho, todas na federação:
`repositorios_github` e `repositorios_deploy` (espelhos da `repos_allowlist` de
`biahflow/infra`, que desde 17/08 é onde o `apply` do pool roda por CI a cada merge) e
`repositorio_infra` — que é **só deste state**: é a impersonação da `hml-infra`, a conta que
roda o próprio `infra-hml.yml`. A transferência de 17/08 já mediu o modo de falha: o token
do caminho novo passa pela condição do provedor e esbarra na impersonação, e o workflow que
poderia consertar é exatamente o que ficou trancado para fora.

## Decisão

### 1. `biahflow/portal-cliente` vira `biahflow/one`

O nome do produto é o nome do repositório. Variáveis e secrets de repositório
(`WIF_PROVIDER`, `CLOUDFLARE_API_TOKEN`) acompanham o rename; os workflows referem o
caminho por `${{ github.repository }}` e acompanham sozinhos.

### 2. As três referências vivas mudam no mesmo PR, e o caminho antigo sai da lista

`repositorios_github`, `repositorios_deploy` e `repositorio_infra` passam a `biahflow/one`.
O caminho antigo **não** fica na lista durante a transição, pelo argumento que o próprio
comentário do arquivo já tinha escrito em 14/08: mantê-lo autorizaria qualquer repositório
recriado naquele caminho. Mudam junto as duas afirmações vivas fora do Terraform: o
comentário de `cloudflare.tf` que diz qual repositório gerencia a zona, e as duas instruções
operativas do runbook `hml-gcp.md` (onde cadastrar `WIF_PROVIDER` e `CLOUDFLARE_API_TOKEN`)
— a primeira delas ainda mandava olhar `biahflow/portal`, repositório que virou `pulse` há
seis dias, e foi corrigida na passada.

### 3. O espelho em `biahflow/infra` muda em PR pareado

`repos_allowlist` e `deploy_sa_repos` de `envs/hml/wif` são autoritativos para o pool e
aplicam por CI no merge de lá. O PR é preparado na mesma sessão que este, pela razão da
ADR 0070: entre o apply daqui e o merge de lá, qualquer apply do state deles com a lista
atrasada reverte a condição e tranca `biahflow/one` para fora.

### 4. A narrativa histórica não é reescrita

As linhas datadas do runbook (a transferência de 17/08), a ADR 0050, a FDD 025 e sua
evidência continuam dizendo `portal-cliente` onde contam o que aconteceu. É o critério da
ADR 0070, que veio da ADR 0034: corrige-se a afirmação viva, preserva-se a nota histórica.

## Ordem de execução

```text
1. merge deste PR
2. infra-hml.yml com aplicar: true   → provedor e impersonação passam a biahflow/one
3. gh repo rename one                → a claim OIDC volta a casar com a condição
4. merge do PR de biahflow/infra     → o CI de lá aplica e os dois states convergem
5. git remote set-url nos checkouts  → o redirect segura, mas não para sempre
```

A ordem não é preferência: o apply do passo 2 precisa rodar **antes** do rename, porque é
ele que atualiza a impersonação da `hml-infra` — depois do rename, o token novo não passa
pela binding antiga e o `infra-hml.yml` só se consertaria com credencial local. Entre 2 e 3
este repositório não autentica no WIF (janela de minutos, controlada por quem executa);
entre 3 e 4 vale o risco do item 3 acima.

`apply` continua Human Gate: `infra-hml.yml` com `aplicar: true`, humano com o plano na
frente.

## Consequências

- A claim OIDC passa a ser `biahflow/one` e as duas listas (daqui e de `biahflow/infra`)
  concordam. O caminho `biahflow/portal-cliente` fica livre e **não deve ser reocupado**:
  um repositório novo naquele nome herdaria o redirect de quem ainda não atualizou o remote.
- Imagens futuras do `deploy-hml` saem sob `ghcr.io/biahflow/one/*`; os digests já
  publicados sob o caminho antigo continuam endereçáveis, como na ADR 0070.
- Clones existentes seguem funcionando pelo redirect; o passo 5 é higiene, não urgência.
- O que a ADR 0070 deixou aberto continua aberto, agora com terceira ocorrência: **que os
  dois repositórios concordem sobre a federação é conferido a olho.** O que os manteve
  juntos foi de novo um par de PRs escrito na mesma sessão, que não é mecanismo.

## Verificação

- `test_roadmap_index.py` e `test_architecture_doc.py` verdes com a linha desta ADR.
- `terraform fmt -check -recursive` — sem deriva.
- O `plan` de `ambientes/hml` publicado no PR mostra a condição do provedor e a binding da
  `hml-infra` trocando de caminho. **Nenhum `apply` foi executado nesta sessão.**
