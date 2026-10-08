"""Limpa o HTML formatado dos passos da estrutura: mantém só negrito, itálico, sublinhado,
cores, marca-texto, tamanho e fonte. Remove scripts, links, imagens e atributos perigosos."""
import re
from html import escape
from html.parser import HTMLParser

TAGS_SIMPLES = {"b", "strong", "i", "em", "u", "s", "strike", "sub", "sup"}
PROPRIEDADES = {"color", "background-color", "font-size", "font-family", "font-weight",
                "font-style", "text-decoration", "text-decoration-line"}
VALOR_SEGURO = re.compile(r"^[#\w\s,.'\"()%-]{1,80}$")
TAMANHO_FONT = {"1": "0.75em", "2": "0.85em", "3": "1em", "4": "1.15em", "5": "1.3em", "6": "1.5em", "7": "1.75em"}
COR_PASSO = re.compile(r"^#[0-9a-fA-F]{6}$")


def _estilo_seguro(estilo):
    partes = []
    for decl in (estilo or "").split(";"):
        if ":" not in decl:
            continue
        prop, valor = (x.strip() for x in decl.split(":", 1))
        prop = prop.lower()
        if prop in PROPRIEDADES and VALOR_SEGURO.match(valor) and "url" not in valor.lower() \
                and "expression" not in valor.lower():
            partes.append(f"{prop}: {valor}")
    return "; ".join(partes)


class _Limpador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.saida = []
        self.pilha = []  # tags abertas que foram mantidas (para fechar corretamente)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "br":
            self.saida.append("<br>")
        elif tag in TAGS_SIMPLES:
            self.saida.append(f"<{tag}>")
            self.pilha.append(tag)
        elif tag in ("span", "font"):
            estilo = attrs.get("style", "")
            if tag == "font":  # <font color size face> vira <span style>
                extra = []
                if attrs.get("color"):
                    extra.append(f"color: {attrs['color']}")
                if attrs.get("size") in TAMANHO_FONT:
                    extra.append(f"font-size: {TAMANHO_FONT[attrs['size']]}")
                if attrs.get("face"):
                    extra.append(f"font-family: {attrs['face']}")
                estilo = "; ".join(extra + [estilo])
            seguro = _estilo_seguro(estilo)
            self.saida.append(f'<span style="{escape(seguro)}">' if seguro else "<span>")
            self.pilha.append(tag)
        elif tag in ("div", "p") and self.saida:
            self.saida.append("<br>")  # quebra de linha do editor
        # qualquer outra tag é descartada, mantendo apenas o texto

    def handle_endtag(self, tag):
        if tag in self.pilha:
            while self.pilha:
                aberta = self.pilha.pop()
                self.saida.append("</span>" if aberta in ("span", "font") else f"</{aberta}>")
                if aberta == tag:
                    break

    def handle_data(self, data):
        self.saida.append(escape(data))

    def resultado(self):
        while self.pilha:
            aberta = self.pilha.pop()
            self.saida.append("</span>" if aberta in ("span", "font") else f"</{aberta}>")
        return re.sub(r"(<br>)+$", "", "".join(self.saida)).strip()


def limpar_html(html):
    p = _Limpador()
    p.feed(html or "")
    p.close()
    return p.resultado()


def texto_puro(html):
    return re.sub(r"<[^>]+>", "", html or "").replace("&nbsp;", " ").strip()


def normalizar_estrutura(lista):
    """Aceita passos antigos (texto simples) ou novos ({html, cor, conector}) e devolve sempre o formato novo.
    conector=True: linha de ligação entre itens, exibida sem número."""
    saida = []
    for passo in lista or []:
        if isinstance(passo, str):
            saida.append({"html": escape(passo), "cor": "", "conector": False})
        elif isinstance(passo, dict):
            cor = passo.get("cor") or ""
            saida.append({"html": passo.get("html", ""), "cor": cor if COR_PASSO.match(cor) else "",
                          "conector": bool(passo.get("conector"))})
    return saida


def limpar_passos(passos):
    """Passos enviados pelo editor: limpa o HTML, valida a cor e descarta passos vazios."""
    limpos = []
    for p in passos or []:
        if not isinstance(p, dict):
            continue
        html = limpar_html(str(p.get("html", "")))
        if texto_puro(html):
            cor = str(p.get("cor") or "")
            limpos.append({"html": html, "cor": cor if COR_PASSO.match(cor) else "",
                           "conector": p.get("conector") is True})
    return limpos
