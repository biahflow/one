# FDD 028 — O frescor que a jornada nunca teve

**Feature ID:** `F-028`

## Status

`READY_FOR_SPEC` — Feature Contract redigido; aguarda gate de Design Approval (DAP r1) e a ADR do
contrato de projeção versionado (ver *Gates humanos*) antes de `READY_FOR_PLANNING`.

> **Classificação: `INTEGRATION_CHANGE` · `BROWSER_REQUIRED`.** Origem: Issue #62. Concretiza a
> consequência escrita da ADR 0067 — "o webhook/snapshot existente evolui para **contrato de
> projeção versionado**" — e dá à jornada do cliente o que ela nunca teve: um carimbo honesto de
> frescor, e um estado que diz quando o dado está velho ou indisponível em vez de mostrá-lo como
> atual.

## Prioridade

Selecionada por humano em 26/08/2026 (Issue #62). `[confirmar sequência com F-026/F-027 no gate]`

## Objetivo e não objetivos

### Problema

O One **já projeta** a jornada — fases, entregáveis, progresso, próxima entrega, ROI, health
amigável, decisões, pendências — em `build_dashboard`, e o `JourneyPanel` a renderiza ("Você está
aqui", Welcome→Optimize). Mas a projeção tem três lacunas medidas:

1. **Não há frescor.** Não existe coluna `synced_at`/`observed_at` no `Project` nem campo de frescor
   no snapshot. A tela mostra "Sincronizado com o Biahflow" com `source` **hardcoded** `"live"`. Pior:
   a ADR 0026 já **removeu** um "Atualizado há 2 dias" que era um frescor **inventado** — a decisão
   explícita hoje é *não* carimbar, porque não havia timestamp honesto. Se o Biahflow parar de
   sincronizar, o cliente vê o último estado como se fosse o de agora, sem indicação.
2. **Não há defesa contra snapshot fora de ordem.** O sync é idempotente (o webhook ignora o corpo e
   re-busca o snapshot inteiro), mas não há comparação de versão/observação — One não tem como
   recusar um snapshot stale ou reconciliar deterministicamente. O único precedente de dedup por
   evento é `external_event_id` no `AgentEvent`, que é outro caminho.
3. **O contrato de projeção não é versionado** (a ADR 0067 pediu explicitamente; não há
   `snapshot_version`/`projection_version` em lugar nenhum), e **decisões não estão na timeline** —
   `Decision` é lista read-only sem vínculo a `ProjectPhase`, então "gates/decisões que
   desbloquearam a fase" não existem como projeção.

### Resultado desejado

A projeção da jornada tem **proveniência e frescor explícitos**; estado stale/indisponível é
**visivelmente representado** (nunca cache mostrado como atual); ingestão idempotente com
**reconciliação determinística** que não corrompe a projeção sob evento duplicado ou fora de ordem;
e a jornada renderiza fase atual, próximo marco, decisões/gates selecionados, pendências do cliente
e timestamps de progresso, com os campos internos filtrados por contrato **e por teste**.

### Escopo

- Definir um **contrato de projeção estável e versionado** de Pulse para One (o snapshot evolui para
  isso — ADR 0067), carregando `observed_at`/`as_of` e uma versão comparável.
- Incluir no mínimo: fase atual client-facing, próximo marco/entrega, decisões/gates selecionados,
  pendências do cliente e timestamps de progresso relevantes.
- **Filtrar explicitamente** notas internas, risk register, detalhe de engenharia, economia interna e
  demais campos não-client-safe (ADR 0067: GitHub/ClickUp/LangGraph/LangSmith/margens).
- Preservar proveniência e o timestamp observado/sincronizado.
- **Expor estado stale/indisponível** em vez de mostrar cache como atual — reusando o padrão honesto
  de `readOnlyReason` (pill + mensagem), não inventando carimbo (ADR 0026).
- Suportar ingestão idempotente de evento/webhook **e reconciliação determinística** quando faltar
  evento — anti-regressão por observação/versão comparável.
- Renderizar uma jornada/timeline client-friendly com o One Design System aprovado.
- Manter comentários/eventos de aceite do One separados da fase de Delivery do Pulse, salvo contrato
  de retorno definido (F-027).

### Fora de escopo

- Tornar o One autoritativo sobre as fases de Delivery do Pulse.
- Expor Issues/PR/CI do GitHub ao cliente por padrão.
- Substituir o workflow de aceite (F-027).
- Expor risco/finanças/operações internos.
- Transição automática de fase por visualização do cliente.

## Jornada e interface

A jornada já renderizada ganha duas coisas visíveis: (a) um **carimbo de frescor honesto**
("Atualizado há X" derivado de `observed_at`) que, acima de um limiar, vira um **estado stale**
(pill + mensagem, no padrão de "Projeto encerrado"/"Projeto removido na origem" da ADR 0036/0037);
(b) **decisões/gates na timeline** — as decisões selecionadas como client-safe aparecem ancoradas à
fase que desbloquearam, não só como lista solta. Detalhe visual e estados no DAP em
[`../features/F-028-o-frescor-que-a-jornada-nunca-teve/design-approval.md`](../features/F-028-o-frescor-que-a-jornada-nunca-teve/design-approval.md).

## Dados, API e permissões

- **Coluna de frescor no `Project`** (migração aditiva): `observed_at`/`synced_at` — ou gravado no fim
  de `sync_snapshot` (`now()`), ou, melhor, **vindo do snapshot** como o momento em que o Pulse
  observou o estado (mais honesto: mede a idade do dado na origem, não a da cópia). `build_dashboard`
  projeta o campo; `page.tsx`/`Overview` o carrega; `JourneyPanel`/`status-card` o renderizam.
- **Versão de projeção** (`projection_version`/`as_of` monotônico) no contrato e no `Project`: a
  reconciliação recusa aplicar um snapshot cuja versão/observação seja **anterior** à atual — o
  precedente é `mark_project_deleted` ("a primeira observação é a verdadeira"; só grava se ainda
  `None`), generalizado para "não regredir".
- **Decisões na timeline:** o contrato marca quais decisões são gates client-facing e a qual fase se
  ancoram (ou correlaciona por `decided_on` × janela da fase). Projeção read-only; One **não origina**
  decisão (ADR 0006/0008).
- **Filtro por contrato e teste:** uma guarda deriva do contrato os campos client-safe e reprova se um
  campo internal-only (lista da ADR 0067) atravessar — no espírito das guardas de consumo/telemetria
  existentes. Nada de escrita nova pelo `portal_app`: a projeção é read-only; quem escreve o snapshot
  é `portal_system`.
- Rotas: as existentes (`GET /api/v1/me/dashboard`, `/api/v1/projects/{id}/dashboard`) ganham os
  campos de frescor/versão; sem rota de escrita nova. 404-nunca-403 preservado; `test_authorization`
  e `test_openapi_contract` cobrem os campos novos.

## Estados de erro e segurança

- **Stale** (frescor acima do limiar): pill + mensagem honesta, dado marcado como possivelmente
  desatualizado — nunca escondido como atual.
- **Indisponível** (falha de fetch): já sobe para `app/error.tsx` ("indisponibilidade tem que parecer
  indisponibilidade"); a fatia mantém isso e acrescenta o caso stale, que é diferente (há dado, mas
  velho).
- **Encerrado/removido:** `archived_at`/`source_deleted_at` já viram modo somente-consulta
  (`readOnlyReason`); a jornada respeita.
- **Isolamento:** cross-tenant/projeto intacto (RLS + `test_rls_isolation`); o contrato não vaza campo
  internal-only (guarda de filtro).

## Restrições e dependências

- **Depende da F-026** (One Design System aplicado ao shell) para a timeline renderizar na pele
  aprovada — ou usa as primitivas diretamente.
- O contrato versionado é **mudança de integração** e exige ADR (ver *Gates humanos*).
- O frescor honesto exige um insumo que hoje não existe (o timestamp de observação): sem ele, a fatia
  não pode inventar carimbo (ADR 0026). A decisão "observado na origem vs sincronizado no One" é do
  ADR/gate.
- Migração **aditiva** (ADR 0066); sem tocar RLS/policy além do já existente (só colunas), então o
  gatilho estrutural do portão pode não disparar — mas o contrato versionado, sendo decisão de
  integração, é citado por ADR de qualquer modo (regra 4).

## Lacunas e riscos

- **Frescor da origem vs da cópia:** se o Pulse não carimbar `observed_at`, o One só sabe quando
  *copiou*, não quando o Pulse *observou* — carimbar a hora da cópia como frescor da origem seria a
  falsa precisão que `results.py` recusa. Preferência: o contrato carrega `observed_at`; fallback
  declarado se não carregar.
- **Reconciliação sem versão na origem:** se o snapshot não trouxer versão monotônica, a defesa
  anti-regressão fica limitada ao `observed_at`; declarar o limite em vez de fingir ordenação total.
- **Decisões×fases:** a correlação decisão→fase pode ser ambígua sem o Pulse marcar o gate; declarar a
  heurística e o que fica de fora.

## Gates humanos

1. **Design Approval** do DAP r1 (frescor/stale + decisões na timeline).
2. **ADR do contrato de projeção versionado** — mudança de integração consequente (ADR 0067 já aponta
   a direção; a versão/observação e a reconciliação são a decisão nova). Aceite humano antes do build.
3. Aprovação de plano; merge humano; `DONE` só após evidência, revisão e decisão humana.

## Telemetria e critérios de aceite

Telemetria: evento `projection.stale_observed` quando a idade cruza o limiar (nome sem interpolação,
detalhe em `extra`; linha em `alerts.md` — ADR 0018/0034). Critérios (Issue #62):

- [ ] One exibe uma jornada client-facing autorizada, originada do Pulse.
- [ ] A projeção tem proveniência e frescor explícitos.
- [ ] Campos internal-only do Pulse são excluídos por contrato **e por teste**.
- [ ] Estado ausente/stale/indisponível é visivelmente representado.
- [ ] Evento duplicado/fora de ordem não corrompe a projeção.
- [ ] A reconciliação recupera eventos perdidos deterministicamente.
- [ ] Isolamento cross-tenant/projeto permanece intacto.

## Referências

- Issue #62; ADR 0067 (One como projeção; contrato versionado); ADR 0006/0008 (portal nunca origina
  status); ADR 0026 (o carimbo de frescor inventado, removido); ADR 0036/0037 (`archived_at`/
  `source_deleted_at`, padrão de estado somente-consulta honesto). Precedente de anti-regressão:
  `mark_project_deleted`. Código: `integrations/biahflow.py` (`sync_snapshot`/`build_dashboard`),
  `models/project.py`, `app/DashboardClient.tsx` (`JourneyPanel`, `readOnlyReason`), `app/page.tsx`.

## Testes e avaliações de IA

- Guarda de filtro: um campo internal-only (lista ADR 0067) no contrato **reprova**.
- Reconciliação: snapshot fora de ordem/duplicado não regride a projeção (teste sobre `sync_snapshot`).
- `test_openapi_contract`/`test_authorization`: campos de frescor/versão declarados; 404-nunca-403.
- `test_rls_isolation`: isolamento intacto.
- Navegador: frescor exibido; estado stale acima do limiar; indisponível; encerrado/removido.
- Sem eval de IA (não toca prompt/recuperador/modelo/ferramenta).
