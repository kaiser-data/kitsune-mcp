from .core import PaymentGateway

GATEWAYS = {
    "PaymentGateway": PaymentGateway,
}


def make_gateway(name):
    return GATEWAYS[name]()
