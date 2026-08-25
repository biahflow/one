/**
 * O wordmark do One, e o único lugar do produto onde ele é escrito (F-025 T02).
 * Antes disto, `One<span>.</span>` — na verdade `portal<span>labs</span>` — vivia
 * duplicado em `app/DashboardClient.tsx` e em `app/login/page.tsx`, sem nada que
 * cobrasse que os dois blocos ficassem idênticos.
 *
 * O que o Design Approval Package aprovou (design-approval.md §"Decisions this
 * package carries", item 2; `design/one-dap-r3.html` §01): `One.` com o ponto
 * final em destaque, mais o descender `by Biahflow`. Sem selo, sem tile — o tile
 * (a inicial comprimida) existe só fora da tela do produto: favicon, atalho de
 * tela, cartão de compartilhamento.
 *
 * O ponto troca de cor sobre o gradiente escuro do painel de autenticação através
 * de `.brand-row > span span` / `.auth-brand-row > span span`, já escritas em
 * `app/globals.css` para o antigo sufixo `labs` — por isso só o ponto é um `<span>`
 * aninhado aqui: envolver "One" ou o descender num `<span>` também cairia no mesmo
 * seletor e herdaria a cor do ponto, que não é a cor deles.
 */
export function Brand() {
  return (
    <span className="one-brand">
      <div className="one-brand-word">
        One<span className="one-brand-dot">.</span>
      </div>
      <div className="one-brand-sub">by Biahflow</div>
    </span>
  );
}
