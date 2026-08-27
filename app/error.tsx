"use client";

import { StatePill } from "@/components/one/StatePill";

/**
 * Fronteira de erro do portal. Existe para que uma falha de rede ou da API
 * apareça como falha — antes desta fase qualquer erro caía no dashboard de
 * demonstração, o que transformava indisponibilidade em dado inventado.
 *
 * O `digest` é o código que o Next calcula para o erro do servidor e é a única
 * parte dele que pode chegar ao navegador — a mensagem é saneada de propósito,
 * para um erro não virar um oráculo. Mostrá-lo é o que faz "A falha foi
 * registrada" ser verificável: a pessoa repete o código e quem atende encontra
 * a linha `web.request_error`, que carrega o `trace_id` da requisição inteira
 * (ADR 0018).
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="state-shell">
      <div className="state-card">
        <p className="eyebrow">ALGO DEU ERRADO</p>
        {/* O terceiro dos três estados honestos do dado (ADR 0076): `danger`, ao lado do
            `warning` do stale e do cinza do encerrado. A cor é o que os torna três estados
            e não um — colapsá-los mentiria sobre qual é o caso. */}
        <p className="state-badge"><StatePill variant="danger">Projeção indisponível</StatePill></p>
        <h1>Não conseguimos carregar seu projeto agora.</h1>
        <p>
          Isso é indisponibilidade, não um projeto vazio: nada foi apagado e nada nesta tela
          foi montado a partir de uma cópia antiga.
        </p>
        <p>
          A falha foi registrada. Tente novamente em instantes; se persistir, fale com o time
          da Biahflow.
        </p>
        {error.digest && (
          <p className="state-code">
            Código: <code>{error.digest}</code>
          </p>
        )}
        <button className="ai-button" onClick={reset}>Tentar de novo</button>
      </div>
    </main>
  );
}
