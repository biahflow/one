/**
 * A guarda de "a pilha está no ar", num lugar só (ADR 0020).
 *
 * Ela existia em quatro cópias, uma por spec, e todas faziam a mesma coisa
 * errada: `test.skip()` quando o `docker compose` não respondia. Fora do CI
 * isso está certo — quem roda o Playwright sem a pilha no ar não quer dezenove
 * falhas, quer um aviso.
 *
 * No CI a mesma frase é mentira. O job `e2e` sobe a pilha inteira antes de
 * chamar o Playwright, então "o docker não respondeu" ali não é uma condição do
 * ambiente de quem desenvolve: é a pilha ter falhado ao subir. Pulado, isso
 * ficava **verde** — e o job ainda era `continue-on-error`, de modo que nem
 * falhar ele podia. Eram dois mecanismos independentes garantindo que o único
 * nível capaz de provar o login de ponta a ponta nunca reprovasse nada.
 *
 * É a mesma regra do `skip_unless_ci` do lado Python, e a mesma que a ADR 0017
 * impôs ao antivírus antes das duas: uma verificação que não aconteceu não é
 * uma verificação que passou.
 */
import { execFileSync } from "node:child_process";

export const STACK_REASON = "Precisa da stack local no ar (docker compose up)";

/** `CI` é definida pelo runner do GitHub Actions. */
export function inCI(): boolean {
  return Boolean(process.env.CI);
}

/** O serviço existe no projeto compose corrente. */
export function serviceIsUp(service: string): boolean {
  try {
    execFileSync("docker", ["compose", "ps", "-q", service], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

/**
 * Traduz "dá para rodar" em "pule" — mas só fora do CI, onde dentro ela falha.
 *
 * Recebe a condição já avaliada, e não o nome do serviço, porque nem toda
 * guarda é uma sonda de contêiner: a de `notifications.spec.ts` é o resultado
 * de um sync que ou aconteceu ou não.
 */
export function stackIsMissing(available: boolean): boolean {
  if (available) return false;
  if (inCI()) {
    throw new Error(
      `${STACK_REASON} — e no CI a pilha é subida pelo próprio job antes dos ` +
        "testes, então isto significa que ela não subiu, não que falta ambiente.",
    );
  }
  return true;
}
