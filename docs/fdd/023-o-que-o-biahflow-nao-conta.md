# FDD — O que o Biahflow não conta ao portal

Fase 6, ADR 0037. Emenda na ADR 0003 do Biahflow.

## Objetivo e não objetivos

**Objetivo.** Fechar as duas coisas que acontecem no Biahflow e não chegavam ao portal: mexer no
roster de funcionários digitais (que não emitia webhook nenhum) e apagar um projeto de vez (que
não emitia, e que o snapshot não tem como declarar depois de acontecer). O cliente deixa de ver um
time digital desatualizado e um projeto morto marcado como ativo.

**Não objetivos.** **Emitir na exclusão de filho**: a medição mostra que ela não é alcançável pelo
produto — a API arquiva, o Django admin não registra entidade de projeto e a retenção só toca linha
já arquivada. **Apagar do portal o que o Biahflow apagou**: o histórico é a evidência das citações
já dadas (ADR 0017), e apagar tenant é decisão de pessoa, executada pelo worker, nunca por rota
HTTP — e um webhook não é exceção. **Esconder o projeto removido do cliente**: mesmo argumento da
FDD 019. **Reconciliar projeto que morreu sem aviso**: se o `deleted` se perder, a linha fica
marcada como viva; a varredura periódica que consertaria isso é fatia própria.

## Jornada e interface

**O roster.** Alguém cadastra um funcionário digital no Biahflow, muda o KPI dele ou o arquiva. O
webhook sai na hora, o portal refaz o snapshot e o painel "Seu Time Digital" do cliente concorda
com a fonte. Antes, nada disso emitia: a mudança só chegava de carona no próximo salvamento de
outra coisa naquele projeto, e o arquivamento — que tira a linha do snapshot — era o mais
silencioso dos três.

**A exclusão.** Alguém apaga o projeto no Biahflow (shell ou migração de dados; a interface
arquiva). O webhook sai com `event: "deleted"`, o portal marca `source_deleted_at` **sem buscar
snapshot** — não há mais snapshot — e, na próxima vez que o cliente abre o portal:

- o cartão de status ganha o selo **"Projeto removido na origem"**, no mesmo lugar e com o mesmo
  cinza neutro do selo de encerramento;
- o chat troca o campo de pergunta por *"Este projeto foi removido no Biahflow. O histórico
  continua disponível para consulta, mas não é possível fazer novas perguntas."*;
- o fio de comentário de cada pendência abre para leitura, sem o campo de escrita.

Se o projeto já estava encerrado, é a frase da remoção que aparece — o estado mais forte vence, na
mesma ordem que a API usa para escolher o `detail` do 409.

Todo o resto continua funcionando: cronograma, documentos, reuniões, pendências, resultados, busca
e download.

## Critérios de aceite

| # | Critério |
|---|---|
| 1 | Salvar um `DigitalEmployee` no Biahflow emite `("updated", "digital_employee", project_id)` |
| 2 | Arquivar um `DigitalEmployee` emite também — é `save()`, e é o caso mais silencioso |
| 3 | Apagar um projeto no Biahflow emite `("deleted", "project", id)` **uma vez**, mesmo com filhos |
| 4 | O webhook `deleted`/`project` **não** busca snapshot |
| 5 | Ele grava `source_deleted_at` e responde `{"status": "deleted", …}` |
| 6 | Reentrega do mesmo webhook não move a data — a primeira observação é a verdadeira |
| 7 | Um id que o portal nunca viu responde `unknown_project` e **não cria** projeto |
| 8 | `sync_snapshot` não limpa `source_deleted_at` |
| 9 | `POST /api/v1/chat` responde **409** com `detail = "Project deleted at source"` |
| 10 | `POST /api/v1/me/pendings/{id}/comments` responde 409 no mesmo caso |
| 11 | Quem **não** tem vínculo continua recebendo **404**, nunca 409 |
| 12 | Com as duas datas preenchidas, o 409 e a tela usam o motivo da remoção |
| 13 | A leitura continua 200, e o dashboard traz `source_deleted_at` |
| 14 | Um webhook antigo (`updated`, ou sem `event`) continua sincronizando como sempre |

## Telemetria

| Evento | Quando | `extra` |
|---|---|---|
| `biahflow.project_deleted` | O Biahflow avisou que apagou o projeto de vez | `biahflow_project_id`, `project_id`, `marked` |

Limiar em `runbooks/alerts.md`: **qualquer ocorrência**, porque exclusão não tem volta do outro
lado — se foi engano, o read model do portal é a única cópia que sobrou. `marked` acima de 1
significa que o mesmo projeto do Biahflow existe em duas organizações daqui, o que só acontece se
ele tiver mudado de cliente lá.

Não há evento para o roster: ele é uma sincronização como as outras, e um evento por webhook de
funcionário digital seria ruído.

## Testes

| Teste | O que prova |
|---|---|
| `test_saving_digital_employee_emits_webhook` (Biahflow) | Critérios 1 e 2 |
| `test_deleting_a_project_emits_once_even_with_children` (Biahflow) | Critério 3, e o desenho de não ter `post_delete` nos filhos |
| `test_o_webhook_de_exclusao_marca_o_projeto_sem_buscar_snapshot` | Critérios 4, 5, 6 e 13 |
| `test_o_webhook_de_exclusao_de_projeto_desconhecido_nao_cria_nada` | Critério 7 |
| `test_o_sync_nao_desfaz_a_exclusao` | Critério 8 |
| `test_o_projeto_apagado_na_origem_recusa_escrita_e_diz_qual_motivo` | Critérios 9 e 13 |
| `test_encerrado_e_apagado_juntos_recusam_pelo_motivo_mais_forte` | Critério 12, lado da API |
| `test_quem_nao_tem_vinculo_leva_404_mesmo_no_projeto_encerrado` | Critério 11, nos dois motivos |
| `test_webhook_syncs_new_object_types` | Critério 14 — o caminho de sempre não mudou |
| `rendered-html.test.mjs` | O selo, a frase por motivo e o critério 12 na tela |

## Casos de eval de IA

Nenhum. A fatia não muda prompt, recuperador, modelo nem ferramenta — como na FDD 019, ela
**impede** o chat de ser chamado, antes de qualquer coisa de IA acontecer.

## Riscos

**Um `deleted` perdido é definitivo.** A entrega é best-effort e sem retentativa, e não haverá
evento seguinte daquele projeto porque não há mais projeto. Um `updated` perdido o próximo
salvamento corrige; este não. Aceito nesta fatia, com a varredura de reconciliação registrada como
aberta na ADR.

**Um projeto removido continua visível ao cliente.** É a decisão, não um efeito colateral — mas
significa que quem quiser tirá-lo da tela precisa passar pelo apagamento em `/admin/organizacao`,
que é mais forte do que o caso pede.

**Mexer no roster passa a gerar webhook.** Uma edição em massa de funcionários digitais (que hoje
não existe na interface de lá) provocaria um snapshot por linha. Se ela existir um dia, o guarda é
o mesmo `if created: return` que a jornada usa.
