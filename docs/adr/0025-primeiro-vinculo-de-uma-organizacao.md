# ADR 0025 — O primeiro vínculo de uma organização

**Status:** aceita — 05/08/2026
**Contexto:** Fase 6. Aparece ao ligar o portal ao Biahflow de verdade (ADR 0006), e o que ela
corrige é uma consequência não prevista da ADR 0011.

## Contexto

A ADR 0011 fechou a escrita de `membership` em `portal_admin`, com policies que leem a GUC de
terceiro estágio publicada **depois** de o `internal_admin` do chamador ser verificado. Em
`admin.py`, toda rota de acesso passa por `access.require_project(..., ADMIN_ONLY)`: para
administrar um projeto é preciso **já ser** `internal_admin` nele.

Isso é circular por desenho, e o desenho estava certo enquanto toda organização vinha do
`seed.py`. No dia em que o sync do Biahflow criou a primeira organização nova, a circularidade
deixou de ter saída:

```
 org         |        name         |  projeto   | projeto_nome | membros
-------------+---------------------+------------+--------------+---------
 biahflow-3  | Acme Brasil         | biahflow-7 | Automação…   |       8   ← seed
 biahflow-1  | Igreja Cartas Vivas | biahflow-1 | Teste        |       0   ← sync
```

O projeto sincronizado existe, tem jornada, marcos e documentos — e **ninguém o enxerga**. Nem
o cliente, que não tem vínculo; nem a equipe interna, cujo vínculo org-wide é de outra
organização; nem quem administra o portal, porque não existe "administrador do portal", só
administrador *de uma organização*. E a tela que criaria o primeiro vínculo exige o vínculo que
ela criaria.

Não é um defeito do conector nem da ADR 0011: é a porta trancada corretamente, sem que ninguém
tivesse escrito como se entra na primeira vez.

## Decisão

**O primeiro vínculo de uma organização nasce por operação, e nunca por rota HTTP.**
`python -m portal_api.grant_access --email … --organization … --role internal_admin`, na forma
de `seed.py`, e com quatro propriedades que são a decisão:

### 1. Não é rota, e é isso que o torna aceitável

Uma rota capaz de criar o primeiro administrador de uma organização é exatamente o caminho que
a ADR 0011 fechou — só que com outro nome. Qualquer autenticação que ela usasse (um papel de
realm, uma chave de serviço, um "super admin") reintroduziria a categoria que este repositório
recusa desde a ADR 0002: alguém que alcança todos os tenants pela web.

É a simétrica da ADR 0017: lá, **nenhuma rota apaga** um tenant — o pedido é gravado e o worker
executa. Aqui, nenhuma rota **inaugura** um. Nos dois casos a operação existe, é auditada, e
mora fora do alcance de uma sessão de navegador. Quem tem shell no servidor já alcança o banco;
o controle não é sobre poder, é sobre *superfície*.

### 2. Roda sob `portal_system`, pelo argumento do seed

É um caminho que inaugura tenant: não há contexto a fixar, e a RLS negaria a escrita —
corretamente. Mesma justificativa que `seed.py` já carrega, e o mesmo motivo pelo qual
`sync_snapshot` roda sob esse papel.

### 3. Recusa quando a organização já tem `internal_admin`

Esta é a linha que impede o CLI de virar uma porta paralela ao `/admin`. Com um administrador
no lugar, existe alguém que alcança a tela — auditável, com registro de quem convidou quem, e
sem pedir shell. Um comando que continua funcionando depois de desnecessário vira o caminho
preferido por conveniência, e a ADR 0011 passa a valer só no papel.

A recusa vem **depois** da checagem de idempotência, de propósito: repetir o mesmo comando tem
de continuar sendo no-op mesmo depois de a organização passar a ter admin — senão a segunda
execução de um script de implantação falharia por ter dado certo na primeira.

### 4. O vínculo é organizacional, não por projeto

`project_id IS NULL`. O sync cria um projeto do portal por projeto do Biahflow, e um vínculo
por projeto obrigaria a repetir o bootstrap a cada novo. `MembershipRepository.roles_for_project`
já soma o vínculo org-wide ao do projeto — é o que faz "primeiro administrador da organização"
significar alguma coisa.

E só papéis internos: `client_member` fica de fora porque cliente entra por convite, que cria a
conta no realm e manda o e-mail. Um vínculo criado aqui seria acesso para alguém que não
consegue entrar.

## Consequências

- Uma organização recém-sincronizada deixa de ser um beco sem saída. O passo é uma linha no
  runbook (`docs/runbooks/integracao-biahflow.md`), executada uma vez por organização.
- O comando grava `audit_log` com `action="membership.bootstrapped"` e `via="grant_access"` — o
  vínculo mais poderoso do sistema não podia ser o único sem rastro. O ator registrado é quem
  **recebeu** o vínculo, e o `data` diz que veio daqui: inventar um ator "sistema" seria pior do
  que dizer a verdade sobre o que se sabe.
- `test_grant_access.py::test_after_the_bootstrap_the_admin_screen_answers` é a asserção que dá
  sentido às outras: `/admin` responde 404 antes e 200 depois. Sem ela, o resto provaria apenas
  que uma linha foi escrita numa tabela.
- **O que isto não resolve, declarado:** o cliente daquela organização continua entrando por
  convite, e alguém precisa convidá-lo. É o desenho — o portal não descobre sozinho quem, do
  lado do cliente, deve enxergar o projeto, e inferir isso do Biahflow seria o portal originando
  autorização (ADR 0006/0008 pela negativa).

## Alternativas recusadas

**Uma rota `POST /api/v1/admin/organizations/{id}/bootstrap`.** Ver decisão 1: é a porta que a
ADR 0011 fechou, com outro nome.

**Fazer o `sync_snapshot` conceder o vínculo sozinho** — por exemplo, dando `internal_admin` a
todo usuário interno na organização nova. Seria conveniente e erra a direção do fluxo: o
Biahflow é fonte da verdade de *status*, não de *autorização*. Um webhook passaria a poder criar
acesso, e a regra 5 do `AGENTS.md` — o backend valida identidade, organização, projeto e papel —
deixaria de ter onde ser aplicada.

**Um papel de realm "super admin" que atravessa organizações.** É a categoria que a ADR 0002
recusa. Um token comprometido passaria a valer para todos os tenants, e a RLS — que existe
justamente para o caso de a aplicação errar — deixaria de ser a segunda barreira, porque a
primeira teria autorizado tudo.

**Deixar como está e resolver com SQL na mão.** É o que aconteceria na prática, e é pior do que
um comando: sem idempotência, sem recusa, sem auditoria, e com o `INSERT` escrito de memória
por quem estiver de plantão.
