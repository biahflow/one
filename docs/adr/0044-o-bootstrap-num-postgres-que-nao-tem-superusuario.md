# ADR 0044 — O bootstrap num Postgres que não tem superusuário

**Status:** aceito
**Data:** 07/08/2026
**Contexto:** HML na GCP com Neon; ADR 0010 (papéis e RLS), ADR 0019 (backup e restore)

## Contexto

O `infra/postgres/bootstrap/roles.sql` nasceu contra o Postgres do compose, onde o papel que o
executa é `POSTGRES_USER` e **nasce superusuário**. Nunca houve outro alvo, então nunca houve
razão para separar "o que o script quer" de "o que só um superusuário pode fazer".

HML muda isso: o banco é **Neon** (PG 16.14), e num Postgres gerenciado não existe superusuário
para a aplicação usar — nem no Neon, nem no Cloud SQL, nem no RDS. É a mesma classe de restrição
que a ADR 0016 do Biahflow encontrou com a política de chaves de conta de serviço: o desenho não
estava subótimo, estava **inconstruível** naquele ambiente.

Medido, e o resultado é mais estreito do que se temia. Das sete cláusulas que o script usa em
`ALTER ROLE`, o Neon aceita **seis**:

| Cláusula | Neon |
|---|---|
| `LOGIN`, `NOCREATEDB`, `NOCREATEROLE`, `PASSWORD` | aceita |
| **`BYPASSRLS`** | **aceita** |
| `NOBYPASSRLS` | aceita |
| `NOSUPERUSER` | **recusa** — `permission denied to alter role` |

`BYPASSRLS` é o que carregava o risco: `portal_system` precisa dele, é o eixo da ADR 0010, e três
testes o afirmam. Ele passa. O que trava é a cláusula que **não muda nada**.

E uma segunda, encontrada na sequência: `ALTER SCHEMA portal OWNER TO portal_migrator` falha com
`must be able to SET ROLE "portal_migrator"`. Desde o PG 16, transferir a posse de um objeto
exige ser membro do papel de destino, e o papel do bootstrap não ganha isso de graça quando não é
superusuário.

## Decisão

**`NOSUPERUSER` sai dos quatro `ALTER ROLE` e volta num bloco guardado**, que só o executa quando
`current_user` é de fato superusuário.

A intenção não mudou; mudou o que o Postgres permite. Só superusuário pode alterar o atributo de
superusuário — **mesmo para reafirmá-lo com o valor que já está lá** —, e `CREATE ROLE` já nasce
`NOSUPERUSER`, então a linha era um no-op que derrubava o bootstrap inteiro.

Por que reafirmar continua valendo onde dá: é defesa contra deriva. Se alguém promover
`portal_app` a superusuário à mão, rodar o bootstrap desfaz. **Onde não há superusuário, ninguém
pode promover ninguém** — a defesa é desnecessária pelo mesmo motivo que é impossível.

**E o bootstrap concede `portal_migrator` a si mesmo quando não é superusuário**, para poder
transferir a posse do schema. Não afrouxa nada: quem roda o script já é o papel mais privilegiado
do banco e poderia conceder-se de qualquer forma. É só o `portal_migrator` — o `portal_system`,
que é o do `BYPASSRLS`, fica de fora.

## Consequências

**O invariante continua guardado, e por quem sempre o guardou de verdade.** O bootstrap era o
*terceiro* lugar a afirmá-lo; os dois que importam continuam intactos — `test_rls_isolation.py`
afirma `rolsuper` e `rolbypassrls` do papel de requisição, e o `restore.sh` os reafirma depois de
restaurar. Um script de bootstrap não é o lugar onde uma promoção indevida seria detectada: ele
roda no deploy, e o teste roda a cada push.

**O Neon serve para o portal do cliente**, e essa era a pergunta que decidia o banco de HML.
Verificado ponta a ponta contra o Neon real: `pgvector` e `btree_gist` criam, o `roles.sql`
inteiro roda sem erro, e os quatro papéis saem com os atributos exatos — `portal_system` com
`bypassrls=true`, os outros três sem, nenhum superusuário.

**E continua servindo para o compose**, que é onde o CI roda: o `db-bootstrap` foi reexecutado
contra o Postgres local e produziu os mesmos atributos, com as 55 asserções de
`test_rls_isolation.py` e `test_admin_rls.py` verdes.

**A mensagem de `NOTICE` é parte da decisão, não enfeite.** Num Postgres gerenciado o bootstrap
diz, em voz alta, que não reafirmou o `NOSUPERUSER` e por quê. Sem ela, a diferença entre os dois
ambientes seria silenciosa — e silêncio sobre privilégio é exatamente o que este repositório
passou várias ADRs consertando.

**Fica aberto:** o `restore.sh` roda o `roles.sql` antes do `pg_restore` (ADR 0019). Restaurar
para dentro de um Postgres gerenciado ainda não foi exercitado, e a ADR 0019 dependia de
`pg_dump` sob `portal_migrator` — que num banco gerenciado não é dono do banco, só do schema.
Entra no roteiro de homologação de HML.
