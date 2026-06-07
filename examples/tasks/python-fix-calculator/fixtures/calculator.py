def add(a, b):
    return a + b


def multiply(a, b):
    total = 0
    for _ in range(a):
        total += b
    return total


def average(values):
    if not values:
        return 0
    return sum(values) // len(values)
