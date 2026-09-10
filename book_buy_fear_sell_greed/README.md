# Buy Fear, Sell Greed — laboratório quantitativo

Projeto educacional independente em português com um scanner e backtests das sete famílias de estratégias estudadas no livro de Larry Connors. O conteúdo é uma síntese técnica original; não é tradução nem reprodução do livro.

## Executar

```powershell
cd C:\Users\bssnm\RSI2\book_buy_fear_sell_greed
python -m pip install -r requirements.txt
streamlit run app.py
```

O painel aceita três fontes:

- **Norgate Data local:** requer Windows, pacote `norgatedata`, assinatura ativa e Norgate Data Updater aberto. Permite informar tickers ou selecionar uma watchlist/database, com séries diárias Total Return, Capital, Capital + dividendos especiais ou sem ajuste.
- **Yahoo Finance:** download de séries ajustadas para testes rápidos.
- **CSV:** colunas `date, open, high, low, close, volume`; para múltiplos ativos, inclua `ticker`.

Para instalar ou atualizar somente a integração Norgate:

```powershell
python -m pip install --upgrade norgatedata
```

## Testar

```powershell
python -m pytest tests -q
```

## Premissas relevantes

- Indicadores usam apenas dados conhecidos na barra correspondente.
- Sinais confirmados no fechamento entram apenas em D+1: na abertura ou por stop-limit DAY no rompimento da barra de sinal. Num gap de alta long (`Open[D+1] > High[D]`), o modelo só registra fill se `Low[D+1] < High[D]`; no short, aplica a condição espelhada.
- Ordens-limitadas só são preenchidas quando a máxima/mínima toca o preço.
- Comissão e slippage são configuráveis; aluguel, juros e impostos não são modelados.
- O custo-padrão é IBKR Pro Tiered, primeira faixa mensal: USD 0,0035 por ação, mínimo USD 0,35 e teto de 1% do valor da ordem. O modo Fixed usa USD 0,005 por ação e mínimo USD 1. Taxas de terceiros são aproximadas em bps.
- O modo padrão usa uma única carteira: cada posição reserva a alocação-alvo completa, saídas liberam capacidade antes de novas entradas e sinais simultâneos são priorizados pela extremidade do indicador, com desempate pelo ticker.
- A alavancagem multiplica o notional da posição-alvo e o limite bruto: alvo de 25%, limite de 100% e 2x produzem alvo efetivo de 50% por posição e teto efetivo de 200%. O valor padrão é 1x. Juros de financiamento, chamadas de margem e borrow de shorts ainda não são modelados.
- Patrimônio, exposição bruta real, exposição reservada, P&L realizado e custos são marcados em cada dia da união dos calendários carregados.
- O modo “Ativos independentes” permanece disponível apenas para diagnóstico.
- O scanner informa setups e gatilhos, não ordens nem recomendações.
- O ledger prospectivo em `state/paper_ledger.jsonl` é somente-acréscimo, idempotente para sinais/fills e encadeado por SHA-256. Ele é resistente à alteração silenciosa, mas não substitui armazenamento WORM externo.
- A integração TWS coloca apenas ordens com `transmit=False`; o usuário precisa revisar e transmitir manualmente. Instale-a com `python -m pip install -r requirements-ibkr.txt` e use a porta configurada para a conta Paper.
- O relatório em `docs/guia_tecnico.pdf` é gerado por `scripts/build_pdf.py`.

## Validação prospectiva e IBKR Paper

1. Fixe regras, universo, custos e tamanho antes de executar o histórico.
2. Registre os sinais futuros na aba **Ordens paper**. Repetir o registro não duplica o mesmo sinal.
3. Para colocar ordens não transmitidas no TWS, habilite a API, conecte-se manualmente à conta Paper e confirme a caixa de segurança no app.
4. Confira as ordens no TWS. O código não oferece opção para mudar `transmit` para `True`.
5. Depois da execução paper, registre o fill usando o Execution ID da IBKR; o identificador impede duplicidade.

## Painel de resultados

O modo **Carteira única** apresenta cinco visões complementares:

- **Visão geral:** capital, lucro, retorno, CAGR, curva patrimonial e tabela integral da estratégia contra o buy-and-hold. Sem rolagem interna, a tabela compara amostra, resultado, eficiência, risco, consistência e uso de capital. Inclui CAGR ajustado ao tempo posicionado (`CAGR / fração de sessões posicionadas`), CAGR por exposição média, retorno sobre drawdown, estatísticas diárias, duração do drawdown, giro, dias e percentual posicionado; o buy-and-hold aparece com 100% de tempo e exposição.
- **Risco:** volatilidade, Sharpe e Sortino com taxa livre de risco zero, Calmar, Ulcer Index, VaR/CVaR históricos, underwater e episódios de drawdown.
- **Operações:** acerto, payoff, profit factor, expectativa, extremos, sequências, custos, distribuições, duração e contribuição por ativo.
- **Meses e anos:** mapa mensal, retorno/drawdown anual e métricas móveis de 252 sessões.
- **Exposição e auditoria:** exposição real/reservada, posições simultâneas, turnover, sinais rejeitados, ordens sem fill e arquivo diário para conferência.

Sharpe, Sortino, volatilidade, drawdown, VaR e CVaR são calculados sobre a curva diária marcada a mercado, incluindo dias sem novas operações e custos já incorridos. VaR/CVaR são estatísticas históricas descritivas, não limites garantidos de perda.
