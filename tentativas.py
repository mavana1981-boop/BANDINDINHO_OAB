"""Sessões de tentativa do módulo "Qual é a peça" (gravadas no banco)."""
import db


def init():
    pk = "SERIAL PRIMARY KEY" if getattr(db, "IS_PG", False) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db.query(f"""CREATE TABLE IF NOT EXISTS quiz_sessoes (
        id {pk}, nome TEXT NOT NULL, created_at TEXT, updated_at TEXT)""", commit=True)
    db.query(f"""CREATE TABLE IF NOT EXISTS quiz_respostas (
        id {pk}, sessao_id INTEGER NOT NULL, prova_id INTEGER NOT NULL,
        peca_escolhida TEXT, acertou INTEGER NOT NULL, created_at TEXT)""", commit=True)


def criar(nome=None):
    n = db.query("SELECT COUNT(*) AS n FROM quiz_sessoes", one=True)["n"]
    nome = (nome or "").strip()[:80] or f"Tentativa {n + 1}"
    agora = db.agora()
    return db.query("INSERT INTO quiz_sessoes (nome, created_at, updated_at) VALUES (?, ?, ?) RETURNING id",
                    (nome, agora, agora), one=True, commit=True)["id"]


def obter(sid):
    return db.query("SELECT * FROM quiz_sessoes WHERE id = ?", (sid,), one=True) if sid else None


def resumo(sid, ids_provas):
    """Acertos (ids), número de erros e de respostas da tentativa, só contando provas que ainda existem."""
    rows = db.query("SELECT prova_id, acertou FROM quiz_respostas WHERE sessao_id = ? ORDER BY id", (sid,))
    rows = [r for r in rows if r["prova_id"] in ids_provas]
    acertos = []
    for r in rows:
        if r["acertou"] and r["prova_id"] not in acertos:
            acertos.append(r["prova_id"])
    erros = sum(1 for r in rows if not r["acertou"])
    return {"acertos": acertos, "erros": erros, "respondidas": len(rows)}


def listar(ids_provas):
    sessoes = db.query("SELECT * FROM quiz_sessoes ORDER BY id DESC")
    total = len(ids_provas)
    for s in sessoes:
        s.update(resumo(s["id"], ids_provas))
        s["n_acertos"] = len(s["acertos"])
        s["concluida"] = total > 0 and s["n_acertos"] == total
        s["pct"] = round(s["n_acertos"] / total * 100) if total else 0
    return sessoes


def responder(sid, prova_id, peca, acertou):
    agora = db.agora()
    db.query("INSERT INTO quiz_respostas (sessao_id, prova_id, peca_escolhida, acertou, created_at) VALUES (?, ?, ?, ?, ?)",
             (sid, prova_id, peca, int(acertou), agora), commit=True)
    db.query("UPDATE quiz_sessoes SET updated_at = ? WHERE id = ?", (agora, sid), commit=True)


def reiniciar(sid):
    db.query("DELETE FROM quiz_respostas WHERE sessao_id = ?", (sid,), commit=True)
    db.query("UPDATE quiz_sessoes SET updated_at = ? WHERE id = ?", (db.agora(), sid), commit=True)


def excluir(sid):
    db.query("DELETE FROM quiz_respostas WHERE sessao_id = ?", (sid,), commit=True)
    db.query("DELETE FROM quiz_sessoes WHERE id = ?", (sid,), commit=True)
