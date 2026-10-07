// Monta o resultado da correção sem usar innerHTML com texto da IA (evita injeção).
function el(tag, attrs = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  for (const f of filhos) if (f != null) n.append(f);
  return n;
}
const fmt = (x) => Number(x || 0).toFixed(2).replace('.', ',');

function renderResultado(alvo, d) {
  alvo.innerHTML = '';
  const box = el('section', {class: 'resultado'});

  box.append(el('h2', {}, 'Correção'));
  box.append(el('div', {class: 'placar'},
    el('span', {class: 'nota'}, fmt(d.nota)),
    el('span', {class: 'de'}, `de ${fmt(d.nota_maxima || 5)} pontos na peça`)));

  if (d.peca_adequada === false) {
    box.append(el('p', {class: 'aviso erro'},
      `Peça inadequada: você redigiu ${d.peca_identificada || 'outra peça'}. Pelo edital, a peça inadequada recebe nota zero.`));
  }
  if (d.risco_identificacao) {
    box.append(el('p', {class: 'aviso erro'},
      'Risco de anulação: há marca de identificação na peça. Assine apenas como "Advogado... OAB/UF nº...".'));
  }
  if (d.observacoes) box.append(el('p', {class: 'lead'}, d.observacoes));

  if (d.itens && d.itens.length) {
    box.append(el('h3', {}, 'Item a item, pelo padrão de resposta'));
    const ul = el('ul', {class: 'itens'});
    d.itens.forEach(i => {
      ul.append(el('li', {class: i.status || ''},
        el('span', {class: 'pts'}, `${fmt(i.pontos_obtidos)} / ${fmt(i.pontos_max)}`),
        el('div', {}, el('p', {class: 'desc'}, i.descricao), i.comentario ? el('p', {class: 'coment'}, i.comentario) : null)));
    });
    box.append(ul);
  }

  if (d.acertos && d.acertos.length) {
    box.append(el('h3', {style: 'margin-top:1.5rem'}, 'Acertos'));
    const ul = el('ul', {class: 'acertos'});
    d.acertos.forEach(a => ul.append(el('li', {}, a)));
    box.append(ul);
  }

  if (d.erros && d.erros.length) {
    box.append(el('h3', {style: 'margin-top:1.5rem'}, 'Erros e como corrigir'));
    const ul = el('ul', {class: 'erros'});
    d.erros.forEach(e => ul.append(el('li', {},
      e.trecho ? el('blockquote', {}, `“${e.trecho}”`) : null,
      el('div', {}, el('strong', {}, e.problema)),
      e.como_corrigir ? el('div', {}, e.como_corrigir) : null)));
    box.append(ul);
  }
  alvo.append(box);
}
