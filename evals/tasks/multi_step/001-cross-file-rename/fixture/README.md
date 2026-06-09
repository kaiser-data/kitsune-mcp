# bank

A tiny payments package.

## Usage

```python
from bank import PaymentGateway

gw = PaymentGateway()
gw.charge(100)
```

Or via the registry:

```python
from bank.registry import make_gateway

gw = make_gateway("PaymentGateway")
```

The `PaymentGateway` class is the single entry point for charging an account.
