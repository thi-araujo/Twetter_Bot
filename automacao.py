"""Regras do bot automático e configuração salva em disco.

São as mesmas ideias dos bots originais de 2022 para o Twitter:
- curtir (e opcionalmente repostar) posts com certas palavras;
- responder menções que contenham certas palavras;
- seguir de volta quem segue a conta.

Cada ciclo tem limites baixos de ações, para o bot não parecer spam nem
estourar o limite de requisições do Bluesky.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from bluesky import ClienteBluesky, ErroBluesky, Notificacao, Perfil, Post, referencia_resposta

ARQUIVO_CONFIG = Path.home() / ".bluesky_bot.json"
MAX_PROCESSADOS = 2000
INTERVALO_MINIMO_MIN = 5


def simplificar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras-chave."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def contem_alguma(texto: str, palavras: list[str]) -> bool:
    alvo = simplificar(texto)
    return any(simplificar(p).strip() and simplificar(p).strip() in alvo for p in palavras)


def separar_palavras(texto: str) -> list[str]:
    return [p.strip() for p in texto.split(",") if p.strip()]


@dataclass
class Regras:
    curtir_ativo: bool = False
    curtir_palavras: list[str] = field(default_factory=lambda: ["python"])
    repostar_tambem: bool = False
    curtir_limite: int = 5

    responder_ativo: bool = False
    responder_palavras: list[str] = field(default_factory=lambda: ["ajuda", "suporte"])
    responder_texto: str = "Oi! Vi sua mensagem e respondo assim que puder."
    responder_limite: int = 5

    seguir_de_volta: bool = False
    seguir_limite: int = 10

    intervalo_min: int = 15


@dataclass
class Agendado:
    texto: str
    quando: str  # "AAAA-MM-DD HH:MM", horário local

    @property
    def data_hora(self) -> datetime:
        return datetime.strptime(self.quando, "%Y-%m-%d %H:%M")


@dataclass
class Configuracao:
    usuario: str = ""
    servidor: str = "https://bsky.social"
    regras: Regras = field(default_factory=Regras)
    agendados: list[Agendado] = field(default_factory=list)
    processados: list[str] = field(default_factory=list)  # URIs já tratadas pelo bot

    def marcar_processado(self, uri: str) -> None:
        self.processados.append(uri)
        if len(self.processados) > MAX_PROCESSADOS:
            del self.processados[: len(self.processados) - MAX_PROCESSADOS]

    def salvar(self, caminho: Path = ARQUIVO_CONFIG) -> None:
        caminho.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def carregar(cls, caminho: Path = ARQUIVO_CONFIG) -> "Configuracao":
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            regras_padrao = asdict(Regras())
            regras = Regras(**{k: dados.get("regras", {}).get(k, v) for k, v in regras_padrao.items()})
            agendados = []
            for item in dados.get("agendados", []):
                agendado = Agendado(str(item["texto"]), str(item["quando"]))
                agendado.data_hora  # valida o formato
                agendados.append(agendado)
            return cls(usuario=str(dados.get("usuario", "")),
                       servidor=str(dados.get("servidor", "https://bsky.social")),
                       regras=regras, agendados=agendados,
                       processados=[str(u) for u in dados.get("processados", [])][-MAX_PROCESSADOS:])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return cls()


# --------------------------------------------------------------------------
# Seleção (funções puras, fáceis de testar)
# --------------------------------------------------------------------------

def posts_para_curtir(posts: list[Post], meu_did: str, processados: set[str], limite: int) -> list[Post]:
    escolhidos = []
    for post in posts:
        if len(escolhidos) >= limite:
            break
        if post.autor_did == meu_did or post.resposta_a or post.curtido or post.uri in processados:
            continue
        escolhidos.append(post)
    return escolhidos


def mencoes_para_responder(notificacoes: list[Notificacao], palavras: list[str], meu_did: str,
                           processados: set[str], limite: int) -> list[Notificacao]:
    escolhidas = []
    for n in notificacoes:
        if len(escolhidas) >= limite:
            break
        if n.motivo not in ("mention", "reply") or n.autor_did == meu_did or n.uri in processados:
            continue
        if contem_alguma(n.texto, palavras):
            escolhidas.append(n)
    return escolhidas


def seguidores_para_seguir(seguidores: list[Perfil], meu_did: str, limite: int) -> list[Perfil]:
    return [p for p in seguidores if not p.seguindo and p.did != meu_did][:limite]


def agendados_vencidos(agendados: list[Agendado], agora: datetime) -> list[Agendado]:
    return [a for a in agendados if a.data_hora <= agora]


# --------------------------------------------------------------------------
# Ciclo do bot
# --------------------------------------------------------------------------

def executar_ciclo(cliente: ClienteBluesky, config: Configuracao,
                   registrar: Callable[[str], None] = print) -> int:
    """Executa uma rodada das regras ativas e devolve quantas ações foram feitas."""
    sessao = cliente.sessao
    if sessao is None:
        raise ErroBluesky("Faça login primeiro.")
    regras = config.regras
    processados = set(config.processados)
    acoes = 0

    if regras.curtir_ativo and regras.curtir_palavras:
        posts: list[Post] = []
        vistos: set[str] = set()
        for termo in regras.curtir_palavras:
            try:
                encontrados = cliente.buscar_posts(termo, limite=25)
            except ErroBluesky as erro:
                registrar(f"Erro na busca por \"{termo}\": {erro}")
                continue
            for post in encontrados:
                if post.uri not in vistos:
                    vistos.add(post.uri)
                    posts.append(post)
        for post in posts_para_curtir(posts, sessao.did, processados, regras.curtir_limite):
            try:
                cliente.curtir(post.uri, post.cid)
                acao = "Curtido"
                if regras.repostar_tambem and not post.repostado:
                    cliente.repostar(post.uri, post.cid)
                    acao = "Curtido e repostado"
                registrar(f"{acao}: @{post.autor_handle}: {post.texto[:60]}")
                acoes += 1
            except ErroBluesky as erro:
                registrar(f"Erro ao curtir post de @{post.autor_handle}: {erro}")
            config.marcar_processado(post.uri)
            processados.add(post.uri)

    if regras.responder_ativo and regras.responder_palavras and regras.responder_texto.strip():
        try:
            notificacoes = cliente.notificacoes(limite=50)
        except ErroBluesky as erro:
            registrar(f"Erro ao ler notificações: {erro}")
            notificacoes = []
        for n in mencoes_para_responder(notificacoes, regras.responder_palavras, sessao.did, processados,
                                        regras.responder_limite):
            try:
                cliente.publicar(regras.responder_texto, resposta=referencia_resposta(n.uri, n.cid, n.resposta_a))
                registrar(f"Respondido: @{n.autor_handle}: {n.texto[:60]}")
                acoes += 1
            except ErroBluesky as erro:
                registrar(f"Erro ao responder @{n.autor_handle}: {erro}")
            config.marcar_processado(n.uri)
            processados.add(n.uri)

    if regras.seguir_de_volta:
        try:
            seguidores = cliente.seguidores(limite=100)
        except ErroBluesky as erro:
            registrar(f"Erro ao ler seguidores: {erro}")
            seguidores = []
        for perfil in seguidores_para_seguir(seguidores, sessao.did, regras.seguir_limite):
            try:
                cliente.seguir(perfil.did)
                registrar(f"Seguindo de volta: @{perfil.handle}")
                acoes += 1
            except ErroBluesky as erro:
                registrar(f"Erro ao seguir @{perfil.handle}: {erro}")

    return acoes


def publicar_agendados(cliente: ClienteBluesky, config: Configuracao, agora: datetime,
                       registrar: Callable[[str], None] = print) -> int:
    publicados = 0
    for agendado in agendados_vencidos(config.agendados, agora):
        try:
            cliente.publicar(agendado.texto)
            registrar(f"Post agendado publicado: {agendado.texto[:60]}")
            publicados += 1
            config.agendados.remove(agendado)
        except ErroBluesky as erro:
            registrar(f"Erro ao publicar post agendado: {erro}")
            if erro.codigo != "RateLimitExceeded" and erro.status not in (0, 429, 500, 502, 503):
                config.agendados.remove(agendado)  # erro permanente: não tenta de novo
    return publicados
