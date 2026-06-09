def binary_search(nums: list[int], target: int) -> int:
    """Return the index of target in sorted list nums, or -1 if not found."""
    lo, hi = 0, len(nums)
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
