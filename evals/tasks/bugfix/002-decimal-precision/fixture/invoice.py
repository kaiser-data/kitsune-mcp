def line_total(unit_price: float, quantity: int, tax_rate: float) -> float:
    subtotal = unit_price * quantity
    total = subtotal * (1 + tax_rate)
    return round(total, 2)
