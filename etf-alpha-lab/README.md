# ETF Alpha Lab

Aplicativo independente para pesquisar um portfólio de estratégias com posições compradas e vendidas, exclusivamente em ETFs listados nos EUA, usando os dados locais da Norgate e preparando ordens para a IBKR.

O objetivo é superar o CAGR do SPY por uma margem configurável (2 p.p. a.a. por padrão), com volatilidade e drawdown menores. O software não presume nem promete que isso acontecerá. Um resultado só recebe sinal verde quando cumpre simultaneamente os três critérios. Backtest não é garantia de retorno futuro.

## O que já está implementado

- validação ETF-only pelos metadados `subtype1/subtype2` da Norgate;
- universo padrão de mais de 70 ETFs, organizado segundo as classes do ETF Database: ações por região/país/setor/fator, renda fixa, imóveis, commodities e moedas;
- preços Total Return e execução causal no open seguinte ao sinal;
- oito sleeves independentes: Macro Leading, US Factor Rotation, GICS Long/Short, Country Momentum, Multi-Asset Trend, Covel-Style Trend (proxy público), Technical Breakout e Credit Cycle;
- oito portfólios-candidatos transparentes, incluindo um teste isolado do proxy público Covel-style;
- sinais semanais ou mensais, com métricas, curva, turnover, dias de rebalanceamento, shorts e correlação por sleeve;
- regime composto por preço/crédito e indicadores antecedentes externos: juros reais, curva, spreads corporativos, M2 e ISM Manufacturing PMI;
- pesos fixos explícitos por candidato e matriz de correlação observada, sem otimizador de período completo;
- exposição bruta máxima de 100%, limite líquido e limite por ETF — sem alavancagem;
- shorts diretos com custo de aluguel anual configurável;
- comissão IBKR Pro Fixed ou Tiered, mínimo por ordem, custos terceiros e slippage;
- comparação líquida com SPY e scorecard em janelas móveis de três anos;
- geração de ordens-alvo long/short e CSV para revisão;
- adaptador opcional para TWS/IB Gateway, restrito a paper nesta versão.

## Instalação e execução

Requisitos: Windows, Norgate Data Updater aberto e assinatura com `US Equities`; Python 3.10+.

```powershell
cd C:\Users\bssnm\RSI2\etf-alpha-lab
python -m pip install -e .
.\scripts\start.ps1
```

Para habilitar a conexão opcional à IBKR:

```powershell
python -m pip install -e ".[ibkr]"
```

Ative a API no TWS/IB Gateway e comece numa conta paper. Portas usuais aceitas pelo bloqueio de segurança: TWS paper `7497`, Gateway paper `4002`. O envio live está intencionalmente desabilitado no código.

Testes:

```powershell
python -m pytest -q
```

## Premissas e limitações importantes

1. A lista inicial privilegia ETFs líquidos e antigos, mas qualquer símbolo aceito como ETF pela Norgate pode ser inserido. ETNs e ações são rejeitados.
2. O custo Tiered usa a primeira faixa (USD 0,0035/ação, mínimo USD 0,35); o Fixed usa USD 0,005/ação, mínimo USD 1. Custos de venue/regulatórios do Tiered são aproximados por `third_party_bps`, pois dependem da rota e liquidez. Confira a [tabela oficial da IBKR](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php).
3. O borrow histórico de cada ETF não está nos preços Norgate. O backtest usa uma taxa anual configurável e conservadora. Antes de cada short real, confirme disponibilidade e taxa na IBKR; um ETF pode ficar hard-to-borrow ou indisponível.
4. Total Return é apropriado para sinais e retorno econômico, mas a execução com OHLC ajustado é uma aproximação. Resultados candidatos devem ser reexecutados com auditoria de eventos/distribuições.
5. O app ainda não faz seleção point-in-time de todo o universo de ETFs. Para evitar viés de sobrevivência, a fase seguinte deve construir um catálogo histórico incluindo `US Equities Delisted` e datas de primeira/última cotação.
6. A tela de janelas móveis não substitui um protocolo walk-forward congelado. Não ajuste parâmetros olhando o período completo.

## Caminho recomendado até produção

- congelar universos point-in-time incluindo ETFs encerrados;
- separar desenvolvimento, validação e teste final nunca observado;
- stressar slippage, borrow, gaps e falhas de execução;
- exigir estabilidade entre regimes e significância após múltiplos testes;
- rodar paper por pelo menos algumas dezenas de rebalanceamentos;
- reconciliar fills e custos reais com o modelo antes de qualquer capital live.

Este projeto é software de pesquisa, não recomendação de investimento.

## Curadoria do universo

A organização segue a [taxonomia de categorias do ETF Database](https://etfdb.com/etfdb-categories/) e sua separação por [países](https://etfdb.com/etfs/country/). O ETFdb é usado como referência de cobertura, não como fonte de preços. A admissão operacional é confirmada na Norgate local: subtipo ETF, listagem em NYSE Arca/Nasdaq/Cboe BZX, série corrente e liquidez recente. Produtos inversos e alavancados são excluídos; a estratégia obtém exposição short vendendo ETFs convencionais diretamente.

## Baseline atual auditado nesta máquina

Com os 76 ETFs padrão, 2005-01-03 a 2025-12-31, Norgate Total Return, indicadores FRED, sinal no fechamento e execução no open seguinte, IBKR Pro Tiered aproximado, slippage de 2 bps/lado e borrow de 3% a.a., os candidatos produziram:

| Candidato | CAGR | Volatilidade | Drawdown máximo |
|---|---:|---:|---:|
| Growth + Regime | 8,45% | 12,41% | -21,59% |
| Alta Convicção | 7,94% | 11,76% | -20,60% |
| Diversificado | 7,82% | 11,94% | -19,94% |
| Rotação Global | 7,49% | 13,00% | -18,92% |
| Alpha Setorial | 7,21% | 12,17% | -22,07% |
| Defensivo Long/Short | 6,16% | 8,90% | -16,60% |
| Trend Multiativo | 5,75% | 9,02% | -16,86% |
| SPY buy & hold | 10,63% | 18,47% | -55,42% |

Todos os candidatos reduzem fortemente risco e drawdown, mas **nenhum satisfaz o objetivo de retorno** e todos são rejeitados pela trava de promoção. A combinação não usa alavancagem, limita a exposição bruta a 100% e cada ETF a 35%. O resultado expõe o trade-off observado: as sleeves defensivas e descorrelacionadas reduzem risco, mas também diluem CAGR. Os candidatos são hipóteses de pesquisa, não uma seleção feita retrospectivamente pelo vencedor.

### Fontes macro

- [FRED DFII10](https://fred.stlouisfed.org/series/DFII10): juro real de 10 anos;
- [FRED T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y): inclinação 10Y–2Y;
- [FRED BAMLC0A0CM](https://fred.stlouisfed.org/series/BAMLC0A0CM) e [BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2): spreads corporate investment grade e high yield;
- [FRED M2SL](https://fred.stlouisfed.org/series/M2SL): oferta monetária M2;
- Norgate local: histórico licenciado do ISM Manufacturing PMI, claims, NFCI e CFNAI.

O ISM Services PMI não é reconstruído por scraping: os relatórios oficiais restringem a criação automatizada de séries derivadas sem autorização. Na ausência de feed licenciado automático, o componente fica `NaN` e não reduz o score do regime.
