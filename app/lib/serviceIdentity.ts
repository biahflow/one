/**
 * A identidade **do serviço**, que é outra coisa que a identidade da pessoa.
 *
 * A `portal-api` sobe com `INGRESS_TRAFFIC_INTERNAL_ONLY` e sem `allUsers` no
 * `run.invoker`, e o módulo do Cloud Run chama isso de duas barreiras: rede e
 * identidade. A segunda **não estava sendo exercida por ninguém** — o BFF manda o
 * token do Keycloak, que diz quem é o usuário e não diz nada ao Cloud Run, então
 * toda chamada interna levaria 403 antes de chegar na aplicação (ADR 0046).
 *
 * O token vai em `X-Serverless-Authorization` e não em `Authorization`, e o header
 * existe exatamente para este caso: `Authorization` já carrega o token de acesso do
 * usuário, e o Cloud Run tira o dele do header próprio antes de repassar a
 * requisição. Sobrepor os dois faria a API perder o principal e responder 401 para
 * uma chamada autorizada.
 *
 * **Não é um segundo mecanismo de autorização.** Quem decide o que a pessoa alcança
 * continua sendo o `access.py`, sob o token do Keycloak. Este aqui só responde ao
 * Cloud Run "esta chamada vem de dentro, e de quem".
 */

/**
 * O host do servidor de metadados. Só existe dentro do Google Cloud.
 *
 * `GCE_METADATA_HOST` é o nome que as bibliotecas do Google já honram para isto —
 * reusá-lo em vez de inventar um deixa o comportamento igual ao do resto do
 * ecossistema, e é o que permite um teste apontar para um servidor de mentira sem
 * o módulo ganhar um parâmetro que só existe para testar.
 */
function metadata(): string {
  const host = process.env.GCE_METADATA_HOST;
  return host ? `http://${host}` : "http://metadata.google.internal";
}

/** Margem antes da expiração. Um token que vence no voo vira 403 intermitente. */
const MARGEM_SEGUNDOS = 300;

type TokenEmCache = { valor: string; expiraEm: number };

const cache = new Map<string, TokenEmCache>();

/**
 * Estamos no Cloud Run?
 *
 * `K_SERVICE` é posto pelo próprio Cloud Run. Fora dele — máquina de alguém, o
 * compose, o CI — não há servidor de metadados, e tentar buscar token custaria um
 * timeout por requisição para conseguir nada.
 */
export function rodandoNoCloudRun(): boolean {
  return Boolean(process.env.K_SERVICE);
}

/** A audiência é a URL **base** do serviço chamado, sem caminho. */
function audienciaDe(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/** O `exp` do JWT, em segundos. `null` quando o formato não é o esperado. */
function expiracaoDe(jwt: string): number | null {
  const partes = jwt.split(".");
  if (partes.length !== 3) return null;
  try {
    const payload = JSON.parse(
      Buffer.from(partes[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"),
    );
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

/**
 * Um ID token para chamar `urlDoServico`, ou `null` quando não há como obtê-lo.
 *
 * **Devolve `null` em vez de levantar**, e é decisão: fora do Cloud Run não há
 * token a buscar e a chamada é local, onde a barreira não existe. Uma exceção aqui
 * transformaria "rodar o portal na sua máquina" em erro de servidor.
 */
export async function tokenDeServico(urlDoServico: string): Promise<string | null> {
  if (!rodandoNoCloudRun()) return null;

  const audiencia = audienciaDe(urlDoServico);
  if (!audiencia) return null;

  const agora = Math.floor(Date.now() / 1000);
  const guardado = cache.get(audiencia);
  if (guardado && guardado.expiraEm - MARGEM_SEGUNDOS > agora) return guardado.valor;

  const endereco =
    `${metadata()}/computeMetadata/v1/instance/service-accounts/default/identity` +
    `?audience=${encodeURIComponent(audiencia)}`;

  let resposta: Response;
  try {
    resposta = await fetch(endereco, {
      headers: { "Metadata-Flavor": "Google" },
      // O servidor de metadados é local e responde em milissegundos. Se ele demora,
      // algo está errado e esperar não conserta — melhor a chamada falhar depressa.
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
  } catch {
    return null;
  }

  if (!resposta.ok) return null;
  const valor = (await resposta.text()).trim();
  if (!valor) return null;

  const exp = expiracaoDe(valor);
  // Sem `exp` legível, guarda por pouco tempo em vez de não guardar: o caminho
  // quente não pode depender de uma chamada de rede por requisição.
  cache.set(audiencia, { valor, expiraEm: exp ?? agora + 600 });
  return valor;
}

/** Só para teste: esquece o que está guardado. */
export function limparCacheDeToken(): void {
  cache.clear();
}
