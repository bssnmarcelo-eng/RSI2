from streamlit.testing.v1 import AppTest


def test_default_app_renders_without_exceptions():
    app = AppTest.from_file("app.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "RSI(2) · Laboratório de estratégias"
    area = next(radio for radio in app.radio if radio.label == "Área")
    assert area.options == [
        "Carteira (capital compartilhado)",
        "Por ativo (independente)",
        "Otimizador (grade por ativo)",
        "Screening de mercado",
        "Análise fundamentalista",
        "Histórico de backtests",
    ]
