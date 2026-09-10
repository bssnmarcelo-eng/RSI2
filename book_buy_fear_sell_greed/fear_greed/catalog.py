"""Catálogo das regras publicadas e parâmetros testáveis."""
from __future__ import annotations

STRATEGIES = {
    "rsi_powerzones": {
        "name": "RSI PowerZones",
        "direction": "Long",
        "assets": "SPY",
        "summary": "Compra sobrevenda de curto prazo dentro da tendência de 200 dias.",
    },
    "crash": {
        "name": "CRASH",
        "direction": "Short",
        "assets": "Ações líquidas e muito voláteis",
        "summary": "Vende altas parabólicas após confirmação extrema pelo ConnorsRSI.",
    },
    "vol_panics": {
        "name": "Vol Panics",
        "direction": "Short",
        "assets": "VXX",
        "summary": "Vende picos de medo e permite escalonamento da posição.",
    },
    "vxx_trend": {
        "name": "VXX Trend",
        "direction": "Short",
        "assets": "VXX",
        "summary": "Segue a tendência de baixa por cruzamento de médias 10/30.",
    },
    "trading_new_highs": {
        "name": "Trading New Highs",
        "direction": "Long",
        "assets": "Ações líquidas",
        "summary": "Compra pânico após máxima de 52 semanas recente.",
    },
    "tps_long": {
        "name": "TPS Long",
        "direction": "Long",
        "assets": "ETFs líquidos não alavancados/não inversos",
        "summary": "Escalona compras enquanto o medo aumenta em tendência de alta.",
    },
    "tps_short": {
        "name": "TPS Short",
        "direction": "Short",
        "assets": "ETFs líquidos não alavancados/não inversos",
        "summary": "Escalona vendas enquanto a ganância aumenta em tendência de baixa.",
    },
    "terror_gaps": {
        "name": "Terror Gaps",
        "direction": "Long",
        "assets": "ETFs líquidos, inclusive alavancados",
        "summary": "Compra continuação intradiária de queda após sobrevenda e gap de baixa.",
    },
}


BOOK_BENCHMARKS = {
    "rsi_powerzones_30_25": {"trades": 202, "win_rate": 90.59, "avg_return": 1.73, "days": 4.95},
    "rsi_powerzones_25_20": {"trades": 147, "win_rate": 92.52, "avg_return": 1.89, "days": 4.84},
    "vol_panics_1234": {"trades": 104, "win_rate": 97.12, "avg_return": 4.86, "days": 3.32},
    "vxx_trend_sma": {"trades": 32, "win_rate": 56.25, "avg_return": 13.02, "days": 53.34},
    "new_highs_7": {"trades": 1367, "win_rate": 77.03, "avg_return": 4.10, "days": 4.03},
    "new_highs_10": {"trades": 533, "win_rate": 79.74, "avg_return": 6.47, "days": 3.87},
    "tps_spy_1234": {"trades": 211, "win_rate": 94.79, "avg_return": 1.12, "days": 4.0},
}


RULE_DETAILS = {
    "rsi_powerzones": {
        "logic": "Explora uma sobrevenda rápida do SPY sem abandonar o regime primário de alta. A queda de poucos dias representa medo local dentro de uma tendência ainda positiva.",
        "universe": "SPY, usando barras diárias ajustadas. O estudo foi desenhado para o índice amplo norte-americano; aplicar a outros ativos é uma nova hipótese que deve ser validada.",
        "setup": [
            "O fechamento permanece acima da média móvel simples de 200 dias.",
            "O RSI de 4 períodos fecha abaixo do primeiro nível: 30 na versão-base ou 25 na versão mais seletiva.",
        ],
        "entry": "O fechamento confirma o sinal em D. A primeira unidade só pode entrar em D+1, na abertura ou pela regra de rompimento escolhida.",
        "management": [
            "Pode-se dividir a posição em duas unidades iguais.",
            "A segunda unidade entra somente em uma barra posterior, se o RSI(4) cair abaixo de 25 — ou 20 na variante 25/20 — e a condição de tendência continuar válida.",
            "Não iniciar nova posição quando o SPY estiver abaixo da SMA(200).",
        ],
        "exit": "Quando RSI(4) fechar acima de 55 em D, encerrar toda a posição na abertura de D+1.",
        "risks": "Uma tendência pode mudar antes de a média de 200 dias reagir. A segunda compra aumenta exposição durante a queda e não constitui stop de risco.",
    },
    "crash": {
        "logic": "Procura ações que subiram de forma extrema e ficaram vulneráveis a uma reversão curta. É uma operação contrária à euforia, executada somente se o preço continuar avançando após o setup.",
        "universe": "Ações com preço acima de US$ 5, média de volume de 21 dias de pelo menos 1 milhão de ações e volatilidade histórica anualizada de 100 dias igual ou superior a 100%. O estudo também avaliou filtros de 60% e 80%.",
        "setup": [
            "ConnorsRSI(3,2,100) fecha em 90 ou mais.",
            "Preço, volume e volatilidade precisam atender aos filtros na barra do setup.",
        ],
        "entry": "No pregão seguinte, colocar uma venda short limitada 3% acima do fechamento do setup; uma variante usa 5%. Só há operação se a máxima tocar o limite.",
        "management": [
            "Não perseguir a entrada se o limite não for alcançado.",
            "A implementação usa uma posição única, sem piramidagem.",
            "Antes de operar, confirmar disponibilidade e custo do aluguel.",
        ],
        "exit": "Quando ConnorsRSI fechar abaixo de 30 em D, recomprar na abertura de D+1. A versão mais exigente espera leitura inferior a 20.",
        "risks": "Short tem perda teoricamente ilimitada, risco de squeeze, recall e gap de alta. O livro discute puts profundas no dinheiro como alternativa de risco definido; opções não são simuladas no app.",
    },
    "vol_panics": {
        "logic": "Vende picos de medo refletidos no VXX. Como produtos de volatilidade tendem a recuar quando o choque desaparece, o método aumenta a posição apenas se o pânico continuar elevando o preço.",
        "universe": "VXX em barras diárias ajustadas. Séries históricas exigem atenção especial a splits, mudanças do produto e disponibilidade do instrumento em cada data.",
        "setup": [
            "O VXX fecha acima da média móvel simples de 5 dias.",
            "O RSI de 4 períodos fecha acima de 70.",
        ],
        "entry": "O fechamento confirma as duas condições em D; o short entra em D+1, na abertura ou pela regra de rompimento escolhida.",
        "management": [
            "Sem escala: posição completa na primeira entrada.",
            "Escala 1/1: duas metades; 2/3/5: 20%, 30% e 50%; 1/2/3/4: 10%, 20%, 30% e 40%.",
            "Cada nova parcela só entra em uma barra posterior cujo fechamento esteja acima do preço da parcela anterior.",
        ],
        "exit": "Quando o VXX fechar abaixo da SMA(5) em D, encerrar toda a posição na abertura de D+1.",
        "risks": "Choques de volatilidade podem persistir e produzir gaps violentos. Escalonar shorts aumenta o risco exatamente quando o preço sobe; limite previamente o capital total.",
    },
    "vxx_trend": {
        "logic": "Captura a tendência estrutural de baixa do VXX, em vez de tentar prever cada pico. É a estratégia seguidora de tendência do conjunto.",
        "universe": "VXX diário, com dados ajustados e histórico suficiente para calcular as médias de 10 e 30 dias.",
        "setup": [
            "Calcular médias móveis de 10 e 30 períodos.",
            "Pode-se escolher médias simples (SMA) ou exponenciais (EMA); a escolha deve permanecer fixa durante o teste.",
        ],
        "entry": "O cruzamento baixista é confirmado no fechamento de D; o short entra em D+1, na abertura ou pela regra de rompimento escolhida.",
        "management": [
            "Usar uma única posição, sem novas entradas enquanto o cruzamento baixista permanecer ativo.",
            "Cruzamentos são identificados comparando a relação das médias atual com a da barra anterior.",
        ],
        "exit": "Quando o cruzamento altista for confirmado no fechamento de D, recomprar na abertura de D+1.",
        "risks": "Pode haver longos períodos de perda aberta e falsos cruzamentos. O retorno depende fortemente da construção e do comportamento histórico do ETN.",
    },
    "trading_new_highs": {
        "logic": "Combina uma âncora positiva — máxima de 52 semanas recente — com uma capitulação rápida. A hipótese é que os participantes continuam ancorados no topo e exageram ao liquidar o recuo.",
        "universe": "Ações acima de US$ 5, com média diária de 21 dias superior a 1 milhão de ações.",
        "setup": [
            "O ativo alcançou uma nova máxima intradiária de 52 semanas em algum dos últimos 20 pregões.",
            "Depois disso, ConnorsRSI fecha abaixo de 15.",
        ],
        "entry": "No pregão seguinte ao setup, colocar compra limitada 7% abaixo do fechamento do sinal; a variante mais profunda usa 10%. A mínima do dia deve tocar o limite.",
        "management": [
            "Cancelar a ideia se a ordem não for executada no pregão seguinte; não carregar indefinidamente uma ordem antiga.",
            "O app utiliza uma única entrada e não faz preço médio.",
        ],
        "exit": "Quando ConnorsRSI fechar acima de 70 em D, vender na abertura de D+1.",
        "risks": "Uma máxima recente não protege contra notícia adversa ou mudança fundamental. O limite profundo pode concentrar preenchimentos nos eventos mais perigosos.",
    },
    "tps_long": {
        "logic": "TPS significa Time, Price and Scale-In. No lado comprado, espera a sobrevenda amadurecer e aumenta gradualmente a posição enquanto o medo produz preços inferiores dentro de um regime de alta.",
        "universe": "ETFs líquidos, não alavancados e não inversos, com média de volume dos 20 pregões anteriores de pelo menos 250 mil cotas.",
        "setup": [
            "Fechamento acima da SMA(200).",
            "RSI(2) abaixo de 25 em dois fechamentos consecutivos.",
        ],
        "entry": "O segundo fechamento consecutivo abaixo de 25 confirma o sinal em D; a primeira parcela entra em D+1, na abertura ou pela regra de rompimento escolhida.",
        "management": [
            "Escala 2/3/5: 20%, 30% e 50%; escala 1/2/3/4: 10%, 20%, 30% e 40%.",
            "Uma nova parcela só entra em dia posterior se o fechamento estiver abaixo do preço da parcela anterior.",
            "Não iniciar nem acrescentar se o ETF fechar abaixo da SMA(200).",
        ],
        "exit": "Quando RSI(2) fechar acima de 70 em D, vender todas as parcelas na abertura de D+1, mesmo que a posição ainda não esteja completa.",
        "risks": "O risco é aberto e cresce durante a queda. ETFs correlacionados podem disparar simultaneamente, transformando várias posições aparentes em uma única aposta de mercado.",
    },
    "tps_short": {
        "logic": "É a versão espelhada do TPS: aumenta o short enquanto um repique movido por otimismo ocorre dentro de uma tendência primária de baixa.",
        "universe": "ETFs líquidos, não alavancados e não inversos, com média de volume dos 20 pregões anteriores de pelo menos 250 mil cotas.",
        "setup": [
            "Fechamento abaixo da SMA(200).",
            "RSI(2) acima de 75 em dois fechamentos consecutivos.",
        ],
        "entry": "O segundo fechamento consecutivo acima de 75 confirma o sinal em D; a primeira parcela short entra em D+1, na abertura ou pela regra de rompimento escolhida.",
        "management": [
            "Usar 20/30/50 ou 10/20/30/40 conforme a escala escolhida.",
            "Acrescentar somente em barra posterior cujo fechamento esteja acima do preço da parcela anterior.",
            "Não iniciar nem acrescentar se o ETF recuperar a SMA(200).",
        ],
        "exit": "Quando RSI(2) fechar abaixo de 30 em D, recomprar toda a posição na abertura de D+1.",
        "risks": "Além do risco de tendência e correlação, há aluguel, recall e gaps de alta. A média de 200 dias confirma o passado e não limita a perda.",
    },
    "terror_gaps": {
        "logic": "Procura a sequência medo acumulado, choque noturno e capitulação intradiária. A compra só acontece depois que uma série já sobrevendida abre em baixa e continua cedendo.",
        "universe": "ETFs com média de volume dos 20 pregões anteriores superior a 250 mil cotas. O estudo incluiu ETFs alavancados, ao contrário do TPS.",
        "setup": [
            "Na sessão anterior, ConnorsRSI fechou abaixo de 5.",
            "A sessão atual abre abaixo do fechamento anterior, caracterizando gap de baixa.",
        ],
        "entry": "Colocar compra limitada 1%, 1,5%, 2% ou 2,5% abaixo da abertura. A operação existe somente se a mínima intradiária alcançar esse preço.",
        "management": [
            "Uma posição por sinal, sem escalonamento adicional.",
            "O teste pode incluir ou excluir 10/10/2008 e 24/08/2015. O estudo publicado os excluiu porque os dois dias concentravam mais de 30% dos sinais.",
            "Sempre comparar os dois recortes para revelar a sensibilidade a eventos raros.",
        ],
        "exit": "Quando ConnorsRSI fechar acima de 70 em D, vender na abertura de D+1.",
        "risks": "O preenchimento ocorre durante queda acelerada e pode anteceder novo gap. Resultados agregados podem ser dominados por poucas datas de pânico e por ativos altamente correlacionados.",
    },
}
