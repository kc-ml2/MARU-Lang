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
    # groups에 있는 그룹들의 weight만 추출 (0 포함)
    all_groups = [(g, group_weights.get(g, 0.0)) for g in groups]

    # weight > 0인 그룹만 정규화 대상
    positive_groups = [(g, w) for g, w in all_groups if w > 0]

    if not positive_groups:
        # 모든 그룹이 weight=0이면 균등 분배
        print("⚠️  No active group weights found, assigning uniform weights")
        uniform_weight = 1.0 / len(groups) if groups else 0.0
        return [(g, uniform_weight) for g in groups]

    # 가중치 합 계산 및 정규화
    weight_sum = sum(w for _, w in positive_groups)
    if weight_sum <= 0:
        print("⚠️  Weight sum is zero or negative, assigning uniform weights")
        uniform_weight = 1.0 / len(groups) if groups else 0.0
        return [(g, uniform_weight) for g in groups]

    # 정규화: positive 그룹만 정규화, zero 그룹은 0 유지
    normalized_weights = {}
    for g, w in positive_groups:
        normalized_weights[g] = w / weight_sum

    # 모든 그룹 포함 (zero 포함)
    normalized_group_weights = [(g, normalized_weights.get(g, 0.0)) for g in groups]

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
        A dict of {group_name: allocated_count} including zero-weight groups with count=0.
    """

    if max_results <= 0 or not groups_with_weights:
        return {}

    # 모든 그룹을 포함 (weight=0인 그룹도 포함, allocation=0으로)
    allocations: dict[str, int] = {g: 0 for g, _ in groups_with_weights}

    # weight > 0인 그룹만 할당 대상
    pos = [(g, w) for g, w in groups_with_weights if w > 0]
    if not pos:
        # 모든 그룹이 weight=0이면 전부 0 반환
        return allocations

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
