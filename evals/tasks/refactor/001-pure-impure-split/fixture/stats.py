def compute_and_report(path):
    with open(path) as f:
        nums = [int(x) for x in f.read().split()]
    total = sum(nums)
    count = len(nums)
    mean = total / count if count else 0.0
    biggest = max(nums) if nums else None
    print(f"total={total} mean={mean} max={biggest} count={count}")
    return {"total": total, "mean": mean, "max": biggest, "count": count}
