# FDD — Backup e restore

Fase 5, ADR 0019.

## Objetivo e não objetivos

**Objetivo.** Que exista um backup do Postgres e dos objetos do storage que se
possa restaurar, e que a restauração seja **provada** — não só as linhas de volta,
mas as garantias: RLS de pé, GRANT de coluna ainda de coluna, uma organização sem
ver a outra.

**Não objetivos.** Backup contínuo (WAL archiving / PITR)
e replicação: pertencem ao item de homologação do roadmap, que é quando existirá
um ambiente com janela de recuperação declarada. Backup automatizado do realm do
Keycloak: o runbook nomeia o `kc.sh export` e diz por que ele é obrigatório, sem
automatizá-lo.

*Corrigido em 06/08/2026 (ADR 0035): este parágrafo abria listando "job de CI recorrente" como
não-objetivo, afirmando que "nada o executa a cada push ainda". O job `backup-restore` existe no
`.github/workflows/ci.yml` desde a ADR 0019, sem `if:` restritivo — roda a cada push e a cada PR —,
e o comentário que o antecede diz textualmente ser "o job que a **FDD 013** pediu e não existia".
A linha ficou descrevendo como futuro algo que já era passado, e quem a lesse para saber a
cobertura de CI do par backup/restore concluiria o contrário do que é verdade.*

## Jornada e interface

Nenhuma superfície do cliente muda. Não há tela, e **não há rota** — a mesma regra
que a ADR 0017 aplicou ao expurgo, pelo mesmo motivo: um endpoint capaz de devolver
o bucket inteiro seria um caminho de requisição capaz de ler dado de todo tenant de
uma vez.

A jornada é de operação, pela linha de comando:

```bash
./scripts/backup.sh                                  # cifrado (exige a chave)
./scripts/restore.sh backups/<ts> --database ensaio  # noutro banco, nunca no atual
```

E é o runbook `docs/runbooks/backup-restore.md` que descreve o resto: o que fazer
com o material de chave que não está no dump, como reexecutar os expurgos que o
restore desfaz, e por que a retenção do backup não pode exceder a da organização.

## Dados, API e permissões

- **Sem migração e sem modelo novo.** Nada é gravado por esta fatia.
- **Sem papel novo.** O backup usa os que já existem, e a escolha é a decisão:
  o dump sob `portal_migrator` (dono, isento da RLS), o censo sob `portal_system`
  (BYPASSRLS), e o `roles.sql` sob o superusuário do cluster. `portal_app` **não
  consegue** tirar backup, e é isso que se testa.
- `infra/postgres/bootstrap/roles.sql` passou a criar `btree_gist` e a fixar
  `WITH SCHEMA public` nas duas extensões. Correção de um defeito latente: a
  extensão veio da migração 0010 e um restore não roda migrações.
- `storage.py` ganhou `iter_keys` e `fetch_object` — leitura, nada mais.

## Estados de erro e segurança

- **Sem chave, sem backup.** `BACKUP_AGE_RECIPIENT` ausente aborta em vez de
  gravar texto claro (`--allow-plaintext` é explícito e vai no log). Mesma regra do
  scanner da ADR 0017.
- **Censo zerado aborta.** Um backup cujo censo soma zero linhas falha alto, porque
  é indistinguível de um backup tirado com a credencial errada.
- **Digest antes do banco.** O `restore.sh` confere o SHA-256 do dump contra o
  manifesto antes do primeiro `CREATE DATABASE`.
- **Objeto corrompido não volta ao bucket.** SHA-256 por objeto no índice do tar;
  divergência recusa o restore inteiro em vez de gravar o arquivo.
- **Chave de tar validada.** Nome de membro que não é uma chave de tenant
  (`/…`, `../`, vazio) é recusado — a ameaça não é travessia de caminho, já que
  nada é extraído para disco, e sim gravar sob uma chave que o expurgo por prefixo
  nunca alcançaria.
- **O que a cifra não cobre.** `AGENT_KEY_PEPPER` e `DRIVE_TOKEN_ENCRYPTION_KEY`
  não estão no dump; guardados junto dele, cifrá-lo seria teatro.
- **O restore desfaz expurgos.** Listados ao final, por `completed_at` posterior ao
  `taken_at` — possível porque a linha do pedido sobrevive ao próprio expurgo.

## Telemetria e critérios de aceite

Eventos nomeados, no formato da ADR 0018: `backup.objects.dumped`,
`backup.objects.restored`, `backup.objects.rejected`. O limiar de alerta
("último backup bem-sucedido há mais de 26 horas") está em
`docs/runbooks/alerts.md`.

Aceite:

1. Um backup tirado com a credencial de requisição **não acontece** — e, quando
   forçado a acontecer, é detectado como vazio.
2. Um backup restaurado num banco limpo tem as mesmas policies, os mesmos GRANTs
   de coluna e o mesmo censo de linhas que a origem.
3. No banco restaurado, uma pessoa da organização A vê A e não vê B; sem contexto
   nenhum, vê zero linhas.
4. Um backup adulterado é recusado antes de qualquer banco ser tocado.
5. Um objeto corrompido não volta ao storage.

## Testes e avaliações de IA

`apps/api/tests/test_backup_restore.py`, treze casos. Os do storage rodam sem rede
e sem banco (o `fake_storage` do `conftest`); os do Postgres são de integração e
pulam sozinhos quando não há banco alcançável **ou** quando o `pg_dump` da máquina
é mais antigo que o servidor — nesse caso `PSQL`/`PG_DUMP`/`PG_RESTORE` apontam
para o binário do contêiner, como o runbook mostra.

Os dois que carregam o resto:

- `test_the_request_credential_cannot_take_a_backup` — prova a recusa **e** prova
  que a flag que a cala devolve um dump de sucesso com zero linhas.
- `test_the_restored_database_still_isolates_one_tenant_from_another` — arranja
  duas organizações antes do backup, porque o seed local tem membros numa só e um
  teste de fronteira sem segunda organização passa por não ter o que separar.

Sem avaliações de IA: esta fatia não toca prompt, retriever, modelo nem ferramenta.
