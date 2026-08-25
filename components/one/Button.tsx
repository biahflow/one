import type { ReactNode } from "react";

/**
 * As quatro variantes do botão do One (F-025 T02, DAP §05). `disabled` e o anel
 * de foco de teclado vêm do `@layer base` de `app/globals.css`
 * (`:focus-visible { outline: 2px solid var(--color-focus); ... }`) — não há CSS
 * de foco próprio aqui, porque é a mesma regra que já cobre todo botão nativo
 * do produto.
 *
 * `onClick` é explícito na assinatura e escrito por extenso na tag do elemento
 * nativo, nunca via espalhamento de props: `tests/rendered-html.test.mjs` varre
 * `components/` e reprova um elemento de botão sem `onClick=` nem
 * `type="submit"` literais no texto-fonte (ADR 0026) — um `{...rest}` apagaria
 * o literal e a primitiva nasceria inerte aos olhos da guarda, mesmo
 * funcionando em runtime.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  type = "button",
  onClick,
  disabled,
  className,
  children,
}: {
  variant?: ButtonVariant;
  type?: "button" | "submit";
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={["btn", `btn--${variant}`, className].filter(Boolean).join(" ")}
    >
      {children}
    </button>
  );
}
