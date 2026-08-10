# Plano de redesign e publicação com Sites

## Estado verificado

O conector Sites foi consultado em modo somente leitura em 10/08/2026. Não existe
`.openai/hosting.json` neste repositório e nenhum dos Sites existentes corresponde
ao RSI2. Portanto, uma futura publicação deve criar um projeto Sites novo, persistir
seu `project_id` em `.openai/hosting.json` e nunca reutilizar IDs dos outros projetos.
Nenhum site foi criado ou publicado nesta etapa.

## Objetivo

Transformar o RSI2 em uma ferramenta de pesquisa financeira clara, responsiva e
acessível, preservando o núcleo quantitativo Python e a reprodutibilidade dos resultados.

## Arquitetura de informação

1. **Visão geral:** atalhos, últimas execuções e estado das fontes.
2. **Backtests:** Carteira e Por ativo em um fluxo Universo → Estratégia → Custos e sizing → Revisão.
3. **Pesquisa:** Otimizador, Screening e Fundamentos.
4. **Histórico:** busca, filtros, comparação, duplicação e exportação de execuções.
5. **Dados e configurações:** CSV/Norgate, moeda, tema, timezone, presets e retenção.

## Design system

- Fundo `#F7F8FA`, superfície `#FFFFFF`, texto `#17202A`, primária `#315CF4`.
- Positivo `#087A55`, negativo `#C43D4B`, alerta `#B66A00`, borda `#DFE4EA`.
- Geist/Inter, números tabulares, escala espacial de 4 px, raios de 8/12 px.
- Navegação sem emojis; termos e mensagens em português com glossário quantitativo.
- Tema escuro equivalente, sem preto puro.

## Telas do protótipo Sites

1. Visão geral.
2. Configurador de carteira com stepper e revisão pré-execução.
3. Resultado da carteira: resumo, exposição, ativos, operações e metodologia.
4. Otimizador: IS/OOS, walk-forward, sensibilidade e alertas de overfitting.
5. Screening com ações para gráfico, fundamentos e backtest.
6. Fundamentos por categorias e data de referência.
7. Histórico pesquisável e comparação de execuções.
8. Estados mobile, loading, vazio, erro e dados parciais.

## Estratégia técnica

### Fase 1 — Streamlit melhorado

Aplicar tokens, idioma consistente, agrupamento visual, estados claros e componentes
reutilizáveis. O tema inicial já está em `.streamlit/config.toml` e `ui/theme.py`.

### Fase 2 — Separar domínio e apresentação

Expor o núcleo `src/` por FastAPI com contratos OpenAPI versionados. Backtests e
otimizações viram jobs persistentes com progresso, cancelamento e downloads.

Rotas propostas: `POST /backtests/portfolio`, `POST /backtests/per-asset`,
`POST /optimizations`, `POST /screenings`, `GET /fundamentals/{ticker}`,
`GET /runs` e `GET /runs/{id}`.

### Fase 3 — Frontend Sites

Criar Next.js + TypeScript, Plotly React, tabelas virtualizadas e rotas endereçáveis.
Migrar verticalmente: Carteira → Por ativo → Otimizador → Screening → Fundamentos → Histórico.
Manter Streamlit até obter paridade numérica com fixtures de regressão.

### Fase 4 — Publicação

1. Criar o novo projeto com Sites e salvar o ID em `.openai/hosting.json`.
2. Configurar repositório-fonte e variáveis sem persistir credenciais.
3. Validar build, acessibilidade e regressão numérica.
4. Salvar uma versão a partir do commit exato.
5. Implantar primeiro com acesso privado e verificar status/logs.
6. Ampliar o acesso somente após aprovação explícita.

## Acessibilidade e responsividade

- WCAG 2.2 AA, contraste ≥ 4,5:1, foco visível e uso completo por teclado.
- Alvos de toque ≥ 44×44 px; labels persistentes e erros associados ao campo.
- Ganho/perda nunca indicado apenas por cor; gráficos têm tabela/exportação equivalente.
- Breakpoints de 360, 768, 1024 e 1440 px; sem scroll horizontal global a 200% de zoom.

## Critérios de aceite

- Um usuário novo configura carteira sem documentação externa.
- A revisão mostra universo, período, regras, custos, sizing e riscos.
- O primeiro viewport do resultado responde retorno, risco, operações e período.
- Otimizador deixa inequívoca a validação IS/OOS ou walk-forward.
- Screening chega a gráfico, fundamentos ou backtest em um clique.
- Histórico encontra execuções por nota, ticker, modo ou data.
- Layout e navegação passam em mobile, teclado e WCAG AA.
- Novo frontend coincide numericamente com as fixtures do Streamlit.
