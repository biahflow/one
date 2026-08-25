import type { ReactNode } from "react";
import { AlertTriangle, Check, Info, XCircle } from "lucide-react";

/**
 * Ícone + texto + cor para cada variante (F-025 T02, DAP §04 — "os quatro estados
 * nunca dependem só da cor"). Sem o ícone o estado depende só de cor e some em
 * tons de cinza ou para quem não distingue as duas — é o critério de aceite da
 * Issue #46.
 */
const ICONS = {
  success: Check,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
} as const;

export type StatePillVariant = keyof typeof ICONS;

export function StatePill({
  variant,
  children,
}: {
  variant: StatePillVariant;
  children: ReactNode;
}) {
  const Icon = ICONS[variant];
  return (
    <span className={`state-pill state-pill--${variant}`}>
      <Icon size={12} strokeWidth={2.4} aria-hidden="true" />
      {children}
    </span>
  );
}
