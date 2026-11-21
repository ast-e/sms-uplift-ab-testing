import numpy as np
import pandas as pd
import pytest

from ab_utils import (
    aa_rejection_rate,
    attach_history,
    cuped_adjust,
    diff_in_means,
    mde_for_n,
    n_per_arm,
    n_with_cuped,
)


# --- Sample size and minimum detectable effect -------------------------------------------------

def test_n_per_arm_baseline_60_mde_1pp():
    assert 37674 <= n_per_arm(0.6, 0.01) <= 37676


def test_mde_matches_analysis_notebook():
    # Notebook 02 reports a minimum detectable effect of about 0.61 pp with ~100K customers per arm.
    assert abs(mde_for_n(0.6, 100_000) - 0.00614) < 0.0001


@pytest.mark.parametrize(
    "call",
    [
        lambda: n_per_arm(0.0, 0.01),    # nobody ever buys: no variance
        lambda: n_per_arm(1.0, 0.01),    # everybody always buys: no variance
        lambda: n_per_arm(0.6, 0.0),     # "detect any difference": infinite sample
        lambda: n_per_arm(0.6, -0.01),   # a negative effect size is not defined
        lambda: mde_for_n(0.6, 0),       # zero customers
    ],
)
def test_invalid_inputs_raise(call):
    with pytest.raises(ValueError):
        call()


# --- A/A simulation -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def control_outcomes():
    return np.random.default_rng(42).binomial(1, 0.6, size=100_000)


def test_aa_single_look_is_near_five_percent(control_outcomes):
    rate = aa_rejection_rate(control_outcomes, n_sims=2000, looks=1, seed=0)
    assert 0.035 <= rate <= 0.065


def test_aa_peeking_inflates_false_positives(control_outcomes):
    rate = aa_rejection_rate(control_outcomes, n_sims=2000, looks=10, seed=0)
    assert rate > 0.12


def test_aa_is_reproducible(control_outcomes):
    first = aa_rejection_rate(control_outcomes, n_sims=200, looks=3, seed=7)
    second = aa_rejection_rate(control_outcomes, n_sims=200, looks=3, seed=7)
    assert first == second


# --- CUPED sample-size saving -------------------------------------------------------------------

def test_n_with_cuped_scales_by_one_minus_rho_squared():
    assert n_with_cuped(40_000, 0.5) == 30_000
    assert n_with_cuped(40_000, 0.0) == 40_000


@pytest.mark.parametrize(
    "args",
    [(0, 0.5), (40_000, 1.0), (40_000, -1.0)],
)
def test_n_with_cuped_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        n_with_cuped(*args)


# --- Effect estimation and CUPED adjustment -----------------------------------------------------

def test_diff_in_means_known_values():
    y = np.array([1, 1, 0, 0, 1, 0, 0, 0])
    t = np.array([1, 1, 1, 1, 0, 0, 0, 0])
    effect, ci_low, ci_high = diff_in_means(y, t)
    assert effect == pytest.approx(0.25)
    assert ci_low < 0.25 < ci_high


def _simulate(effect=0.0, n=50_000, seed=0):
    """Outcome driven by a pre-experiment covariate x; a random half receives `effect`."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    t = rng.permutation(np.repeat([0, 1], n // 2))
    y = 0.7 * x + rng.normal(size=n) + effect * t
    return x, y, t


def test_cuped_reduces_variance_by_one_minus_rho_squared():
    x, y, _ = _simulate()
    y_adj, _ = cuped_adjust(y, x)
    rho = np.corrcoef(x, y)[0, 1]
    assert abs(np.var(y_adj) / np.var(y) - (1 - rho**2)) < 0.02


def test_cuped_does_not_shift_the_effect():
    x, y, t = _simulate(effect=0.05)
    y_adj, _ = cuped_adjust(y, x)
    _, lo_raw, hi_raw = diff_in_means(y, t)
    _, lo_adj, hi_adj = diff_in_means(y_adj, t)
    assert lo_adj < 0.05 < hi_adj
    assert (hi_adj - lo_adj) < (hi_raw - lo_raw)


def test_cuped_constant_covariate_raises():
    with pytest.raises(ValueError):
        cuped_adjust(np.array([1.0, 2.0, 3.0, 4.0]), np.ones(4))


# --- Attaching purchase history (Review Focus 1: customers with no history must not be dropped) ---

def test_attach_history_keeps_customers_without_history():
    train = pd.DataFrame({"client_id": ["a", "b", "c", "d", "e"], "treatment_flg": [1, 0, 1, 0, 1], "target": [1, 0, 1, 1, 0]})
    features = pd.DataFrame({
        "client_id": ["a", "c", "d"],  # "b" and "e" have no purchases before the campaign
        "n_transactions": [4, 10, 1],
        "total_spend": [120.0, 900.0, 15.0],
        "log_spend": np.log1p([120.0, 900.0, 15.0]),
        "last_purchase_date": pd.to_datetime(["2019-03-01", "2019-03-10", "2019-02-02"]),
        "has_history": [True, True, True],
    })

    out = attach_history(train, features)

    assert len(out) == 5                                     # nobody is dropped
    assert list(out["client_id"]) == ["a", "b", "c", "d", "e"]  # same order as the training table
    no_history = out[out["client_id"].isin(["b", "e"])]
    assert (no_history["n_transactions"] == 0).all()
    assert (no_history["log_spend"] == 0).all()
    assert not no_history["has_history"].any()
    with_history = out[out["client_id"].isin(["a", "c", "d"])]
    assert with_history["has_history"].all()
    assert list(with_history["n_transactions"]) == [4, 10, 1]  # their real values are untouched
    assert pd.api.types.is_integer_dtype(out["n_transactions"])
    assert out["has_history"].dtype == bool
