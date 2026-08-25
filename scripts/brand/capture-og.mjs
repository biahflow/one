/**
 * Gera `public/og.png` a partir de `scripts/brand/og-card.html` (F-025 T03).
 *
 * Mora em `scripts/` pela razão do `backup.sh`, do `loadtest.py` e do `audit.mjs`:
 * é operação, não produto — nada em `app/` ou em `apps/api/` o importa, e ele não
 * roda em CI. Existe para que o cartão de compartilhamento continue tendo fonte:
 * o `og.png` que ele substituiu era um binário sem origem, e por isso estampou o
 * nome antigo até alguém abrir a imagem.
 *
 * Captura a 1×, com viewport de 1200×630 — o tamanho exato do cartão, e não o
 * dobro dele. O anterior tinha 1,1 MB por ter sido salvo grande demais.
 *
 *   node scripts/brand/capture-og.mjs
 */
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..", "..");
const source = path.join(root, "scripts", "brand", "og-card.html");
const target = path.join(root, "public", "og.png");

const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1200, height: 630 },
    deviceScaleFactor: 1,
  });
  await page.goto(pathToFileURL(source).href);
  // `document.fonts.ready` e não um `waitForTimeout`: o que atrasa a pintura aqui
  // é a fonte, e esperar por ela é determinístico onde esperar por relógio não é.
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: target });
} finally {
  await browser.close();
}

console.log(`escrito: ${path.relative(root, target)}`);
