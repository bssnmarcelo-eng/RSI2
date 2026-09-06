# Estudo ampliado de seleção de trades — run `20260906-174817-698`

Data: 6 de setembro de 2026.

## Conclusão executiva

Não foi encontrada uma regra causal que, ao mesmo tempo, produzisse mais de
95% de acerto fora da amostra e pelo menos 20 operações em **cada** ano. A meta
de 100% também não foi alcançada de forma válida. O resultado de 49/49 do estudo
anterior desaparece quando se exige uma amostra anual útil; mantê-lo como se
fosse uma solução seria sobreajuste.

A descoberta mais útil foi um filtro de **densidade de sinais**: operar somente
quando há pelo menos 10 candidatos com entrada na mesma data. Ele é conhecido
antes da abertura, não usa o resultado do trade e melhorou substancialmente o
período final, embora tenha ficado aquém da meta:

| Amostra | Baseline | Candidatos ≥ 10 | Trades filtrados | Mínimo/ano |
|---|---:|---:|---:|---:|
| Validação 2011–2018 | 91,68% | **95,24%** | 819 | 36 |
| Teste 2019–2026 | 89,06% | **92,11%** | 760 | 30 |

No teste final, a expectativa por operação subiu de 3,56% para **4,93%**, o
profit factor calculado sobre retornos subiu de 2,80 para **5,55**, e a frequência
de perdas de 20% ou mais caiu de 3,71% para **1,58%**. O intervalo exato de 95%
para os 700 acertos em 760 operações é 89,95%–93,92%; portanto, os dados também
não sustentam estatisticamente uma taxa verdadeira de 95%.

O filtro foi implementado como opção experimental, desativada por padrão. Como
o limiar foi investigado neste mesmo conjunto, ele precisa de confirmação
prospectiva antes de uso real.

## Dados e protocolo

O log contém 6.451 operações semanais, 455 tickers com trades e histórico de
1993 a 2026. Foram preservados três blocos cronológicos:

| Bloco | Período | Trades | Uso |
|---|---:|---:|---|
| Treino | 1993–2010 | 3.229 | ajuste dos parâmetros |
| Validação | 2011–2018 | 1.659 | escolha de regras/modelos |
| Teste final | 2019–2026 | 1.563 | medição fora da amostra |

Todas as variáveis usam somente o fechamento da barra de sinal ou informações
já encerradas. A seleção acontece antes da abertura seguinte. Foram geradas 131
variáveis e rankings cross-sectional, incluindo:

- **estatísticas:** volatilidade, downside volatility, z-score, assimetria,
  curtose, autocorrelação, beta/correlação e histórico anterior do ticker;
- **técnicas:** RSI, médias e inclinações, Bandas de Bollinger, estocástico,
  ATR e breadth acima das médias de 20/50/200 semanas;
- **gráficas/price action:** corpo e sombras, posição do fechamento, gap,
  inside bar, compressão e menor amplitude;
- **momentum:** retornos e força relativa em 1, 2, 4, 13, 26 e 52 semanas,
  além de tendência e drawdown do Nasdaq-100;
- **regime:** momentum, tendência, volatilidade e TRIN do mercado, além da
  quantidade simultânea de sinais.

Foram examinados 4.978 limiares univariados derivados do treino. Destes, 3.884
mantiveram no mínimo 20 trades em cada ano tanto na validação quanto no teste;
**nenhum** superou 95% nos dois blocos. Também foram examinadas conjunções das
100 regras mais promissoras: entre as 33 que respeitaram a frequência anual,
nenhuma superou 95% nos dois blocos.

Além das regras transparentes, regressões logísticas regularizadas classificaram
os candidatos e admitiram os 2–4 melhores em cada data. A arquitetura e a
regularização foram escolhidas exclusivamente na validação e reajustadas no
conjunto pré-teste.

## Resultado por família multivariada

| Família | Acerto validação | Trades validação | Acerto teste | Trades teste | Mínimo no ano de teste |
|---|---:|---:|---:|---:|---:|
| Técnica | 90,94% | 552 | 86,81% | 508 | 50 |
| Gráfica | 90,02% | 882 | 86,90% | 832 | 77 |
| Momentum | 90,58% | 552 | **88,19%** | 508 | 50 |
| Estatística | 90,58% | 552 | 87,80% | 508 | 50 |
| Combinada | 90,79% | 738 | 87,96% | 681 | 65 |

Os rankings escolheram trades suficientes, mas não melhoraram o baseline no
teste. Isso indica que, entre sinais RSI2 já acionados na mesma semana, os
indicadores do próprio ativo não separam consistentemente vencedores e
perdedores. A informação mais relevante foi a existência de muitos sinais ao
mesmo tempo — um efeito de regime, não uma capacidade de identificar com
certeza qual ação vencerá.

## Regras que pareciam perfeitas, mas falharam no critério anual

Quedas fortes do Nasdaq produziram grupos de altíssima precisão após 2010. Por
exemplo, momentum de 13 semanas do índice abaixo de −13,47% teve 33/33 na
validação e 106/107 no teste. Porém, não gerou qualquer trade em 20 dos 34 anos,
e no treino teve somente 81,48% de acerto. É uma condição rara de repique, não
uma solução anual robusta.

O melhor limiar que cumpriu 20 trades em cada ano da validação e do teste foi o
quartil inferior de downside volatility entre candidatos: 95,85% na validação,
mas apenas 90,88% no teste. A melhor conjunção elegível atingiu 96,80% na
validação e 89,62% no teste. Esses tombos são o padrão esperado quando uma regra
é selecionada entre milhares de tentativas; o risco de backtest overfitting é
descrito formalmente por Bailey et al. ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)).

## Fundamentalistas: por que não entraram no backtest

O provedor disponível neste repositório entrega fundamentos como fotografia
atual, não como série histórica point-in-time. Aplicar hoje P/L, ROE, crescimento,
qualidade ou F-score a sinais de 1993–2026 introduziria look-ahead e viés de
sobrevivência. Por isso, a família fundamentalista foi especificada, mas não
pontuada artificialmente.

Um teste válido exigiria uma base com data de publicação e revisões históricas.
As definições de profitability e investment podem seguir a
[Data Library de Kenneth French](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.HTML)
e o modelo de cinco fatores de [Fama e French](https://www.aea.ru/data/pdf/fama2015.pdf);
qualidade contábil pode seguir o F-score de
[Piotroski](https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf).
Sem os dados point-in-time, qualquer número produzido seria inválido.

## Interpretação e recomendação

Há evidência de que padrões técnicos podem carregar informação incremental, mas
não determinística — coerente com Lo, Mamaysky e Wang
([NBER](https://www.nber.org/papers/w7613)). Momentum também é um efeito
documentado por Jegadeesh e Titman
([DOI](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)), mas nesta estratégia
não separou os melhores sinais fora da amostra.

Recomendação prática:

1. não usar o filtro antigo de 49/49 como promessa de 100%;
2. testar `mínimo de candidatos simultâneos = 10` apenas como experimento e com
   dimensionamento conservador;
3. coletar resultados prospectivos sem reajustar o limiar;
4. obter fundamentos point-in-time antes de testar qualidade/valuation;
5. tratar 95% como hipótese a validar, não como parâmetro que o backtest precisa
   necessariamente fabricar.

## Reprodutibilidade

- enriquecimento e busca de regras: `scripts/analyze_trade_filters.py`;
- modelos e separação temporal: `scripts/study_trade_selection.py`;
- artefatos detalhados são gerados em `.local-run/` e ficam fora do Git por
  tamanho e por serem reproduzíveis a partir do log salvo.

Comando principal:

```powershell
python scripts\study_trade_selection.py 20260906-174817-698
```
