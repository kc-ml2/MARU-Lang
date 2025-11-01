from typing import List, Tuple, Dict

def allocate_by_weight(
    groups_with_weights: List[Tuple[str, float]],
    max_results: int,
    ensure_min_one: bool = True,
    include_zero_weight_groups: bool = True,
) -> Dict[str, int]:
    if max_results <= 0 or not groups_with_weights:
        return {}

    # 안전 가중치(음수 -> 0)
    safe = [(g, (w if (isinstance(w, (int, float)) and w > 0) else 0.0))
            for g, w in groups_with_weights]

    all_groups = [g for g, _ in safe]
    allocations: Dict[str, int] = {g: 0 for g in all_groups}

    # w>0만 배분 대상
    pos = [(g, w) for g, w in safe if w > 0.0]
    if not pos:
        # 전부 0이면 모두 0으로 반환
        return allocations if include_zero_weight_groups else {}

    remaining = max_results

    # Step 1) 최소 1개 보장
    if ensure_min_one:
        if len(pos) <= max_results:
            for g, _ in pos:
                allocations[g] = 1
            remaining -= len(pos)
        else:
            # 양수 그룹이 max_results보다 많으면 상위 weight만 1개씩
            top = sorted(pos, key=lambda x: x[1], reverse=True)[:max_results]
            for g, _ in top:
                allocations[g] = 1
            remaining = 0

    if remaining == 0:
        return allocations if include_zero_weight_groups else {g: allocations[g] for g, _ in pos}

    # Step 2) Largest Remainder for the rest
    total_weight = sum(w for _, w in pos)
    if total_weight <= 0:
        # 방어적: weight합 0이면 남은 좌석을 상위 weight 순으로 1씩
        for g, _ in sorted(pos, key=lambda x: x[1], reverse=True):
            if remaining <= 0:
                break
            allocations[g] += 1
            remaining -= 1
        return allocations if include_zero_weight_groups else {g: allocations[g] for g, _ in pos}

    quotas = []
    for g, w in pos:
        q = remaining * (w / total_weight)
        base = int(q)
        frac = q - base
        quotas.append((g, w, base, frac))

    used = sum(base for _, _, base, _ in quotas)
    for g, _, base, _ in quotas:
        allocations[g] += base

    left = remaining - used
    if left > 0:
        # 타이브레이크: frac DESC, weight DESC, name ASC
        quotas_sorted = sorted(
            quotas,
            key=lambda t: (-t[3], -t[1], t[0])
        )
        for i in range(left):
            g = quotas_sorted[i][0]
            allocations[g] += 1

    return allocations if include_zero_weight_groups else {g: allocations[g] for g, _ in pos}