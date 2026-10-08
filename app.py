"""OAB 2ª fase — Direito do Trabalho: treino de identificação e redação de peças."""
import json
import os
import random

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

import db
import ia
from formatacao import limpar_passos, normalizar_estrutura

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
META_PROVAS = 30

def _pasta(nome):
    """Usa a subpasta se existir; senão, a raiz (repositório enviado sem pastas)."""
    p = os.path.join(BASE_DIR, nome)
    return p if os.path.isdir(p) else BASE_DIR


TEMPLATES_DIR = _pasta("templates")
STATIC_DIR = _pasta("static")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=None)


@app.route("/static/<path:filename>", endpoint="static")
def estaticos(filename):
    # só serve CSS e JS: evita expor app.py, .env ou o banco quando os arquivos estão na raiz
    if os.path.splitext(filename)[1].lower() not in {".css", ".js"}:
        abort(404)
    return send_from_directory(STATIC_DIR, filename)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

with open(db.caminho_dado("pecas.json"), encoding="utf-8") as f:
    PECAS_BASE = json.load(f)


def catalogo():
    """Peças do pecas.json com as edições do usuário (gravadas no banco) por cima."""
    edicoes = db.edicoes_pecas()
    pecas = []
    for p in PECAS_BASE:
        peca = {**p, **edicoes.get(p["key"], {}), "editada": p["key"] in edicoes}
        peca["estrutura"] = normalizar_estrutura(peca.get("estrutura"))
        pecas.append(peca)
    return pecas


def por_key():
    return {p["key"]: p for p in catalogo()}
# peças mais cobradas entram com mais frequência como alternativas do quiz
FREQUENTES = ["contestacao", "recurso_ordinario", "reclamacao_trabalhista", "agravo_peticao",
              "embargos_execucao", "recurso_revista", "contrarrazoes", "mandado_seguranca"]

db.init_db()


@app.context_processor
def globais():
    return {"PECAS_POR_KEY": por_key()}


def _peca_ou_404(key):
    peca = por_key().get(key)
    if not peca:
        abort(404)
    return peca


def _prova_ou_404(prova_id):
    prova = db.obter_prova(prova_id)
    if not prova:
        abort(404)
    return prova


@app.route("/")
def inicio():
    return render_template("index.html", oficiais=db.contar_oficiais(), meta=META_PROVAS,
                           total=len(db.listar_provas()), n_pecas=len(PECAS_BASE))


# ------------------------------------------------------------------ 1. Qual é a peça
# As estatísticas deste módulo ficam só na sessão do navegador: somem ao clicar em "Sair"
# ou ao fechar o navegador. Nada é gravado no banco.

def _quiz():
    q = session.get("quiz") or {"acertos": [], "erros": 0, "respondidas": 0}
    session["quiz"] = q
    return q


@app.route("/qual-e-a-peca")
def qual_peca_lista():
    provas = db.listar_provas()
    q = _quiz()
    ids = {p["id"] for p in provas}
    acertos = [i for i in q["acertos"] if i in ids]
    return render_template("qual_peca_lista.html", provas=provas, acertos=set(acertos),
                           n_acertos=len(acertos), erros=q["erros"], respondidas=q["respondidas"],
                           concluiu=bool(provas) and len(acertos) == len(provas),
                           oficiais=db.contar_oficiais(), meta=META_PROVAS)


@app.route("/qual-e-a-peca/sortear")
def qual_peca_sortear():
    provas = db.listar_provas()
    if not provas:
        return redirect(url_for("importar"))
    acertos = set(_quiz()["acertos"])
    pendentes = [p for p in provas if p["id"] not in acertos]
    if not pendentes:  # acertou todas: não repete nenhuma
        return redirect(url_for("qual_peca_lista"))
    atual = request.args.get("atual", type=int)
    if len(pendentes) > 1:  # evita cair de novo na mesma prova logo em seguida
        pendentes = [p for p in pendentes if p["id"] != atual]
    return redirect(url_for("qual_peca", prova_id=random.choice(pendentes)["id"]))


@app.route("/qual-e-a-peca/<int:prova_id>")
def qual_peca(prova_id):
    prova = _prova_ou_404(prova_id)
    if prova_id in _quiz()["acertos"]:
        flash(f"Você já acertou {prova['exame']} nesta sessão. Sorteie outra prova.", "ok")
        return redirect(url_for("qual_peca_lista"))
    correta = prova["peca_correta"]
    pool = [k for k in FREQUENTES if k != correta]
    outras = [p["key"] for p in PECAS_BASE if p["key"] not in pool and p["key"] != correta]
    distratores = random.sample(pool, 3) + random.sample(outras, 1)
    pk = por_key()
    opcoes = [pk[k] for k in distratores + [correta]]
    random.shuffle(opcoes)
    return render_template("qual_peca.html", prova=prova, opcoes=opcoes)


@app.post("/api/qual-e-a-peca/<int:prova_id>")
def api_qual_peca(prova_id):
    prova = _prova_ou_404(prova_id)
    escolhida = (request.get_json(silent=True) or {}).get("peca")
    correta = por_key()[prova["peca_correta"]]
    acertou = escolhida == correta["key"]
    q = _quiz()
    q["respondidas"] += 1
    if acertou and prova_id not in q["acertos"]:
        q["acertos"].append(prova_id)
    elif not acertou:
        q["erros"] += 1
    session["quiz"] = q
    session.modified = True
    restantes = len([p for p in db.listar_provas() if p["id"] not in q["acertos"]])
    return jsonify({
        "acertou": acertou,
        "correta": correta["key"],
        "correta_nome": correta["nome"],
        "justificativa": prova["padrao"].get("justificativa", ""),
        "quando": correta["quando"],
        "prazo": correta["prazo"],
        "link_estrutura": url_for("redigir", key=correta["key"], prova_id=prova_id),
        "restantes": restantes,
    })


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("inicio"))


# ------------------------------------------------------------------ 2. Estruturas

@app.route("/estruturas")
def estruturas():
    contagem = {}
    for p in db.listar_provas():
        contagem[p["peca_correta"]] = contagem.get(p["peca_correta"], 0) + 1
    return render_template("estruturas.html", pecas=catalogo(), contagem=contagem)


@app.route("/estruturas/<key>")
def estrutura_peca(key):
    peca = _peca_ou_404(key)
    return render_template("estrutura_peca.html", peca=peca, casos=db.listar_provas(key))


@app.route("/estruturas/<key>/editar", methods=["GET", "POST"])
def editar_peca(key):
    peca = _peca_ou_404(key)
    if request.method == "POST":
        def linhas(campo):
            return [l.strip() for l in request.form.get(campo, "").splitlines() if l.strip()]
        dados = {c: request.form.get(c, "").strip() for c in ["nome", "quando", "prazo", "base_legal", "enderecamento"]}
        try:
            dados["estrutura"] = limpar_passos(json.loads(request.form.get("estrutura_json") or "[]"))
        except (ValueError, TypeError):
            dados["estrutura"] = []
        dados["dicas"] = linhas("dicas")
        if not dados["nome"] or not dados["estrutura"]:
            flash("O nome e ao menos um passo da estrutura são obrigatórios.", "erro")
            return render_template("editar_peca.html", peca={**peca, **dados})
        db.salvar_edicao_peca(key, dados)
        flash("Estrutura salva.", "ok")
        return redirect(url_for("estrutura_peca", key=key))
    return render_template("editar_peca.html", peca=peca)


@app.route("/estruturas/<key>/imprimir")
def imprimir_peca(key):
    return render_template("imprimir_peca.html", peca=_peca_ou_404(key), data=db.agora())


@app.post("/estruturas/<key>/restaurar")
def restaurar_peca(key):
    _peca_ou_404(key)
    db.remover_edicao_peca(key)
    flash("Estrutura original restaurada.", "ok")
    return redirect(url_for("estrutura_peca", key=key))


@app.route("/estruturas/<key>/caso/<int:prova_id>")
def redigir(key, prova_id):
    peca = _peca_ou_404(key)
    prova = _prova_ou_404(prova_id)
    if prova["peca_correta"] != key:
        return redirect(url_for("redigir", key=prova["peca_correta"], prova_id=prova_id))
    return render_template("redigir.html", peca=peca, prova=prova)


@app.post("/api/corrigir/<int:prova_id>")
def api_corrigir(prova_id):
    prova = _prova_ou_404(prova_id)
    resposta = ((request.get_json(silent=True) or {}).get("resposta") or "").strip()
    if len(resposta) < 200:
        return jsonify({"erro": "A peça está curta demais para correção. Escreva ao menos o esqueleto completo."}), 400
    if not prova["padrao"].get("itens"):
        return jsonify({"erro": "Esta prova foi importada sem padrão de resposta. Importe o PDF do padrão para corrigir."}), 400
    try:
        resultado = ia.corrigir(prova, por_key()[prova["peca_correta"]], resposta)
    except ia.ErroIA as e:
        return jsonify({"erro": str(e)}), 502
    db.registrar_tentativa(prova_id, "redacao", resposta=resposta, resultado=resultado,
                           nota=resultado["nota"])
    return jsonify(resultado)


# ------------------------------------------------------------------ importação e histórico

@app.route("/importar", methods=["GET", "POST"])
def importar():
    if request.method == "POST":
        if request.form.get("tipo") == "json":
            arquivo = request.files.get("arquivo_json")
            try:
                dados = json.load(arquivo)
                dados = dados if isinstance(dados, list) else [dados]
                for d in dados:
                    if d.get("peca_correta") not in por_key():
                        raise ValueError(f"peca_correta inválida: {d.get('peca_correta')}")
                    d.setdefault("origem", "oficial")
                    db.inserir_prova(d)
                flash(f"{len(dados)} prova(s) importada(s).", "ok")
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                flash(f"JSON inválido: {e}", "erro")
            return redirect(url_for("importar"))

        pdfs = [f.read() for f in request.files.getlist("pdfs") if f and f.filename]
        try:
            dados = ia.importar_pdfs(pdfs, catalogo())
        except ia.ErroIA as e:
            flash(str(e), "erro")
            return redirect(url_for("importar"))
        novo_id = db.inserir_prova(dados)
        flash(f"{dados['exame']} importado: peça {por_key()[dados['peca_correta']]['nome']}. "
              "Confira o enunciado e a pontuação antes de treinar.", "ok")
        return redirect(url_for("revisar", prova_id=novo_id))
    return render_template("importar.html", provas=db.listar_provas(),
                           oficiais=db.contar_oficiais(), meta=META_PROVAS)


@app.route("/provas/<int:prova_id>")
def revisar(prova_id):
    return render_template("revisar.html", prova=_prova_ou_404(prova_id))


@app.post("/provas/<int:prova_id>/excluir")
def excluir(prova_id):
    db.excluir_prova(prova_id)
    flash("Prova excluída.", "ok")
    return redirect(url_for("importar"))


@app.route("/historico")
def historico():
    return render_template("historico.html", tentativas=db.historico())


@app.route("/historico/<int:tid>")
def tentativa(tid):
    t = db.obter_tentativa(tid)
    if not t or t["modo"] != "redacao":
        abort(404)
    return render_template("tentativa.html", t=t, prova=db.obter_prova(t["prova_id"]))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
