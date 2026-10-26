import datetime
import time

import pytest

from CTFd.models import (
    Challenges,
    Fails,
    HintUnlocks,
    Solves,
    Submissions,
    Teams,
    Users,
)
from CTFd.plugins.challenges import CTFdStandardChallenge
from CTFd.plugins.dynamic_challenges import DynamicValueChallenge
from CTFd.utils import get_config, set_config
from CTFd.utils.config import is_teams_mode
from tests.helpers import (
    FakeRequest,
    create_ctfd,
    destroy_ctfd,
    gen_award,
    gen_challenge,
    gen_fail,
    gen_flag,
    gen_hint,
    gen_module,
    gen_solution,
    gen_solve,
    gen_team,
    gen_unlock,
    gen_user,
    login_as_user,
)


@pytest.fixture
def app(request):
    app = create_ctfd(user_mode=getattr(request, "param", "users"), enable_plugins=True)
    try:
        with app.app_context():
            set_config("allow_solve_retraction", True)
            yield app
    finally:
        destroy_ctfd(app)


def test_retraction_defaults_to_disabled():
    instance = create_ctfd(enable_plugins=True)
    try:
        with instance.app_context():
            assert not get_config("allow_solve_retraction")
            admin = login_as_user(instance, name="admin")
            assert b'name="allow_solve_retraction"' in admin.get("/admin/config").data
            configs = admin.get("/api/v1/configs").get_json()["data"]
            assert any(item["key"] == "allow_solve_retraction" for item in configs)
    finally:
        destroy_ctfd(instance)


@pytest.mark.parametrize("app", ["users", "teams"], indirect=True)
def test_retraction_can_be_disabled_and_reenabled(app):
    team = gen_team(app.db, member_count=0) if is_teams_mode() else None
    user = gen_user(app.db, team_id=team.id if team else None)
    challenge = gen_challenge(app.db)
    gen_solve(app.db, user_id=user.id, team_id=user.team_id, challenge_id=challenge.id)
    client = login_as_user(app, name=user.name)
    assert (
        "retractSolve()"
        in client.get("/api/v1/challenges/1").get_json()["data"]["view"]
    )
    admin = login_as_user(app, name="admin")
    response = admin.patch("/api/v1/configs", json={"allow_solve_retraction": False})
    assert response.status_code == 200
    assert (
        "retractSolve()"
        not in client.get("/api/v1/challenges/1").get_json()["data"]["view"]
    )
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 403
    assert Solves.query.count() == 1
    assert (
        client.patch(
            "/api/v1/configs", json={"allow_solve_retraction": True}
        ).status_code
        == 403
    )
    assert (
        admin.patch(
            "/api/v1/configs", json={"allow_solve_retraction": True}
        ).status_code
        == 200
    )
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 200
    assert Solves.query.count() == 0


@pytest.mark.parametrize("app", ["users", "teams"], indirect=True)
def test_retract_and_resolve_updates_scores_and_cached_challenges(app):
    """A teammate can retract the shared solve; both modes can solve again."""
    from CTFd.utils.challenges import (
        get_solve_counts_for_challenges,
        get_solve_ids_for_user_id,
        get_solves_for_challenge_id,
    )

    team = gen_team(app.db, member_count=0) if is_teams_mode() else None
    solver = gen_user(app.db, name="solver", team_id=team.id if team else None)
    actor = solver
    if team:
        actor = gen_user(
            app.db, name="teammate", email="teammate@examplectf.com", team_id=team.id
        )
    challenge = gen_challenge(app.db, max_attempts=5)
    gen_flag(app.db, challenge_id=challenge.id)
    fail = gen_fail(app.db, user_id=solver.id, team_id=solver.team_id, challenge_id=1)
    hint = gen_hint(app.db, challenge_id=1, cost=10)
    gen_unlock(app.db, user_id=solver.id, team_id=solver.team_id, target=hint.id)
    gen_award(app.db, user_id=solver.id, team_id=solver.team_id, value=-10)
    solver_id, actor_id, actor_name, fail_id = solver.id, actor.id, actor.name, fail.id
    account_model, account_id = (Teams, team.id) if team else (Users, solver_id)
    client = login_as_user(app, name=solver.name)
    result = client.post(
        "/api/v1/challenges/attempt", json={"challenge_id": 1, "submission": "flag"}
    )
    assert result.get_json()["data"]["status"] == "correct"

    assert account_model.query.get(account_id).get_score() == 90
    assert get_solve_counts_for_challenges() == {1: 1}
    assert len(get_solves_for_challenge_id(1)) == 1
    assert get_solve_ids_for_user_id(solver_id) == {1}
    assert get_solve_ids_for_user_id(actor_id) == {1}
    client = login_as_user(app, name=actor_name)
    assert client.get("/api/v1/challenges/1").get_json()["data"]["solved_by_me"]
    client.get("/api/v1/scoreboard")

    result = client.delete("/api/v1/challenges/1/solve", json={})
    assert result.status_code == 200
    assert result.get_json() == {"success": True}
    assert Solves.query.count() == 0
    assert Submissions.query.filter_by(type="correct").count() == 0
    assert Fails.query.get(fail_id) is not None
    assert HintUnlocks.query.count() == 1
    assert account_model.query.get(account_id).get_score() == -10
    assert get_solve_counts_for_challenges() == {}
    assert get_solves_for_challenge_id(1) == []
    assert get_solve_ids_for_user_id(solver_id) == set()
    assert get_solve_ids_for_user_id(actor_id) == set()
    detail = client.get("/api/v1/challenges/1").get_json()["data"]
    assert detail["solved_by_me"] is False
    assert detail["solves"] == 0
    assert client.get("/api/v1/scoreboard").get_json()["data"][0]["score"] == -10
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 404

    result = client.post(
        "/api/v1/challenges/attempt", json={"challenge_id": 1, "submission": "flag"}
    )
    assert result.get_json()["data"]["status"] == "correct"
    assert account_model.query.get(account_id).get_score() == 90
    assert Solves.query.one().user_id == actor_id


@pytest.mark.parametrize("app", ["users", "teams"], indirect=True)
def test_retraction_cannot_target_another_account(app):
    team = gen_team(app.db, member_count=0) if is_teams_mode() else None
    owner = gen_user(app.db, name="owner", team_id=team.id if team else None)
    other_team = (
        gen_team(app.db, name="other", email="other@examplectf.com", member_count=0)
        if team
        else None
    )
    attacker = gen_user(
        app.db,
        name="attacker",
        email="attacker@examplectf.com",
        team_id=other_team.id if other_team else None,
    )
    gen_challenge(app.db)
    solve = gen_solve(app.db, user_id=owner.id, team_id=owner.team_id, challenge_id=1)
    owner_id, owner_team_id, solve_id = owner.id, owner.team_id, solve.id
    attacker_id, attacker_team_id = attacker.id, attacker.team_id
    client = login_as_user(app, name=attacker.name)
    result = client.delete(
        "/api/v1/challenges/1/solve",
        json={"user_id": owner_id, "team_id": owner_team_id, "submission_id": solve_id},
    )
    assert result.status_code == 404
    assert Solves.query.count() == 1

    own_solve = gen_solve(
        app.db, user_id=attacker_id, team_id=attacker_team_id, challenge_id=1
    )
    own_solve_id = own_solve.id
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 200
    assert Solves.query.get(own_solve_id) is None
    assert Solves.query.one().id == solve_id


@pytest.mark.parametrize(
    "settings",
    [
        {"paused": True},
        {"start": int(time.time()) + 3600},
        {"end": 1, "view_after_ctf": True},
        {"challenge_visibility": "admins"},
        {"verify_emails": True},
    ],
)
def test_retraction_respects_competition_restrictions(app, settings):
    user = gen_user(app.db)
    gen_challenge(app.db)
    gen_solve(app.db, user_id=user.id, challenge_id=1)
    client = login_as_user(app, name=user.name)
    for key, value in settings.items():
        set_config(key, value)
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 403
    assert Solves.query.count() == 1


@pytest.mark.parametrize("state, status", [("hidden", 404), ("locked", 403)])
def test_retraction_respects_challenge_state(app, state, status):
    user = gen_user(app.db)
    gen_challenge(app.db, state=state)
    gen_solve(app.db, user_id=user.id, challenge_id=1)
    client = login_as_user(app, name=user.name)
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == status
    assert Solves.query.count() == 1


def test_retraction_requires_authentication_and_csrf(app):
    user = gen_user(app.db)
    gen_challenge(app.db)
    gen_solve(app.db, user_id=user.id, challenge_id=1)
    assert (
        app.test_client().delete("/api/v1/challenges/1/solve", json={}).status_code
        == 403
    )
    client = login_as_user(app, name=user.name)
    # Send a raw body to avoid the test client's automatic CSRF header.
    result = client.delete(
        "/api/v1/challenges/1/solve", data="{}", content_type="application/json"
    )
    assert result.status_code == 403
    assert Solves.query.count() == 1


@pytest.mark.parametrize("app", ["teams"], indirect=True)
def test_retraction_requires_current_team(app):
    user = gen_user(app.db)
    gen_challenge(app.db)
    gen_solve(app.db, user_id=user.id, challenge_id=1)
    client = login_as_user(app, name=user.name)
    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 403
    assert Solves.query.count() == 1


@pytest.mark.parametrize("restricted", ["scheduled", "module"])
def test_retraction_respects_current_challenge_access(app, restricted):
    user = gen_user(app.db)
    options = {}
    if restricted == "scheduled":
        options["scheduled_at"] = datetime.datetime.utcnow() + datetime.timedelta(
            days=1
        )
    else:
        options["module_id"] = gen_module(app.db, name="restricted").id
    challenge = gen_challenge(app.db, **options)
    gen_solve(app.db, user_id=user.id, challenge_id=challenge.id)
    challenge_id = challenge.id
    client = login_as_user(app, name=user.name)
    assert (
        client.delete(f"/api/v1/challenges/{challenge_id}/solve", json={}).status_code
        == 404
    )
    assert Solves.query.count() == 1


def test_retraction_revokes_prerequisites_and_solved_solution_access(app):
    user = gen_user(app.db)
    gen_challenge(app.db)
    solution_id = gen_solution(app.db, challenge_id=1, state="solved").id
    gen_challenge(app.db, name="dependent", requirements={"prerequisites": [1]})
    gen_flag(app.db, challenge_id=2)
    gen_solve(app.db, user_id=user.id, challenge_id=1)
    client = login_as_user(app, name=user.name)
    assert client.get("/api/v1/challenges/2").status_code == 200
    assert client.get(f"/api/v1/solutions/{solution_id}").status_code == 200
    assert (
        client.get("/api/v1/challenges/1").get_json()["data"]["solution_id"]
        == solution_id
    )

    assert client.delete("/api/v1/challenges/1/solve", json={}).status_code == 200
    assert client.get("/api/v1/challenges/2").status_code == 403
    assert client.get(f"/api/v1/solutions/{solution_id}").status_code == 404
    assert client.get("/api/v1/challenges/1").get_json()["data"]["solution_id"] is None
    result = client.post(
        "/api/v1/challenges/attempt", json={"challenge_id": 2, "submission": "flag"}
    )
    assert result.status_code == 403
    assert client.delete("/api/v1/challenges/999/solve", json={}).status_code == 404


@pytest.mark.parametrize(
    "challenge_class", [CTFdStandardChallenge, DynamicValueChallenge]
)
@pytest.mark.parametrize("function", ["linear", "logarithmic"])
def test_retraction_recalculates_dynamic_values_for_remaining_solvers(
    app, challenge_class, function
):
    first = gen_user(app.db, name="first")
    second = gen_user(app.db, name="second", email="second@examplectf.com")
    challenge = challenge_class.create(
        FakeRequest(
            form={
                "name": "dynamic",
                "category": "test",
                "state": "visible",
                "initial": 100,
                "minimum": 10,
                "decay": 2,
                "function": function,
            }
        )
    )
    gen_flag(app.db, challenge_id=challenge.id)
    challenge_id, first_id, second_id = challenge.id, first.id, second.id
    for name in ("first", "second"):
        client = login_as_user(app, name=name)
        result = client.post(
            "/api/v1/challenges/attempt",
            json={"challenge_id": challenge_id, "submission": "flag"},
        )
        assert result.get_json()["data"]["status"] == "correct"
    assert Challenges.query.get(challenge_id).value < 100
    assert (
        Users.query.get(first_id).get_score()
        == Challenges.query.get(challenge_id).value
    )

    assert (
        client.delete(f"/api/v1/challenges/{challenge_id}/solve", json={}).status_code
        == 200
    )
    assert Challenges.query.get(challenge_id).value == 100
    assert Users.query.get(first_id).get_score() == 100
    assert Users.query.get(second_id).get_score() == 0
    challenges = client.get("/api/v1/challenges").get_json()["data"]
    assert challenges[0]["value"] == 100
    assert challenges[0]["solves"] == 1

    client = login_as_user(app, name="first")
    assert (
        client.delete(f"/api/v1/challenges/{challenge_id}/solve", json={}).status_code
        == 200
    )
    assert Challenges.query.get(challenge_id).value == 100
    assert Solves.query.count() == 0
