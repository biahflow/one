# ADR 0066 — O `drop_column` que nenhum portão veria

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e a sexta ADR aceita neste dia, depois da 0061, da 0062, da 0063, da 0064 e da 0065

## Contexto

O `AGENTS.md` tem seis princípios inegociáveis, e a ADR 0035 os transformou em portões
derivados — um por regra, com o corpus saindo de artefato publicado em vez de lista
digitada. Ela deixou **uma** de fora, e disse por quê com todas as letras:

> **A regra 4 continua sem guarda automática**, e é a única. "Migrações são aditivas" não é
> verificável por `alembic check` — nada impede um `op.drop_column` dentro de um
> `upgrade()` — e "exige ADR/RFC" é julgamento.

O `CLAUDE.md` repete a frase, e desde então ela é citada como fato estabelecido. **A
primeira metade daquele argumento está certa e a segunda não sobrevive à medição.** O
`alembic check` de fato não vê: ele compara modelos com migrações, e uma coluna apagada
nos dois lados passa verde nele — o gate existe contra *deriva*, não contra *perda*. Mas
o que ele não vê, o AST vê, e a ADR 0035 nomeia o sítio exato ao dizer "dentro de um
`upgrade()`".

E "exige ADR/RFC" deixa de ser julgamento quando o gatilho é **estrutural**: policy, RLS e
privilégio são as três formas de o Postgres dizer *quem alcança qual linha*, e quem as
escreve está mexendo na segunda barreira da ADR 0010 por construção, não por opinião. É o
mesmo sinal que dispensou allowlist em (f) da ADR 0065 — o primeiro segmento de um
hostname `run.app` é um serviço por construção da própria URL — e o inverso do que a ADR
0033 chama de defeito, que é decidir corpus por nome digitado.

**O que esta fatia não pode alegar, e diz antes de qualquer outra coisa:** ela não achou
defeito. As 30 migrações do disco estão certas nas duas metades da regra. O precedente é
da própria ADR 0035, que registrou o mesmo desfecho nos cinco casos negativos que criou:
*"a fronteira já estava certa; o que faltava era a prova"* — e completou que isso não
desvaloriza a fatia, porque significa que o repositório passou meses a um refactor de
distância de um defeito que nada acusaria.

O inventário, medido antes de escrever qualquer linha de código, sobre
`apps/api/src/portal_api/db/migrations/versions/` (30 arquivos):

| Afirmação | Medido |
|---|---|
| `upgrade()` com `op.drop_table` / `op.drop_column` | **zero** |
| `upgrade()` com SQL que apaga dado | **zero** |
| `downgrade()` com `drop_*` | **23 arquivos** |
| `upgrade()` com `DROP` de outra espécie | **um** — `0013_drive_connector.py`, `DROP DEFAULT` e `DROP TYPE …_old` recriando o enum `document_origin` |
| migrações que tocam policy, RLS ou privilégio | **15** |
| dessas, que citam ADR ou RFC | **15 de 15** |
| citações penduradas (ADR/RFC que não existe) | **nenhuma** |

Os 23 `downgrade()` são o número que decide o desenho: um predicado de arquivo inteiro
acusaria os 23 e nasceria vermelho **sobre o comportamento correto**, que é a forma de
guarda que alguém desliga na primeira semana.

## Decisão

**Um arquivo novo, `apps/api/tests/test_migration_rules.py`**, com quatro asserções, sem
rede e sem banco — ao contrário de `test_migration.py`, que é de integração —, dentro do
job `api-quality` e sem job novo.

### (a) Toda migração é aditiva

Corpus derivado por glob das versões, **fail-closed**: glob vazio reprova, no argumento da
ADR 0064, porque verde por não ter olhado é a forma do `dependency-review` da ADR 0023.

O escopo do predicado é a **função `upgrade()`**, e é a decisão que os 23 `downgrade()`
impõem — a mesma lição de "o corpus de um predicado é o bloco em que ele vale" que a ADR
0065 pagou ao ver uma fence de `gcloud` herdar o escopo de outra.

Reprova o que apaga **dado**: `drop_table` e `drop_column` — casados pelo **nome do
atributo** e não pelo receptor, de modo que o `batch_op.drop_column` de um
`batch_alter_table` cai junto —, mais `DROP TABLE`, `DROP COLUMN` e `TRUNCATE` em literal
de SQL, porque `op.execute` é a porta pela qual metade destas migrações fala com o
Postgres.

**Não** reprova `DROP POLICY`, `DROP TYPE`, `DROP DEFAULT` nem `DROP INDEX`: mudam regime,
não linhas. A fronteira não é opinião — é o `0013_drive_connector.py`, que recria um enum
inteiro no `upgrade()` sem perder uma linha sequer, e é a amostra que separa esta guarda
de uma versão ingênua que reprovasse todo `DROP`.

`ADDITIVE_BY_EXCEPTION` nasce **vazia**, com motivo em prosa e **sem prazo**, no precedente
do `PINNED_BY_EXCEPTION` (ADR 0063) e não no do `advisories.json` (ADR 0023): migração
aplicada não caduca por calendário. Quem a vence é a asserção de obsolescência.

### (b) Quem mexe em tenancy cita decisão que existe

Gatilho estrutural sobre os literais de SQL — `CREATE/ALTER/DROP POLICY`,
`ROW LEVEL SECURITY`, `GRANT`, `REVOKE` — e a citação conferida contra `docs/adr/` e
`docs/rfc/`. O corpus das decisões **não é relido aqui**: `_accepted`/`_adrs` vêm por
import de `test_roadmap_index.py`, pelo motivo que aquele arquivo já escreveu — duas
leituras do mesmo corpus divergem sobre o que conta como aceita, e a divergência não deixa
nada vermelho. O precedente de import entre testes é `test_openapi_contract.py`.

A direção inversa é asserção própria, no precedente da ADR 0034, onde as duas direções já
falharam em documentos diferentes: uma citação pendurada faz a revisão exigida pela regra
4 **parecer feita**, e é a ADR 0065 na superfície que ninguém tinha olhado. Ela usa
`_accepted` e não "o arquivo existe", porque uma ADR recusada por escrito não justifica
mudança de tenancy.

### O que fica de fora, declarado em vez de fingido

A regra 4 nomeia quatro áreas e só duas têm sinal estrutural no SQL. **RAG e retenção
ficam fora**: cobrá-las exigiria uma lista de nomes de tabela escrita à mão, que é o
defeito da ADR 0033 e o que estas guardas existem para não repetir. É a assimetria de (d)
na ADR 0064 e da direção pendurada de (f) na ADR 0065 — o portão cobre o que consegue
computar, e diz o que não cobre.

E a leitura de literais precisou de um recorte que não é detalhe: **docstring não conta**.
A prosa deste repositório fala de `DROP` e de `GRANT` o tempo todo — o docstring do
`0007_rls_tenant_context.py` explica as policies que ele cria —, e contar a explicação
como se fosse a operação faria a guarda acusar exatamente quem documentou bem.

## Medição

**As quatro asserções nascem verdes**, e por isso o que as sustenta não é contagem de
achado, é mutação. Dez, cada uma declarando o resultado esperado, com o harness em Python
e restauração do arquivo em seguida:

| Mutação | Resultado |
|---|---|
| `op.drop_column` num `upgrade()` | **acusa** — `0022_project_archived_at.py linha 51: \`drop_column\`` |
| `op.execute("ALTER TABLE … DROP COLUMN …")` | **acusa** — `linha 51: SQL \`DROP COLUMN\`` |
| tirar **todas** as citações de uma migração com policy | **acusa** — `0009_notifications.py` |
| trocar a citação por `ADR 0099` | **acusa** — `0009_notifications.py → ADR 0099` |
| `ADDITIVE_BY_EXCEPTION` com entrada que não corresponde a nada | **acusa** — `o arquivo não existe mais` |
| glob das migrações vazio | **acusa** — fail-closed |
| **o mesmo `drop_column` movido para `downgrade()`** | **verde** — o escopo é a função |
| **`DROP INDEX` e `DROP DEFAULT` no `upgrade()`** | **verde** — regime não é dado |
| **tirar a citação de migração que não toca tenancy** | **verde** — o gatilho é o SQL, não o arquivo |
| **docstring que menciona `DROP COLUMN`** | **verde** — a prosa não é a operação |

As quatro verdes provam mais que as seis vermelhas: são o que separa esta guarda de uma
versão ingênua, e três delas correspondem a padrões que **existem hoje** no repositório.

**E uma mutação nasceu malformada, o que vale registrar porque se disfarça de guarda
fraca.** Tirar a citação de `0009_notifications.py` substituindo só a primeira ocorrência
passou **verde**, e parecia buraco no predicado — o arquivo cita `ADR 0012` e `ADR 0006`,
e a segunda continuava lá, corretamente satisfazendo a asserção. Substituídas as duas, ela
acusa. Antes de concluir que a guarda falhou, confira se a mutação produziu o estado que
pretendia.

**Portões:** 659 testes de API (**0 pulados**, sem `test_backup_restore.py`, com Postgres e
MinIO de pé) — 655 antes desta fatia e os 4 novos. `alembic check`,
`python -m portal_api.openapi --write`, `npm test`, `npm run audit` e `node scripts/pins.mjs`
**não se aplicam**: a fatia não toca modelo, migração, rota, dependência, web nem workflow.

## Consequências

- **A regra 4 deixou de ser a exceção, e o `CLAUDE.md` foi corrigido no mesmo commit.** A
  frase "a regra 4 fica declaradamente sem guarda, e é a única" passou a ser falsa; nada a
  reprova, porque a ADR 0064 recusou guarda sobre o `CLAUDE.md` de propósito, e por isso
  ela é item de revisão humana e não de portão.
- **A ADR 0035 não foi editada.** O repositório corrige por decisão nova que supera, não
  reescrevendo decisão aceita — o mesmo critério que a ADR 0034 aplicou ao recusar apagar
  o registro do próprio erro.
- **A guarda nasceu verde, e o valor dela é temporal.** Ela não descreve um defeito de
  hoje; ela impede que o `drop_column` de amanhã atravesse com o `alembic check` verde ao
  lado. Quem quiser aferir se ela vale, roda uma das seis mutações vermelhas.
- **Fica aberto, e nomeado:** RAG e retenção não têm gatilho, pelo motivo escrito acima; e
  (a) não sabe distinguir uma migração **aplicada** de uma que ainda não saiu da máquina
  de quem a escreveu, de modo que ela cobra aditividade também de quem ainda podia
  reescrever livremente o próprio arquivo. Cobrar de menos ali exigiria consultar o banco
  — rede num teste que hoje não tem nenhuma —, e cobrar de mais custa uma reescrita que o
  autor faz em segundos.
- **E fica aberto o que nenhuma das duas metades alcança:** "revisadas", da regra 4, é a
  palavra que continua sem portão. Nenhuma asserção daqui sabe se alguém *leu* a migração;
  o que se prova é que a decisão existe, está aceita e está citada.

## O que esta fatia não é

O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto acrescenta portão a
uma regra do `AGENTS.md`; nada aqui foi observado servindo cliente, nenhum comportamento de
produto mudou, nenhuma migração foi escrita ou alterada, e nenhum defeito foi encontrado —
o que a fatia entrega é a prova que faltava.
