"""Servidor Bluesky simulado para os testes: responde no formato da API real
e guarda as chamadas recebidas."""

import json
import urllib.parse

MEU_DID = "did:plc:minhaconta"


def post_api(n, autor="maria.bsky.social", did=None, texto="Aprendendo Python hoje", curtido=False,
             resposta=None):
    registro = {"$type": "app.bsky.feed.post", "text": texto, "createdAt": "2026-11-18T12:00:00.000Z"}
    if resposta:
        registro["reply"] = resposta
    return {
        "uri": f"at://{did or 'did:plc:' + autor.split('.')[0]}/app.bsky.feed.post/{n}",
        "cid": f"bafy{n}",
        "author": {"did": did or f"did:plc:{autor.split('.')[0]}", "handle": autor,
                   "displayName": autor.split(".")[0].title()},
        "record": registro,
        "likeCount": 3, "repostCount": 1, "replyCount": 0,
        "viewer": {"like": "at://x/app.bsky.feed.like/1"} if curtido else {},
    }


def notificacao_api(n, motivo="mention", autor="joao.bsky.social", texto="@eu preciso de ajuda", resposta=None):
    registro = {"$type": "app.bsky.feed.post", "text": texto, "createdAt": "2026-11-18T12:00:00.000Z"}
    if resposta:
        registro["reply"] = resposta
    return {
        "uri": f"at://did:plc:{autor.split('.')[0]}/app.bsky.feed.post/n{n}", "cid": f"bafyn{n}",
        "author": {"did": f"did:plc:{autor.split('.')[0]}", "handle": autor, "viewer": {}},
        "reason": motivo, "record": registro, "isRead": False, "indexedAt": "2026-11-18T12:00:01.000Z",
    }


class ServidorFalso:
    def __init__(self):
        self.chamadas = []  # (nsid, parametros, corpo, cabeçalho Authorization)
        self.posts_busca = {"python": [post_api(1), post_api(2, autor="eu.bsky.social", did=MEU_DID),
                                       post_api(3, curtido=True), post_api(4, autor="ana.bsky.social")]}
        self.notificacoes = []
        self.seguidores = []
        self.senha_certa = "abcd-efgh-ijkl-mnop"
        self.token_expirado = False
        self.handles = {"maria.bsky.social": "did:plc:maria"}
        self.registros = 0

    def criados(self, colecao=None):
        return [c[2] for c in self.chamadas
                if c[0] == "com.atproto.repo.createRecord" and (colecao is None or c[2]["collection"] == colecao)]

    def __call__(self, metodo, url, cabecalhos, corpo):
        partes = urllib.parse.urlsplit(url)
        nsid = partes.path.rsplit("/", 1)[-1]
        parametros = dict(urllib.parse.parse_qsl(partes.query))
        dados = json.loads(corpo) if corpo else None
        self.chamadas.append((nsid, parametros, dados, cabecalhos.get("Authorization")))

        def ok(resposta):
            return 200, json.dumps(resposta)

        def erro(status, codigo, mensagem=""):
            return status, json.dumps({"error": codigo, "message": mensagem})

        if nsid == "com.atproto.server.createSession":
            if dados["password"] != self.senha_certa:
                return erro(401, "AuthenticationRequired", "Invalid identifier or password")
            return ok({"did": MEU_DID, "handle": "eu.bsky.social", "accessJwt": "acesso1", "refreshJwt": "renova1"})
        if nsid == "com.atproto.server.refreshSession":
            self.token_expirado = False
            return ok({"did": MEU_DID, "handle": "eu.bsky.social", "accessJwt": "acesso2", "refreshJwt": "renova2"})
        if self.token_expirado:
            return erro(400, "ExpiredToken", "Token has expired")
        if nsid == "com.atproto.identity.resolveHandle":
            did = self.handles.get(parametros["handle"])
            return ok({"did": did}) if did else erro(400, "InvalidRequest", "Unable to resolve handle")
        if nsid == "com.atproto.repo.createRecord":
            self.registros += 1
            return ok({"uri": f"at://{MEU_DID}/{dados['collection']}/r{self.registros}", "cid": f"bafyr{self.registros}"})
        if nsid == "app.bsky.feed.searchPosts":
            return ok({"posts": self.posts_busca.get(parametros["q"].lower(), [])})
        if nsid == "app.bsky.notification.listNotifications":
            return ok({"notifications": self.notificacoes})
        if nsid == "app.bsky.graph.getFollowers":
            return ok({"subject": {"did": MEU_DID}, "followers": self.seguidores})
        if nsid == "app.bsky.notification.updateSeen":
            return 200, ""
        return erro(404, "MethodNotImplemented")
