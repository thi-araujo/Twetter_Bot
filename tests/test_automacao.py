import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import automacao as au  # noqa: E402
from bluesky import ClienteBluesky  # noqa: E402
from servidor_falso import MEU_DID, ServidorFalso, notificacao_api  # noqa: E402


class TestPalavras(unittest.TestCase):
    def test_ignora_maiusculas_e_acentos(self):
        self.assertTrue(au.contem_alguma("Preciso de AJUDA!", ["ajuda"]))
        self.assertTrue(au.contem_alguma("Dúvida sobre o bot", ["duvida"]))
        self.assertFalse(au.contem_alguma("Bom dia", ["ajuda", ""]))

    def test_separar(self):
        self.assertEqual(au.separar_palavras(" python, tkinter ,,bluesky "), ["python", "tkinter", "bluesky"])


class TestCiclo(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorFalso()
        self.cliente = ClienteBluesky(transporte=self.servidor)
        self.cliente.entrar("eu.bsky.social", self.servidor.senha_certa)
        self.config = au.Configuracao()
        self.log = []

    def rodar(self):
        return au.executar_ciclo(self.cliente, self.config, self.log.append)

    def test_curtir_por_palavra(self):
        self.config.regras.curtir_ativo = True
        self.config.regras.curtir_palavras = ["python"]
        self.assertEqual(self.rodar(), 2)  # pula o próprio post e o já curtido
        curtidos = [c["record"]["subject"]["uri"] for c in self.servidor.criados("app.bsky.feed.like")]
        self.assertEqual([u.rsplit("/", 1)[-1] for u in curtidos], ["1", "4"])
        self.assertEqual(self.servidor.criados("app.bsky.feed.repost"), [])
        # Segundo ciclo não repete
        self.assertEqual(self.rodar(), 0)

    def test_curtir_e_repostar_com_limite(self):
        regras = self.config.regras
        regras.curtir_ativo, regras.curtir_palavras, regras.repostar_tambem, regras.curtir_limite = (
            True, ["python"], True, 1)
        self.assertEqual(self.rodar(), 1)
        self.assertEqual(len(self.servidor.criados("app.bsky.feed.repost")), 1)

    def test_responder_mencoes(self):
        raiz = {"uri": "at://did:plc:x/app.bsky.feed.post/raiz", "cid": "c0"}
        self.servidor.notificacoes = [
            notificacao_api(1, texto="@eu preciso de AJUDA com o bot"),
            notificacao_api(2, texto="@eu bom dia"),
            notificacao_api(3, motivo="like"),
            notificacao_api(4, motivo="reply", texto="suporte por favor", resposta={"root": raiz, "parent": raiz}),
        ]
        regras = self.config.regras
        regras.responder_ativo = True
        self.assertEqual(self.rodar(), 2)
        respostas = [c["record"] for c in self.servidor.criados("app.bsky.feed.post")]
        self.assertEqual(respostas[0]["text"], regras.responder_texto)
        self.assertEqual(respostas[0]["reply"]["parent"]["uri"], self.servidor.notificacoes[0]["uri"])
        self.assertEqual(respostas[1]["reply"]["root"], raiz)
        self.assertEqual(self.rodar(), 0)

    def test_seguir_de_volta(self):
        self.servidor.seguidores = [
            {"did": "did:plc:a", "handle": "a.bsky.social", "viewer": {}},
            {"did": "did:plc:b", "handle": "b.bsky.social", "viewer": {"following": "at://x"}},
        ]
        self.config.regras.seguir_de_volta = True
        self.assertEqual(self.rodar(), 1)
        self.assertEqual(self.servidor.criados("app.bsky.graph.follow")[0]["record"]["subject"], "did:plc:a")

    def test_nada_ativo_nao_chama_api(self):
        chamadas = len(self.servidor.chamadas)
        self.assertEqual(self.rodar(), 0)
        self.assertEqual(len(self.servidor.chamadas), chamadas)

    def test_agendados(self):
        self.config.agendados = [au.Agendado("Bom dia!", "2026-11-18 08:00"),
                                 au.Agendado("Boa noite!", "2026-11-18 22:00")]
        publicados = au.publicar_agendados(self.cliente, self.config, datetime(2026, 11, 18, 9, 0), self.log.append)
        self.assertEqual(publicados, 1)
        self.assertEqual([a.texto for a in self.config.agendados], ["Boa noite!"])
        self.assertEqual(self.servidor.criados("app.bsky.feed.post")[0]["record"]["text"], "Bom dia!")


class TestConfiguracao(unittest.TestCase):
    def test_salvar_e_carregar(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "config.json"
            config = au.Configuracao(usuario="eu.bsky.social", agendados=[au.Agendado("oi", "2026-12-01 10:00")])
            config.regras.curtir_palavras = ["tkinter"]
            config.marcar_processado("at://x/1")
            config.salvar(arquivo)
            carregada = au.Configuracao.carregar(arquivo)
            self.assertEqual(carregada, config)
            self.assertNotIn("senha", arquivo.read_text(encoding="utf-8").lower())

    def test_arquivo_invalido(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "config.json"
            arquivo.write_text('{"agendados": [{"texto": "x", "quando": "amanhã"}]}', encoding="utf-8")
            self.assertEqual(au.Configuracao.carregar(arquivo), au.Configuracao())

    def test_limite_de_processados(self):
        config = au.Configuracao()
        for i in range(au.MAX_PROCESSADOS + 10):
            config.marcar_processado(str(i))
        self.assertEqual(len(config.processados), au.MAX_PROCESSADOS)
        self.assertEqual(config.processados[0], "10")


if __name__ == "__main__":
    unittest.main()
