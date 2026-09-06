from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyDefinition:
    objective: str
    universe: str
    signal: str
    regime: str
    frequency: str
    long_rule: str
    short_rule: str
    exit_rule: str
    portfolio_role: str


@dataclass(frozen=True)
class CandidateProfile:
    name: str
    objective: str
    expected_tradeoff: str
    weights: dict[str, float]


STRATEGY_CATALOG: dict[str, StrategyDefinition] = {
    "Macro Leading": StrategyDefinition(
        objective="Capturar expansão e preservar capital quando os antecedentes enfraquecem.",
        universe="QQQ, SPY, MDY, IWM; defesa em IEF, TLT, GLD e BIL.",
        signal="Momentum de 6/12 meses combinado ao score de juros reais, curva, crédito, M2, PMI e atividade.",
        regime="Compra crescimento somente com score risk-on; fora dele escolhe o defensivo de maior momentum.",
        frequency="Mensal",
        long_rule="Melhor ETF de crescimento em risk-on; melhor ETF defensivo nos demais regimes.",
        short_rule="Não vende a descoberto.",
        exit_rule="Troca no fechamento mensal quando muda o regime ou o líder de momentum.",
        portfolio_role="Motor direcional principal e proteção macro.",
    ),
    "US Factor Rotation": StrategyDefinition(
        objective="Rotacionar entre fatores e estilos líquidos dos EUA.",
        universe="SPY, QQQ, VUG, MTUM, QUAL, XLK, MDY, IWM, RSP; defesa USMV, XLU, XLP, IEF, GLD, BIL.",
        signal="Força relativa ponderada de 3/6/12 meses e filtro de média móvel de 200 dias.",
        regime="Evita fatores ofensivos em risk-off.",
        frequency="Mensal",
        long_rule="Até três líderes acima da média de 200 dias; caso contrário, o melhor defensivo.",
        short_rule="Não vende a descoberto.",
        exit_rule="Sai quando perde top 3, tendência de 200 dias ou quando o regime muda.",
        portfolio_role="Motor de alpha em ações americanas.",
    ),
    "GICS Long/Short": StrategyDefinition(
        objective="Explorar dispersão entre os 11 setores GICS.",
        universe="XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLB, XLRE, XLK e XLU.",
        signal="Momentum relativo de 12 meses, descontando o último mês, mais tendência de 200 dias.",
        regime="Long reduzido fora de risk-on; shorts somente quando o ambiente não é risk-on.",
        frequency="Mensal",
        long_rule="Três setores líderes que estejam acima da média de 200 dias.",
        short_rule="Dois setores mais fracos, abaixo da média de 200 dias, em regime adverso.",
        exit_rule="Fecha quando sai dos extremos do ranking, recupera/perde tendência ou muda o regime.",
        portfolio_role="Alpha relativo e hedge parcial do beta acionário.",
    ),
    "Country Momentum": StrategyDefinition(
        objective="Capturar tendências persistentes entre bolsas nacionais.",
        universe="19 ETFs de países desenvolvidos e emergentes; caixa em BIL.",
        signal="Força relativa de 6/12 meses, descontando reversão do último mês, e média de 200 dias.",
        regime="Não abre risco de países em risk-off.",
        frequency="Mensal",
        long_rule="Três países líderes com tendência absoluta positiva.",
        short_rule="Não vende a descoberto.",
        exit_rule="Vai para BIL quando não há candidato elegível ou o regime fica risk-off.",
        portfolio_role="Diversificação geográfica e captura de ciclos fora dos EUA.",
    ),
    "Multi-Asset Trend": StrategyDefinition(
        objective="Capturar tendências lentas em classes de ativos pouco correlacionadas.",
        universe="SPY, QQQ, IWM, EFA, EEM, IEF, TLT, LQD, HYG, GLD, DBC e UUP.",
        signal="Sinal combinado de 6/12 meses, dimensionado pelo inverso da volatilidade de 63 dias.",
        regime="Independente do score macro para diversificar o risco de modelo.",
        frequency="Mensal",
        long_rule="Compra cada ETF quando ambas ou uma das janelas aponta tendência positiva.",
        short_rule="Short direto quando a tendência combinada é negativa; pesos normalizados para gross 100%.",
        exit_rule="Inverte ou zera quando os sinais de 6/12 meses mudam.",
        portfolio_role="Convexidade em crises prolongadas e diversificação multiativo.",
    ),
    "Covel-Style Trend (Public Proxy)": StrategyDefinition(
        objective="Testar uma aproximação pública e reproduzível do trend following clássico.",
        universe="SPY, QQQ, IWM, EFA, EEM, IEF, TLT, LQD, HYG, GLD, DBC e UUP.",
        signal="Rompimento Donchian de 55 pregões, long ou short, dimensionado pela volatilidade de 20 pregões.",
        regime="Independente de previsões, fundamentos e do score macro.",
        frequency="Sinais diários; pesos atualizados semanalmente",
        long_rule="Compra quando o fechamento supera a máxima dos 55 pregões anteriores.",
        short_rule="Vende quando o fechamento rompe a mínima dos 55 pregões anteriores.",
        exit_rule="Sai pela banda oposta de 20 pregões; execução no open seguinte.",
        portfolio_role="Benchmark transparente da filosofia; não representa regras proprietárias de Michael Covel.",
    ),
    "Technical Breakout": StrategyDefinition(
        objective="Capturar movimentos intermediários sem depender de dados macro.",
        universe="SPY, QQQ, IWM, EFA, EEM, TLT e GLD.",
        signal="Canal Donchian de 126 pregões com canal de saída de 63 pregões.",
        regime="Independente do regime; preço é o único gatilho.",
        frequency="Semanal",
        long_rule="Compra no rompimento da máxima anterior de 126 pregões.",
        short_rule="Short somente nos ETFs líquidos de ações ao romper a mínima de 126 pregões.",
        exit_rule="Sai pela banda oposta de 63 pregões; não usa stop intradiário.",
        portfolio_role="Diversificação técnica e resposta a novas tendências.",
    ),
    "Credit Cycle": StrategyDefinition(
        objective="Negociar expansão e contração do ciclo de crédito.",
        universe="HYG, LQD, FLOT e IEF.",
        signal="Tendência de 6 meses e média de 200 dias do spread de preço HYG/LQD.",
        regime="O score macro agrava a postura defensiva em risk-off.",
        frequency="Mensal",
        long_rule="HYG/FLOT quando o crédito melhora; IEF/LQD quando deteriora.",
        short_rule="Short de 20% em HYG somente na combinação de crédito fraco e risk-off.",
        exit_rule="Reverte quando HYG/LQD cruza tendência ou muda o regime.",
        portfolio_role="Baixa volatilidade, renda fixa e hedge de estresse de crédito.",
    ),
}


CANDIDATES: dict[str, CandidateProfile] = {
    "covel_proxy": CandidateProfile(
        "Covel-style (proxy público)",
        "Isolar um sistema clássico de trend following para comparação limpa.",
        "Pode sofrer falsos rompimentos e longos períodos de underperformance.",
        {"Covel-Style Trend (Public Proxy)": 1.0},
    ),
    "balanced": CandidateProfile(
        "Diversificado",
        "Equilibrar motores direcionais, relativos, técnicos e defensivos.",
        "Maior diversificação; pode diluir o retorno nos bull markets.",
        {"Macro Leading": .25, "US Factor Rotation": .25, "GICS Long/Short": .12,
         "Country Momentum": .08, "Multi-Asset Trend": .10, "Technical Breakout": .10,
         "Credit Cycle": .10},
    ),
    "growth_regime": CandidateProfile(
        "Growth + Regime",
        "Concentrar os motores de retorno em growth/fatores, com filtros macro.",
        "Maior CAGR potencial e maior dependência de ações growth dos EUA.",
        {"Macro Leading": .35, "US Factor Rotation": .35, "GICS Long/Short": .15,
         "Technical Breakout": .10, "Credit Cycle": .05},
    ),
    "sector_alpha": CandidateProfile(
        "Alpha Setorial",
        "Priorizar dispersão GICS e rotação de liderança nos EUA.",
        "Menor beta estrutural, mas maior risco de reversões rápidas entre setores.",
        {"Macro Leading": .15, "US Factor Rotation": .15, "GICS Long/Short": .40,
         "Country Momentum": .10, "Technical Breakout": .10, "Credit Cycle": .10},
    ),
    "global_rotation": CandidateProfile(
        "Rotação Global",
        "Explorar ciclos diferentes entre países e regiões.",
        "Diversifica os EUA, porém assume risco cambial e político indireto.",
        {"Macro Leading": .20, "US Factor Rotation": .15, "GICS Long/Short": .10,
         "Country Momentum": .35, "Multi-Asset Trend": .10, "Credit Cycle": .10},
    ),
    "trend_diversified": CandidateProfile(
        "Trend Multiativo",
        "Dar protagonismo a tendências long/short e breakouts.",
        "Tende a proteger crises persistentes, mas sofre em mercados laterais.",
        {"Macro Leading": .15, "US Factor Rotation": .10, "GICS Long/Short": .10,
         "Country Momentum": .05, "Multi-Asset Trend": .35, "Technical Breakout": .15,
         "Credit Cycle": .10},
    ),
    "defensive_ls": CandidateProfile(
        "Defensivo Long/Short",
        "Reduzir drawdown com trend, crédito e shorts setoriais complementares.",
        "Menor risco esperado, ao custo de carregar proteção durante altas fortes.",
        {"Macro Leading": .15, "US Factor Rotation": .10, "GICS Long/Short": .20,
         "Multi-Asset Trend": .25, "Technical Breakout": .10, "Credit Cycle": .20},
    ),
    "high_conviction": CandidateProfile(
        "Alta Convicção",
        "Maximizar exposição aos sleeves com maior expectativa de retorno histórico.",
        "Pouca diversificação de modelos e maior sensibilidade ao regime acionário.",
        {"Macro Leading": .45, "US Factor Rotation": .35, "GICS Long/Short": .10,
         "Technical Breakout": .10},
    ),
}


def get_candidate(key: str) -> CandidateProfile:
    if key not in CANDIDATES:
        raise ValueError(f"Candidato desconhecido: {key}")
    return CANDIDATES[key]
