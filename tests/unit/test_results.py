"""Turn results: immutable, compared by value, outcomes kept in order."""

import dataclasses

import pytest

from airlanes.results import (
    Arrival,
    Departure,
    Reroute,
    TurnOutcome,
    TurnResult,
)

DEPARTURE = Departure("D1", "start", "goal", "start-goal")
ARRIVAL = Arrival("D1", "start", "goal", "start-goal")
REROUTE = Reroute("D1", "start", ("a", "goal"), ("b", "goal"))


@pytest.mark.parametrize(
    ("outcome", "field"),
    [
        pytest.param(DEPARTURE, "lane", id="departure"),
        pytest.param(ARRIVAL, "destination", id="arrival"),
        pytest.param(REROUTE, "new_route", id="reroute"),
    ],
)
def test_outcomes_are_immutable(outcome: TurnOutcome, field: str) -> None:
    assert isinstance(outcome, TurnOutcome)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(outcome, field, "x")


def test_turn_result_is_immutable() -> None:
    result = TurnResult(1, (DEPARTURE,))

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.outcomes = ()  # type: ignore[misc]


def test_departure_and_arrival_describe_the_same_leg() -> None:
    """Departure and Arrival carry the same fields, so an arrival can be
    understood without finding its departure."""
    assert (
        DEPARTURE.aircraft,
        DEPARTURE.origin,
        DEPARTURE.destination,
        DEPARTURE.lane,
    ) == ("D1", "start", "goal", "start-goal")
    assert dataclasses.astuple(ARRIVAL) == dataclasses.astuple(DEPARTURE)


def test_reroute_keeps_both_routes() -> None:
    assert REROUTE.hub == "start"
    assert REROUTE.old_route == ("a", "goal")
    assert REROUTE.new_route == ("b", "goal")


def test_results_compare_by_value_and_keep_outcome_order() -> None:
    first = TurnResult(1, (DEPARTURE, ARRIVAL))

    assert first == TurnResult(
        1,
        (
            Departure("D1", "start", "goal", "start-goal"),
            Arrival("D1", "start", "goal", "start-goal"),
        ),
    )
    assert first != TurnResult(1, (ARRIVAL, DEPARTURE))


def test_a_completed_turn_may_have_no_outcomes() -> None:
    assert TurnResult(2, ()).outcomes == ()
