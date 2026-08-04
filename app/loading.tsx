/**
 * A página é renderizada no servidor e agora depende de duas chamadas à API
 * (`/me` e o dashboard), então a espera passou a ser visível.
 */
export default function Loading() {
  return (
    <main className="state-shell">
      <div className="state-card">
        <p className="eyebrow">CARREGANDO</p>
        <h1>Buscando seu projeto…</h1>
      </div>
    </main>
  );
}
