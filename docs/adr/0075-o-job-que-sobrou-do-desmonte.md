# ADR 0075 — O job que sobrou do desmonte

**Status:** proposto
**Data:** 26/08/2026
**Fase:** 7 — limpeza de infraestrutura

> **Proposta pendente de gate humano.** Esta ADR registra a decisão e o caminho de
> execução; ela **não** foi aplicada. Nenhum `terraform apply` contra `biahflow-hml`
> nem `gcloud` imperativo foi executado por esta fatia. O estado `proposto` é
> deliberado: quem confirma que `createsuperuser` já não serve é quem o criou, e o
> `apply` é decisão de operação com credencial de nuvem. Descoberto em `biahflow/one#58`.

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

**Apagar o job, por caminho declarativo — não declará-lo permanentemente.**

O critério é uso e não estética. `createsuperuser --noinput` cria o **primeiro** admin de
um ambiente; é operação de inauguração, de uso único, e não roda em workflow nenhum. Os
dois trabalhos que têm casa permanente em `local.trabalhos` (`servicos.tf`) rodam a cada
deploy porque o deploy precisa deles: `pulse-migrate` (o deploy para se o schema não subir)
e `pulse-check` (`check_integrations`). `createsuperuser` não tem essa recorrência — dar-lhe
uma linha em `local.trabalhos` seria criar casa permanente para um recurso que roda uma vez
por vida de ambiente, e ainda herdaria a imagem `pulse-api` sem que nada exercitasse a herança.

A alternativa **(a) declarar** como `pulse-createsuperuser` foi considerada e recusada:
- ela conserta o nome mas mantém em produção contínua um recurso sem gatilho, que é o
  oposto do que a linha de `local.trabalhos` documenta ("trabalhos que começam e terminam"
  e são invocados por deploy);
- se um dia o produto precisar recriar o admin inaugural, o comando é `gcloud run jobs
  execute` sobre a `pulse-api` já publicada, ou um job efêmero — não um recurso permanente
  no state.

O que **não** é aceitável (fora de escopo, e escrito aqui para não ser tentado): apagar por
`gcloud run jobs delete` imperativo. Um recurso que saiu do IaC não volta ao IaC por um
comando fora dele; ele sai **pelo mesmo mecanismo** que criaria qualquer outro — o plano
revisado.

## O caminho declarativo de exclusão (procedimento, não aplicado)

O job está fora do state e o módulo `modulos/job` é `for_each` sobre `local.trabalhos` com
`deletion_protection = true` por padrão. Logo, apagar declarativamente é **adotar e então
destruir**, em dois `apply` revisados. Ambos são gate humano com credencial de `biahflow-hml`
e não foram executados.

**Passo 1 — adotar para o state (`import`).** Em `ambientes/hml-biahflow`, acrescentar
temporariamente a entrada ao mapa e um bloco `import` que a case com o recurso existente.
A entrada precisa carregar `protegido = false`, senão o `destroy` do Passo 2 é recusado pela
trava do módulo (que hoje o `module "trabalhos"` não repassa — ver *Consequências*):

```hcl
# temporário, some no Passo 2
import {
  to = module.trabalhos["cockpit-createsuperuser"].google_cloud_run_v2_job.job
  id = "projects/biahflow-hml/locations/us-east1/jobs/cockpit-createsuperuser"
}
```

`terraform plan` deve mostrar **import** (e nenhuma recriação; a divergência de imagem é
absorvida pelo `ignore_changes` do módulo). Revisar e `apply`.

**Passo 2 — destruir.** Remover a entrada do mapa e o bloco `import`. `terraform plan` deve
mostrar exatamente **um** `destroy` — o `google_cloud_run_v2_job.job` daquela instância — e
nada mais. Revisar e `apply`.

## Consequências

- O job sai do ambiente pelo plano revisado, satisfazendo o guardrail que o criou à mão
  violava.
- `gcloud run jobs list` em `biahflow-hml` deixa de devolver qualquer coisa com prefixo
  `cockpit-` — o critério (4) da issue.
- **Uma lacuna medida no módulo:** `module "trabalhos"` (`ambientes/hml-biahflow/main.tf`)
  **não repassa** `protegido` às instâncias, então elas herdam o default `true`. Para o
  Passo 2 destruir, ou o módulo passa a aceitar `protegido` por entrada do mapa (aditivo,
  simétrico ao que `modulos/servico-cloudrun` já discute), ou o `apply` do Passo 2 roda com
  a trava rebaixada só para aquela instância. A primeira forma é a preferível e fica
  registrada como o ajuste que o procedimento exige; ela é mudança de infraestrutura
  revisada, não deste documento.
- Nada de estado se perde: o job não tem estado, e o admin que ele criou uma vez continua
  existindo no banco de `biahflow-hml` independentemente do job.

## O que fica aberto

- A confirmação de que `createsuperuser` já não é necessário é de quem o criou. Se a resposta
  for "ainda preciso recriar o admin às vezes", a decisão muda para um job **efêmero
  documentado no runbook**, não para uma casa permanente no state — e isso seria emenda a
  esta ADR, não silêncio.
- A execução dos dois `apply` e o ajuste de `protegido` no módulo são gate humano de operação.
