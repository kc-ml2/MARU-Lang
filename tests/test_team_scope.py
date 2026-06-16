"""scope_team_ids — per-message team scoping for chat search (pure, no DB)."""
from maru_lang.services.team import scope_team_ids

TEAMS = [
    {"id": 1, "name": "alpha", "role": "member"},
    {"id": 2, "name": "beta", "role": "admin"},
    {"id": 3, "name": "gamma", "role": "member"},
]


def test_empty_request_falls_back_to_all_teams():
    assert scope_team_ids(None, TEAMS) == ([1, 2, 3], ["alpha", "beta", "gamma"])
    assert scope_team_ids([], TEAMS) == ([1, 2, 3], ["alpha", "beta", "gamma"])


def test_subset_request_is_honored():
    assert scope_team_ids([2], TEAMS) == ([2], ["beta"])


def test_order_follows_user_teams_not_request():
    assert scope_team_ids([3, 1], TEAMS) == ([1, 3], ["alpha", "gamma"])


def test_inaccessible_ids_are_dropped():
    # 99 is not the user's team -> only the accessible ones survive.
    assert scope_team_ids([1, 99], TEAMS) == ([1], ["alpha"])


def test_only_inaccessible_ids_returns_none():
    assert scope_team_ids([99], TEAMS) is None


def test_single_int_is_coerced():
    assert scope_team_ids(2, TEAMS) == ([2], ["beta"])
