# FDD — O projeto encerrado

Fase 6, ADR 0036.

## Objetivo e não objetivos

**Objetivo.** Que arquivar um projeto no Biahflow chegue ao portal, e que o cliente veja um
projeto encerrado marcado como encerrado — com o histórico inteiro disponível e a escrita
fechada. Até aqui o portal continuava mostrando o projeto como ativo enquanto durasse o
arquivamento.

**Não objetivos.** **Esconder o projeto do cliente**: tirar do alcance o histórico de um projeto
encerrado tornaria impossível conferir uma resposta antiga, que é o argumento da ADR 0017 para o
documento sobreviver ao expurgo por idade. **Apagar qualquer coisa**: o portal não apaga por
conta própria, e o encerramento não é apagamento — restaurar no Biahflow tem de trazer tudo de
volta. **Arquivamento originado no portal**: não existe e não deve existir; quem encerra projeto
é o Biahflow (ADR 0006/0008). **Hard delete**: o Biahflow não tem `post_delete` nenhum, então
exclusão definitiva não avisa — registrado como tropeço, é fatia própria. **Item arquivado
individualmente**: já funcionava nos dois sentidos antes desta fatia, e continua.

## Jornada e interface

Alguém arquiva o projeto no Biahflow. O webhook chega, o portal grava `archived_at`, e na próxima
vez que o cliente abre o portal:

- o cartão de status ganha o selo **"Projeto encerrado"**, ao lado da saúde e não no lugar dela —
  um projeto pode terminar "No prazo", e as duas informações respondem perguntas diferentes;
- o chat troca o campo de pergunta por *"Este projeto foi encerrado. O histórico continua
  disponível para consulta, mas não é possível fazer novas perguntas."* — o histórico de
  conversas acima permanece inteiro;
- o fio de comentário de cada pendência abre normalmente para leitura, sem o campo de escrita.

Todo o resto — cronograma, documentos, reuniões, pendências, resultados, busca, download de
documento — continua funcionando igual.

Restaurar no Biahflow desfaz tudo isso sozinho, no próximo webhook.

## Critérios de aceite

| # | Critério |
|---|---|
| 1 | Arquivar o projeto no Biahflow responde 200 no webhook e grava `archived_at` no portal |
| 2 | O snapshot de um projeto arquivado responde **200** com `archived_at` preenchido, e não 404 |
| 3 | O histórico vem inteiro no snapshot do projeto arquivado (marcos, documentos, reuniões, pendências) |
| 4 | `POST /api/v1/chat` responde **409** para quem tem vínculo com um projeto encerrado |
| 5 | `POST /api/v1/me/pendings/{id}/comments` responde **409** no mesmo caso |
| 6 | Quem **não** tem vínculo continua recebendo **404** no projeto encerrado — nunca 409 |
| 7 | A leitura continua respondendo 200, e o dashboard traz `archived_at` |
| 8 | Restaurar no Biahflow devolve `archived_at` a `NULL` e reabre as escritas |
| 9 | Um snapshot **sem** a chave `archived_at` (Biahflow anterior) sincroniza como ativo |
| 10 | `status` não é sobrescrito pelo arquivamento — encerrado e "em implementação" coexistem |

## Telemetria

| Evento | Quando | `extra` |
|---|---|---|
| `biahflow.snapshot_missing` | O Biahflow avisou de um projeto e respondeu 404 no snapshot | `biahflow_project_id` |

Limiar em `runbooks/alerts.md` (5 em 1 h). Não há evento para o arquivamento em si: ele é um
estado do read model, visível em `project.archived_at`, e um evento por sincronização de projeto
encerrado seria ruído a cada webhook.

## Testes

| Teste | O que prova |
|---|---|
| `test_snapshot_serve_projeto_arquivado_declarando_o_arquivamento` (Biahflow) | Critérios 2, 3 e 8, mais o 404 continuando a significar "não existe" |
| `test_sync_carrega_o_arquivamento_do_biahflow_nos_dois_sentidos` | Critérios 1, 8, 9 e 10 |
| `test_o_projeto_encerrado_recusa_escrita_com_409_e_nao_com_404` | Critérios 4 e 7 |
| `test_quem_nao_tem_vinculo_leva_404_mesmo_no_projeto_encerrado` | Critério 6 — a metade que erraria em silêncio |
| `test_openapi_contract.py` | O 409 declarado, e nenhum 403 |
| `rendered-html.test.mjs` | O selo na tela |

## Casos de eval de IA

Nenhum. Esta fatia não muda prompt, recuperador, modelo nem ferramenta — ela **impede** o chat de
ser chamado num projeto encerrado, antes de qualquer coisa de IA acontecer. A política de
`docs/ai/eval-dataset.md` não é acionada.

## Riscos

**Uma pergunta em projeto encerrado consome janela de taxa antes de ser recusada**, porque
`chat_limit.consume` roda fora da transação e antes de haver projeto (ADR 0021). É o mesmo preço
que o 404 já pagava, e a tela não oferece o campo — só chega aqui quem chama a API direto.

**O 409 é código novo nesta API.** Um cliente gerado a partir do esquema antigo o trata como erro
genérico. Aceito: a alternativa era reusar 404, que corromperia o significado da única resposta
que a regra 6 verifica.
