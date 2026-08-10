"""Static markdown blocks shown in the UI (strategy description + disclaimer)."""

STRATEGY_DESCRIPTION = """
**Estratégia comprada de reversão à média.** Um sinal é confirmado no
**fechamento** do candle quando as duas condições são satisfeitas:

1. o **RSI(2)** está abaixo do limite de entrada, por padrão **10**; e
2. o candle apresenta um padrão de reversão altista, por padrão **Hammer**.

Como o sinal só é conhecido após o fechamento, o padrão realista é executar
entradas e saídas na **abertura do candle seguinte**, evitando viés de antecipação.
"""


DISCLAIMER = """
⚠️ **Resultados de backtest são hipotéticos.** Desempenho passado não garante
resultados futuros. Valide a estratégia fora da amostra e considere custos,
liquidez e risco antes de qualquer uso real. Esta ferramenta serve apenas para
pesquisa e educação e **não constitui recomendação de investimento**.
"""
