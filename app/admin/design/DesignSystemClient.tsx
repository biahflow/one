"use client";

import { useRef, useState, useSyncExternalStore } from "react";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/one/Brand";
import { Button, type ButtonVariant } from "@/components/one/Button";
import { StatePill, type StatePillVariant } from "@/components/one/StatePill";

/**
 * Um token do `@theme`, **lido do navegador** e não digitado aqui.
 *
 * O risco nomeado no contrato da T04 é a vitrine virar segunda fonte de verdade dos
 * tokens: quem escreve o hex de novo dentro dela faz a próxima mudança de token deixar a
 * vitrine mentindo, e uma vitrine que mente é pior que nenhuma. Daí a enumeração em
 * runtime — a tela mostra o que o navegador realmente resolveu, e não o que alguém achava
 * que o CSS dizia.
 *
 * Efeito colateral que **interessa à guarda**: um `var(--token)` montado por template
 * string não aparece no texto-fonte, então a vitrine não conta como consumidora na
 * asserção de consumo de `tests/rendered-html.test.mjs`. Um token órfão acrescentado ao
 * `@theme` aparece aqui na tela e continua reprovando lá — que é o comportamento certo.
 * Se a lista fosse escrita à mão, a vitrine seria consumidora de tudo e a guarda viraria
 * enfeite (ADR 0033).
 */
type ThemeToken = { name: string; value: string };

const FAMILIES = ["color", "radius", "shadow", "font", "weight"] as const;
type Family = (typeof FAMILIES)[number];

const FAMILY_TITLES: Record<Family, string> = {
  color: "Cor",
  radius: "Raio",
  shadow: "Elevação",
  font: "Família tipográfica",
  weight: "Peso tipográfico",
};

const BUTTON_VARIANTS: ButtonVariant[] = ["primary", "secondary", "ghost", "danger"];

const BUTTON_LABELS: Record<ButtonVariant, string> = {
  primary: "Perguntar à IA",
  secondary: "Ver cronograma",
  ghost: "Cancelar",
  danger: "Revogar acesso",
};

const PILL_VARIANTS: StatePillVariant[] = ["success", "warning", "danger", "info"];

const PILL_LABELS: Record<StatePillVariant, string> = {
  success: "Concluído",
  warning: "Atenção",
  danger: "Falhou",
  info: "Informativo",
};

const PILL_MEANINGS: Record<StatePillVariant, string> = {
  success: "Aconteceu, e não pede nada de ninguém.",
  warning: "Ainda dá para agir, e alguém precisa.",
  danger: "Não aconteceu, e a tela não finge que aconteceu.",
  info: "Contexto que muda a leitura sem exigir ação.",
};

/**
 * Os pares de contraste que o pacote de design mediu (DAP §02).
 *
 * A lista é de **pares** — qual cor senta sobre qual —, que é decisão de design e não
 * valor de token; os valores continuam vindo do navegador, e a razão é calculada aqui.
 * É o que faz esta seção envelhecer junto com o `@theme`: trocar um hex reprova na tela,
 * na hora, em vez de deixar a tabela do documento afirmando um número que ninguém refez.
 *
 * Só pares de **texto normal**. O critério é AA 4,5:1 porque nada neste produto usa texto
 * grande — o corpo secundário é 14px e a pastilha de estado é 10px em negrito.
 */
const CONTRAST_PAIRS: { foreground: string; background: string; role: string }[] = [
  { foreground: "--color-ink", background: "--color-surface", role: "texto primário sobre cartão" },
  { foreground: "--color-muted", background: "--color-surface", role: "texto secundário sobre cartão" },
  { foreground: "--color-muted", background: "--color-canvas", role: "texto secundário sobre a página" },
  { foreground: "--color-success-600", background: "--color-success-50", role: "pastilha de concluído" },
  { foreground: "--color-warning-600", background: "--color-warning-50", role: "pastilha de atenção" },
  { foreground: "--color-danger-600", background: "--color-danger-50", role: "pastilha de falha" },
  { foreground: "--color-info-600", background: "--color-info-50", role: "pastilha informativa" },
  { foreground: "--color-brand-700", background: "--color-brand-50", role: "texto de marca sobre o tinto claro" },
  { foreground: "--color-surface", background: "--color-brand-500", role: "rótulo do botão primário" },
];

const AA_NORMAL_TEXT = 4.5;

/** Todo `CSSStyleRule` da folha, inclusive os que moram dentro de `@layer` ou `@media`. */
function styleRules(rules: CSSRuleList): CSSStyleRule[] {
  const found: CSSStyleRule[] = [];
  for (const rule of Array.from(rules)) {
    if (rule instanceof CSSStyleRule) found.push(rule);
    // `@layer theme { :root, :host { … } }` é exatamente onde o Tailwind v4 põe o
    // `@theme`, então parar no primeiro nível devolveria zero token.
    else if ("cssRules" in rule) found.push(...styleRules((rule as CSSGroupingRule).cssRules));
  }
  return found;
}

/**
 * Os tokens do `@theme` como o navegador os resolveu.
 *
 * O valor sai de `getComputedStyle`, e não do texto da regra, porque há token que aponta
 * para outro (`--color-focus: var(--color-brand-500)`): o texto diria `var(…)` e a tela
 * mostraria a indireção em vez da cor.
 */
function readThemeTokens(): ThemeToken[] {
  const resolved = getComputedStyle(document.documentElement);
  const found = new Map<string, string>();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // folha de outra origem: o navegador recusa, e não há o que ler
    }
    for (const rule of styleRules(rules)) {
      if (!/(^|,)\s*:root\b/.test(rule.selectorText)) continue;
      for (const property of Array.from(rule.style)) {
        if (!/^--(color|radius|shadow|font)-/.test(property)) continue;
        found.set(property, resolved.getPropertyValue(property).trim());
      }
    }
  }
  return [...found]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * O instantâneo da folha de estilo, memoizado no módulo.
 *
 * `useSyncExternalStore` chama `getSnapshot` a cada renderização e compara por identidade:
 * devolver um array novo em cada chamada seria laço infinito. A folha não muda durante a
 * vida da página — quando ela muda, é porque houve recompilação, e aí houve recarga.
 */
let snapshot: ThemeToken[] | null = null;

function themeSnapshot(): ThemeToken[] {
  if (snapshot === null) snapshot = readThemeTokens();
  return snapshot;
}

/** Nada a assinar: a folha não emite evento, e este é o contrato mínimo da API. */
function subscribeToStyleSheet(): () => void {
  return () => {};
}

/**
 * A família de um token, pelo prefixo. `--font-weight-*` sai antes de `--font-*`: os dois
 * casam o mesmo prefixo e desenhá-los igual mostraria um peso como se fosse uma fonte.
 */
function familyOf(token: ThemeToken): Family | null {
  if (token.name.startsWith("--font-weight-")) return "weight";
  if (token.name.startsWith("--color-")) return "color";
  if (token.name.startsWith("--radius-")) return "radius";
  if (token.name.startsWith("--shadow-")) return "shadow";
  if (token.name.startsWith("--font-")) return "font";
  return null;
}

/** A amostra de cada família: a que se vê é o token aplicado, nunca uma cópia dele. */
function chipStyle(family: Family, name: string): React.CSSProperties {
  const reference = `var(${name})`;
  if (family === "color") return { background: reference };
  if (family === "shadow") return { boxShadow: reference };
  if (family === "radius") return { borderRadius: reference };
  if (family === "weight") return { fontWeight: reference };
  return { fontFamily: reference };
}

/** Os três canais de uma cor, ou `null` quando a forma não é reconhecida. */
function channels(value: string): [number, number, number] | null {
  const short = /^#([\da-f])([\da-f])([\da-f])$/i.exec(value);
  if (short) {
    const [, r, g, b] = short;
    return [parseInt(r + r, 16), parseInt(g + g, 16), parseInt(b + b, 16)];
  }
  const long = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(value);
  if (long) return [parseInt(long[1], 16), parseInt(long[2], 16), parseInt(long[3], 16)];
  const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(value);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  return null;
}

/** Luminância relativa da WCAG 2.1. */
function luminance([red, green, blue]: [number, number, number]): number {
  const channel = (raw: number) => {
    const scaled = raw / 255;
    return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
}

/**
 * A razão de contraste do par, ou `null` quando falta base.
 *
 * `null` é resposta, não erro: é o mesmo princípio com que `results.py` declara a lacuna
 * em vez de dividir por zero. Um número inventado aqui seria pior que a ausência dele,
 * porque a tela existe justamente para se conferir a conta.
 */
function contrastRatio(foreground: string, background: string): number | null {
  const first = channels(foreground);
  const second = channels(background);
  if (!first || !second) return null;
  const lighter = Math.max(luminance(first), luminance(second));
  const darker = Math.min(luminance(first), luminance(second));
  return (lighter + 0.05) / (darker + 0.05);
}

function Section({
  eyebrow,
  title,
  lead,
  children,
}: {
  eyebrow: string;
  title: string;
  lead: string;
  children: React.ReactNode;
}) {
  return (
    <article className="panel section-gap">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="design-note">{lead}</p>
      {children}
    </article>
  );
}

/**
 * A vitrine do sistema de design do One (F-025 T04).
 *
 * **Todo controle daqui é de verdade** — nada de botão desenhado para a foto. A ADR 0026
 * achou onze controles inertes na tela do cliente, e a lição foi que um elemento de botão
 * sem `onClick` renderiza HTML idêntico a um que funciona: só a forma do código o
 * distingue, e é isso que `inertButtons()` afirma. Numa vitrine a tentação é máxima, então
 * ela demonstra estado **mexendo em estado**: os seletores trocam a variante ao vivo, e o
 * único elemento permanentemente desabilitado é o que está ali para mostrar `disabled`.
 *
 * O nome da tag não é escrito por extenso nesta prosa de propósito: a guarda varre o
 * texto-fonte e não distingue comentário de markup — foi ela que cobrou, e a resposta é a
 * mesma que `components/one/Button.tsx` já tinha dado.
 */
export default function DesignSystemClient() {
  // A folha de estilo é um sistema externo ao React, e é assim que se lê um: no servidor
  // não existe `document`, e o instantâneo de servidor é `null` — "ainda não dá para
  // dizer", que é diferente de "não há token nenhum" e ganha texto próprio lá embaixo.
  const tokens = useSyncExternalStore(subscribeToStyleSheet, themeSnapshot, () => null);
  const [pill, setPill] = useState<StatePillVariant>("info");
  const [spotlight, setSpotlight] = useState<ButtonVariant>("primary");
  const [rowDisabled, setRowDisabled] = useState(false);
  const [sample, setSample] = useState("Acme Indústria");
  const fieldRef = useRef<HTMLInputElement>(null);


  const valueOf = (name: string) =>
    tokens?.find((token) => token.name === name)?.value ?? "";

  return (
    <main className="admin-shell">
      <header className="admin-head">
        <Link className="admin-back" href="/admin">
          <ArrowLeft size={16} /> Voltar à administração
        </Link>
        <div className="design-brand">
          <Brand />
        </div>
        <p className="eyebrow">SISTEMA DE DESIGN</p>
        <h1>A vitrine do One</h1>
        <p className="admin-lead">
          O sistema desenhado numa tela de verdade, num navegador de verdade. É o que torna
          conferível o que antes só existia em captura: os quatro estados semânticos, as
          quatro variantes de botão, o foco de teclado, os três raios e a paleta — com as
          razões de contraste <strong>calculadas aqui</strong>, a partir dos valores que o
          navegador resolveu, e não copiadas de tabela nenhuma.
        </p>
      </header>

      <Section
        eyebrow="ESTADOS SEMÂNTICOS"
        title="Ícone, texto e cor dizem a mesma coisa"
        lead="Nenhum estado depende só da cor: cada pastilha carrega ícone e palavra, o que a
          faz sobreviver a daltonismo, a captura em tons de cinza e a impressão."
      >
        <div className="design-row">
          {PILL_VARIANTS.map((variant) => (
            <div key={variant} className="design-cell">
              <StatePill variant={variant}>{PILL_LABELS[variant]}</StatePill>
              <span className="design-meta">{PILL_MEANINGS[variant]}</span>
            </div>
          ))}
        </div>

        <div className="design-live">
          <p className="eyebrow">A MESMA PASTILHA, TROCANDO DE TIPO</p>
          <div className="design-row">
            {PILL_VARIANTS.map((variant) => (
              <Button
                key={variant}
                variant={variant === pill ? "primary" : "secondary"}
                onClick={() => setPill(variant)}
              >
                {PILL_LABELS[variant]}
              </Button>
            ))}
          </div>
          <div className="design-pill-live">
            <StatePill variant={pill}>{PILL_LABELS[pill]}</StatePill>
            <span className="design-meta">{PILL_MEANINGS[pill]}</span>
          </div>
        </div>
      </Section>

      <Section
        eyebrow="CONTROLES E FOCO"
        title="Quatro variantes, o desabilitado e o anel de teclado"
        lead="O foco é a decisão visual que mais some quando ninguém a desenha, e é a que
          decide se o produto é operável por teclado. Alvo de toque mínimo de 44px."
      >
        <div className="design-row">
          {BUTTON_VARIANTS.map((variant) => (
            <span
              key={variant}
              className={`design-slot${variant === spotlight ? " design-spot" : ""}`}
            >
              <Button
                variant={variant}
                disabled={rowDisabled}
                onClick={() => setSpotlight(variant)}
              >
                {BUTTON_LABELS[variant]}
              </Button>
            </span>
          ))}
        </div>
        <p className="design-meta">
          Em destaque: <strong>{spotlight}</strong>. O anel é o mesmo{" "}
          <code>--color-focus</code> que <code>:focus-visible</code> desenha — navegue com
          Tab para vê-lo aparecer sozinho.
        </p>

        <div className="design-live">
          <p className="eyebrow">DESABILITADO</p>
          <div className="design-row">
            <Button variant="primary" disabled onClick={() => setRowDisabled(false)}>
              Indisponível
            </Button>
            <Button variant="ghost" onClick={() => setRowDisabled(!rowDisabled)}>
              {rowDisabled ? "Reabilitar as quatro acima" : "Desabilitar as quatro acima"}
            </Button>
          </div>
          <p className="design-meta">
            O primeiro está sempre desabilitado — é a amostra. O segundo desabilita a fila
            de cima, para que o estado se veja acontecendo em vez de ser desenhado.
          </p>
        </div>

        <div className="design-live">
          <p className="eyebrow">CAMPO EM REPOUSO E CAMPO COM FOCO</p>
          <div className="design-fields">
            <label className="design-field-label">
              <span>Em repouso</span>
              <input
                ref={fieldRef}
                className="design-field"
                value={sample}
                onChange={(event) => setSample(event.target.value)}
              />
            </label>
            <label className="design-field-label">
              <span>Com foco</span>
              <input
                className="design-field design-field--focus"
                value={sample}
                onChange={(event) => setSample(event.target.value)}
              />
            </label>
          </div>
          <div className="design-row">
            <Button variant="secondary" onClick={() => fieldRef.current?.focus()}>
              Levar o foco ao campo em repouso
            </Button>
          </div>
          <p className="design-meta">
            Borda <code>brand-500</code> mais halo <code>brand-100</code>. Nunca{" "}
            <code>outline: none</code> cru: no Tailwind v4 ele grava{" "}
            <code>--tw-outline-style: none</code> no elemento e faz toda regra de foco
            escrita depois resolver para nada, em silêncio.
          </p>
        </div>
      </Section>

      <Section
        eyebrow="RAIO"
        title="Três valores, e cada um tem um dono"
        lead="Cartão, controle e pastilha. Nunca um quarto raio informal — que é como uma
          tela começa a parecer feita por duas pessoas que não se falaram."
      >
        <div className="design-row">
          {["--radius-card", "--radius-control", "--radius-pill"].map((name) => (
            <div key={name} className="design-cell">
              <span
                className="design-figure"
                style={{ borderRadius: `var(${name})` }}
                aria-hidden="true"
              />
              <code className="design-token">{name}</code>
              <span className="design-meta">{valueOf(name) || "—"}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section
        eyebrow="PALETA"
        title="Os tokens como o navegador os resolveu"
        lead="Esta lista não é digitada: ela é lida da folha de estilo em runtime. Uma
          vitrine que repete os hexes à mão passa a mentir na primeira mudança de token, e
          uma vitrine que mente é pior que nenhuma. Por isso ela mostra mais do que o
          @theme do One declara — vêm junto os degraus do Tailwind que a tela ainda usa
          fora da linguagem, e vê-los aqui é a informação, não o ruído."
      >
        {tokens === null ? (
          <p className="empty-state">Lendo a folha de estilo…</p>
        ) : tokens.length === 0 ? (
          <p className="empty-state">
            Não consegui ler nenhum token da folha de estilo. Isto não quer dizer que o
            <code> @theme</code> esteja vazio — quer dizer que esta tela não tem base para
            afirmar coisa alguma sobre ele.
          </p>
        ) : (
          FAMILIES.map((family) => {
            const ofFamily = tokens.filter((token) => familyOf(token) === family);
            if (ofFamily.length === 0) return null;
            return (
              <div key={family} className="design-live">
                <p className="eyebrow">
                  {FAMILY_TITLES[family]} · {ofFamily.length}
                </p>
                <div className="design-swatches">
                  {ofFamily.map((token) => (
                    <div key={token.name} className="design-swatch">
                      <span
                        className="design-chip"
                        style={chipStyle(family, token.name)}
                        aria-hidden={family !== "font" && family !== "weight"}
                      >
                        {family === "font" || family === "weight" ? "Aa" : ""}
                      </span>
                      <code className="design-token">{token.name}</code>
                      <span className="design-meta">{token.value || "—"}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </Section>

      <Section
        eyebrow="CONTRASTE"
        title="Os pares medidos, recalculados a cada visita"
        lead="Luminância relativa da WCAG 2.1 sobre os valores que o navegador resolveu,
          contra AA para texto normal (4,5:1) — não AA-large, porque nada nesta tela usa
          texto grande."
      >
        <div className="field-list">
          {CONTRAST_PAIRS.map((pair) => {
            const ratio = contrastRatio(valueOf(pair.foreground), valueOf(pair.background));
            return (
              <div key={`${pair.foreground}|${pair.background}`} className="field-row">
                <span className="field-label">
                  <span
                    className="design-pair"
                    style={{
                      color: `var(${pair.foreground})`,
                      background: `var(${pair.background})`,
                    }}
                  >
                    Texto de exemplo
                  </span>
                  <br />
                  <code className="design-token">{pair.foreground}</code> sobre{" "}
                  <code className="design-token">{pair.background}</code> · {pair.role}
                </span>
                <span className="field-value">
                  {ratio === null ? (
                    <StatePill variant="info">sem base para medir</StatePill>
                  ) : (
                    <StatePill variant={ratio >= AA_NORMAL_TEXT ? "success" : "danger"}>
                      {ratio.toFixed(2).replace(".", ",")}:1
                    </StatePill>
                  )}
                </span>
              </div>
            );
          })}
        </div>
        <p className="design-meta">
          Uma razão vermelha aqui é defeito do sistema, não desta tela: o token reprovou o
          critério e a correção é no <code>@theme</code>.
        </p>
      </Section>
    </main>
  );
}
