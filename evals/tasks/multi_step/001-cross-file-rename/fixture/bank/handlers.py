from .core import PaymentGateway


def process_payment(amount):
    gateway = PaymentGateway()
    return gateway.charge(amount)
