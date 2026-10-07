"""Banco de dados: SQLite em desenvolvimento, PostgreSQL quando DATABASE_URL existir (Railway)."""
import json
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg2
    import psycopg2.extras


def _connect():
    if IS_PG:
        return psycopg2.connect(DATABASE_URL.replace("postgres://", "postgresql://", 1))
    conn = sqlite3.connect(os.path.join(BASE_DIR, "oab_trabalho.db"))
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=(), one=False, commit=False):
    """Executa SQL com placeholders '?' (convertidos para %s no Postgres)."""
    if IS_PG:
        sql = sql.replace("?", "%s")
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if IS_PG else conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        if commit:
            conn.commit()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init_db():
    pk = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    query(f"""
        CREATE TABLE IF NOT EXISTS provas (
            id {pk},
            exame TEXT NOT NULL,
            ano TEXT,
            ordem INTEGER DEFAULT 0,
            origem TEXT DEFAULT 'oficial',
            peca_correta TEXT NOT NULL,
            enunciado TEXT NOT NULL,
            padrao_json TEXT NOT NULL,
            created_at TEXT
        )""", commit=True)
    query(f"""
        CREATE TABLE IF NOT EXISTS tentativas (
            id {pk},
            prova_id INTEGER NOT NULL,
            modo TEXT NOT NULL,
            peca_escolhida TEXT,
            acertou INTEGER,
            resposta TEXT,
            resultado_json TEXT,
            nota REAL,
            created_at TEXT
        )""", commit=True)
    _seed_exemplos()


def _seed_exemplos():
    if query("SELECT id FROM provas WHERE origem = 'exemplo' LIMIT 1", one=True):
        return
    with open(os.path.join(BASE_DIR, "data", "casos_exemplo.json"), encoding="utf-8") as f:
        for caso in json.load(f):
            inserir_prova(caso)


def inserir_prova(d):
    row = query(
        """INSERT INTO provas (exame, ano, ordem, origem, peca_correta, enunciado, padrao_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (d["exame"], d.get("ano", ""), int(d.get("ordem") or 0), d.get("origem", "oficial"),
         d["peca_correta"], d["enunciado"], json.dumps(d["padrao"], ensure_ascii=False), agora()),
        one=True, commit=True)
    return row["id"]


def _hidratar(p):
    if p:
        p["padrao"] = json.loads(p.pop("padrao_json"))
    return p


def listar_provas(peca=None):
    sql = "SELECT * FROM provas"
    params = ()
    if peca:
        sql += " WHERE peca_correta = ?"
        params = (peca,)
    sql += " ORDER BY ordem DESC, id ASC"
    return [_hidratar(p) for p in query(sql, params)]


def obter_prova(prova_id):
    return _hidratar(query("SELECT * FROM provas WHERE id = ?", (prova_id,), one=True))


def excluir_prova(prova_id):
    query("DELETE FROM tentativas WHERE prova_id = ?", (prova_id,), commit=True)
    query("DELETE FROM provas WHERE id = ?", (prova_id,), commit=True)


def contar_oficiais():
    return query("SELECT COUNT(*) AS n FROM provas WHERE origem = 'oficial'", one=True)["n"]


def registrar_tentativa(prova_id, modo, peca_escolhida=None, acertou=None,
                        resposta=None, resultado=None, nota=None):
    query("""INSERT INTO tentativas (prova_id, modo, peca_escolhida, acertou, resposta,
             resultado_json, nota, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
          (prova_id, modo, peca_escolhida, None if acertou is None else int(acertou), resposta,
           json.dumps(resultado, ensure_ascii=False) if resultado else None, nota, agora()),
          commit=True)


def status_quiz():
    """Última tentativa do modo 'qual é a peça' por prova: {prova_id: acertou}."""
    rows = query("SELECT prova_id, acertou FROM tentativas WHERE modo = 'peca' ORDER BY id")
    return {r["prova_id"]: bool(r["acertou"]) for r in rows}


def historico(limite=100):
    rows = query("""SELECT t.*, p.exame, p.peca_correta FROM tentativas t
                    JOIN provas p ON p.id = t.prova_id ORDER BY t.id DESC LIMIT ?""", (limite,))
    for r in rows:
        r["resultado"] = json.loads(r.pop("resultado_json")) if r.get("resultado_json") else None
    return rows


def obter_tentativa(tid):
    r = query("SELECT * FROM tentativas WHERE id = ?", (tid,), one=True)
    if r:
        r["resultado"] = json.loads(r.pop("resultado_json")) if r.get("resultado_json") else None
    return r
