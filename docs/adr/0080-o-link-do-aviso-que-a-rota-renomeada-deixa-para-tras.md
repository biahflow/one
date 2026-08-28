# ADR 0080 — O link do aviso que a rota renomeada deixa para trás

**Status:** aceito
**Data:** 28/08/2026
**Fase:** 7

> Par da [ADR 0079](0079-engagement-como-raiz-da-navegacao-e-a-conta-que-se-chamava-cliente.md),
> que renomeou cinco rotas de administração **sem redirect**. Esta trata do que aquele
> rename custa a um dado que já está gravado no banco, e por que a resposta é uma migração
> e não uma rota de compatibilidade.

## Contexto

`notification.link` é **dado gravado**, não uma rota resolvida na leitura. Desde a ADR 0043
o campo tem escritor: `fan_out` congela a URL na linha, e o sino a renderiza como `<a href>`.
Duas formas são escritas hoje:

- `deep_link()` produz `/?project=<uuid>&tab=<rótulo>[&item=<âncora>]` para os avisos de
  cliente;
- `onboarding.alert_if_stuck` passa `link` **explícito** — `/admin/funil` — e o explícito
  vence em `fan_out`, porque a rota do funil não é aba de cliente e não sairia de
  `deep_link`.

O rename da ADR 0079 não toca a primeira forma: a rota do cliente continua `/`, e o rótulo
de aba continua em português por decisão. A segunda quebra: todo aviso de
`onboarding_stuck` já gravado aponta para `/admin/funil`, que agora responde 404.

**A audiência daquele aviso é `_INTERNAL_ONLY`** (ADR 0040) — é o primeiro e único aviso que
não vai para cliente nenhum. E o portal está fora do ar desde 13/08/2026 (ADR 0053), então o
volume real é o que houver de sincronização local e de homologação. O custo é interno e
conhecido; ele não é zero, e o modo de falha é o pior tipo: **um `href` para rota inexistente
renderiza exatamente igual a um que funciona**, que é a família de defeito que
`inertButtons()` existe para pegar em outra superfície (ADR 0026).

## Decisão

**Uma migração reescreve as linhas antigas**, e não há redirect.

`0038_notification_link_rename.py` executa um `UPDATE` por igualdade com o literal exato que
`onboarding.py` escrevia:

```sql
UPDATE notification SET link = '/admin/funnel' WHERE link = '/admin/funil'
```

Três coisas sustentam essa forma:

1. **Consertar o dado, não acrescentar rota.** Um redirect seria uma rota permanente
   sustentando um dado antigo — a rota morta que a decisão de renomear sem compatibilidade
   existe para não deixar. A migração some depois de aplicada; o redirect ficaria.
2. **Igualdade, não `LIKE` nem prefixo.** Nenhum outro produtor grava esse valor, e um
   casador solto poderia alcançar um link de cliente que só *contivesse* o texto.
3. **`UPDATE`, e nada é apagado.** A linha continua a mesma, com o mesmo `dedupe_key`, o
   mesmo `occurred_at` e o mesmo `read_at`. `test_migration_rules.py` classifica só
   `DROP TABLE/COLUMN` e `TRUNCATE` como perda de dado; esta migração não é destrutiva por
   construção nem por interpretação.

O `downgrade()` reverte o `UPDATE`, o que é o certo aqui e não é o caso geral: a migração é
uma tradução, e o inverso da tradução existe.

**E o par código↔migração ganha guarda.** `test_o_link_gravado_no_aviso_e_o_mesmo_que_a_migracao_reescreveu`
lê o literal que `onboarding.py` grava e o `NEW_LINK` da migração, e reprova se divergirem.
Sem ela, o próximo rename de rota escreveria um valor novo sem trazer o histórico junto — e o
defeito seria mudo pela razão do parágrafo acima. É a mesma forma da guarda bidirecional de
eventos da ADR 0034: quem produz e quem descreve têm de concordar.

## Consequências

- Avisos internos já gravados voltam a abrir a tela certa depois de `alembic upgrade head`.
  Em ambiente sem nenhuma linha antiga, o `UPDATE` alcança zero linhas e é um no-op — que é
  o caso da homologação recriada e do banco de teste.
- Fica registrado o que **não** foi tocado: `deep_link()` e os links de cliente
  (`/?project=…&tab=…`). Eles continuam válidos porque o rename não alcançou nem a rota nem
  o rótulo de aba. Se um dia o rótulo de aba mudar, esta ADR é o precedente e o remédio é o
  mesmo — com a diferença de que ali a audiência **é** o cliente, e o cálculo de custo muda.
- O mecanismo geral continua ausente e nomeado: não há guarda que descubra sozinha que uma
  rota renomeada tem link gravado apontando para ela. A guarda desta fatia é sobre **um**
  par conhecido. Uma varredura que derive de `app/` os caminhos existentes e cobre que todo
  literal `/admin/...` do Python resolva para um deles seria o portão completo, e não foi
  construída aqui — o escopo desta fatia é o dado, não o mecanismo.
