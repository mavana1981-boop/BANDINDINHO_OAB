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
    chave = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not chave:
        raise ErroIA("Defina a variável ANTHROPIC_API_KEY para usar a importação e a correção por IA.")
    return anthropic.Anthropic(api_key=chave)


def _objetos_json(texto):
    """Lê todos os objetos/listas JSON da resposta, mesmo que venham vários em sequência."""
    texto = re.sub(r"```(?:json)?", "", texto)
    dec = json.JSONDecoder()
    objetos, i = [], 0
    while True:
        ini = min([p for p in (texto.find("{", i), texto.find("[", i)) if p != -1], default=-1)
        if ini == -1:
            break
        try:
            obj, fim = dec.raw_decode(texto, ini)
        except json.JSONDecodeError:
            i = ini + 1
            continue
        objetos.extend(obj if isinstance(obj, list) else [obj])
        i = fim
    objetos = [o for o in objetos if isinstance(o, dict)]
    if not objetos:
        raise ErroIA("A IA não devolveu um JSON válido. Tente novamente.")
    return objetos


def _extrair_json(texto):
    return _objetos_json(texto)[0]


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
Receberá um PDF: caderno de prova, padrão de resposta, ou um arquivo com vários exames.
Extraia APENAS as peças prático-profissionais (ignore as questões discursivas). Se houver mais de um exame no PDF, devolva um item por exame.

Regras para cada item:
- "enunciado": transcreva o enunciado da peça integralmente, como está na prova.
- "peca_correta": use exatamente uma das chaves abaixo. Se o padrão aceitar mais de uma peça, use a principal e cite as aceitas na justificativa.
{chaves}
- "padrao.itens": reproduza a tabela de distribuição dos pontos, um item por linha, com a pontuação de cada item (a soma deve ser 5,00). Junte subitens da mesma linha.
- "padrao.gabarito_texto": o gabarito comentado da peça, resumido sem perder fundamentos legais e súmulas.
- "padrao.justificativa": por que essa é a peça cabível, segundo o padrão.
- "exame": ex. "XXXVIII Exame" e "ordem": número arábico do exame (ex. 38). "ano": ano de aplicação.
- Se o PDF não contiver o padrão de resposta, deixe "itens" vazio e "gabarito_texto" vazio.

Responda SOMENTE com um único JSON, sem markdown:
{{"provas": [{{"exame": "", "ordem": 0, "ano": "", "peca_correta": "", "enunciado": "",
  "padrao": {{"justificativa": "", "gabarito_texto": "", "itens": [{{"descricao": "", "pontos": 0.0}}]}}}}]}}"""


def importar_pdf(pdf_bytes, catalogo):
    """Processa UM PDF e devolve a lista de provas encontradas nele."""
    if not pdf_bytes:
        raise ErroIA("Arquivo vazio.")
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": base64.standard_b64encode(pdf_bytes).decode()}},
        {"type": "text", "text": "Extraia a(s) peça(s) de Direito do Trabalho conforme as instruções."},
    ]
    brutos = []
    for obj in _objetos_json(_chamar(_system_importacao(catalogo), content, 16000)):
        brutos.extend(obj["provas"] if isinstance(obj.get("provas"), list) else [obj])

    chaves = {p["key"] for p in catalogo}
    provas, problemas = [], []
    for d in brutos:
        if not isinstance(d, dict) or not d.get("enunciado"):
            continue
        if d.get("peca_correta") not in chaves:
            problemas.append(f"{d.get('exame') or 'prova'}: peça não reconhecida ({d.get('peca_correta')!r})")
            continue
        d.setdefault("padrao", {})
        d["padrao"].setdefault("itens", [])
        try:
            d["ordem"] = int(d.get("ordem") or 0)
        except (TypeError, ValueError):
            d["ordem"] = 0
        d["origem"] = "oficial"
        provas.append(d)
    if not provas:
        raise ErroIA("; ".join(problemas) or "Não encontrei o enunciado de nenhuma peça neste PDF.")
    return provas, problemas


def importar_pdfs(pdfs, catalogo):
    """Compatibilidade: vários PDFs, um de cada vez. Devolve a primeira prova."""
    todas = []
    for b in pdfs:
        todas.extend(importar_pdf(b, catalogo)[0])
    if not todas:
        raise ErroIA("Envie ao menos um PDF.")
    return todas[0]


# --------------------------------------------------------------------------- questões discursivas

SYSTEM_IMPORTAR_QUESTOES = """Você extrai as QUESTÕES DISCURSIVAS da 2ª fase da OAB (FGV), área Direito do Trabalho.
Receberá um PDF: padrão de resposta (preferível) ou caderno de prova. Ignore a peça prático-profissional; extraia só as questões (normalmente 4 por exame, cada uma com itens A e B).

Para cada questão:
- "numero": 1, 2, 3 ou 4.
- "enunciado": o caso comum da questão, transcrito integralmente.
- "itens": um por letra, com:
  - "letra": "A", "B"...
  - "pergunta": a pergunta do item, transcrita.
  - "gabarito": o gabarito comentado do item, sem perder fundamentos legais e súmulas (pode resumir o texto corrido).
  - "distribuicao": a tabela de distribuição dos pontos do item, uma linha por faixa de pontuação, com a descrição do que é exigido e os pontos (ex.: "Não, pois a prescrição é bienal (0,50). Art. 7º, XXIX, CF (0,10)" vira duas linhas: 0.50 e 0.10).
- "exame": ex. "XXXVIII Exame"; "ordem": número arábico do exame (38); "ano": ano de aplicação.
- Se o PDF não tiver o padrão de resposta, deixe "gabarito" vazio e "distribuicao" vazia.
Seja conciso no gabarito para caber tudo na resposta.

Responda SOMENTE com um único JSON, sem markdown:
{"questoes": [{"exame": "", "ordem": 0, "ano": "", "numero": 1, "enunciado": "",
  "itens": [{"letra": "A", "pergunta": "", "gabarito": "", "distribuicao": [{"descricao": "", "pontos": 0.0}]}]}]}"""


def importar_questoes_pdf(pdf_bytes):
    if not pdf_bytes:
        raise ErroIA("Arquivo vazio.")
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": base64.standard_b64encode(pdf_bytes).decode()}},
        {"type": "text", "text": "Extraia as questões discursivas conforme as instruções."},
    ]
    brutos = []
    for obj in _objetos_json(_chamar(SYSTEM_IMPORTAR_QUESTOES, content, 20000)):
        brutos.extend(obj["questoes"] if isinstance(obj.get("questoes"), list) else [obj])
    questoes = []
    for q in brutos:
        if not isinstance(q, dict) or not q.get("enunciado") or not isinstance(q.get("itens"), list):
            continue
        try:
            q["numero"] = int(q.get("numero") or 0)
            q["ordem"] = int(q.get("ordem") or 0)
        except (TypeError, ValueError):
            continue
        itens = []
        for i in q["itens"]:
            if isinstance(i, dict) and i.get("pergunta"):
                dist = [{"descricao": str(d.get("descricao", "")), "pontos": float(d.get("pontos") or 0)}
                        for d in (i.get("distribuicao") or []) if isinstance(d, dict)]
                itens.append({"letra": str(i.get("letra") or "").upper()[:2], "pergunta": i["pergunta"],
                              "gabarito": i.get("gabarito", ""), "distribuicao": dist})
        if q["numero"] and itens:
            q["itens"] = itens
            q.setdefault("exame", f"Exame {q['ordem']}" if q["ordem"] else "Exame")
            questoes.append(q)
    if not questoes:
        raise ErroIA("Não encontrei questões discursivas neste PDF.")
    return questoes


SYSTEM_CORRIGIR_QUESTAO = """Você é examinador da 2ª fase da OAB (FGV), Direito do Trabalho, corrigindo uma QUESTÃO DISCURSIVA.
Corrija cada item estritamente pela distribuição de pontos do padrão de resposta, como a banca:
- Cada linha da distribuição vale os pontos indicados. Conceda integral se o candidato atendeu, zero se não atendeu. A FGV não costuma dar fração de uma linha; use pontuação parcial só se a linha agrupar exigências separáveis.
- Fundamento legal só pontua se correto e ligado à conclusão certa. Mera citação de artigo, sem resposta, não pontua. Conclusão certa com fundamento errado pontua só a conclusão.
- Aceite redação diferente com o mesmo sentido jurídico e fundamentos equivalentes admitidos pelo padrão.
- Resposta em branco ou que só copia o enunciado: zero.
- Seja objetivo, em português do Brasil.

Responda SOMENTE com JSON, sem markdown:
{"itens": [{"letra": "A", "linhas": [{"descricao": "linha da distribuição", "pontos_max": 0.0, "pontos_obtidos": 0.0, "comentario": "..."}],
   "acertos": ["..."], "erros": [{"problema": "...", "como_corrigir": "..."}]}],
 "observacoes": "síntese em 1 a 3 frases"}"""


def corrigir_questao(questao, respostas):
    """respostas: {letra: texto}. Devolve resultado com notas recalculadas pelo servidor."""
    partes = [f"ENUNCIADO:\n{questao['enunciado']}\n"]
    for i in questao["itens"]:
        dist = "\n".join(f"  - ({d['pontos']:.2f}) {d['descricao']}" for d in i["distribuicao"])
        partes.append(f"ITEM {i['letra']}\nPergunta: {i['pergunta']}\nGabarito: {i['gabarito']}\n"
                      f"Distribuição dos pontos:\n{dist}\n"
                      f"RESPOSTA DO CANDIDATO ({i['letra']}):\n<<<\n{respostas.get(i['letra'], '').strip() or '(em branco)'}\n>>>\n")
    resultado = _extrair_json(_chamar(SYSTEM_CORRIGIR_QUESTAO, "\n".join(partes), 6000))
    # a nota é recalculada aqui, limitada ao máximo de cada linha e de cada item
    max_por_letra = {i["letra"]: sum(d["pontos"] for d in i["distribuicao"]) for i in questao["itens"]}
    total = 0.0
    for item in resultado.get("itens", []):
        soma = 0.0
        for linha in item.get("linhas", []):
            pm = float(linha.get("pontos_max") or 0)
            po = max(0.0, min(float(linha.get("pontos_obtidos") or 0), pm))
            linha["pontos_max"], linha["pontos_obtidos"] = pm, po
            soma += po
        item["nota"] = round(min(soma, max_por_letra.get(item.get("letra"), soma)), 2)
        item["nota_maxima"] = round(max_por_letra.get(item.get("letra"), 0), 2)
        total += item["nota"]
    resultado["nota"] = round(total, 2)
    resultado["nota_maxima"] = round(sum(max_por_letra.values()), 2)
    return resultado
