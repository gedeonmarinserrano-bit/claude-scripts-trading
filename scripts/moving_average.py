def simple_moving_average(prices, window):
    if window <= 0:
        raise ValueError("window must be positive")
    if len(prices) < window:
        return []
    return [
        sum(prices[i:i + window]) / window
        for i in range(len(prices) - window + 1)
    ]
