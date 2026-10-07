# OAB 2ª fase · Direito do Trabalho

Treino da peça prático-profissional em dois módulos:

1. **Qual é a peça**: enunciados das provas da FGV; você escolhe a peça cabível entre 5 alternativas e vê a justificativa do padrão de resposta.
2. **Estruturas**: as 14 peças trabalhistas por nome, com esqueleto-modelo. Você resolve o caso numa folha pautada (contador de ≈150 linhas) e a IA corrige item a item pela distribuição de pontos da banca, apontando acertos, erros, peça inadequada (nota zero) e risco de identificação.

## Rodar localmente
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...                 # Windows: set ANTHROPIC_API_KEY=...
    python app.py                                       # http://localhost:5000

Sem DATABASE_URL o app usa SQLite (oab_trabalho.db). Vem com 4 casos de treino (originais, não oficiais) para testar tudo antes de importar provas.

## Cadastrar as 30 provas oficiais
Menu Provas: envie o caderno de prova de Direito do Trabalho e o padrão de resposta (PDFs do site da FGV). A IA extrai enunciado, peça cabível, gabarito comentado e tabela de pontos. Confira a tela de revisão (a soma deve dar 5,00) antes de treinar.
Também aceita JSON em lote, no formato de data/casos_exemplo.json.

## Deploy no Railway
1. Suba o repositório e crie o serviço (Nixpacks detecta Python e usa o Procfile).
2. Adicione o plugin PostgreSQL (DATABASE_URL é criada sozinha).
3. Variáveis: ANTHROPIC_API_KEY, SECRET_KEY e, opcionalmente, CLAUDE_MODEL.

O timeout do gunicorn está em 180 s porque importação e correção podem passar de 30 s.
