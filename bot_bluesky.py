"""Bot para o Bluesky com interface gráfica.

    python bot_bluesky.py

Entre com seu usuário (ex.: fulano.bsky.social) e uma SENHA DE APP, criada no
Bluesky em Configurações > Privacidade e segurança > Senhas de app.
Também é possível preencher o login pelas variáveis de ambiente
BLUESKY_USUARIO e BLUESKY_SENHA_APP.
"""

from __future__ import annotations

import os
import platform
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any, Callable

import automacao as au
from bluesky import LIMITE_CARACTERES, ClienteBluesky, ErroBluesky, contar_caracteres, referencia_resposta

VERIFICAR_AGENDADOS_MS = 30_000
MOTIVOS = {"like": "Curtiu", "repost": "Repostou", "follow": "Seguiu você", "mention": "Mencionou",
           "reply": "Respondeu", "quote": "Citou"}

CORES = {
    "fundo": "#0f172a",
    "painel": "#1e293b",
    "borda": "#334155",
    "texto": "#e2e8f0",
    "texto_suave": "#94a3b8",
    "destaque": "#38bdf8",
    "verde": "#22c55e",
    "vermelho": "#ef4444",
    "ambar": "#f59e0b",
}

WINDOWS = platform.system() == "Windows"
FONTE = "Segoe UI" if WINDOWS else "Helvetica"
FONTE_MONO = "Consolas" if WINDOWS else "DejaVu Sans Mono"


def resumo(texto: str, tamanho: int = 90) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= tamanho else texto[: tamanho - 1] + "…"


def data_local(iso: str) -> str:
    try:
        quando = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso[:16]
    return quando.strftime("%d/%m %H:%M")


def configurar_estilo(raiz: tk.Tk) -> None:
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")
    sem_borda = dict(bordercolor=CORES["painel"], lightcolor=CORES["painel"], darkcolor=CORES["painel"])
    fundo_sem_borda = dict(bordercolor=CORES["fundo"], lightcolor=CORES["fundo"], darkcolor=CORES["fundo"])
    estilo.configure(".", background=CORES["fundo"], foreground=CORES["texto"], font=(FONTE, 10))
    estilo.configure("Painel.TFrame", background=CORES["painel"])
    estilo.configure("Painel.TLabel", background=CORES["painel"])
    estilo.configure("Suave.TLabel", foreground=CORES["texto_suave"])
    estilo.configure("PainelSuave.TLabel", background=CORES["painel"], foreground=CORES["texto_suave"])
    estilo.configure("Titulo.TLabel", background=CORES["painel"], foreground=CORES["destaque"],
                     font=(FONTE, 11, "bold"))
    estilo.configure("TNotebook", background=CORES["fundo"], borderwidth=0, tabmargins=(16, 8, 16, 0),
                     **fundo_sem_borda)
    estilo.configure("TNotebook.Tab", background=CORES["painel"], foreground=CORES["texto_suave"],
                     padding=(16, 7), borderwidth=0, font=(FONTE, 10, "bold"), **fundo_sem_borda)
    estilo.map("TNotebook.Tab", background=[("selected", CORES["borda"])],
               foreground=[("selected", CORES["destaque"])], expand=[("selected", (0, 0, 0, 0))])
    estilo.configure("TButton", background=CORES["borda"], foreground=CORES["texto"], borderwidth=0,
                     padding=(12, 6), font=(FONTE, 10, "bold"))
    estilo.map("TButton", background=[("disabled", CORES["painel"]), ("active", "#475569")],
               foreground=[("disabled", CORES["texto_suave"])])
    estilo.configure("Destaque.TButton", background=CORES["destaque"], foreground=CORES["fundo"])
    estilo.map("Destaque.TButton", background=[("disabled", CORES["painel"]), ("active", "#0ea5e9")])
    estilo.configure("Verde.TButton", background=CORES["verde"], foreground="#052e16")
    estilo.map("Verde.TButton", background=[("disabled", CORES["painel"]), ("active", "#16a34a")])
    estilo.configure("Perigo.TButton", background=CORES["vermelho"], foreground="white")
    estilo.map("Perigo.TButton", background=[("disabled", CORES["painel"]), ("active", "#dc2626")])
    estilo.configure("TCheckbutton", background=CORES["painel"], foreground=CORES["texto"])
    estilo.map("TCheckbutton", background=[("active", CORES["painel"])],
               indicatorcolor=[("selected", CORES["destaque"]), ("!selected", CORES["fundo"])])
    campo = dict(fieldbackground=CORES["fundo"], foreground=CORES["texto"], insertcolor=CORES["texto"],
                 bordercolor=CORES["borda"], lightcolor=CORES["fundo"], darkcolor=CORES["fundo"])
    estilo.configure("TEntry", **campo)
    estilo.configure("TSpinbox", arrowcolor=CORES["texto"], background=CORES["borda"], **campo)
    estilo.configure("Treeview", background=CORES["painel"], fieldbackground=CORES["painel"],
                     foreground=CORES["texto"], borderwidth=0, rowheight=30, **sem_borda)
    estilo.configure("Treeview.Heading", background=CORES["borda"], foreground=CORES["texto_suave"],
                     borderwidth=0, font=(FONTE, 9, "bold"), padding=(6, 5))
    estilo.map("Treeview", background=[("selected", CORES["borda"])],
               foreground=[("selected", CORES["destaque"])])
    estilo.configure("Vertical.TScrollbar", background=CORES["borda"], troughcolor=CORES["painel"],
                     borderwidth=0, arrowcolor=CORES["texto_suave"], **sem_borda)
    estilo.map("Vertical.TScrollbar", background=[("disabled", CORES["painel"]), ("active", "#475569")],
               arrowcolor=[("disabled", CORES["painel"])])


def tabela(pai: tk.Widget, colunas: list[tuple[str, str, int, str]], altura: int = 10) -> ttk.Treeview:
    quadro = ttk.Frame(pai)
    quadro.pack(fill="both", expand=True)
    arvore = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", height=altura,
                          selectmode="browse")
    for chave, titulo, largura, ancora in colunas:
        arvore.heading(chave, text=titulo, anchor=ancora)
        arvore.column(chave, width=largura, anchor=ancora, stretch=chave in ("texto", "post"))
    barra = ttk.Scrollbar(quadro, orient="vertical", command=arvore.yview)
    arvore.configure(yscrollcommand=barra.set)
    arvore.pack(side="left", fill="both", expand=True)
    barra.pack(side="right", fill="y")
    return arvore


class Aplicativo(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bot para Bluesky")
        self.geometry("900x660")
        self.minsize(820, 600)
        self.configure(bg=CORES["fundo"])
        configurar_estilo(self)

        self.config_app = au.Configuracao.carregar()
        self.cliente = ClienteBluesky(servidor=self.config_app.servidor)
        self.respostas: queue.Queue = queue.Queue()
        self.posts_busca: dict[str, Any] = {}
        self.notificacoes: dict[str, Any] = {}
        self.respondendo: dict | None = None
        self.bot_ligado = False
        self._timer_bot: str | None = None

        self.tela_login = self._montar_login()
        self.tela_principal: ttk.Frame | None = None
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.after(100, self._processar_respostas)

    # ------------------------------------------------------------------ tarefas

    def em_segundo_plano(self, funcao: Callable[[], Any], ao_concluir: Callable[[Any], None],
                         ao_falhar: Callable[[ErroBluesky], None] | None = None) -> None:
        """Executa uma chamada de rede sem travar a janela."""
        def tarefa():
            try:
                self.respostas.put((ao_concluir, funcao()))
            except ErroBluesky as erro:
                self.respostas.put((ao_falhar or self._erro_padrao, erro))
        threading.Thread(target=tarefa, daemon=True).start()

    def _processar_respostas(self) -> None:
        while True:
            try:
                retorno, valor = self.respostas.get_nowait()
            except queue.Empty:
                break
            retorno(valor)
        self.after(100, self._processar_respostas)

    def _erro_padrao(self, erro: ErroBluesky) -> None:
        self.status(str(erro), "vermelho")

    def status(self, texto: str, cor: str = "texto_suave") -> None:
        if self.tela_principal:
            self.lbl_status.configure(text=texto, foreground=CORES[cor])

    def _salvar(self) -> None:
        try:
            self.config_app.salvar()
        except OSError as erro:
            self.status(f"Não foi possível salvar a configuração: {erro}", "vermelho")

    # ------------------------------------------------------------------ login

    def _montar_login(self) -> ttk.Frame:
        tela = ttk.Frame(self)
        tela.pack(fill="both", expand=True)
        caixa = ttk.Frame(tela, style="Painel.TFrame", padding=28)
        caixa.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(caixa, text="🦋  Bot para Bluesky", font=(FONTE, 18, "bold"), bg=CORES["painel"],
                 fg=CORES["destaque"]).pack(anchor="w")
        ttk.Label(caixa, text="Publique, agende, busque e automatize ações na sua conta.",
                  style="PainelSuave.TLabel").pack(anchor="w", pady=(2, 18))

        self.var_usuario = tk.StringVar(value=os.environ.get("BLUESKY_USUARIO") or self.config_app.usuario)
        self.var_senha = tk.StringVar(value=os.environ.get("BLUESKY_SENHA_APP", ""))
        self.var_servidor = tk.StringVar(value=self.config_app.servidor)
        campos = (("Usuário", self.var_usuario, "", "ex.: fulano.bsky.social"),
                  ("Senha de app", self.var_senha, "•", "Configurações > Privacidade e segurança > Senhas de app"),
                  ("Servidor", self.var_servidor, "", "deixe como está, a não ser que use outro servidor"))
        for rotulo, var, oculto, dica in campos:
            ttk.Label(caixa, text=rotulo, style="Painel.TLabel", font=(FONTE, 10, "bold")).pack(anchor="w")
            entrada = ttk.Entry(caixa, textvariable=var, show=oculto, width=42)
            entrada.pack(anchor="w", ipady=3, pady=(3, 1))
            entrada.bind("<Return>", lambda _e: self._entrar())
            ttk.Label(caixa, text=dica, style="PainelSuave.TLabel", font=(FONTE, 8)).pack(anchor="w", pady=(0, 10))

        self.btn_entrar = ttk.Button(caixa, text="Entrar", style="Destaque.TButton", command=self._entrar)
        self.btn_entrar.pack(fill="x", pady=(6, 0))
        self.lbl_login = ttk.Label(caixa, text="Use uma senha de app, nunca a senha principal da conta.",
                                   style="PainelSuave.TLabel", font=(FONTE, 9), wraplength=340)
        self.lbl_login.pack(anchor="w", pady=(10, 0))
        return tela

    def _entrar(self) -> None:
        usuario, senha = self.var_usuario.get().strip(), self.var_senha.get().strip()
        if not usuario or not senha:
            self.lbl_login.configure(text="Preencha o usuário e a senha de app.", foreground=CORES["ambar"])
            return
        self.cliente.servidor = self.var_servidor.get().strip() or "https://bsky.social"
        self.btn_entrar.state(["disabled"])
        self.lbl_login.configure(text="Entrando...", foreground=CORES["destaque"])

        def falhou(erro: ErroBluesky) -> None:
            self.btn_entrar.state(["!disabled"])
            self.lbl_login.configure(text=str(erro), foreground=CORES["vermelho"])

        self.em_segundo_plano(lambda: self.cliente.entrar(usuario, senha), self._logado, falhou)

    def _logado(self, sessao) -> None:
        self.var_senha.set("")
        self.config_app.usuario = sessao.handle
        self.config_app.servidor = self.cliente.servidor
        self._salvar()
        self.tela_login.destroy()
        self._montar_principal(sessao.handle)
        self.status(f"Conectado como @{sessao.handle}.", "verde")
        self.after(1000, self._verificar_agendados)
        self.carregar_notificacoes()

    def _sair(self) -> None:
        self._parar_bot()
        self.cliente.sessao = None
        if self.tela_principal:
            self.tela_principal.destroy()
            self.tela_principal = None
        self.tela_login = self._montar_login()

    # ------------------------------------------------------------------ tela principal

    def _montar_principal(self, handle: str) -> None:
        self.tela_principal = ttk.Frame(self)
        self.tela_principal.pack(fill="both", expand=True)
        topo = ttk.Frame(self.tela_principal, padding=(16, 12, 16, 0))
        topo.pack(fill="x")
        tk.Label(topo, text="🦋  Bot para Bluesky", font=(FONTE, 14, "bold"), bg=CORES["fundo"],
                 fg=CORES["destaque"]).pack(side="left")
        ttk.Button(topo, text="Sair", command=self._sair).pack(side="right")
        ttk.Label(topo, text=f"@{handle}", style="Suave.TLabel").pack(side="right", padx=10)

        rodape = ttk.Frame(self.tela_principal, padding=(16, 6, 16, 10))
        rodape.pack(side="bottom", fill="x")
        self.lbl_status = ttk.Label(rodape, text="", style="Suave.TLabel")
        self.lbl_status.pack(side="left")

        self.abas = ttk.Notebook(self.tela_principal)
        self.abas.pack(fill="both", expand=True)
        for titulo, montar in (("Publicar", self._aba_publicar), ("Buscar", self._aba_buscar),
                               ("Notificações", self._aba_notificacoes), ("Bot automático", self._aba_bot)):
            aba = ttk.Frame(self.abas, padding=16)
            montar(aba)
            self.abas.add(aba, text=titulo)

    # ------------------------------------------------------------------ aba Publicar

    def _aba_publicar(self, aba: ttk.Frame) -> None:
        self.aba_publicar = aba
        painel = ttk.Frame(aba, style="Painel.TFrame", padding=14)
        painel.pack(fill="x")
        cabeca = ttk.Frame(painel, style="Painel.TFrame")
        cabeca.pack(fill="x")
        ttk.Label(cabeca, text="Novo post", style="Titulo.TLabel").pack(side="left")
        self.lbl_resposta = ttk.Label(cabeca, text="", style="PainelSuave.TLabel")
        self.lbl_resposta.pack(side="left", padx=10)
        self.btn_cancelar_resposta = ttk.Button(cabeca, text="Cancelar resposta", command=self._cancelar_resposta)

        self.txt_post = tk.Text(painel, height=5, wrap="word", bg=CORES["fundo"], fg=CORES["texto"],
                                insertbackground=CORES["texto"], relief="flat", font=(FONTE, 11), padx=10,
                                pady=8, highlightthickness=1, highlightbackground=CORES["borda"],
                                highlightcolor=CORES["destaque"])
        self.txt_post.pack(fill="x", pady=(10, 6))
        self.txt_post.bind("<<Modified>>", self._contar)

        linha = ttk.Frame(painel, style="Painel.TFrame")
        linha.pack(fill="x")
        self.lbl_contador = ttk.Label(linha, text=f"0/{LIMITE_CARACTERES}", style="PainelSuave.TLabel",
                                      font=(FONTE_MONO, 10))
        self.lbl_contador.pack(side="left")
        ttk.Label(linha, text="  Links, #hashtags e @menções ficam clicáveis.", style="PainelSuave.TLabel",
                  font=(FONTE, 9)).pack(side="left")
        self.btn_publicar = ttk.Button(linha, text="Publicar agora", style="Destaque.TButton",
                                       command=self._publicar)
        self.btn_publicar.pack(side="right")

        agenda = ttk.Frame(painel, style="Painel.TFrame")
        agenda.pack(fill="x", pady=(12, 0))
        ttk.Label(agenda, text="Agendar para", style="Painel.TLabel").pack(side="left")
        daqui_1h = datetime.now() + timedelta(hours=1)
        self.var_data = tk.StringVar(value=daqui_1h.strftime("%d/%m/%Y"))
        self.var_hora = tk.StringVar(value=daqui_1h.strftime("%H"))
        self.var_minuto = tk.StringVar(value="00")
        ttk.Entry(agenda, textvariable=self.var_data, width=11).pack(side="left", padx=(8, 6), ipady=2)
        for var, maximo in ((self.var_hora, 23), (self.var_minuto, 59)):
            ttk.Spinbox(agenda, from_=0, to=maximo, textvariable=var, width=3, wrap=True,
                        format="%02.0f").pack(side="left")
            if var is self.var_hora:
                ttk.Label(agenda, text=":", style="Painel.TLabel").pack(side="left", padx=2)
        ttk.Button(agenda, text="Agendar", command=self._agendar).pack(side="left", padx=10)

        ttk.Button(aba, text="Remover agendamento", command=self._remover_agendado).pack(
            side="bottom", anchor="e", pady=(8, 0))
        ttk.Label(aba, text="Posts agendados (publicados enquanto o programa estiver aberto)",
                  style="Suave.TLabel").pack(anchor="w", pady=(14, 6))
        self.tbl_agendados = tabela(aba, [("quando", "Quando", 130, "w"), ("texto", "Post", 500, "w")], altura=4)
        self._atualizar_agendados()

    def _contar(self, _evento=None) -> None:
        self.txt_post.edit_modified(False)
        total = contar_caracteres(self.txt_post.get("1.0", "end-1c"))
        excedeu = total > LIMITE_CARACTERES
        self.lbl_contador.configure(text=f"{total}/{LIMITE_CARACTERES}",
                                    foreground=CORES["vermelho"] if excedeu else CORES["texto_suave"])
        self.btn_publicar.state(["disabled"] if excedeu or total == 0 else ["!disabled"])

    def _texto_post(self) -> str | None:
        texto = self.txt_post.get("1.0", "end-1c").strip()
        if not texto:
            self.status("Escreva o post primeiro.", "ambar")
            return None
        if contar_caracteres(texto) > LIMITE_CARACTERES:
            self.status(f"O post passa de {LIMITE_CARACTERES} caracteres.", "ambar")
            return None
        return texto

    def _publicar(self) -> None:
        texto = self._texto_post()
        if not texto:
            return
        resposta = self.respondendo
        self.btn_publicar.state(["disabled"])
        self.status("Publicando...", "destaque")

        def pronto(resultado) -> None:
            self.txt_post.delete("1.0", "end")
            self._cancelar_resposta()
            self.status("Post publicado." if not resposta else "Resposta publicada.", "verde")

        def falhou(erro) -> None:
            self._contar()
            self.status(f"Não foi possível publicar: {erro}", "vermelho")

        self.em_segundo_plano(lambda: self.cliente.publicar(texto, resposta=resposta), pronto, falhou)

    def _agendar(self) -> None:
        texto = self._texto_post()
        if not texto:
            return
        try:
            data = datetime.strptime(self.var_data.get().strip(), "%d/%m/%Y")
            quando = data.replace(hour=int(self.var_hora.get()), minute=int(self.var_minuto.get()))
        except ValueError:
            self.status("Data ou hora inválida. Use DD/MM/AAAA.", "ambar")
            return
        if quando <= datetime.now():
            self.status("Escolha um horário no futuro.", "ambar")
            return
        if self.respondendo:
            self.status("Respostas não podem ser agendadas; publique agora.", "ambar")
            return
        self.config_app.agendados.append(au.Agendado(texto, quando.strftime("%Y-%m-%d %H:%M")))
        self.config_app.agendados.sort(key=lambda a: a.quando)
        self._salvar()
        self.txt_post.delete("1.0", "end")
        self._atualizar_agendados()
        self.status(f"Post agendado para {quando:%d/%m/%Y %H:%M}.", "verde")

    def _atualizar_agendados(self) -> None:
        self.tbl_agendados.delete(*self.tbl_agendados.get_children())
        for i, agendado in enumerate(self.config_app.agendados):
            self.tbl_agendados.insert("", "end", iid=str(i), values=(
                agendado.data_hora.strftime("%d/%m/%Y %H:%M"), resumo(agendado.texto)))

    def _remover_agendado(self) -> None:
        selecao = self.tbl_agendados.selection()
        if selecao:
            del self.config_app.agendados[int(selecao[0])]
            self._salvar()
            self._atualizar_agendados()

    def _verificar_agendados(self) -> None:
        if not self.cliente.sessao:
            return
        vencidos = au.agendados_vencidos(self.config_app.agendados, datetime.now())
        if vencidos:
            mensagens: list[str] = []

            def pronto(publicados: int) -> None:
                self._salvar()
                self._atualizar_agendados()
                for mensagem in mensagens:
                    self._registrar(mensagem)
                if publicados:
                    self.status(f"{publicados} post(s) agendado(s) publicado(s).", "verde")

            self.em_segundo_plano(
                lambda: au.publicar_agendados(self.cliente, self.config_app, datetime.now(), mensagens.append), pronto)
        self.after(VERIFICAR_AGENDADOS_MS, self._verificar_agendados)

    def responder(self, autor: str, uri: str, cid: str, reply: dict | None) -> None:
        self.respondendo = referencia_resposta(uri, cid, reply)
        self.lbl_resposta.configure(text=f"Respondendo a @{autor}", foreground=CORES["ambar"])
        self.btn_cancelar_resposta.pack(side="right")
        self.abas.select(self.aba_publicar)
        self.txt_post.focus_set()

    def _cancelar_resposta(self) -> None:
        self.respondendo = None
        self.lbl_resposta.configure(text="")
        self.btn_cancelar_resposta.pack_forget()

    # ------------------------------------------------------------------ aba Buscar

    def _aba_buscar(self, aba: ttk.Frame) -> None:
        linha = ttk.Frame(aba)
        linha.pack(fill="x", pady=(0, 10))
        self.var_busca = tk.StringVar()
        entrada = ttk.Entry(linha, textvariable=self.var_busca, font=(FONTE, 11))
        entrada.pack(side="left", fill="x", expand=True, ipady=3)
        entrada.bind("<Return>", lambda _e: self._buscar())
        ttk.Button(linha, text="Buscar", style="Destaque.TButton", command=self._buscar).pack(side="left", padx=(8, 0))

        self.tbl_busca = tabela(aba, [("autor", "Autor", 170, "w"), ("texto", "Post", 460, "w"),
                                      ("curtidas", "♥", 50, "center"), ("data", "Quando", 90, "center")])
        self.tbl_busca.tag_configure("curtido", foreground=CORES["vermelho"])
        self.tbl_busca.bind("<Double-1>", lambda _e: self._abrir_post(self.tbl_busca, self.posts_busca))
        botoes = ttk.Frame(aba)
        botoes.pack(fill="x", pady=(10, 0))
        ttk.Button(botoes, text="♥ Curtir", command=lambda: self._acao_post("curtir")).pack(side="left")
        ttk.Button(botoes, text="Repostar", command=lambda: self._acao_post("repostar")).pack(side="left", padx=8)
        ttk.Button(botoes, text="Responder", command=self._responder_busca).pack(side="left")
        ttk.Button(botoes, text="Abrir no navegador",
                   command=lambda: self._abrir_post(self.tbl_busca, self.posts_busca)).pack(side="right")

    def _buscar(self) -> None:
        termo = self.var_busca.get().strip()
        if not termo:
            return
        self.status(f"Buscando \"{termo}\"...", "destaque")

        def pronto(posts) -> None:
            self.tbl_busca.delete(*self.tbl_busca.get_children())
            self.posts_busca = {p.uri: p for p in posts}
            for p in posts:
                self.tbl_busca.insert("", "end", iid=p.uri, tags=("curtido",) if p.curtido else (), values=(
                    f"@{p.autor_handle}", resumo(p.texto), p.curtidas, data_local(p.criado_em)))
            self.status(f"{len(posts)} post(s) encontrados para \"{termo}\".", "verde" if posts else "ambar")

        self.em_segundo_plano(lambda: self.cliente.buscar_posts(termo, limite=50), pronto)

    def _post_selecionado(self):
        selecao = self.tbl_busca.selection()
        return self.posts_busca.get(selecao[0]) if selecao else None

    def _acao_post(self, acao: str) -> None:
        post = self._post_selecionado()
        if not post:
            self.status("Selecione um post na lista.", "ambar")
            return
        if acao == "curtir":
            funcao, feito = (lambda: self.cliente.curtir(post.uri, post.cid)), "Curtido"
        else:
            funcao, feito = (lambda: self.cliente.repostar(post.uri, post.cid)), "Repostado"

        def pronto(_resultado) -> None:
            if acao == "curtir":
                post.curtido = True
                post.curtidas += 1
                self.tbl_busca.item(post.uri, tags=("curtido",))
                self.tbl_busca.set(post.uri, "curtidas", post.curtidas)
            self.status(f"{feito}: post de @{post.autor_handle}.", "verde")

        self.em_segundo_plano(funcao, pronto)

    def _responder_busca(self) -> None:
        post = self._post_selecionado()
        if post:
            self.responder(post.autor_handle, post.uri, post.cid, post.resposta_a)

    def _abrir_post(self, arvore: ttk.Treeview, itens: dict) -> None:
        selecao = arvore.selection()
        item = itens.get(selecao[0]) if selecao else None
        if item is not None and hasattr(item, "link"):
            webbrowser.open(item.link)
        elif item is not None:
            webbrowser.open(f"https://bsky.app/profile/{item.autor_handle}")

    # ------------------------------------------------------------------ aba Notificações

    def _aba_notificacoes(self, aba: ttk.Frame) -> None:
        linha = ttk.Frame(aba)
        linha.pack(fill="x", pady=(0, 10))
        ttk.Button(linha, text="Atualizar", style="Destaque.TButton",
                   command=self.carregar_notificacoes).pack(side="left")
        self.lbl_notificacoes = ttk.Label(linha, text="", style="Suave.TLabel")
        self.lbl_notificacoes.pack(side="left", padx=10)

        self.tbl_notif = tabela(aba, [("tipo", "Tipo", 100, "w"), ("autor", "De", 170, "w"),
                                      ("texto", "Texto", 420, "w"), ("data", "Quando", 90, "center")])
        self.tbl_notif.tag_configure("nova", foreground=CORES["destaque"])
        botoes = ttk.Frame(aba)
        botoes.pack(fill="x", pady=(10, 0))
        ttk.Button(botoes, text="Responder", command=self._responder_notificacao).pack(side="left")
        ttk.Button(botoes, text="♥ Curtir", command=self._curtir_notificacao).pack(side="left", padx=8)
        ttk.Button(botoes, text="Seguir de volta", command=self._seguir_notificacao).pack(side="left")
        ttk.Button(botoes, text="Abrir perfil",
                   command=lambda: self._abrir_post(self.tbl_notif, self.notificacoes)).pack(side="right")

    def carregar_notificacoes(self) -> None:
        def pronto(lista) -> None:
            self.tbl_notif.delete(*self.tbl_notif.get_children())
            self.notificacoes = {n.uri: n for n in lista}
            novas = 0
            for n in lista:
                novas += not n.lida
                texto = resumo(n.texto) if n.motivo in ("mention", "reply", "quote") else ""
                self.tbl_notif.insert("", "end", iid=n.uri, tags=() if n.lida else ("nova",), values=(
                    MOTIVOS.get(n.motivo, n.motivo), f"@{n.autor_handle}", texto, data_local(n.data)))
            self.lbl_notificacoes.configure(text=f"{novas} nova(s) de {len(lista)}")
            if novas:
                self.em_segundo_plano(self.cliente.marcar_notificacoes_lidas, lambda _r: None, lambda _e: None)

        self.em_segundo_plano(lambda: self.cliente.notificacoes(limite=50), pronto)

    def _notificacao_selecionada(self):
        selecao = self.tbl_notif.selection()
        if not selecao:
            self.status("Selecione uma notificação.", "ambar")
            return None
        return self.notificacoes.get(selecao[0])

    def _responder_notificacao(self) -> None:
        n = self._notificacao_selecionada()
        if n and n.motivo in ("mention", "reply", "quote"):
            self.responder(n.autor_handle, n.uri, n.cid, n.resposta_a)
        elif n:
            self.status("Só dá para responder menções, respostas e citações.", "ambar")

    def _curtir_notificacao(self) -> None:
        n = self._notificacao_selecionada()
        if n and n.motivo in ("mention", "reply", "quote"):
            self.em_segundo_plano(lambda: self.cliente.curtir(n.uri, n.cid),
                                  lambda _r: self.status(f"Curtido: post de @{n.autor_handle}.", "verde"))
        elif n:
            self.status("Esta notificação não é um post.", "ambar")

    def _seguir_notificacao(self) -> None:
        n = self._notificacao_selecionada()
        if n:
            self.em_segundo_plano(lambda: self.cliente.seguir(n.autor_did),
                                  lambda _r: self.status(f"Seguindo @{n.autor_handle}.", "verde"))

    # ------------------------------------------------------------------ aba Bot automático

    def _aba_bot(self, aba: ttk.Frame) -> None:
        regras = self.config_app.regras
        painel = ttk.Frame(aba, style="Painel.TFrame", padding=14)
        painel.pack(fill="x")

        def linha_regra(texto: str, valor: bool) -> tk.BooleanVar:
            var = tk.BooleanVar(value=valor)
            ttk.Checkbutton(painel, text=texto, variable=var).pack(anchor="w", pady=(8, 2))
            return var

        def campo(rotulo: str, valor: str, largura: int = 50) -> tk.StringVar:
            var = tk.StringVar(value=valor)
            linha = ttk.Frame(painel, style="Painel.TFrame")
            linha.pack(fill="x", padx=(26, 0), pady=1)
            ttk.Label(linha, text=rotulo, style="PainelSuave.TLabel", width=22).pack(side="left")
            ttk.Entry(linha, textvariable=var, width=largura).pack(side="left", fill="x", expand=True, ipady=2)
            return var

        self.var_curtir = linha_regra("Curtir posts que contenham estas palavras", regras.curtir_ativo)
        self.var_curtir_palavras = campo("Palavras (com vírgula)", ", ".join(regras.curtir_palavras))
        self.var_repostar = tk.BooleanVar(value=regras.repostar_tambem)
        ttk.Checkbutton(painel, text="Também repostar", variable=self.var_repostar).pack(anchor="w", padx=(26, 0))

        self.var_responder = linha_regra("Responder menções que contenham estas palavras", regras.responder_ativo)
        self.var_responder_palavras = campo("Palavras (com vírgula)", ", ".join(regras.responder_palavras))
        self.var_responder_texto = campo("Texto da resposta", regras.responder_texto)

        self.var_seguir = linha_regra("Seguir de volta quem me segue", regras.seguir_de_volta)

        linha = ttk.Frame(painel, style="Painel.TFrame")
        linha.pack(fill="x", pady=(12, 0))
        ttk.Label(linha, text="Rodar a cada", style="Painel.TLabel").pack(side="left")
        self.var_intervalo = tk.StringVar(value=str(regras.intervalo_min))
        ttk.Spinbox(linha, from_=au.INTERVALO_MINIMO_MIN, to=240, textvariable=self.var_intervalo,
                    width=4).pack(side="left", padx=6)
        ttk.Label(linha, text=f"minutos  ·  no máximo {regras.curtir_limite} curtidas, {regras.responder_limite} "
                              f"respostas e {regras.seguir_limite} follows por rodada",
                  style="PainelSuave.TLabel").pack(side="left")

        botoes = ttk.Frame(aba)
        botoes.pack(fill="x", pady=12)
        self.btn_bot = ttk.Button(botoes, text="▶ Ligar bot", style="Verde.TButton", command=self._alternar_bot)
        self.btn_bot.pack(side="left")
        ttk.Button(botoes, text="Rodar uma vez agora", command=self._rodar_bot).pack(side="left", padx=8)
        self.lbl_bot = ttk.Label(botoes, text="Bot desligado", style="Suave.TLabel")
        self.lbl_bot.pack(side="left", padx=8)

        self.txt_log = tk.Text(aba, height=8, bg=CORES["painel"], fg=CORES["texto_suave"], relief="flat",
                               font=(FONTE_MONO, 9), padx=10, pady=6, state="disabled", highlightthickness=0)
        self.txt_log.pack(fill="both", expand=True)

    def _ler_regras(self) -> bool:
        regras = self.config_app.regras
        try:
            intervalo = max(au.INTERVALO_MINIMO_MIN, int(self.var_intervalo.get()))
        except ValueError:
            intervalo = regras.intervalo_min
        self.var_intervalo.set(str(intervalo))
        regras.curtir_ativo = self.var_curtir.get()
        regras.curtir_palavras = au.separar_palavras(self.var_curtir_palavras.get())
        regras.repostar_tambem = self.var_repostar.get()
        regras.responder_ativo = self.var_responder.get()
        regras.responder_palavras = au.separar_palavras(self.var_responder_palavras.get())
        regras.responder_texto = self.var_responder_texto.get().strip()
        regras.seguir_de_volta = self.var_seguir.get()
        regras.intervalo_min = intervalo
        self._salvar()
        if not (regras.curtir_ativo or regras.responder_ativo or regras.seguir_de_volta):
            self.status("Marque pelo menos uma regra do bot.", "ambar")
            return False
        return True

    def _registrar(self, mensagem: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{datetime.now():%H:%M:%S}] {mensagem}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _alternar_bot(self) -> None:
        if self.bot_ligado:
            self._parar_bot()
        elif self._ler_regras():
            self.bot_ligado = True
            self.btn_bot.configure(text="■ Desligar bot", style="Perigo.TButton")
            self._registrar("Bot ligado.")
            self._rodar_bot()

    def _parar_bot(self) -> None:
        if self._timer_bot:
            self.after_cancel(self._timer_bot)
            self._timer_bot = None
        if self.bot_ligado:
            self.bot_ligado = False
            self.btn_bot.configure(text="▶ Ligar bot", style="Verde.TButton")
            self.lbl_bot.configure(text="Bot desligado")
            self._registrar("Bot desligado.")

    def _rodar_bot(self) -> None:
        if not self._ler_regras():
            return
        mensagens: list[str] = []
        self.lbl_bot.configure(text="Rodando...")

        def pronto(acoes: int) -> None:
            for mensagem in mensagens:
                self._registrar(mensagem)
            self._registrar(f"Rodada concluída: {acoes} ação(ões).")
            self._salvar()
            if self.bot_ligado:
                minutos = self.config_app.regras.intervalo_min
                proxima = datetime.now() + timedelta(minutes=minutos)
                self.lbl_bot.configure(text=f"Bot ligado · próxima rodada às {proxima:%H:%M}")
                self._timer_bot = self.after(minutos * 60_000, self._rodar_bot)
            else:
                self.lbl_bot.configure(text="Bot desligado")

        def falhou(erro: ErroBluesky) -> None:
            self._registrar(f"Erro: {erro}")
            pronto(0)

        self.em_segundo_plano(lambda: au.executar_ciclo(self.cliente, self.config_app, mensagens.append),
                              pronto, falhou)

    # ------------------------------------------------------------------ fechar

    def _ao_fechar(self) -> None:
        if self.bot_ligado or self.config_app.agendados:
            if not messagebox.askyesno("Fechar", "O bot e os posts agendados só funcionam com o programa "
                                                 "aberto.\n\nFechar mesmo assim?", parent=self):
                return
        self.destroy()


def main() -> None:
    Aplicativo().mainloop()


if __name__ == "__main__":
    main()
