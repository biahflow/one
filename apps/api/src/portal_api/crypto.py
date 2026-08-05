"""Cifra simétrica para segredo que precisa voltar em claro (ADR 0016).

Este é o primeiro segredo **reversível** do repositório, e a diferença com
``agent_auth.hash_key`` é a razão de existir um módulo novo em vez de uma função
lá dentro.

A chave de agente só precisa ser **verificada**: o portal recebe uma chave,
calcula o HMAC e compara. Nunca precisa recuperá-la — e é por isso que o HMAC é a
escolha certa lá, porque um vazamento do banco não devolve credencial nenhuma.

O refresh token do Google não tem essa forma. Ele precisa ser **reapresentado** ao
provedor a cada sincronização, então o portal tem de conseguir lê-lo de volta. Não
existe "comparar" um refresh token; existe usá-lo.

O que se perde com isso é real e vale dizer em voz alta: com a chave de cifra, o
conteúdo do banco vira credencial. É a mesma exposição de ``agent_key_pepper``, com
uma consequência a mais — lá o par (banco + pepper) ainda exigiria alguém
apresentando a chave em claro; aqui o par (banco + chave) já é o segredo. Daí a
chave viver só em variável de ambiente, nunca no banco que ela protege, e daí a
falha ser fechada quando ela não existe.

**AES-GCM com AAD, e não Fernet**, por uma razão concreta: ``portal_admin`` escreve
nesta tabela, e um ciphertext sem vínculo criptográfico ao tenant é um ciphertext
copiável de uma linha para outra. Amarrando o dado associado a
``drive-refresh:<organization_id>:<project_id>``, um refresh token movido para
outro projeto **falha a decifra** em vez de sincronizar a pasta errada. A RLS já
impede a leitura cruzada; isto é a segunda barreira, e custa uma string.

**Duas chaves, e a segunda não é luxo.** O pepper da ADR 0013 pode ser rotacionado
porque as chaves de agente são reemissíveis — basta gerar outra. Aqui não: girar a
chave sem uma janela de decifra obrigaria **cada projeto a refazer o consentimento
no Google**. O identificador da chave viaja no próprio texto selado, então o sync
seguinte decifra com a anterior e re-sela com a atual, sem migração de dados.

Formato: ``v1.<key_id>.<nonce b64url>.<ciphertext b64url>``.
"""

from __future__ import annotations

import base64
import hashlib
import os

from portal_api.config import Settings, get_settings

#: Versão do formato. Existe para uma troca de primitivo no futuro ser detectável
#: no próprio dado, em vez de ser adivinhada pelo tamanho.
VERSION = "v1"
#: AES-256-GCM: 32 bytes de chave, 12 de nonce (o tamanho recomendado pelo NIST,
#: e o único em que o GCM é usado sem ressalva).
KEY_BYTES = 32
NONCE_BYTES = 12


class SealedSecretError(RuntimeError):
    """A chave não está configurada, ou o texto selado não abre com ela."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_key() -> str:
    """Chave nova no formato que ``DRIVE_TOKEN_ENCRYPTION_KEY`` espera.

    Existe para o runbook e para os testes terem uma forma canônica de produzir
    uma chave válida — não é chamada pelo caminho de requisição.
    """
    return _b64encode(os.urandom(KEY_BYTES))


def _key_material(value: str) -> bytes:
    try:
        raw = _b64decode(value)
    except Exception as exc:
        raise SealedSecretError("encryption key is malformed") from exc
    if len(raw) != KEY_BYTES:
        raise SealedSecretError("encryption key is malformed")
    return raw


def _key_id(raw: bytes) -> str:
    """Rótulo público da chave. Não é segredo — é o que permite decifrar com a
    anterior sem tentar as duas às cegas, e é seguro num log."""
    return hashlib.sha256(raw).hexdigest()[:8]


def _keys(settings: Settings) -> list[bytes]:
    """A atual primeiro, a anterior depois. Sem chave nenhuma, falha fechada."""
    values = [settings.drive_token_encryption_key, settings.drive_token_encryption_key_previous]
    keys = [_key_material(value) for value in values if value]
    if not keys:
        # Como `hash_key` sem pepper: sem chave configurada nenhuma conexão do
        # Drive funciona, em vez de um ambiente mal configurado guardar refresh
        # token em claro sem ninguém notar.
        raise SealedSecretError("DRIVE_TOKEN_ENCRYPTION_KEY is not configured")
    return keys


def ensure_configured(settings: Settings | None = None) -> None:
    """Levanta se não há chave. Existe para quem precisa falhar **antes** de agir.

    A rota de conectar usa isto: começar um consentimento sem poder selar o
    refresh token deixaria a pessoa atravessar a tela do Google para descobrir no
    fim que nada foi guardado.
    """
    _keys(settings or get_settings())


def aad_for(organization_id: object, project_id: object) -> str:
    """O dado associado que amarra o segredo ao tenant.

    Uma função e não uma f-string espalhada: se o formato mudar num lugar e não no
    outro, todas as conexões param de abrir de uma vez.
    """
    return f"drive-refresh:{organization_id}:{project_id}"


def seal(plaintext: str, *, aad: str, settings: Settings | None = None) -> str:
    """Cifra e autentica sob a chave **atual**. O retorno cabe numa coluna de texto."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    settings = settings or get_settings()
    key = _keys(settings)[0]
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode())
    return ".".join([VERSION, _key_id(key), _b64encode(nonce), _b64encode(ciphertext)])


def unseal(sealed: str, *, aad: str, settings: Settings | None = None) -> str:
    """Devolve o texto em claro, ou levanta ``SealedSecretError``.

    Tenta a chave cujo id está no texto; se ela não estiver configurada, não tenta
    as outras — abrir com uma chave que não foi a que selou é impossível de
    qualquer forma, e sair cedo mantém o erro legível.
    """
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    settings = settings or get_settings()
    keys = _keys(settings)

    parts = sealed.split(".")
    if len(parts) != 4 or parts[0] != VERSION:
        raise SealedSecretError("sealed secret is not in the expected format")
    _, key_id, nonce_b64, ciphertext_b64 = parts

    key = next((candidate for candidate in keys if _key_id(candidate) == key_id), None)
    if key is None:
        # Chave girada sem janela, ou banco restaurado noutro ambiente. Os dois
        # casos têm a mesma resposta operacional: reconectar a pasta.
        raise SealedSecretError("sealed secret was written with an unknown key")

    try:
        raw = AESGCM(key).decrypt(_b64decode(nonce_b64), _b64decode(ciphertext_b64), aad.encode())
    except (InvalidTag, ValueError) as exc:
        # `InvalidTag` cobre tanto adulteração quanto AAD errado — e o AAD errado
        # é justamente o ciphertext movido para outro projeto.
        raise SealedSecretError("sealed secret does not open with the current key") from exc
    return raw.decode()


def needs_resealing(sealed: str, settings: Settings | None = None) -> bool:
    """Se o texto foi selado com a chave anterior, o próximo sync re-sela.

    É o que faz a rotação terminar sozinha, sem migração e sem ninguém refazer o
    consentimento no Google.
    """
    settings = settings or get_settings()
    parts = sealed.split(".")
    if len(parts) != 4:
        return False
    return parts[1] != _key_id(_keys(settings)[0])
