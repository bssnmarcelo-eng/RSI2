"""Norgate fundamental-data layer (LSEG/Refinitiv via norgatedata).

Norgate provides *current* (point-in-time snapshot) fundamentals only — there is
no historical timeseries for these fields. Each value comes back paired with the
last date of the reporting period it applies to. Fundamentals are included with
Gold/Platinum/Diamond US stock subscriptions.

This module is import-safe without norgatedata installed: the package is only
imported lazily inside the fetch functions.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Each field: (token, label, unit). unit is one of:
#   "M" — millions of dollars (displayed scaled to M/B/T)
#   "%" — already expressed in percent (e.g. 46.9 -> "46.90%")
#   "N" — plain number / ratio / per-share dollars (2 decimals)
#   "I" — integer count (e.g. number of analyst estimates)
Field = Tuple[str, str, str]

# Ordered catalog: tab title -> (help text, [fields]). Field tokens and groupings
# are taken verbatim from Norgate's data-content reference.
CATALOG: "list[tuple[str, str, list[Field]]]" = [
    ("TTM (12 meses)",
     "Fundamentos dos últimos 12 meses (trailing twelve months).",
     [
        ("ttmrev",        "Receita (TTM)",                         "M"),
        ("ttmrevps",      "Receita por ação",                      "N"),
        ("ttmrevchg",     "Variação da receita (TTM vs TTM)",      "%"),
        ("ttmebitd",      "EBITD",                                 "M"),
        ("ttmebitdps",    "EBITD por ação",                        "N"),
        ("ttmebt",        "Lucro antes de impostos",               "M"),
        ("ttmniac",       "Lucro líquido (acionistas ord.)",       "M"),
        ("vdes_ttm",      "LPA normalizado (diluído)",             "N"),
        ("ttmepsxclx",    "LPA ex-extraordinários",                "N"),
        ("ttmepsincx",    "LPA inc-extraordinários",               "N"),
        ("ttmbepsxcl",    "LPA básico ex-extraordinários",         "N"),
        ("ttmepschg",     "Variação do LPA (TTM vs TTM)",          "%"),
        ("ttmcfshr",      "Fluxo de caixa por ação",               "N"),
        ("ttmfcf",        "Fluxo de caixa livre (FCF)",            "M"),
        ("ttmfcfshr",     "FCF por ação",                          "N"),
        ("focf2rev_ttm",  "FCF operacional / Receita",             "%"),
        ("ttmgrosmgn",    "Margem bruta",                          "%"),
        ("ttmopmgn",      "Margem operacional",                    "%"),
        ("ttmptmgn",      "Margem pré-impostos",                   "%"),
        ("ttmnpmgn",      "Margem líquida",                        "%"),
        ("ttmroapct",     "ROA (retorno s/ ativos médios)",        "%"),
        ("ttmroepct",     "ROE (retorno s/ patrimônio médio)",     "%"),
        ("ttmroipct",     "ROI (retorno s/ investimento)",         "%"),
        ("ttmastturn",    "Giro do ativo",                         "N"),
        ("ttminvturn",    "Giro de estoques",                      "N"),
        ("ttmrecturn",    "Giro de recebíveis",                    "N"),
        ("ttmintcov",     "Cobertura de juros",                    "N"),
        ("ttmpayrat",     "Payout (distribuição)",                 "%"),
        ("ttmdivshr",     "Dividendos ord. por ação",              "N"),
        ("ttmdivshradj",  "Dividendos ord. por ação (ajust.)",     "N"),
        ("ev2fcf_curttm", "EV / FCF (atual)",                      "N"),
        ("ttmrevpere",    "Receita por funcionário",               "N"),
        ("ttmniperem",    "Lucro líquido por funcionário",         "N"),
     ]),
    ("Preço & Valuation",
     "Múltiplos que referenciam o preço atual (atualizados diariamente).",
     [
        ("mktcap",          "Valor de mercado",                    "M"),
        ("beta",            "Beta (vs. índice de mercado)",        "N"),
        ("peexclxor",       "P/L ex-extraordinários (TTM)",        "N"),
        ("peinclxor",       "P/L inc-extraordinários (TTM)",       "N"),
        ("pebexclxor",      "P/L básico ex-extraord. (TTM)",       "N"),
        ("ttmpehigh",       "P/L máximo (TTM)",                    "N"),
        ("ttmpelow",        "P/L mínimo (TTM)",                    "N"),
        ("ttmpr2rev",       "Preço / Vendas (TTM)",                "N"),
        ("apr2rev",         "Preço / Vendas (ano fiscal)",         "N"),
        ("price2bk",        "Preço / Valor patrim. (trim.)",       "N"),
        ("aprice2bk",       "Preço / Valor patrim. (ano fiscal)",  "N"),
        ("pr2tanbk",        "Preço / Patrim. tangível (trim.)",    "N"),
        ("apr2tanbk",       "Preço / Patrim. tangível (ano)",      "N"),
        ("ttmprcfps",       "Preço / Fluxo de caixa (TTM)",        "N"),
        ("ttmprfcfps",      "Preço / FCF (TTM)",                   "N"),
        ("aprfcfps",        "Preço / FCF (ano fiscal)",            "N"),
        ("divyield_curttm", "Dividend yield atual (TTM)",          "%"),
     ]),
    ("Trimestre (MRQ)",
     "Período de reporte trimestral/interino mais recente.",
     [
        ("revchngyr",  "Variação receita (trim. vs 1 ano)",        "%"),
        ("epschngyr",  "Variação LPA (trim. vs 1 ano)",            "%"),
        ("qbvps",      "Valor patrimonial por ação",               "N"),
        ("qtanbvps",   "Valor patrim. tangível por ação",          "N"),
        ("qcshps",     "Caixa por ação",                           "N"),
        ("qcurratio",  "Liquidez corrente",                        "N"),
        ("qquickrati", "Liquidez seca",                            "N"),
        ("qltd2eq",    "Dívida LP / patrimônio",                   "%"),
        ("qtotd2eq",   "Dívida total / patrimônio",                "%"),
        ("netdebt_i",  "Dívida líquida",                           "M"),
     ]),
    ("Ano Fiscal",
     "Último ano fiscal completo reportado (inclui médias de 5 anos).",
     [
        ("arev",        "Receita",                                 "M"),
        ("arevps",      "Receita por ação",                        "N"),
        ("aebitd",      "EBITDA",                                  "M"),
        ("aebt",        "Lucro antes de impostos",                 "M"),
        ("aebtnorm",    "Lucro antes de impostos (normalizado)",   "M"),
        ("aniac",       "Lucro líquido (acionistas ord.)",         "M"),
        ("aniacnorm",   "Lucro líquido ord. (normalizado)",        "M"),
        ("aepsxclxor",  "LPA ex-extraordinários",                  "N"),
        ("aepsinclxo",  "LPA inc-extraordinários",                 "N"),
        ("abepsxclxo",  "LPA básico ex-extraordinários",           "N"),
        ("aepsnorm",    "LPA normalizado",                         "N"),
        ("acfshr",      "Fluxo de caixa por ação",                 "N"),
        ("a1fcf",       "Fluxo de caixa livre",                    "M"),
        ("abvps",       "Valor patrimonial por ação",              "N"),
        ("atanbvps",    "Valor patrim. tangível por ação",         "N"),
        ("acshps",      "Caixa por ação",                          "N"),
        ("acurratio",   "Liquidez corrente",                       "N"),
        ("aquickrati",  "Liquidez seca",                           "N"),
        ("altd2eq",     "Dívida LP / patrimônio",                  "%"),
        ("atotd2eq",    "Dívida total / patrimônio",               "%"),
        ("netdebt_a",   "Dívida líquida",                          "M"),
        ("agrosmgn",    "Margem bruta",                            "%"),
        ("aopmgnpct",   "Margem operacional",                      "%"),
        ("aptmgnpct",   "Margem pré-impostos",                     "%"),
        ("anpmgnpct",   "Margem líquida",                          "%"),
        ("aroapct",     "ROA",                                     "%"),
        ("aroepct",     "ROE",                                     "%"),
        ("aroipct",     "ROI",                                     "%"),
        ("aastturn",    "Giro do ativo",                           "N"),
        ("ainvturn",    "Giro de estoques",                        "N"),
        ("arecturn",    "Giro de recebíveis",                      "N"),
        ("aintcov",     "Cobertura de juros",                      "N"),
        ("apayratio",   "Payout",                                  "%"),
        ("adivshr",     "Dividendos ord. por ação",                "N"),
        ("ev2fcf_cura", "EV / FCF",                                "N"),
        ("arevperemp",  "Receita por funcionário",                 "N"),
        ("aniperemp",   "Lucro líquido por funcionário",           "N"),
        ("grosmgn5yr",  "Margem bruta (média 5 anos)",             "%"),
        ("opmgn5yr",    "Margem operacional (média 5 anos)",       "%"),
        ("ptmgn5yr",    "Margem pré-impostos (média 5 anos)",      "%"),
        ("margin5yr",   "Margem líquida (média 5 anos)",           "%"),
        ("aroa5yavg",   "ROA (média 5 anos)",                      "%"),
        ("aroe5yavg",   "ROE (média 5 anos)",                      "%"),
        ("focf2rev_aavg5", "FCF op./Receita (média 5 anos)",       "%"),
        ("adiv5yavg",   "Dividendo por ação (média 5 anos)",       "%"),
        ("yld5yavg",    "Dividend yield (média 5 anos)",           "%"),
     ]),
    ("Crescimento (CAGR)",
     "Taxas de crescimento anual composto (3 e 5 anos).",
     [
        ("revgrpct",          "Receita — CAGR 3 anos",             "%"),
        ("revtrendgr",        "Receita — CAGR 5 anos",             "%"),
        ("revps5ygr",         "Receita por ação — CAGR 5 anos",    "%"),
        ("epsgrpct",          "LPA — CAGR 3 anos",                 "%"),
        ("epstrendgr",        "LPA — CAGR 5 anos",                 "%"),
        ("ebitda_ayr5cagr",   "EBITDA — CAGR 5 anos",              "%"),
        ("ebitda_ttmy5cagr",  "EBITDA — CAGR 5 anos (TTM)",        "%"),
        ("focf_ayr5cagr",     "FCF operacional — CAGR 5 anos",     "%"),
        ("bvtrendgr",         "Valor patrim./ação — CAGR 5 anos",  "%"),
        ("tanbv_ayr5cagr",    "Patrim. tangível — CAGR 5 anos",    "%"),
        ("npmtrendgr",        "Margem líquida — CAGR 5 anos",      "%"),
        ("csptrendgr",        "Investimentos (capex) — CAGR 5 a.", "%"),
        ("stld_ayr5cagr",     "Dívida total — CAGR 5 anos",        "%"),
        ("divgrpct",          "Dividendos — CAGR 3 anos",          "%"),
     ]),
    ("Consenso de Analistas",
     "Projeções e estimativas de consenso de corretoras (LSEG/Refinitiv).",
     [
        ("targetprice",       "Preço-alvo (consenso 12 meses)",    "N"),
        ("projltgrowthrate",  "Crescimento LP do LPA (5 anos)",    "%"),
        ("projeps",           "LPA anual — consenso",              "N"),
        ("projepsh",          "LPA anual — estimativa alta",       "N"),
        ("projepsl",          "LPA anual — estimativa baixa",      "N"),
        ("projepsnumofest",   "LPA anual — nº de estimativas",     "I"),
        ("projepsq",          "LPA trimestral — consenso",         "N"),
        ("projepsqh",         "LPA trim. — estimativa alta",       "N"),
        ("projepsql",         "LPA trim. — estimativa baixa",      "N"),
        ("projepsqnumofest",  "LPA trim. — nº de estimativas",     "I"),
        ("projsales",         "Receita anual — consenso",          "M"),
        ("projsalesh",        "Receita anual — estimativa alta",   "M"),
        ("projsalesl",        "Receita anual — estimativa baixa",  "M"),
        ("projsalesnumofest", "Receita anual — nº de estimativas", "I"),
        ("projsalesq",        "Receita trim. — consenso",          "M"),
        ("projsalesqh",       "Receita trim. — estimativa alta",   "M"),
        ("projsalesql",       "Receita trim. — estimativa baixa",  "M"),
        ("projsalesqnumofest","Receita trim. — nº de estimativas", "I"),
        ("projprofit",        "Lucro líquido — consenso",          "M"),
        ("projprofith",       "Lucro líquido — estimativa alta",   "M"),
        ("projprofitl",       "Lucro líquido — estimativa baixa",  "M"),
        ("projprofitnumofest","Lucro líquido — nº de estimativas", "I"),
        ("projdps",           "Dividendo/ação anual — consenso",   "N"),
        ("projdpsh",          "Dividendo/ação — estimativa alta",  "N"),
        ("projdpsl",          "Dividendo/ação — estimativa baixa", "N"),
        ("projdpsnumofest",   "Dividendo/ação — nº de estimativas","I"),
        ("epsactual",         "LPA anual realizado (anterior)",    "N"),
        ("epsactualq",        "LPA trim. realizado (anterior)",    "N"),
        ("epssurprise",       "Surpresa anual de LPA",             "N"),
        ("epssurpriseprc",    "Surpresa anual de LPA (%)",         "%"),
        ("epssurpriseq",      "Surpresa trim. de LPA",             "N"),
        ("epssurpriseqprc",   "Surpresa trim. de LPA (%)",         "%"),
     ]),
]

# Flat list of every (token, unit) for bulk fetching.
ALL_FIELDS: List[Field] = [f for _, _, fields in CATALOG for f in fields]


# ── lazy norgatedata import ────────────────────────────────────────────────────

def _nd():
    import norgatedata  # noqa: PLC0415
    return norgatedata


def is_available() -> bool:
    try:
        return bool(_nd().status())
    except Exception:
        return False


# ── value formatting ────────────────────────────────────────────────────────────

def format_value(value, unit: str) -> str:
    """Format a fundamental value for display according to its unit."""
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v:  # NaN
        return "—"
    if unit == "M":          # value is in millions of dollars
        a = abs(v)
        if a >= 1_000_000:
            return f"$ {v / 1_000_000:,.2f} T"
        if a >= 1_000:
            return f"$ {v / 1_000:,.2f} B"
        return f"$ {v:,.2f} M"
    if unit == "%":
        return f"{v:,.2f}%"
    if unit == "I":
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"       # "N"


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_one(symbol: str, field: str) -> Tuple[Optional[float], Optional[str]]:
    """Single fundamental field -> (value, as-of date) or (None, None)."""
    try:
        return _nd().fundamental(symbol, field, datetimeformat="iso")
    except Exception:
        return None, None


def fetch_all(symbol: str) -> Dict[str, Tuple[Optional[float], Optional[str]]]:
    """Fetch every catalog field for *symbol*: token -> (value, date).

    Uses a small thread pool — the norgatedata package is documented as
    thread-safe and each call is an independent local NDU lookup, so this cuts
    the ~130-field wall-clock time substantially.
    """
    from concurrent.futures import ThreadPoolExecutor

    tokens = [tok for tok, _, _ in ALL_FIELDS]

    def _get(tok):
        return tok, fetch_one(symbol, tok)

    out: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tok, res in ex.map(_get, tokens):
            out[tok] = res
    return out


def overview(symbol: str) -> dict:
    """Headline metadata + text summaries for the overview tab."""
    nd = _nd()

    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    def _gics(level):
        try:
            return nd.classification_at_level(symbol, "GICS", "Name", level)
        except Exception:
            return None

    return {
        "name":        _safe(nd.security_name, symbol),
        "exchange":    _safe(nd.exchange_name_full, symbol),
        "currency":    _safe(nd.currency, symbol),
        "domicile":    _safe(nd.domicile, symbol),
        "subtype1":    _safe(nd.subtype1, symbol),
        "subtype2":    _safe(nd.subtype2, symbol),
        "gics_sector":       _gics(1),
        "gics_industry_grp": _gics(2),
        "gics_industry":     _gics(3),
        "gics_sub_industry": _gics(4),
        "business_summary":  _safe(nd.business_summary, symbol),
        "financial_summary": _safe(nd.financial_summary, symbol),
        "last_quoted":       _safe(lambda s: nd.last_quoted_date(s, datetimeformat="iso"), symbol),
    }
