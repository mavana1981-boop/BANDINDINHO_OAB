"""Questões discursivas da 2ª fase: armazenamento e respostas corrigidas."""
import json

import db


def init():
    pk = "SERIAL PRIMARY KEY" if getattr(db, "IS_PG", False) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db.query(f"""CREATE TABLE IF NOT EXISTS questoes (
        id {pk}, exame TEXT NOT NULL, ordem INTEGER DEFAULT 0, ano TEXT, numero INTEGER NOT NULL,
        enunciado TEXT NOT NULL, itens_json TEXT NOT NULL, created_at TEXT)""", commit=True)
    db.query(f"""CREATE TABLE IF NOT EXISTS questoes_respostas (
        id {pk}, questao_id INTEGER NOT NULL, respostas_json TEXT NOT NULL,
        resultado_json TEXT, nota REAL, created_at TEXT)""", commit=True)


def _hidratar(q):
    if q:
        q["itens"] = json.loads(q.pop("itens_json"))
        q["pontos_max"] = round(sum(sum(float(d.get("pontos") or 0) for d in i.get("distribuicao", []))
                                    for i in q["itens"]), 2)
    return q


def tem_gabarito(q):
    return any(i.get("distribuicao") for i in q["itens"])


def listar(uid):
    qs = [_hidratar(q) for q in db.query("SELECT * FROM questoes ORDER BY ordem DESC, exame, numero")]
    melhores = {r["questao_id"]: r["melhor"] for r in
                db.query("""SELECT questao_id, MAX(nota) AS melhor FROM questoes_respostas
                            WHERE usuario_id = ? GROUP BY questao_id""", (uid,))}
    for q in qs:
        q["melhor_nota"] = melhores.get(q["id"])
    return qs


def obter(qid):
    return _hidratar(db.query("SELECT * FROM questoes WHERE id = ?", (qid,), one=True))


def gravar(q):
    """Insere a questão; se o mesmo exame/número já existe, completa o gabarito em vez de duplicar."""
    if q.get("ordem"):
        existente = db.query("SELECT * FROM questoes WHERE ordem = ? AND numero = ?",
                             (q["ordem"], q["numero"]), one=True)
    else:
        existente = db.query("SELECT * FROM questoes WHERE exame = ? AND numero = ?",
                             (q["exame"], q["numero"]), one=True)
    itens = json.dumps(q["itens"], ensure_ascii=False)
    novo_tem_gabarito = any(i.get("distribuicao") for i in q["itens"])
    if not existente:
        row = db.query("""INSERT INTO questoes (exame, ordem, ano, numero, enunciado, itens_json, created_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                       (q["exame"], q.get("ordem") or 0, q.get("ano", ""), q["numero"], q["enunciado"],
                        itens, db.agora()), one=True, commit=True)
        return row["id"], "nova"
    if not tem_gabarito(_hidratar(dict(existente))) and novo_tem_gabarito:
        db.query("UPDATE questoes SET enunciado = ?, itens_json = ?, ano = ? WHERE id = ?",
                 (q["enunciado"], itens, q.get("ano", ""), existente["id"]), commit=True)
        return existente["id"], "completada"
    return existente["id"], "repetida"


def excluir(qid):
    db.query("DELETE FROM questoes_respostas WHERE questao_id = ?", (qid,), commit=True)
    db.query("DELETE FROM questoes WHERE id = ?", (qid,), commit=True)


def registrar(qid, uid, respostas, resultado):
    return db.query("""INSERT INTO questoes_respostas (questao_id, respostas_json, resultado_json, nota, created_at, usuario_id)
                       VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
                    (qid, json.dumps(respostas, ensure_ascii=False), json.dumps(resultado, ensure_ascii=False),
                     resultado.get("nota"), db.agora(), uid), one=True, commit=True)["id"]


def tentativas(qid, uid):
    """Só as respostas do próprio usuário."""
    rows = db.query("SELECT * FROM questoes_respostas WHERE questao_id = ? AND usuario_id = ? ORDER BY id DESC",
                    (qid, uid))
    for r in rows:
        r["respostas"] = json.loads(r.pop("respostas_json"))
        r["resultado"] = json.loads(r.pop("resultado_json")) if r.get("resultado_json") else None
    return rows
