from fear_greed.ibkr_paper import build_order_specs


def test_builds_non_transmitted_ibkr_specs():
    rows = [{"ticker": "SPY", "direcao": "long", "tipo_ordem": "BUY STP LMT", "preco_stop": 100, "preco_limite": 100.03, "fechamento": 99}]
    specs = build_order_specs(rows, allocation_usd=10_000)
    assert len(specs) == 1
    assert specs[0].order_type == "STP LMT"
    assert specs[0].quantity == 99
    assert specs[0].transmit is False


def test_does_not_stage_open_dependent_terror_gap_order():
    rows = [{"ticker": "SPY", "direcao": "long", "tipo_ordem": "COND BUY LMT", "preco_limite": None, "fechamento": 100}]
    assert build_order_specs(rows, allocation_usd=10_000) == []


def test_first_order_uses_only_initial_scale_tranche():
    rows = [{"ticker": "SPY", "direcao": "long", "tipo_ordem": "MKT", "preco_limite": None, "fechamento": 100, "parcela_inicial": 0.1}]
    specs = build_order_specs(rows, allocation_usd=10_000)
    assert specs[0].quantity == 10
