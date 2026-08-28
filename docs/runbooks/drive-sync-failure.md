# Runbook — Falha de Drive

Pausar a pasta afetada, preservar último índice válido, renovar autorização somente pelo
administrador autorizado e notificar os membros internos. **Nunca ampliar escopo de Drive para
contornar a falha.**

O conector já implementa a primeira metade disso sozinho (ADR 0016): consentimento vencido pausa
a pasta e não toca no índice, e uma listagem incompleta nunca remove nada. O que sobra para uma
pessoa é diagnosticar e reconectar.

## Onde olhar primeiro

A própria linha da conexão responde quase tudo, e a tela `/admin/knowledge` a mostra:
`last_sync_at`, `last_sync_error` e `last_sync_stats`. Não é preciso ler log para saber o que a
última sincronização fez.

| Sintoma na tela | Causa provável | O que fazer |
|---|---|---|
| "A sincronização está pausada" + *Autorização revogada* | Consentimento retirado na conta Google, **ou o app do Google ainda está em "Testing"** | Reconectar a pasta (ver abaixo) |
| `failed` com erro de rede, pasta ainda ligada | Indisponibilidade do Google | Nada. O próximo tick tenta de novo; o índice está intacto |
| `running` há muito tempo | Worker morreu no meio | Espera `DRIVE_SYNC_STALE_AFTER_SECONDS` (30 min) e o próximo tick reivindica |
| "Sincronizado" mas o chat não cita | O documento pode estar `unsupported` | Ver o estado na lista; o motivo está na linha |
| `rejected > 0` em `last_sync_stats` | Atalhos ou arquivos de fora da pasta | Esperado. É a fronteira funcionando |
| `truncated: true` | A pasta passou de `DRIVE_MAX_FILES` | Reorganizar a pasta, ou subir o teto conscientemente |

## A armadilha do "Testing"

Enquanto o app do Google estiver em modo **Testing** no console, o refresh token **expira em
sete dias**. A conexão funciona a semana toda e morre sem ninguém mexer em nada. É a causa mais
comum de "parou de sincronizar do nada" numa demo. A correção é publicar o app, não reconectar
toda semana.

## Reconectar

1. `/admin/knowledge`, no projeto afetado.
2. "Conectar Google Drive" e consentir novamente. O `state` anterior já não vale — ele é de uso
   único e tem prazo.
3. Conferir que a pasta autorizada continua a certa (a reconexão não a perde, mas trocar de
   pasta é a operação mais consequente da tela).
4. "Sincronizar agora" para não esperar o próximo tick.

Reconectar **não** apaga nada: os documentos já indexados continuam, e o sync seguinte
reconcilia.

## Pausar sem desconectar

`enabled = false` na linha da conexão é o que este runbook chama de "pausar a pasta". Desconectar
jogaria fora o consentimento junto com o problema; pausar mantém a credencial e para o sync.
Hoje o worker faz isso sozinho quando o consentimento vence — e a tela oferece reconectar, não
"despausar", porque o caso em que ela pausa é justamente aquele em que a credencial não serve mais.

## O que nunca fazer

- **Ampliar o escopo.** `drive.readonly` é o único aceito, e a conexão é recusada se o Google
  conceder outro. Um erro de sync nunca é resolvido por mais permissão.
- **Apagar documento do Drive pela tela.** Ele não é apagável ali de propósito — voltaria no
  próximo sync. Tire-o da pasta e o sync o remove.
- **Rodar dois `beat`.** Ele é singleton; duas réplicas geram ticks duplicados. A guarda de
  sobreposição absorve, mas o desenho não é esse.
- **Girar `DRIVE_TOKEN_ENCRYPTION_KEY` sem passar a antiga em
  `DRIVE_TOKEN_ENCRYPTION_KEY_PREVIOUS`.** Sem a janela, **todo projeto precisa refazer o
  consentimento**. Com ela, o sync seguinte re-sela sozinho e a antiga pode sair depois.
