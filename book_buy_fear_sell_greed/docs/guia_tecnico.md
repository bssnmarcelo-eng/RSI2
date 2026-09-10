# Comprar o medo, vender a ganância

## Guia técnico independente para estudo e validação

Este material organiza, em linguagem própria, as regras quantitativas observadas durante a leitura de *Buy the Fear, Sell the Greed*. Não é tradução, substituto do livro ou recomendação financeira. Os resultados históricos citados pertencem ao estudo original e precisam ser reproduzidos com dados, universo e custos claramente definidos antes de qualquer uso.

## A tese central

O fio condutor é a reversão à média causada por comportamento extremo. Em tendências de alta, quedas rápidas expulsam compradores frágeis e podem criar entradas long. Em tendências de baixa, repiques fortes atraem compradores tardios e podem criar entradas short. A emoção fornece a hipótese; regras mensuráveis, execução disciplinada e controle de risco tornam a hipótese testável.

O método separa quatro decisões: regime, extremo, execução e saída. A média de 200 dias define o regime em várias estratégias. RSI ou ConnorsRSI medem o extremo. Ordens no fechamento ou limites definem a execução. A normalização do oscilador ou um cruzamento de médias define a saída.

## Indicadores

### RSI de Wilder

O RSI compara ganhos e perdas suavizados. Períodos curtos, como RSI(2) e RSI(4), reagem fortemente às últimas barras e são usados aqui para identificar movimentos de curtíssimo prazo. O valor deve ser calculado de forma causal, sem preencher o início da série com informação futura.

### ConnorsRSI

O indicador padrão combina três componentes na mesma escala de zero a cem:

1. RSI de três períodos sobre o fechamento;
2. RSI de dois períodos sobre a duração assinada da sequência de altas ou baixas;
3. PercentRank do retorno de um dia contra os cem retornos anteriores.

`ConnorsRSI(3,2,100) = [RSI(Close,3) + RSI(Streak,2) + PercentRank(Return,100)] / 3`

PercentRank compara o retorno atual apenas com retornos anteriores. Esse deslocamento é essencial para evitar look-ahead.

## As sete famílias de estratégia

### 1. RSI PowerZones

Universo principal: SPY. O fechamento deve estar acima da SMA(200). Compra-se quando RSI(4) cai abaixo de 30; uma variante mais seletiva usa 25. Pode-se acrescentar uma segunda unidade se o RSI(4) alcançar 25 ou 20. A posição é encerrada quando RSI(4) supera 55. É uma estratégia long de reversão dentro de tendência de alta.

### 2. CRASH

Universo: ações acima de US$ 5, com média de volume de 21 dias de pelo menos um milhão e volatilidade histórica de cem dias muito elevada. Um ConnorsRSI de 90 ou mais forma o setup. No pregão seguinte, tenta-se vender short por limite 3% ou 5% acima do fechamento do setup. A saída ocorre quando ConnorsRSI cai abaixo de 30 ou 20. O risco de squeeze, gap e indisponibilidade de aluguel é central.

### 3. Vol Panics

Ativo: VXX. O setup short ocorre quando o fechamento está acima da SMA(5) e RSI(4) supera 70. A saída principal acontece quando o preço fecha abaixo da SMA(5). O estudo também discute saída por RSI(4) abaixo de 20. O escalonamento pode usar 20/30/50 ou 10/20/30/40, adicionando apenas quando o preço fecha acima da entrada anterior.

### 4. VXX Trend

Ativo: VXX. Vende-se no cruzamento da média de 10 períodos para baixo da média de 30; encerra-se no cruzamento oposto. Médias simples e exponenciais são variantes. É uma estratégia seguidora de tendência, diferente das demais estratégias predominantemente contrárias.

### 5. Trading New Highs

Universo: ações líquidas acima de US$ 5. O ativo deve ter alcançado uma máxima intradiária de 52 semanas nos vinte pregões anteriores e depois registrar ConnorsRSI abaixo de 15. No dia seguinte, coloca-se compra limitada 7% ou 10% abaixo do fechamento do setup. A saída ocorre com ConnorsRSI acima de 70. A tese é que a âncora mental da máxima recente amplifica a capitulação no recuo.

### 6. TPS — Time, Price and Scale-In

No lado long, o ETF precisa estar acima da SMA(200), e RSI(2) deve fechar abaixo de 25 por dois dias consecutivos. A primeira fração é comprada no fechamento; novas frações só entram em fechamentos inferiores à compra anterior e enquanto o filtro de tendência continua válido. A saída ocorre com RSI(2) acima de 70.

No lado short, as regras se invertem: preço abaixo da SMA(200), RSI(2) acima de 75 por dois dias, aumentos somente a preços superiores e saída quando RSI(2) cai abaixo de 30. Escalas usuais são 20/30/50 e 10/20/30/40.

### 7. Terror Gaps

Universo: ETFs com média de volume de vinte dias acima de 250 mil. O fechamento anterior apresenta ConnorsRSI abaixo de 5; a sessão seguinte abre em gap de baixa e continua caindo. A compra limitada fica 1%, 1,5%, 2% ou 2,5% abaixo da abertura. A saída ocorre quando ConnorsRSI supera 70.

O estudo publicou números sem 10/10/2008 e 24/08/2015: mais de 30% dos sinais estavam concentrados nesses dois episódios. Uma análise honesta deve exibir ambos os recortes e explicar a decisão, pois excluir eventos extremos altera a pergunta respondida pelo teste.

## Construção correta do backtest

Cada sinal deve ser calculado com dados disponíveis naquele instante. Um setup confirmado no fechamento de D só pode executar em D+1. No modelo de abertura usa-se a abertura seguinte; no rompimento, stop-limit DAY na máxima de D para long e na mínima de D para short. Se houver gap além do gatilho, o teste exige retorno através do nível da barra de sinal. Ordens limitadas próprias das estratégias só executam quando a máxima/mínima alcança o preço. O teste inclui custos, slippage e marcação diária a mercado. Posições restantes não são encerradas artificialmente por padrão.

No teste multiativo, todos os sinais disputam uma única carteira. Saídas são processadas antes das entradas; a posição-alvo completa é reservada desde a primeira parcela; sinais simultâneos são ordenados pela extremidade do indicador, com desempate pelo ticker. Patrimônio e exposição bruta são recalculados em cada data da união dos calendários.

O controle de **alavancagem** multiplica tanto o notional-alvo quanto o teto bruto configurado. Assim, posição-alvo de 25%, exposição máxima de 100% e alavancagem de 2x equivalem a uma posição efetiva de 50% e limite bruto efetivo de 200% do patrimônio. A curva diária incorpora integralmente os ganhos e perdas desse notional maior, mas a versão atual não desconta juros de financiamento, não simula chamadas de margem e não cobra borrow nos shorts. Resultados alavancados devem ser interpretados como uma aproximação antes desses custos e restrições.

## Leitura dos resultados

Na aba **Visão geral**, a tabela **Estratégia × Buy & Hold** apresenta métricas de resultado, risco, consistência e uso de capital. Além do retorno e do drawdown, ela informa quantos dias e qual percentual do período a estratégia permaneceu posicionada. O buy-and-hold é modelado com uma posição contínua e exposição de 100%, deixando explícita a diferença entre obter um resultado permanecendo integralmente investido e obtê-lo mantendo caixa em parte do período.

O **CAGR ajustado ao tempo posicionado** é definido neste aplicativo como `CAGR / percentual de sessões posicionadas`. Por exemplo, CAGR de 5% com presença no mercado em 25% das sessões resulta em 20% por unidade de tempo exposto. Trata-se de uma normalização linear para comparar eficiência temporal, não de uma promessa de que o capital ocioso poderia repetir ou compor o mesmo retorno. A tabela também mostra `CAGR / exposição bruta média`, retorno total sobre drawdown máximo, desvio negativo anual, duração do maior drawdown, frequência e extremos dos retornos diários e giro anual.

Retorno total e CAGR medem crescimento, mas precisam ser lidos junto de volatilidade, drawdown máximo, Calmar e Ulcer Index. Sharpe e Sortino usam a série diária completa e taxa livre de risco zero. VaR e CVaR de 95% são quantis históricos dos retornos diários; descrevem a amostra e não garantem uma perda máxima futura.

As estatísticas de operações incluem acerto, retorno médio e mediano, ganho/perda médios, payoff, profit factor, expectativa em dólares, extremos, duração e sequências. A análise por ativo revela concentração de P&L. O mapa mensal, os resultados anuais e as janelas móveis de 252 sessões ajudam a verificar se o desempenho depende de poucos períodos. Exposição real, exposição reservada, posições simultâneas, turnover, custos e sinais rejeitados mostram se o resultado seria operacionalmente compatível com a carteira definida.

Para comparação com tabelas históricas, documente fornecedor de dados, tratamento de dividendos e splits, universo sobrevivente ou ponto-no-tempo, datas, liquidez e regras de arredondamento. Igualdade exata não é esperada sem a mesma base original.

## Riscos que as taxas de acerto escondem

Taxa de acerto não mede o tamanho das perdas. Estratégias contrárias podem acumular perdas abertas antes da reversão, e escalonar amplia essa exposição. Stops não garantem o preço em gaps. Shorts podem ser recomprados compulsoriamente e ETFs de volatilidade têm decadência estrutural, splits e mudanças de produto.

Durante pânicos, sinais de países e setores diferentes convergem para o mesmo risco de mercado. Limites por fator, setor e direção são mais úteis que contar cada ticker como posição independente. Quando vários ETFs representam quase a mesma cesta, prefira o instrumento mais líquido.

## Processo de validação adotado

1. Congele as regras antes do teste.
2. Execute as regras fixas uma vez no histórico escolhido, sem treinamento ou otimização de parâmetros.
3. Meça retorno médio, distribuição, drawdown, exposição, capacidade, turnover e concentração por data.
4. Registre prospectivamente cada sinal em ledger append-only; qualquer mudança de parâmetro cria uma nova hipótese.
5. Prepare ordens na conta Paper com `transmit=False`, revise-as no TWS e registre os fills efetivos pelo Execution ID.
6. Compare continuamente fills, custos e slippage paper com as premissas do backtest antes de comprometer capital real.

## Construção de operações com opções

O apêndice apresenta a ideia de risco definido e retorno assimétrico. Num cenário altista, uma estrutura conceitual vende um spread de puts próximo do dinheiro e usa o crédito para financiar uma call fora do dinheiro. No cenário baixista, inverte-se a lógica. Isso não elimina risco: vencimento, volatilidade implícita, liquidez, exercício antecipado e escolha dos strikes alteram completamente o resultado.

## Conclusão

A contribuição mais útil é um processo: identificar o regime, quantificar uma emoção extrema, definir a execução antes do sinal e controlar o risco agregado. A vantagem histórica só é relevante quando sobrevive a dados novos, custos realistas e decisões tomadas sem conhecer o futuro.
