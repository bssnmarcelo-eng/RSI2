from __future__ import annotations

from dataclasses import dataclass, field

UNIVERSE_GROUPS: dict[str, tuple[str, ...]] = {
    "Ações EUA — núcleo, tamanho e fatores": (
        "SPY", "QQQ", "IWM", "MDY", "RSP", "VTV", "VUG", "QUAL", "MTUM", "USMV",
    ),
    "Ações EUA — 11 setores GICS": (
        "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    ),
    "Ações globais e regiões": (
        "ACWI", "VT", "EFA", "VGK", "VPL", "EEM",
    ),
    "Países desenvolvidos": (
        "EWJ", "EWU", "EWG", "EWC", "EWA", "EWS", "EWH", "EWL", "EWP", "EWI",
    ),
    "Países emergentes": (
        "FXI", "INDA", "EWZ", "EWW", "EWT", "EWY", "EZA", "TUR", "KSA",
    ),
    "Renda fixa EUA e internacional": (
        "BIL", "SHY", "IEI", "IEF", "TLT", "TIP", "STIP", "AGG", "MBB", "LQD",
        "HYG", "EMB", "BNDX", "BWX", "FLOT", "SRLN",
    ),
    "Imóveis, infraestrutura e commodities": (
        "VNQ", "VNQI", "IGF", "GLD", "SLV", "GDX", "DBC", "PDBC", "USO", "UNG", "DBA",
    ),
    "Moedas": ("UUP", "FXE", "FXY"),
}

DEFAULT_UNIVERSE = tuple(
    symbol for symbols in UNIVERSE_GROUPS.values() for symbol in symbols
)


@dataclass(frozen=True)
class CostConfig:
    pricing: str = "tiered"
    commission_per_share: float = 0.0035
    minimum_per_order: float = 0.35
    maximum_fraction: float = 0.01
    third_party_bps: float = 0.10
    slippage_bps: float = 2.0
    short_borrow_rate: float = 0.03


@dataclass(frozen=True)
class RiskConfig:
    max_gross: float = 1.0
    max_net: float = 1.0
    max_symbol_weight: float = 0.35
    target_volatility: float = 0.30
    volatility_lookback: int = 63
    rebalance_weekday: int = 0


@dataclass(frozen=True)
class LabConfig:
    symbols: tuple[str, ...] = DEFAULT_UNIVERSE
    benchmark: str = "SPY"
    start_date: str = "2005-01-01"
    end_date: str | None = None
    initial_capital: float = 100_000.0
    candidate: str = "balanced"
    costs: CostConfig = field(default_factory=CostConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
