"""OAB 2ª fase — Direito do Trabalho: treino de identificação e redação de peças."""
import json
import os
import random

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

import db
import ia

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
META_PROVAS = 30

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

with open(db.caminho_dado("pecas.json"), encoding="utf-8") as f:
    PECAS = json.load(f)
PECAS_POR_KEY = {p["key"]: p for p in PECAS}
# peças mais cobradas entram com mais frequência como alternativas do quiz
FREQUENTES = ["contestacao", "recurso_ordinario", "reclamacao_trabalhista", "agravo_peticao",
              "embargos_execucao", "recurso_revista", "contrarrazoes", "mandado_seguranca"]

db.init_db()


@app.context_processor
def globais():
    return {"PECAS_POR_KEY": PECAS_POR_KEY}


def _peca_ou_404(key):
    peca = PECAS_POR_KEY.get(key)
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
                           total=len(db.listar_provas()), n_pecas=len(PECAS))


# ------------------------------------------------------------------ 1. Qual é a peça

@app.route("/qual-e-a-peca")
def qual_peca_lista():
    provas = db.listar_provas()
    return render_template("qual_peca_lista.html", provas=provas, status=db.status_quiz(),
                           oficiais=db.contar_oficiais(), meta=META_PROVAS)


@app.route("/qual-e-a-peca/sortear")
def qual_peca_sortear():
    provas = db.listar_provas()
    if not provas:
        return redirect(url_for("importar"))
    status = db.status_quiz()
    pendentes = [p for p in provas if not status.get(p["id"])] or provas
    return redirect(url_for("qual_peca", prova_id=random.choice(pendentes)["id"]))


@app.route("/qual-e-a-peca/<int:prova_id>")
def qual_peca(prova_id):
    prova = _prova_ou_404(prova_id)
    correta = prova["peca_correta"]
    pool = [k for k in FREQUENTES if k != correta]
    outras = [p["key"] for p in PECAS if p["key"] not in pool and p["key"] != correta]
    distratores = random.sample(pool, 3) + random.sample(outras, 1)
    opcoes = [PECAS_POR_KEY[k] for k in distratores + [correta]]
    random.shuffle(opcoes)
    return render_template("qual_peca.html", prova=prova, opcoes=opcoes)


@app.post("/api/qual-e-a-peca/<int:prova_id>")
def api_qual_peca(prova_id):
    prova = _prova_ou_404(prova_id)
    escolhida = (request.get_json(silent=True) or {}).get("peca")
    correta = PECAS_POR_KEY[prova["peca_correta"]]
    acertou = escolhida == correta["key"]
    db.registrar_tentativa(prova_id, "peca", peca_escolhida=escolhida, acertou=acertou)
    return jsonify({
        "acertou": acertou,
        "correta": correta["key"],
        "correta_nome": correta["nome"],
        "justificativa": prova["padrao"].get("justificativa", ""),
        "quando": correta["quando"],
        "prazo": correta["prazo"],
        "link_estrutura": url_for("redigir", key=correta["key"], prova_id=prova_id),
    })


# ------------------------------------------------------------------ 2. Estruturas

@app.route("/estruturas")
def estruturas():
    contagem = {}
    for p in db.listar_provas():
        contagem[p["peca_correta"]] = contagem.get(p["peca_correta"], 0) + 1
    return render_template("estruturas.html", pecas=PECAS, contagem=contagem)


@app.route("/estruturas/<key>")
def estrutura_peca(key):
    peca = _peca_ou_404(key)
    return render_template("estrutura_peca.html", peca=peca, casos=db.listar_provas(key))


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
        resultado = ia.corrigir(prova, PECAS_POR_KEY[prova["peca_correta"]], resposta)
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
                    if d.get("peca_correta") not in PECAS_POR_KEY:
                        raise ValueError(f"peca_correta inválida: {d.get('peca_correta')}")
                    d.setdefault("origem", "oficial")
                    db.inserir_prova(d)
                flash(f"{len(dados)} prova(s) importada(s).", "ok")
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                flash(f"JSON inválido: {e}", "erro")
            return redirect(url_for("importar"))

        pdfs = [f.read() for f in request.files.getlist("pdfs") if f and f.filename]
        try:
            dados = ia.importar_pdfs(pdfs, PECAS)
        except ia.ErroIA as e:
            flash(str(e), "erro")
            return redirect(url_for("importar"))
        novo_id = db.inserir_prova(dados)
        flash(f"{dados['exame']} importado: peça {PECAS_POR_KEY[dados['peca_correta']]['nome']}. "
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
