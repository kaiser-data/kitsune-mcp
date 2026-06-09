from bank import PaymentGateway
from bank.registry import make_gateway
from bank.handlers import process_payment


def test_direct():
    gw = PaymentGateway()
    assert gw.charge(100) == {"gateway": "PaymentGateway", "amount": 100, "status": "ok"}


def test_registry():
    gw = make_gateway("PaymentGateway")
    assert isinstance(gw, PaymentGateway)
    assert gw.charge(50)["gateway"] == "PaymentGateway"


def test_handler():
    assert process_payment(25)["status"] == "ok"


if __name__ == "__main__":
    test_direct()
    test_registry()
    test_handler()
    print("all tests pass")
