"""O primeiro login de um usuário desconhecido é uma corrida (ADR 0052, defeito 7).

``resolve_user`` seleciona e depois insere. O BFF busca ``/me`` e o dashboard **em
paralelo** — é o desenho, e está escrito no ``CLAUDE.md`` —, de modo que no primeiro
login as duas requisições chegam a ``_provision`` com o mesmo ``sub``: uma ganha, a outra
bate em ``uq_user_email``. A tela mostra "não conseguimos carregar seu projeto", e
recarregar resolve, porque aí a linha existe.

**Por que ninguém tinha visto.** No compose o ``seed`` já cria os usuários, então o
caminho exercitado é sempre o do passo 2 (reivindicar linha semeada). "Primeiro login de
quem o banco não conhece" só acontece contra um banco de verdade sem seed — foi o que a
primeira subida do portal em HML fez.

**Como este teste força a corrida sem thread.** As fixtures de sessão são transacionais e
revertidas ao fim, então duas conexões que comitam não cabem nelas. O que caracteriza a
corrida não é o paralelismo em si: é *a segunda resolução ter feito o seu SELECT antes de
a primeira existir*. Isso se reproduz deixando a linha já inserta na transação e cegando
as buscas **uma vez só** — o ``INSERT`` seguinte encontra a mesma restrição de unicidade
que encontraria em produção, e a releitura da recuperação enxerga, como enxerga lá.

Cegar as buscas para sempre seria caricatura: quem perde a corrida erra o primeiro SELECT
porque a outra transação ainda não comitou, e acerta o segundo justamente porque ela
comitou. Um teste que cega os dois provaria que o código não consegue recuperar de uma
linha que não existe — o que é verdade e não interessa.

E prova as duas metades do conserto: sem ``SAVEPOINT``, o ``IntegrityError`` deixa a
transação do Postgres abortada e a releitura falharia com "current transaction is
aborted" — o mesmo argumento que a ADR 0041 escreveu para ``onboarding.stamp_within``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from portal_api import identity
from portal_api.principal import Principal

pytestmark = pytest.mark.integration


def _cega_uma_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    """Faz a **primeira** busca de cada tipo errar, e as seguintes valerem de verdade.

    É a forma da janela: quem perde a corrida erra o primeiro SELECT porque a outra
    transação ainda não comitou, e acerta o da recuperação porque ela comitou.
    """
    for nome in ("_by_subject", "_claim_seeded_row"):
        real = getattr(identity, nome)
        estado = {"primeira": True}

        def falso(*args: object, _real=real, _estado=estado, **kwargs: object):  # type: ignore[no-untyped-def]
            if _estado["primeira"]:
                _estado["primeira"] = False
                return None
            return _real(*args, **kwargs)

        monkeypatch.setattr(identity, nome, falso)


def _principal() -> Principal:
    return Principal(
        subject="7f0a1c4e-corrida-no-primeiro-login",
        email="corrida@exemplo.test",
        full_name="Quem Chegou Duas Vezes",
    )


def test_duas_resolucoes_do_mesmo_sub_devolvem_a_mesma_linha(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = _principal()
    primeiro = identity.resolve_user(db_session, principal)

    _cega_uma_vez(monkeypatch)
    segundo = identity.resolve_user(db_session, principal)

    assert segundo.id == primeiro.id, (
        "a segunda resolução criou outro usuário ou estourou: o primeiro login de "
        "qualquer pessoa nova cai nesta corrida, porque o BFF paraleliza"
    )


def test_a_transacao_sobrevive_a_corrida(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Depois de recuperar, a sessão ainda serve — é o que o SAVEPOINT compra.

    Sem ele, engolir o ``IntegrityError`` trocaria um erro visível por uma transação
    abortada, e a falha reapareceria mais adiante, longe da causa.
    """
    principal = _principal()
    identity.resolve_user(db_session, principal)
    _cega_uma_vez(monkeypatch)
    identity.resolve_user(db_session, principal)

    # A sessão continua utilizável depois do conflito — é o que o SAVEPOINT compra.
    assert identity._by_subject(db_session, principal.subject) is not None
