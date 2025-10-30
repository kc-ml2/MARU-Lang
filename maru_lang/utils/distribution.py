from typing import List, Tuple, Dict

def normalized_groups_weights(
    groups: List[str],
    group_weights: Dict[str, float]) -> List[Tuple[str, float]]:
    """
    Normalize groups and weights to sum to 1.

    Args:
        groups: List of group names to include
        group_weights: Dictionary of group weights {group_name: weight}

    Returns:
        List of (group_name, normalized_weight) tuples
    """
    # groups에 있는 그룹들의 weight만 추출
    active_groups = [(g, group_weights.get(g, 0.0)) for g in groups]
    active_groups = [(g, w) for g, w in active_groups if w > 0]

    if not active_groups:
        print("⚠️  No active group weights found, assigning uniform weights")
        uniform_weight = 1.0 / len(groups) if groups else 0.0
        active_groups = [(g, uniform_weight) for g in groups]

    # 가중치 합 계산 및 정규화
    weight_sum = sum(w for _, w in active_groups)
    if weight_sum <= 0:
        print("⚠️  Weight sum is zero or negative, assigning uniform weights")
        uniform_weight = 1.0 / len(groups) if groups else 0.0
        normalized_group_weights = [(g, uniform_weight) for g in groups]
    else:
        normalized_group_weights = [(g, w / weight_sum) for g, w in active_groups]

    return normalized_group_weights


def allocate_by_weight(
    groups_with_weights: List[Tuple[str, float]],
    max_results: int,
    ensure_min_one: bool = True
) -> Dict[str, int]:
    """
    Allocate integer counts to groups based on normalized weights using the
    Largest Remainder Method (Hamilton Apportionment).

    Args:
        normalized_groups: List of (group_name, normalized_weight) pairs.
                           Weights should sum to approximately 1.
        max_results: Total number of results to allocate.
        ensure_min_one: If True, guarantees at least 1 allocation for each
                        group with positive weight when possible.

    Returns:
        A list of (group_name, allocated_count) tuples whose total equals `max_results`.
    """

    if max_results <= 0 or not groups_with_weights:
        return {}

    pos = [(g, w) for g, w in groups_with_weights if w > 0]
    if not pos:
        return {}

    allocations: dict[str, int] = {g: 0 for g, _ in pos}
    remaining = max_results

    # Step 1: Minimum allocation (if possible)
    if ensure_min_one:
        if len(pos) <= max_results:
            for g, _ in pos:
                allocations[g] = 1
            remaining -= len(pos)
        else:
            top = sorted(pos, key=lambda x: x[1], reverse=True)[:max_results]
            for g, _ in top:
                allocations[g] = 1
            remaining = 0
    if remaining == 0:
        return {g: allocations[g] for g, _ in pos}

    # Step 2: Largest Remainder Method
    total_weight = sum(w for _, w in pos)
    if total_weight <= 0:
        for g, _ in sorted(pos, key=lambda x: x[1], reverse=True):
            if remaining <= 0:
                break
            allocations[g] += 1
            remaining -= 1
        return {g: allocations[g] for g, _ in pos}

    quotas: List[Tuple[str, int, float]] = []
    for g, w in pos:
        q = remaining * (w / total_weight)
        base = int(q)
        frac = q - base
        quotas.append((g, base, frac))

    used = sum(base for _, base, _ in quotas)
    for g, base, _ in quotas:
        allocations[g] += base
    remaining2 = remaining - used

    if remaining2 > 0:
        quotas_sorted = sorted(quotas, key=lambda x: x[2], reverse=True)
        for i in range(remaining2):
            g = quotas_sorted[i][0]
            allocations[g] += 1

    return {g: allocations[g] for g, _ in pos}
