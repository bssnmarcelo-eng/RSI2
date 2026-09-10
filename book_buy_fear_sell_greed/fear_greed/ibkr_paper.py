"""Preparação segura de ordens não transmitidas no TWS/IB Gateway."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import threading
import time
from typing import Any, Iterable


@dataclass(slots=True)
class PaperOrderSpec:
    ticker: str
    action: str
    quantity: int
    order_type: str
    tif: str = "DAY"
    stop_price: float | None = None
    limit_price: float | None = None
    transmit: bool = False
    order_ref: str = "fear-greed-paper"


def build_order_specs(rows: Iterable[dict[str, Any]], allocation_usd: float) -> list[PaperOrderSpec]:
    """Converte candidatos do scanner em ordens; ignora condições sem preço conhecido."""
    specs: list[PaperOrderSpec] = []
    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        order_type = str(row.get("tipo_ordem", ""))
        reference = row.get("preco_limite") or row.get("fechamento")
        try:
            reference = float(reference)
        except (TypeError, ValueError):
            continue
        if not ticker or not math.isfinite(reference) or reference <= 0 or order_type.startswith("COND"):
            continue
        tranche_weight = float(row.get("parcela_inicial", 1.0) or 1.0)
        quantity = int((allocation_usd * tranche_weight) // reference)
        if quantity < 1:
            continue
        action = "BUY" if str(row.get("direcao")) == "long" else "SELL"
        if order_type == "MKT":
            ib_type = "MKT"
        elif "STP LMT" in order_type:
            ib_type = "STP LMT"
        elif "LMT" in order_type:
            ib_type = "LMT"
        else:
            continue
        stop = row.get("preco_stop")
        limit = row.get("preco_limite")
        specs.append(PaperOrderSpec(
            ticker=ticker,
            action=action,
            quantity=quantity,
            order_type=ib_type,
            stop_price=float(stop) if stop is not None and not _is_nan(stop) else None,
            limit_price=float(limit) if limit is not None and not _is_nan(limit) else None,
        ))
    return specs


def _is_nan(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def stage_untransmitted_orders(
    specs: Iterable[PaperOrderSpec],
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 71,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Coloca ordens no TWS com ``transmit=False``; nunca as envia ao mercado."""
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.order import Order
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise RuntimeError("Instale a integração opcional: python -m pip install -r requirements-ibkr.txt") from exc

    class Client(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.next_id: int | None = None
            self.errors: list[str] = []

        def nextValidId(self, orderId):  # noqa: N802 - nome definido pela API
            self.next_id = int(orderId)
            self.ready.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
            if int(errorCode) not in {2104, 2106, 2158}:
                self.errors.append(f"{errorCode}: {errorString}")

    client = Client()
    client.connect(host, int(port), int(client_id))
    thread = threading.Thread(target=client.run, daemon=True, name="ibkr-paper-api")
    thread.start()
    if not client.ready.wait(timeout):
        client.disconnect()
        raise TimeoutError("TWS/IB Gateway não forneceu nextValidId. Confira API, porta paper e Client ID.")

    staged: list[dict[str, Any]] = []
    try:
        for spec in specs:
            contract = Contract()
            contract.symbol = spec.ticker
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"

            order = Order()
            order.action = spec.action
            order.totalQuantity = spec.quantity
            order.orderType = spec.order_type
            order.tif = spec.tif
            order.transmit = False  # barreira de segurança deliberadamente não configurável
            order.orderRef = spec.order_ref
            if spec.order_type in {"LMT", "STP LMT"}:
                if spec.limit_price is None:
                    raise ValueError(f"{spec.ticker}: preço limite ausente.")
                order.lmtPrice = spec.limit_price
            if spec.order_type == "STP LMT":
                if spec.stop_price is None:
                    raise ValueError(f"{spec.ticker}: preço stop ausente.")
                order.auxPrice = spec.stop_price

            order_id = int(client.next_id)
            client.next_id += 1
            client.placeOrder(order_id, contract, order)
            staged.append({**asdict(spec), "ibkr_order_id": order_id, "host": host, "port": int(port), "client_id": int(client_id), "transmit": False})
        time.sleep(0.5)
        if client.errors:
            raise RuntimeError("; ".join(client.errors))
        return staged
    finally:
        client.disconnect()


def fetch_paper_executions(
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 71,
    timeout: float = 8.0,
    order_ref: str = "fear-greed-paper",
) -> list[dict[str, Any]]:
    """Consulta fills visíveis ao TWS e retorna apenas os originados pelo app."""
    try:
        from ibapi.client import EClient
        from ibapi.execution import ExecutionFilter
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise RuntimeError("Instale a integração opcional: python -m pip install -r requirements-ibkr.txt") from exc

    class Client(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.connected = threading.Event()
            self.done = threading.Event()
            self.executions: dict[str, dict[str, Any]] = {}
            self.commissions: dict[str, dict[str, Any]] = {}
            self.errors: list[str] = []

        def nextValidId(self, orderId):  # noqa: N802
            self.connected.set()

        def execDetails(self, reqId, contract, execution):  # noqa: N802
            if str(getattr(execution, "orderRef", "")) != order_ref:
                return
            exec_id = str(execution.execId)
            self.executions[exec_id] = {
                "execution_id": exec_id,
                "ibkr_order_id": int(execution.orderId),
                "ticker": str(contract.symbol),
                "side": str(execution.side),
                "quantity": float(execution.shares),
                "price": float(execution.price),
                "execution_time": str(execution.time),
                "exchange": str(execution.exchange),
                "account": str(execution.acctNumber),
                "order_ref": str(execution.orderRef),
            }

        def commissionReport(self, report):  # noqa: N802
            self.commissions[str(report.execId)] = {
                "commission": float(report.commission),
                "commission_currency": str(report.currency),
                "realized_pnl": float(report.realizedPNL),
            }

        def execDetailsEnd(self, reqId):  # noqa: N802
            self.done.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
            if int(errorCode) not in {2104, 2106, 2158}:
                self.errors.append(f"{errorCode}: {errorString}")

    client = Client()
    client.connect(host, int(port), int(client_id))
    thread = threading.Thread(target=client.run, daemon=True, name="ibkr-paper-executions")
    thread.start()
    if not client.connected.wait(timeout):
        client.disconnect()
        raise TimeoutError("TWS/IB Gateway não respondeu. Confira API, porta paper e Client ID.")
    try:
        client.reqExecutions(91_001, ExecutionFilter())
        if not client.done.wait(timeout):
            raise TimeoutError("A consulta de execuções da IBKR não terminou no prazo.")
        time.sleep(0.3)
        if client.errors:
            raise RuntimeError("; ".join(client.errors))
        return [{**execution, **client.commissions.get(exec_id, {})} for exec_id, execution in sorted(client.executions.items())]
    finally:
        client.disconnect()
