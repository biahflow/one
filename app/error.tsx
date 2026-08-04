"use client";

/**
 * Fronteira de erro do portal. Existe para que uma falha de rede ou da API
 * apareça como falha — antes desta fase qualquer erro caía no dashboard de
 * demonstração, o que transformava indisponibilidade em dado inventado.
 */
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="state-shell">
      <div className="state-card">
        <p className="eyebrow">ALGO DEU ERRADO</p>
        <h1>Não conseguimos carregar seu projeto agora.</h1>
        <p>
          A falha foi registrada. Tente novamente em instantes; se persistir, fale com o time
          da Portal Labs.
        </p>
        <button className="ai-button" onClick={reset}>Tentar de novo</button>
      </div>
    </main>
  );
}
