# ADR 0075 — O job que sobrou do desmonte

**Status:** aceito
**Data:** 26/08/2026 (proposta) · decisão revista e aceita em 27/08/2026
**Fase:** 7 — limpeza de infraestrutura

> **Decisão revista antes do aceite.** A versão de 26/08/2026 deste documento propunha
> apagar `cockpit-createsuperuser` sem lhe dar casa permanente — a opção (b) da Issue
> `biahflow/one#58`. Ela mesma deixava em aberto quem poderia mudar isso: *"a confirmação
> de que `createsuperuser` já não é necessário é de quem o criou"*. Em 27/08/2026, Daniel
> Campos — quem criou o job à mão em 20/08/2026, e portanto exatamente quem aquela frase
> apontava — decidiu o oposto do proposto: declarar o job permanentemente, como
> `pulse-createsuperuser`, herdando o ambiente da `pulse-api` como os outros dois
> trabalhos. Isso vai além do próprio recuo que a versão anterior previa (que cogitava, no
> máximo, um job **efêmero** documentado em runbook) — e por isso é emenda a esta ADR, e
> não silêncio, como aquele parágrafo já antecipava. A proposta de 26/08 e sua análise
> ficam preservadas, na íntegra, na seção **Proposta original (26/08/2026), superada**, ao
> final. **Nenhum `terraform apply` contra `biahflow-hml` nem `gcloud` imperativo foi
> executado por esta fatia** — criar `pulse-createsuperuser` e remover
> `cockpit-createsuperuser` continuam sendo `apply`s revisados, gate humano de operação
> com credencial de nuvem. Descoberto em `biahflow/one#58`.

## Contexto

`biahflow-hml/us-east1` tem um Cloud Run job chamado `cockpit-createsuperuser` que
**nenhum Terraform declara**. Foi criado à mão por credencial de pessoa
(`daniel@biahflow.ai`, não CI) em 2026-08-20, roda `python manage.py createsuperuser
--noinput`, e aponta para a imagem `us-east1-docker.pkg.dev/biahflow-hml/hml/cockpit-api`
por tag imutável.

Conferido contra `gs://biahflow-hml-tfstate/ambientes/hml-biahflow/default.tfstate`
(serial 24): o state gerencia **8 recursos, todos `pulse-*`**. `createsuperuser` não
aparece. Ele sobrou visível no desmonte dos `cockpit-*` (PRs #51, #56, #57 e a ADR 0070):
o apply final destruiu os sete recursos gerenciados e este ficou — porque o Terraform
nunca soube dele.

A ironia é o argumento. A investigação que originou o desmonte (`biahflow/pulse#34`)
começou afirmando que os recursos do CRM tinham sido criados à mão e estavam fora do IaC;
**aquilo era falso** — estavam todos declarados. A afirmação só é verdadeira para este
sexto recurso, que ninguém tinha olhado e que só apareceu quando os outros saíram da frente.

São dois problemas, e o segundo é o que importa:

1. **O nome.** Carrega o prefixo `cockpit-`, que a ADR 0070 aposentou. Cosmético.
2. **Não é declarado.** Este é o real, e viola o guardrail de infraestrutura
   (`docs/engineering-os/core/guardrails/infrastructure.md`): recurso que um provider
   Terraform sabe gerenciar deve ser provisionado por configuração versionada, com `plan`
   revisado. Ele referencia a imagem `cockpit-api`, que **deixou de ser publicada** no
   rename (o registro recebe `pulse-api` desde 25/08). A tag imutável ainda existe, então
   não quebrou — mas está congelado num artefato antigo e ninguém é notificado disso.

## Decisão

**Declarar `pulse-createsuperuser` permanentemente, e apagar `cockpit-createsuperuser` por
caminho declarado.** É a opção (a) da Issue, e o critério que a decide não é mais
recorrência de uso — é ter o comando de criação do primeiro admin sob controle de versão,
com o mesmo nome e o mesmo ambiente dos outros cinco recursos deste produto, em vez de
depender de alguém lembrar o `gcloud` certo na próxima vez que um ambiente precisar de um
admin inaugural. Foi exatamente a ausência dessa casa que produziu este job sem Terraform
saber, em 20/08/2026; não lhe dar uma permanente deixaria o mesmo buraco aberto para a
próxima vez.

### 1. `pulse-createsuperuser` entra em `local.trabalhos`

```hcl
pulse-createsuperuser = {
  servico = "pulse-api"
  comando = ["python", "manage.py", "createsuperuser", "--noinput"]
}
```

Ao contrário de `pulse-migrate` (o deploy para se o schema não subir) e `pulse-check`
(`check_integrations`, que valida integrações a cada deploy), este trabalho **não é
invocado por workflow de deploy nenhum** — `createsuperuser --noinput` cria o admin
inaugural de um ambiente, não algo que se repete a cada publicação de imagem. Ele herda a
imagem, as variáveis e os segredos da `pulse-api` pela mesma razão que os outros dois:
`local.trabalhos` existe para não manter uma segunda verdade sobre o mesmo ambiente.

### 2. `cockpit-createsuperuser` sai do ambiente pelo plano revisado

Nenhuma rota imperativa: o job saiu do IaC uma vez (nunca esteve nele) e não volta a sair
dele por um comando fora do Terraform — ele sai pelo mesmo mecanismo que o criaria, na
forma da ADR 0070. Como o recurso real não está em nenhum state, "apagar por caminho
declarado" significa **primeiro reconciliar a deriva** (importar para a configuração o
que foi criado por fora, como o guardrail de infraestrutura exige) e só então remover —
não um simples `terraform destroy`, que não alcançaria um recurso que o Terraform
desconhece. O procedimento exato está na seção seguinte.

### 3. A imagem `cockpit-api` não é reintroduzida

`pulse-createsuperuser` referencia `local.imagem["pulse-api"]`, como qualquer outro
trabalho — nunca a imagem `cockpit-api` congelada que o job antigo carrega. O rename da
ADR 0070 não é revertido por este job.

## O caminho declarado (procedimento, não aplicado)

`cockpit-createsuperuser` está fora do state; `module "trabalhos"` (`main.tf`) é `for_each`
sobre `local.trabalhos`, e `modulos/job` nasce com `deletion_protection = true`. Logo, tirar
o job antigo do ambiente por caminho declarado exige **adotar e então destruir**, em
`apply`s distintos e revisados — o mesmo procedimento que a proposta de 26/08 já havia
desenhado para a exclusão, agora executado depois (e ao lado) da criação do
`pulse-createsuperuser` permanente. Nenhum dos dois passos abaixo foi executado; ambos são
gate humano com credencial de `biahflow-hml`.

**Passo 0 — declarar o novo job.** Este PR acrescenta `pulse-createsuperuser` a
`local.trabalhos` (seção anterior). `terraform plan` em `ambientes/hml-biahflow` deve
mostrar um único `create`: `module.trabalhos["pulse-createsuperuser"].google_cloud_run_v2_job.job`.
Revisar e `apply` — independente dos passos 1 e 2, e sem risco: é recurso novo.

**Passo 1 — adotar o job antigo para o state (`import`).** O endereço deriva do mesmo
`module "trabalhos"` e do seu `for_each`: a chave é o nome atual do recurso na nuvem,
`cockpit-createsuperuser` (não `pulse-createsuperuser` — o `for_each` casa por chave do
mapa, e a chave tem de ser a do recurso que existe). Acrescentar **temporariamente** a
`local.trabalhos` uma entrada com essa chave — o conteúdo de `servico`/`comando` é
irrelevante para o import em si, pois `terraform import` só associa endereço a ID; ele não
lê nem grava argumentos — e então:

```bash
terraform -chdir=infra/terraform/ambientes/hml-biahflow import \
  'module.trabalhos["cockpit-createsuperuser"].google_cloud_run_v2_job.job' \
  projects/biahflow-hml/locations/us-east1/jobs/cockpit-createsuperuser
```

(Um bloco `import {}` declarativo, no formato que a proposta de 26/08 registrava, é
equivalente — Terraform ≥ 1.9 aceita as duas formas. O ID, `projects/{projeto}/locations/
{região}/jobs/{nome}`, é o formato de import do provider Google para
`google_cloud_run_v2_job`.)

`terraform plan` a seguir deve mostrar **só** a divergência que o `lifecycle.ignore_changes`
do módulo já absorve (a imagem `cockpit-api`, e `client`/`client_version`) — nenhum
`create` nem `destroy`. Revisar e, se o plano estiver limpo além do ignorado, não é
necessário `apply` (import já escreveu o state); se houver diferença não absorvida,
decidir e aplicar antes de prosseguir.

**Passo 2 — remover a entrada temporária e destruir.** Remover do `servicos.tf` a entrada
`cockpit-createsuperuser` acrescentada no Passo 1 (ela nunca é permanente — o par
create/import+destroy não coexiste com uma terceira entrada "cockpit" viva). Com a
configuração assim, `terraform plan` deve mostrar exatamente **um** `destroy`:
`module.trabalhos["cockpit-createsuperuser"].google_cloud_run_v2_job.job`, e nada mais —
é essa remoção de configuração que produz o `destroy` no plano, e não um `terraform state
rm` (que apenas desvincularia o recurso do state sem apagá-lo na nuvem, deixando o job
órfão e falhando o critério de aceite "`gcloud run jobs list` não devolve mais nada com
prefixo `cockpit-`"). Revisar o plano e `apply`.

**Bloqueio conhecido no Passo 2, herdado da proposta de 26/08:**
`module "trabalhos"` não repassava `protegido` às instâncias de `modulos/job`, que por isso
herdavam o default `true`. Com `deletion_protection = true`, o provider recusa o `destroy`
do Passo 2 antes mesmo de chegar à nuvem. Resolver isso era mudança de infraestrutura própria
— `main.tf` passaria a repassar `protegido = try(each.value.protegido, true)` a
`module "trabalhos"`, aditiva e simétrica ao que `modulos/servico-cloudrun` já discute — e
ficou **fora do escopo desta fatia**: é ajuste de módulo, não uma entrada em
`local.trabalhos`. Sem ele, o Passo 2 pararia no `apply`, não no `plan`.

> **Atualização (27/08/2026):** esse ajuste **foi feito** e mergeado no PR #78 —
> `main.tf` agora repassa `protegido = try(each.value.protegido, true)`. O Passo 2
> deixa de ter bloqueio de configuração; resta apenas declarar `protegido = false`
> na entrada temporária `cockpit-createsuperuser` do Passo 1 para que o provider
> aceite o `destroy`. Ver a **Emenda (27/08/2026)** ao final.

## Consequências

- `pulse-createsuperuser` some da lista de "criado à mão fora do IaC" pela primeira vez
  desde 20/08/2026 — ele nasce sob Terraform, com `plan` revisado desde o primeiro
  `create`.
- `cockpit-createsuperuser` sai do ambiente pelo plano revisado (Passo 1 + Passo 2),
  satisfazendo o guardrail que ele violava ao ter sido criado à mão.
- `gcloud run jobs list` em `biahflow-hml` deixa de devolver qualquer coisa com prefixo
  `cockpit-` — o critério (4) da issue — uma vez que o Passo 2 seja aplicado.
- ~~**A lacuna do módulo permanece medida e não resolvida** (ver bloqueio acima): o Passo 2
  não pode ser aplicado com sucesso até `module "trabalhos"` aceitar `protegido` por
  entrada.~~ **Resolvida em 27/08/2026 pelo PR #78** — `module "trabalhos"` passou a repassar
  `protegido = try(each.value.protegido, true)`. Como a proposta observava, isto valia
  independentemente de qual opção (a ou b) fosse escolhida — era consequência de destruir
  *qualquer* job hoje, não desta decisão específica; por isso saiu em fatia própria. Ver a
  **Emenda (27/08/2026)** ao final.
- Nada de estado se perde: o job antigo não tem estado, e o admin que ele criou uma vez
  continua existindo no banco de `biahflow-hml` independentemente do job em si.
- Há janela em que os dois jobs coexistem irregularmente durante os passos 0–2 (o novo já
  criado, o antigo ainda não destruído) — sem efeito prático, porque nenhum dos dois é
  invocado por workflow algum; a ordem entre os passos não é sensível a corrida.

## O que fica aberto

- ~~O ajuste em `module "trabalhos"` para repassar `protegido` por entrada do mapa —
  necessário para o Passo 2 ter sucesso — é mudança de infraestrutura revisada própria,
  não desta fatia.~~ **Fechado pelo PR #78 (27/08/2026)** — ver a Emenda abaixo.
- A execução dos três `apply`s (Passo 0, Passo 1, Passo 2) é gate humano de operação com
  credencial de `biahflow-hml`. **É tudo o que resta** para satisfazer o critério (4) da
  issue; nenhum deles foi executado aqui.

## Emenda (27/08/2026) — o Passo 2 foi destravado pelo #78

*Aditiva à decisão aceita acima; não a reescreve. Registrada quando o único bloqueio
técnico que a ADR deixava em aberto foi resolvido em fatia própria.*

A decisão de 27/08 deixou dois itens em aberto: (1) o repasse de `protegido` por
`module "trabalhos"`, sem o qual o `destroy` do Passo 2 é recusado pelo provider antes de
chegar à nuvem; e (2) os três `apply`s de operação. O item (1) **saiu em fatia própria e
está mergeado (PR #78)**: `main.tf` repassa `protegido = try(each.value.protegido, true)`,
mantendo o default `true` do módulo — desproteger passa a ser ato explícito, escrito por
entrada do mapa.

O efeito no procedimento é local e não reabre a decisão:

- **Passo 0** (criar `pulse-createsuperuser`) e **Passo 1** (`import` do job antigo) são
  inalterados.
- **Passo 2** deixa de ter bloqueio de configuração. Para o `destroy` ser aceito, a entrada
  temporária `cockpit-createsuperuser` do Passo 1 declara `protegido = false` no mapa; o
  `terraform plan` então mostra exatamente um `destroy` e nada mais.

O que **não** mudou: os três `apply`s contra `biahflow-hml` seguem sendo gate humano de
operação com credencial de nuvem, não executados por esta fatia nem pela do #78. O critério
(4) da issue (`gcloud run jobs list` sem prefixo `cockpit-`) só é satisfeito quando o
operador aplica o Passo 2.

## Proposta original (26/08/2026), superada

*Preservada como registro do que foi considerado e por quê — não como afirmação vigente.
A decisão em vigor é a das seções acima.*

> **Decisão original:** Apagar o job, por caminho declarativo — não declará-lo
> permanentemente.
>
> O critério era uso e não estética. `createsuperuser --noinput` cria o **primeiro** admin
> de um ambiente; é operação de inauguração, de uso único, e não roda em workflow nenhum.
> Os dois trabalhos que têm casa permanente em `local.trabalhos` (`servicos.tf`) rodam a
> cada deploy porque o deploy precisa deles: `pulse-migrate` (o deploy para se o schema não
> subir) e `pulse-check` (`check_integrations`). `createsuperuser` não tinha essa
> recorrência — dar-lhe uma linha em `local.trabalhos` criaria casa permanente para um
> recurso que roda uma vez por vida de ambiente, e ainda herdaria a imagem `pulse-api` sem
> que nada exercitasse a herança.
>
> A alternativa **(a) declarar** como `pulse-createsuperuser` foi considerada e recusada
> naquele momento:
> - ela conserta o nome mas mantém em produção contínua um recurso sem gatilho, o oposto do
>   que a linha de `local.trabalhos` documenta ("trabalhos que começam e terminam" e são
>   invocados por deploy);
> - se um dia o produto precisasse recriar o admin inaugural, o comando seria `gcloud run
>   jobs execute` sobre a `pulse-api` já publicada, ou um job efêmero — não um recurso
>   permanente no state.
>
> O que não seria aceitável (fora de escopo, e escrito para não ser tentado): apagar por
> `gcloud run jobs delete` imperativo.
>
> **O que fica aberto, na versão original:** a confirmação de que `createsuperuser` já não
> é necessário é de quem o criou. Se a resposta for "ainda preciso recriar o admin às
> vezes", a decisão muda para um job efêmero documentado no runbook, não para uma casa
> permanente no state — e isso seria emenda a esta ADR, não silêncio.
>
> *(Esta última frase é a que a emenda de 27/08/2026, no topo do documento, invoca — com uma
> resposta mais forte do que a que ela previa: não um job efêmero, e sim uma casa
> permanente.)*
