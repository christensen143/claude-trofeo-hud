"""Polling cadence for the usage endpoint.

The endpoint rate-limits harder than the collector's original cadence assumed:
it admits roughly one call every two minutes and answers HTTP 429 otherwise.
At 60s that meant every other poll failed — measured across a 5-hour run, 103
of 145 failures were exactly 120s apart (one success, one refusal, repeating),
and a request that returned 200 returned 429 when repeated two seconds later.

The 429 carries no rate-limit metadata and `Retry-After: 0`, so a client can
only stay clear of the limiter by polling below its rate.
"""
from claude_trofeo_hud.collectors.limits import LimitsCollector

# The shortest interval observed to be refused.
_OBSERVED_REFUSAL_BOUNDARY_S = 120.0


def test_cadence_stays_clear_of_the_endpoint_rate_limit():
    assert LimitsCollector.cadence_s > _OBSERVED_REFUSAL_BOUNDARY_S


def test_cadence_keeps_a_margin_over_the_boundary():
    """The boundary is a floor, not a published limit — leave room."""
    assert LimitsCollector.cadence_s >= 1.5 * _OBSERVED_REFUSAL_BOUNDARY_S
