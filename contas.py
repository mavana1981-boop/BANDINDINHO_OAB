"""Contas de usuário: cadastro, login, administrador, chave de sessão e cores do menu Estruturas."""
import os
import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

import db

EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COR_OK = re.compile(r"^#[0-9a-fA-F]{6}$")
# tabelas que guardam resoluções e passam a ter dono
TABELAS_COM_DONO = ["quiz_sessoes", "questoes_respostas", "tentativas"]
_HASH_FALSO = generate_password_hash("senha-que-ninguem-usa")


class ErroConta(Exception):
    pass


def init():
    pk = "SERIAL PRIMARY KEY" if getattr(db, "IS_PG", False) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db.query(f"""CREATE TABLE IF NOT EXISTS usuarios (
        id {pk}, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
        admin INTEGER DEFAULT 0, created_at TEXT)""", commit=True)
    db.query("CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT)", commit=True)
    db.query("CREATE TABLE IF NOT EXISTS pecas_cores (chave TEXT PRIMARY KEY, cor TEXT)", commit=True)
    for tabela in TABELAS_COM_DONO:  # migração: acrescenta a coluna de dono se ainda não existir
        try:
            db.query(f"ALTER TABLE {tabela} ADD COLUMN usuario_id INTEGER", commit=True)
        except Exception:
            pass


def chave_secreta():
    """SECRET_KEY do ambiente; se não houver, uma chave aleatória guardada no banco (igual para todos os workers)."""
    env = os.environ.get("SECRET_KEY", "")
    if env and env != "troque-esta-chave":
        return env
    linha = db.query("SELECT valor FROM config WHERE chave = 'secret_key'", one=True)
    if linha:
        return linha["valor"]
    try:
        db.query("INSERT INTO config (chave, valor) VALUES ('secret_key', ?)", (secrets.token_hex(32),), commit=True)
    except Exception:
        pass  # outro worker gravou primeiro
    return db.query("SELECT valor FROM config WHERE chave = 'secret_key'", one=True)["valor"]


def obter(uid):
    if not uid:
        return None
    u = db.query("SELECT id, nome, email, admin FROM usuarios WHERE id = ?", (uid,), one=True)
    if u:
        u["admin"] = bool(u["admin"])
    return u


def _normalizar_email(email):
    return (email or "").strip().lower()


def cadastrar(nome, email, senha, convite=""):
    nome, email = (nome or "").strip()[:80], _normalizar_email(email)
    codigo = os.environ.get("CODIGO_CONVITE", "").strip()
    if codigo and (convite or "").strip() != codigo:
        raise ErroConta("Código de convite inválido.")
    if not nome:
        raise ErroConta("Informe seu nome.")
    if not EMAIL_OK.match(email):
        raise ErroConta("Informe um e-mail válido.")
    if len(senha or "") < 8:
        raise ErroConta("A senha precisa ter pelo menos 8 caracteres.")
    if db.query("SELECT id FROM usuarios WHERE email = ?", (email,), one=True):
        raise ErroConta("Já existe uma conta com este e-mail. Use Entrar.")

    admin_email = _normalizar_email(os.environ.get("ADMIN_EMAIL"))
    ja_tem_admin = bool(db.query("SELECT id FROM usuarios WHERE admin = 1 LIMIT 1", one=True))
    # administrador: o e-mail de ADMIN_EMAIL; sem essa variável, a primeira conta criada
    admin = (email == admin_email) if admin_email else not ja_tem_admin

    uid = db.query("""INSERT INTO usuarios (nome, email, senha_hash, admin, created_at)
                      VALUES (?, ?, ?, ?, ?) RETURNING id""",
                   (nome, email, generate_password_hash(senha), int(admin), db.agora()),
                   one=True, commit=True)["id"]
    if admin and not ja_tem_admin:
        # o primeiro administrador herda o que foi feito antes de existir login
        for tabela in TABELAS_COM_DONO:
            db.query(f"UPDATE {tabela} SET usuario_id = ? WHERE usuario_id IS NULL", (uid,), commit=True)
    return obter(uid)


def autenticar(email, senha):
    u = db.query("SELECT * FROM usuarios WHERE email = ?", (_normalizar_email(email),), one=True)
    if not u:
        check_password_hash(_HASH_FALSO, senha or "")  # mesmo tempo de resposta com e sem conta
        return None
    return obter(u["id"]) if check_password_hash(u["senha_hash"], senha or "") else None


def trocar_senha(uid, atual, nova):
    u = db.query("SELECT senha_hash FROM usuarios WHERE id = ?", (uid,), one=True)
    if not u or not check_password_hash(u["senha_hash"], atual or ""):
        raise ErroConta("A senha atual está incorreta.")
    if len(nova or "") < 8:
        raise ErroConta("A nova senha precisa ter pelo menos 8 caracteres.")
    db.query("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (generate_password_hash(nova), uid), commit=True)


# ------------------------------------------------------------------ cores dos nomes no menu Estruturas

def cores_pecas():
    return {r["chave"]: r["cor"] for r in db.query("SELECT chave, cor FROM pecas_cores")}


def salvar_cor_peca(chave, cor):
    db.query("DELETE FROM pecas_cores WHERE chave = ?", (chave,), commit=True)
    if cor:
        if not COR_OK.match(cor):
            raise ErroConta("Cor inválida.")
        db.query("INSERT INTO pecas_cores (chave, cor) VALUES (?, ?)", (chave, cor), commit=True)
