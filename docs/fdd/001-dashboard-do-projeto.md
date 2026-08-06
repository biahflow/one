# FDD 001 — Dashboard do projeto

Exibe status, próxima entrega, cronograma, ROI, horas economizadas, pendências e atualizações recentes apenas do projeto autorizado. Indicadores exibem data e premissas; cliente não os edita.

## Todo controle da tela faz alguma coisa (ADR 0026)

Critério de aceite, e é mecânico: **nenhum `<button>` sob `app/` ou `components/` existe sem
`onClick` ou `type="submit"`**. `inertButtons()` em `tests/rendered-html.test.mjs` varre o
código-fonte a cada `npm test` e reprova nomeando arquivo e linha.

A regra é do controle, não do dado, e é a única guarda do repositório que não olha um valor —
porque um botão inerte renderiza HTML idêntico a um que funciona, e nem as asserções sobre o
SSR nem o Playwright conseguem distingui-los. Foi assim que onze controles sobreviveram à
fatia que declarou tê-los eliminado (ADR 0024).

Quando um controle não tem destino, a resposta é **apagá-lo e escrever a frase**, não deixá-lo
inerte nem rotulá-lo "em breve":

- "Editar" no perfil saiu porque nome e e-mail vivem no Keycloak e o GRANT de coluna de
  `portal_app` em `user` os exclui de propósito (ADR 0010/0011/0012). A tela diz onde se muda.
- Os menus `⋯` saíram porque toda ação que caberia neles seria originar status, que o portal
  não faz (ADR 0006/0008).
- "Salvar alterações" saiu porque idioma, fuso e tema são constantes do produto. Os dois
  literais estão no laço de proibidos do mesmo teste.

## Telemetria

Nenhuma nova: a fatia não acrescenta rota nem chamada. Os dois cliques ligados
("Ver cronograma", "Ver todas as pendências") trocam de aba no cliente, sem ida à API.
