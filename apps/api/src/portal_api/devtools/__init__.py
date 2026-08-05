"""Ferramentas de desenvolvimento — nunca importadas pelo caminho de requisição.

O que mora aqui existe para a stack local e para o e2e. Nada em ``portal_api``
fora deste pacote importa nada dele, e é essa a linha que impede um dublê de
provedor de virar dependência acidental de produção.
"""
