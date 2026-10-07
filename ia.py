"""Chamadas à API do Claude: correção da peça e importação de provas em PDF."""
import base64
import json
import os
import re

import anthropic

MODELO = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


class ErroIA(Exception):
    pass


def _cliente():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ErroIA("Defina a variável ANTHROPIC_API_KEY para usar a correção por IA.")
    return anthropic.Anthropic()


def _extrair_json(texto):
    texto = re.sub(r"```(?:json)?", "", texto).strip()
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ErroIA("A IA não devolveu um JSON válido. Tente novamente.")
    try:
        return json.loads(texto[ini:fim + 1])
    except json.JSONDecodeError as e:
        raise ErroIA(f"Não foi possível ler a resposta da IA ({e}).")


def _chamar(system, content, max_tokens):
    try:
        msg = _cliente().messages.create(
            model=MODELO, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}])
    except anthropic.APIError as e:
        raise ErroIA(f"Erro na API do Claude: {e}")
    return "".join(b.text for b in msg.content if b.type == "text")


# --------------------------------------------------------------------------- correção

SYSTEM_CORRECAO = """Você é examinador da prova prático-profissional da OAB (FGV), área Direito do Trabalho.
Corrija a peça do candidato estritamente pelo padrão de resposta fornecido, como a banca faz:
- Cada item do padrão tem pontuação própria. Atribua pontos integrais, parciais ou zero, com justificativa curta.
- A banca aceita fundamentos equivalentes (ex.: art. 11 CLT no lugar do art. 7º, XXIX, CF) quando o padrão os admite ou quando são juridicamente idênticos. Não dê pontos por mera transcrição de lei sem relação com o caso.
- Se a peça redigida não for a peça adequada (ou equivalente aceita pela banca), a nota da peça é ZERO, conforme o edital; informe isso.
- Se o candidato se identificar (nome próprio, assinatura, qualquer marca fora do padrão "Advogado... OAB..."), aponte como risco de anulação.
- Aponte erros de estrutura (endereçamento, interposição e razões separadas, pressupostos, pedidos, fechamento), fundamentos ausentes e erros jurídicos.
- Seja objetivo e técnico, em português do Brasil. Não invente itens fora do padrão; observações extras vão em "observacoes".

Responda SOMENTE com JSON, sem markdown, neste formato:
{
  "peca_adequada": true,
  "peca_identificada": "nome da peça que o candidato redigiu",
  "nota": 0.0,
  "nota_maxima": 5.0,
  "itens": [{"descricao": "...", "pontos_max": 0.0, "pontos_obtidos": 0.0, "status": "atendido|parcial|ausente", "comentario": "..."}],
  "acertos": ["..."],
  "erros": [{"trecho": "trecho curto do candidato ou vazio", "problema": "...", "como_corrigir": "..."}],
  "risco_identificacao": false,
  "observacoes": "síntese final em 2 a 4 frases"
}"""


def corrigir(prova, peca, resposta):
    padrao = prova["padrao"]
    itens = "\n".join(f"- ({i['pontos']:.2f}) {i['descricao']}" for i in padrao.get("itens", []))
    conteudo = (
        f"ENUNCIADO:\n{prova['enunciado']}\n\n"
        f"PEÇA ESPERADA: {peca['nome']}\n"
        f"JUSTIFICATIVA DA PEÇA: {padrao.get('justificativa', '')}\n\n"
        f"PADRÃO DE RESPOSTA (gabarito comentado):\n{padrao.get('gabarito_texto', '')}\n\n"
        f"DISTRIBUIÇÃO DOS PONTOS:\n{itens}\n\n"
        f"RESPOSTA DO CANDIDATO:\n<<<\n{resposta}\n>>>"
    )
    resultado = _extrair_json(_chamar(SYSTEM_CORRECAO, conteudo, 6000))
    soma = sum(float(i.get("pontos_obtidos") or 0) for i in resultado.get("itens", []))
    if resultado.get("peca_adequada") is False:
        soma = 0.0
    resultado["nota"] = round(min(soma, 5.0), 2)
    resultado.setdefault("nota_maxima", 5.0)
    return resultado


# --------------------------------------------------------------------------- importação

def _system_importacao(catalogo):
    chaves = "\n".join(f"- {p['key']}: {p['nome']}" for p in catalogo)
    return f"""Você extrai dados de provas da 2ª fase da OAB (FGV), área Direito do Trabalho.
Receberá o caderno de prova e/ou o padrão de resposta em PDF. Extraia APENAS a peça prático-profissional (ignore as 4 questões discursivas).

Regras:
- "enunciado": transcreva o enunciado da peça integralmente, como está na prova.
- "peca_correta": use exatamente uma das chaves abaixo. Se o padrão aceitar mais de uma peça, use a principal e cite as aceitas na justificativa.
{chaves}
- "padrao.itens": reproduza a tabela de distribuição dos pontos, um item por linha, com a pontuação de cada item (a soma deve ser 5,00). Junte subitens da mesma linha.
- "padrao.gabarito_texto": o gabarito comentado da peça, resumido sem perder fundamentos legais e súmulas.
- "padrao.justificativa": por que essa é a peça cabível, segundo o padrão.
- "exame": ex. "XXXVIII Exame" e "ordem": número arábico do exame (ex. 38). "ano": ano de aplicação.
- Se o PDF não contiver o padrão de resposta, deixe "itens" vazio e "gabarito_texto" vazio.

Responda SOMENTE com JSON:
{{"exame": "", "ordem": 0, "ano": "", "peca_correta": "", "enunciado": "",
  "padrao": {{"justificativa": "", "gabarito_texto": "", "itens": [{{"descricao": "", "pontos": 0.0}}]}}}}"""


def importar_pdfs(pdfs, catalogo):
    """pdfs: lista de bytes (caderno de prova e/ou padrão de resposta)."""
    if not pdfs:
        raise ErroIA("Envie ao menos um PDF.")
    content = [{"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": base64.standard_b64encode(b).decode()}} for b in pdfs]
    content.append({"type": "text", "text": "Extraia a peça de Direito do Trabalho conforme as instruções."})
    dados = _extrair_json(_chamar(_system_importacao(catalogo), content, 12000))
    chaves = {p["key"] for p in catalogo}
    if dados.get("peca_correta") not in chaves:
        raise ErroIA(f"Peça não reconhecida no catálogo: {dados.get('peca_correta')!r}.")
    if not dados.get("enunciado"):
        raise ErroIA("Não encontrei o enunciado da peça no PDF.")
    dados["origem"] = "oficial"
    return dados
