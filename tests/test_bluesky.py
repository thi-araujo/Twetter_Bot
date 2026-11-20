import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bluesky import ClienteBluesky, ErroBluesky, gerar_facets, referencia_resposta  # noqa: E402
from servidor_falso import MEU_DID, ServidorFalso, post_api  # noqa: E402

SENHA = "abcd-efgh-ijkl-mnop"


class TestFacets(unittest.TestCase):
    def test_link_e_hashtag_com_posicao_em_bytes(self):
        texto = "Olá #Python, veja https://docs.bsky.app."
        facets = gerar_facets(texto)
        self.assertEqual(len(facets), 2)
        tag, link = facets
        self.assertEqual(tag["features"][0], {"$type": "app.bsky.richtext.facet#tag", "tag": "Python"})
        # "Olá " tem 5 bytes em UTF-8 (á ocupa 2)
        self.assertEqual(tag["index"], {"byteStart": 5, "byteEnd": 12})
        self.assertEqual(link["features"][0]["uri"], "https://docs.bsky.app")  # sem o ponto final
        inicio, fim = link["index"]["byteStart"], link["index"]["byteEnd"]
        self.assertEqual(texto.encode()[inicio:fim].decode(), "https://docs.bsky.app")

    def test_mencao_resolvida(self):
        resolver = {"maria.bsky.social": "did:plc:maria"}.get
        facets = gerar_facets("Valeu @maria.bsky.social e @ninguem.bsky.social!", resolver)
        self.assertEqual(len(facets), 1)
        self.assertEqual(facets[0]["features"][0]["did"], "did:plc:maria")
        self.assertEqual(facets[0]["index"], {"byteStart": 6, "byteEnd": 24})

    def test_ignora_hashtag_numerica_e_email(self):
        self.assertEqual(gerar_facets("Item #1 e contato@exemplo.com"), [])


class TestCliente(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorFalso()
        self.cliente = ClienteBluesky(transporte=self.servidor)

    def entrar(self):
        self.cliente.entrar("@eu.bsky.social", SENHA)

    def test_login(self):
        sessao = self.cliente.entrar(" @eu.bsky.social ", SENHA)
        self.assertEqual(sessao.did, MEU_DID)
        nsid, _, corpo, autorizacao = self.servidor.chamadas[0]
        self.assertEqual(corpo["identifier"], "eu.bsky.social")
        self.assertIsNone(autorizacao)

    def test_senha_errada(self):
        with self.assertRaises(ErroBluesky) as contexto:
            self.cliente.entrar("eu.bsky.social", "errada")
        self.assertEqual(str(contexto.exception), "Usuário ou senha de app incorretos.")
        self.assertIsNone(self.cliente.sessao)

    def test_precisa_de_login(self):
        with self.assertRaises(ErroBluesky):
            self.cliente.publicar("oi")

    def test_publicar(self):
        self.entrar()
        resposta = self.cliente.publicar("Meu primeiro post com @maria.bsky.social #python")
        self.assertIn("uri", resposta)
        corpo = self.servidor.criados("app.bsky.feed.post")[0]
        self.assertEqual(corpo["repo"], MEU_DID)
        registro = corpo["record"]
        self.assertEqual(registro["$type"], "app.bsky.feed.post")
        self.assertEqual(registro["langs"], ["pt"])
        self.assertTrue(registro["createdAt"].endswith("Z"))
        self.assertEqual({f["features"][0]["$type"].rsplit("#")[-1] for f in registro["facets"]}, {"mention", "tag"})
        self.assertEqual(self.servidor.chamadas[-1][3], "Bearer acesso1")

    def test_post_vazio_ou_longo(self):
        self.entrar()
        for texto in ("   ", "x" * 301):
            with self.assertRaises(ErroBluesky):
                self.cliente.publicar(texto)
        self.assertEqual(self.servidor.criados(), [])

    def test_resposta_mantem_raiz_da_conversa(self):
        raiz = {"uri": "at://a/app.bsky.feed.post/raiz", "cid": "c0"}
        ref = referencia_resposta("at://b/app.bsky.feed.post/meio", "c1", {"root": raiz, "parent": raiz})
        self.assertEqual(ref["root"], raiz)
        self.assertEqual(ref["parent"]["uri"], "at://b/app.bsky.feed.post/meio")
        primeira = referencia_resposta("at://b/app.bsky.feed.post/x", "c2", None)
        self.assertEqual(primeira["root"], primeira["parent"])

    def test_curtir_repostar_seguir(self):
        self.entrar()
        self.cliente.curtir("at://x/app.bsky.feed.post/1", "c1")
        self.cliente.repostar("at://x/app.bsky.feed.post/1", "c1")
        self.cliente.seguir("did:plc:maria")
        colecoes = [c["collection"] for c in self.servidor.criados()]
        self.assertEqual(colecoes, ["app.bsky.feed.like", "app.bsky.feed.repost", "app.bsky.graph.follow"])
        self.assertEqual(self.servidor.criados()[0]["record"]["subject"],
                         {"uri": "at://x/app.bsky.feed.post/1", "cid": "c1"})
        self.assertEqual(self.servidor.criados()[2]["record"]["subject"], "did:plc:maria")

    def test_buscar(self):
        self.entrar()
        posts = self.cliente.buscar_posts("python")
        self.assertEqual(len(posts), 4)
        self.assertEqual(posts[0].autor_handle, "maria.bsky.social")
        self.assertTrue(posts[2].curtido)
        self.assertEqual(posts[0].link, "https://bsky.app/profile/maria.bsky.social/post/1")
        self.assertEqual(self.servidor.chamadas[-1][1]["sort"], "latest")

    def test_renova_token_expirado(self):
        self.entrar()
        self.servidor.token_expirado = True
        self.cliente.buscar_posts("python")
        nsids = [c[0] for c in self.servidor.chamadas]
        self.assertEqual(nsids[-3:], ["app.bsky.feed.searchPosts", "com.atproto.server.refreshSession",
                                      "app.bsky.feed.searchPosts"])
        self.assertEqual(self.servidor.chamadas[-2][3], "Bearer renova1")
        self.assertEqual(self.servidor.chamadas[-1][3], "Bearer acesso2")

    def test_sem_conexao(self):
        def sem_rede(*_):
            raise OSError("rede indisponível")
        cliente = ClienteBluesky(transporte=sem_rede)
        with self.assertRaises(ErroBluesky) as contexto:
            cliente.entrar("eu.bsky.social", SENHA)
        self.assertIn("Sem conexão", str(contexto.exception))

    def test_post_de_api_com_campos_faltando(self):
        dados = post_api(9)
        del dados["author"]["displayName"], dados["viewer"], dados["likeCount"]
        from bluesky import Post
        post = Post.de_api(dados)
        self.assertEqual(post.autor_nome, "maria.bsky.social")
        self.assertEqual(post.curtidas, 0)


if __name__ == "__main__":
    unittest.main()
