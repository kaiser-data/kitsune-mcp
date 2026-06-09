class PaymentGateway:
    """A PaymentGateway processes charges against an account."""

    name = "PaymentGateway"

    def charge(self, amount):
        return {"gateway": self.name, "amount": amount, "status": "ok"}
