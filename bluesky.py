"""Cliente mínimo da API do Bluesky (AT Protocol), só com a biblioteca padrão.

Documentação: https://docs.bsky.app

A autenticação usa uma "senha de app", criada em Configurações > Privacidade
e segurança > Senhas de app. Ela dá acesso à conta, mas pode ser revogada a
qualquer momento sem trocar a senha principal.

O transporte HTTP é recebido por parâmetro, o que permite testar o cliente
sem internet.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

SERVIDOR_PADRAO = "https://bsky.social"
LIMITE_CARACTERES = 300
TEMPO_LIMITE = 20

# transporte(metodo, url, cabecalhos, corpo) -> (status, texto da resposta)
Transporte = Callable[[str, str, dict, "bytes | None"], "tuple[int, str]"]


class ErroBluesky(Exception):
    def __init__(self, mensagem: str, codigo: str = "", status: int = 0) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.status = status


MENSAGENS_ERRO = {
    "AuthenticationRequired": "Usuário ou senha de app incorretos.",
    "AccountTakedown": "Esta conta foi suspensa pelo Bluesky.",
    "RateLimitExceeded": "Limite de requisições atingido. Espere alguns minutos.",
    "InvalidRequest": "Requisição inválida.",
}


def transporte_urllib(metodo: str, url: str, cabecalhos: dict, corpo: bytes | None) -> tuple[int, str]:
    requisicao = urllib.request.Request(url, data=corpo, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE) as resposta:
            return resposta.status, resposta.read().decode("utf-8")
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode("utf-8", errors="replace")


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def contar_caracteres(texto: str) -> int:
    """Aproximação da contagem do Bluesky (que conta grafemas).

    Emojis compostos (ex.: família, bandeiras) contam como vários aqui, então
    a conta nunca fica abaixo da real.
    """
    return len(texto)


# --------------------------------------------------------------------------
# Rich text: links, hashtags e menções viram "facets" com posição em bytes
# --------------------------------------------------------------------------

_REGEX_LINK = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")
_REGEX_TAG = re.compile(r"(?:^|(?<=\s))#([^\s#.,;:!?()\[\]\"']+)")
_REGEX_MENCAO = re.compile(r"(?:^|(?<=[\s(]))@([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,})")


def _bytes(texto: str, inicio: int, fim: int) -> dict[str, int]:
    return {"byteStart": len(texto[:inicio].encode("utf-8")), "byteEnd": len(texto[:fim].encode("utf-8"))}


def gerar_facets(texto: str, resolver: Callable[[str], str | None] | None = None) -> list[dict]:
    """Marca links, #hashtags e @menções para o Bluesky exibir como clicáveis.

    `resolver` converte um handle (fulano.bsky.social) no DID da conta; menções
    que não forem resolvidas ficam como texto simples.
    """
    facets = []
    for achado in _REGEX_LINK.finditer(texto):
        facets.append({"index": _bytes(texto, achado.start(), achado.end()),
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": achado.group()}]})
    for achado in _REGEX_TAG.finditer(texto):
        tag = achado.group(1)
        if tag.isdigit() or len(tag) > 64:
            continue
        facets.append({"index": _bytes(texto, achado.start(1) - 1, achado.end(1)),
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]})
    if resolver:
        for achado in _REGEX_MENCAO.finditer(texto):
            did = resolver(achado.group(1))
            if did:
                facets.append({"index": _bytes(texto, achado.start(1) - 1, achado.end(1)),
                               "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}]})
    facets.sort(key=lambda f: f["index"]["byteStart"])
    return facets


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------

@dataclass
class Post:
    uri: str
    cid: str
    autor_did: str
    autor_handle: str
    autor_nome: str
    texto: str
    criado_em: str
    curtidas: int = 0
    reposts: int = 0
    respostas: int = 0
    curtido: bool = False
    repostado: bool = False
    resposta_a: dict | None = None  # campo "reply" do registro, se for resposta

    @classmethod
    def de_api(cls, dados: dict) -> "Post":
        autor = dados.get("author", {})
        registro = dados.get("record", {})
        viewer = dados.get("viewer", {})
        return cls(
            uri=dados["uri"], cid=dados["cid"], autor_did=autor.get("did", ""),
            autor_handle=autor.get("handle", ""), autor_nome=autor.get("displayName") or autor.get("handle", ""),
            texto=registro.get("text", ""), criado_em=registro.get("createdAt", ""),
            curtidas=dados.get("likeCount", 0), reposts=dados.get("repostCount", 0),
            respostas=dados.get("replyCount", 0), curtido=bool(viewer.get("like")),
            repostado=bool(viewer.get("repost")), resposta_a=registro.get("reply"),
        )

    @property
    def referencia(self) -> dict:
        return {"uri": self.uri, "cid": self.cid}

    @property
    def link(self) -> str:
        return f"https://bsky.app/profile/{self.autor_handle}/post/{self.uri.rsplit('/', 1)[-1]}"


@dataclass
class Notificacao:
    uri: str
    cid: str
    motivo: str  # like, repost, follow, mention, reply, quote
    autor_did: str
    autor_handle: str
    autor_nome: str
    texto: str
    data: str
    lida: bool
    resposta_a: dict | None = None
    autor_seguido: bool = False

    @classmethod
    def de_api(cls, dados: dict) -> "Notificacao":
        autor = dados.get("author", {})
        registro = dados.get("record", {})
        return cls(
            uri=dados["uri"], cid=dados["cid"], motivo=dados.get("reason", ""),
            autor_did=autor.get("did", ""), autor_handle=autor.get("handle", ""),
            autor_nome=autor.get("displayName") or autor.get("handle", ""),
            texto=registro.get("text", "") if isinstance(registro, dict) else "",
            data=dados.get("indexedAt", ""), lida=dados.get("isRead", False),
            resposta_a=registro.get("reply") if isinstance(registro, dict) else None,
            autor_seguido=bool(autor.get("viewer", {}).get("following")),
        )

    @property
    def referencia(self) -> dict:
        return {"uri": self.uri, "cid": self.cid}


@dataclass
class Perfil:
    did: str
    handle: str
    nome: str
    seguindo: bool = False  # se eu sigo esta conta

    @classmethod
    def de_api(cls, dados: dict) -> "Perfil":
        return cls(did=dados["did"], handle=dados.get("handle", ""),
                   nome=dados.get("displayName") or dados.get("handle", ""),
                   seguindo=bool(dados.get("viewer", {}).get("following")))


@dataclass
class Sessao:
    did: str
    handle: str
    token_acesso: str
    token_renovacao: str


def referencia_resposta(alvo_uri: str, alvo_cid: str, alvo_reply: dict | None) -> dict:
    """Monta o campo "reply" de uma resposta: raiz da conversa e post respondido."""
    pai = {"uri": alvo_uri, "cid": alvo_cid}
    raiz = (alvo_reply or {}).get("root") or pai
    return {"root": raiz, "parent": pai}


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------

@dataclass
class ClienteBluesky:
    servidor: str = SERVIDOR_PADRAO
    transporte: Transporte = field(default=transporte_urllib, repr=False)
    sessao: Sessao | None = None
    _cache_handles: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------- HTTP

    def _chamar(self, metodo: str, nsid: str, parametros: dict | None = None, corpo: dict | None = None,
                token: str | None = None, renovar: bool = True) -> dict:
        url = f"{self.servidor.rstrip('/')}/xrpc/{nsid}"
        if parametros:
            url += "?" + urllib.parse.urlencode({k: v for k, v in parametros.items() if v is not None},
                                                doseq=True)
        cabecalhos = {"Accept": "application/json", "User-Agent": "twetter-bot-bluesky/1.0"}
        dados = None
        if corpo is not None:
            cabecalhos["Content-Type"] = "application/json"
            dados = json.dumps(corpo).encode("utf-8")
        if token is None and self.sessao:
            token = self.sessao.token_acesso
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"

        try:
            status, texto = self.transporte(metodo, url, cabecalhos, dados)
        except (urllib.error.URLError, OSError) as erro:
            raise ErroBluesky(f"Sem conexão com {self.servidor}: {erro}") from erro
        try:
            resposta = json.loads(texto) if texto else {}
        except ValueError:
            resposta = {}
        if status < 400:
            return resposta

        codigo = resposta.get("error", "")
        if codigo == "ExpiredToken" and renovar and self.sessao:
            self.renovar_sessao()
            return self._chamar(metodo, nsid, parametros, corpo, renovar=False)
        mensagem = MENSAGENS_ERRO.get(codigo) or resposta.get("message") or f"Erro HTTP {status}"
        raise ErroBluesky(mensagem, codigo, status)

    def _exigir_sessao(self) -> Sessao:
        if not self.sessao:
            raise ErroBluesky("Faça login primeiro.")
        return self.sessao

    # ------------------------------------------------------------- sessão

    def entrar(self, usuario: str, senha_app: str) -> Sessao:
        usuario = usuario.strip().lstrip("@")
        dados = self._chamar("POST", "com.atproto.server.createSession",
                             corpo={"identifier": usuario, "password": senha_app.strip()}, token="")
        self.sessao = Sessao(dados["did"], dados["handle"], dados["accessJwt"], dados["refreshJwt"])
        return self.sessao

    def renovar_sessao(self) -> None:
        sessao = self._exigir_sessao()
        dados = self._chamar("POST", "com.atproto.server.refreshSession", token=sessao.token_renovacao,
                             renovar=False)
        sessao.token_acesso = dados["accessJwt"]
        sessao.token_renovacao = dados["refreshJwt"]

    def resolver_handle(self, handle: str) -> str | None:
        handle = handle.lower().lstrip("@")
        if handle not in self._cache_handles:
            try:
                dados = self._chamar("GET", "com.atproto.identity.resolveHandle", {"handle": handle})
                self._cache_handles[handle] = dados.get("did")
            except ErroBluesky:
                self._cache_handles[handle] = None
        return self._cache_handles[handle]

    # ------------------------------------------------------------- escrita

    def _criar_registro(self, colecao: str, registro: dict) -> dict:
        sessao = self._exigir_sessao()
        registro = {"$type": colecao, **registro, "createdAt": agora_iso()}
        return self._chamar("POST", "com.atproto.repo.createRecord",
                            corpo={"repo": sessao.did, "collection": colecao, "record": registro})

    def publicar(self, texto: str, resposta: dict | None = None, idiomas: list[str] | None = None) -> dict:
        """Publica um post e devolve {"uri", "cid"}. `resposta` vem de referencia_resposta()."""
        texto = texto.strip()
        if not texto:
            raise ErroBluesky("O post está vazio.")
        if contar_caracteres(texto) > LIMITE_CARACTERES:
            raise ErroBluesky(f"O post passa de {LIMITE_CARACTERES} caracteres.")
        registro: dict[str, Any] = {"text": texto, "langs": idiomas or ["pt"]}
        facets = gerar_facets(texto, self.resolver_handle)
        if facets:
            registro["facets"] = facets
        if resposta:
            registro["reply"] = resposta
        return self._criar_registro("app.bsky.feed.post", registro)

    def curtir(self, uri: str, cid: str) -> dict:
        return self._criar_registro("app.bsky.feed.like", {"subject": {"uri": uri, "cid": cid}})

    def repostar(self, uri: str, cid: str) -> dict:
        return self._criar_registro("app.bsky.feed.repost", {"subject": {"uri": uri, "cid": cid}})

    def seguir(self, did: str) -> dict:
        return self._criar_registro("app.bsky.graph.follow", {"subject": did})

    # ------------------------------------------------------------- leitura

    def buscar_posts(self, termo: str, limite: int = 25, idioma: str | None = None) -> list[Post]:
        dados = self._chamar("GET", "app.bsky.feed.searchPosts",
                             {"q": termo, "limit": min(limite, 100), "lang": idioma, "sort": "latest"})
        return [Post.de_api(p) for p in dados.get("posts", [])]

    def notificacoes(self, limite: int = 50) -> list[Notificacao]:
        dados = self._chamar("GET", "app.bsky.notification.listNotifications", {"limit": min(limite, 100)})
        return [Notificacao.de_api(n) for n in dados.get("notifications", [])]

    def marcar_notificacoes_lidas(self) -> None:
        self._chamar("POST", "app.bsky.notification.updateSeen", corpo={"seenAt": agora_iso()})

    def seguidores(self, limite: int = 100) -> list[Perfil]:
        sessao = self._exigir_sessao()
        perfis: list[Perfil] = []
        cursor = None
        while len(perfis) < limite:
            dados = self._chamar("GET", "app.bsky.graph.getFollowers",
                                 {"actor": sessao.did, "limit": min(100, limite - len(perfis)), "cursor": cursor})
            perfis += [Perfil.de_api(p) for p in dados.get("followers", [])]
            cursor = dados.get("cursor")
            if not cursor or not dados.get("followers"):
                break
        return perfis
