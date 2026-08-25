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
 * Três elementos, todos `<span>` (`.one-brand` é `grid`, então o empilhamento
 * não depende do tipo de elemento) — dentro de `<span>` também é `<span>`, nunca
 * `<div>`, porque HTML inválido não é preço a pagar por conveniência de CSS
 * (revisão da T02, achado 1). Cada um tem regra de cor própria em
 * `app/globals.css`: `.one-brand-dot` no claro e sob `.auth-brand-row` no
 * gradiente escuro — nada aqui depende de um seletor `> span span` genérico.
 */
export function Brand() {
  return (
    <span className="one-brand">
      <span className="one-brand-word">
        One<span className="one-brand-dot">.</span>
      </span>
      <span className="one-brand-sub">by Biahflow</span>
    </span>
  );
}
