from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 71
    account: str = ""
    paper_only: bool = True


class IBKRBroker:
    def __init__(self, config: IBKRConfig):
        self.config = config
        self._ib = None

    def connect(self) -> None:
        try:
            from ib_async import IB
        except ImportError as exc:
            raise RuntimeError("Instale a integração com: pip install -e .[ibkr]") from exc
        if self.config.paper_only and self.config.port not in {7497, 4002}:
            raise RuntimeError("Modo paper aceita apenas as portas TWS 7497 ou Gateway 4002")
        self._ib = IB()
        self._ib.connect(self.config.host, self.config.port, clientId=self.config.client_id, readonly=False)

    def account_snapshot(self) -> tuple[float, dict[str, float]]:
        self._require_connection()
        summaries = self._ib.accountSummary(self.config.account or "")
        net_liquidation = next(
            float(item.value) for item in summaries if item.tag == "NetLiquidation" and item.currency == "USD"
        )
        positions = {
            position.contract.symbol: float(position.position)
            for position in self._ib.positions(self.config.account or "")
            if position.contract.secType == "STK" and position.contract.currency == "USD"
        }
        return net_liquidation, positions

    def submit_market_orders(self, orders: pd.DataFrame, transmit: bool = False) -> list[int]:
        self._require_connection()
        from ib_async import MarketOrder, Stock

        if transmit and self.config.paper_only is False:
            raise RuntimeError("Envio live não é habilitado nesta versão; use paper ou exporte as ordens")
        identifiers: list[int] = []
        for row in orders.to_dict("records"):
            contract = Stock(row["symbol"], "SMART", "USD")
            self._ib.qualifyContracts(contract)
            trade = self._ib.placeOrder(
                contract,
                MarketOrder(row["action"], row["quantity"], transmit=transmit),
            )
            identifiers.append(int(trade.order.orderId))
        return identifiers

    def disconnect(self) -> None:
        if self._ib is not None:
            self._ib.disconnect()

    def _require_connection(self) -> None:
        if self._ib is None or not self._ib.isConnected():
            raise RuntimeError("IBKR não conectada")
