"""Statistics helpers for the A/B testing project: experiment design and simulation."""
import math

import numpy as np
import pandas as pd
from scipy.stats import norm


def _check_p(p: float) -> None:
    """Baseline rate must be strictly between 0 and 1, otherwise the variance p(1-p) is zero."""
    if not 0 < p < 1:
        raise ValueError(f"baseline rate p must be strictly between 0 and 1, got {p}")


def _z_sum(alpha: float, power: float) -> float:
    """z_(1 - alpha/2) + z_(power): the two normal quantiles in the sample-size formula."""
    return norm.ppf(1 - alpha / 2) + norm.ppf(power)


def n_per_arm(p: float, mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Customers needed in each arm to detect an absolute difference `mde` in a rate with baseline `p`.

    n = ceil( 2 * (z_(1 - alpha/2) + z_(power))**2 * p * (1 - p) / mde**2 )
    """
    _check_p(p)
    if mde <= 0:
        raise ValueError(f"mde must be positive, got {mde}")
    return math.ceil(2 * (_z_sum(alpha, power)) ** 2 * p * (1 - p) / mde**2)


def mde_for_n(p: float, n: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest absolute difference detectable with `n` customers per arm (inverse of n_per_arm)."""
    _check_p(p)
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return _z_sum(alpha, power) * math.sqrt(2 * p * (1 - p) / n)


def n_with_cuped(n: int, rho: float) -> int:
    """Sample size per arm after CUPED: the variance shrinks by a factor (1 - rho**2)."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if abs(rho) >= 1:
        raise ValueError(f"|rho| must be below 1, got {rho}")
    return math.ceil(n * (1 - rho**2))


def aa_rejection_rate(
    y: np.ndarray, n_sims: int, looks: int = 1, alpha: float = 0.05, seed: int = 0
) -> float:
    """Share of A/A simulations in which a two-proportion z-test 'finds' a difference.

    `y` must contain outcomes of control customers only (0/1), so any difference is pure chance.
    Each simulation randomly splits `y` into two equal halves and tests at `looks` equally spaced
    cumulative sample sizes; the simulation counts as a false positive if ANY look has p < alpha.
    """
    y = np.asarray(y, dtype=float)
    if looks < 1:
        raise ValueError(f"looks must be at least 1, got {looks}")
    rng = np.random.default_rng(seed)
    half = len(y) // 2
    sizes = np.linspace(half / looks, half, looks).astype(int)  # cumulative customers per arm
    z_crit = norm.ppf(1 - alpha / 2)

    rejected = 0
    for _ in range(n_sims):
        shuffled = rng.permutation(y)
        successes_a = np.cumsum(shuffled[:half])[sizes - 1]
        successes_b = np.cumsum(shuffled[half : 2 * half])[sizes - 1]
        pooled = (successes_a + successes_b) / (2 * sizes)
        se = np.sqrt(pooled * (1 - pooled) * 2 / sizes)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (successes_a - successes_b) / sizes / se
        if np.any(np.abs(z) > z_crit):
            rejected += 1
    return rejected / n_sims


def diff_in_means(y: np.ndarray, t: np.ndarray, alpha: float = 0.05) -> tuple[float, float, float]:
    """Treated-minus-control difference in means with a (1 - alpha) normal-approximation CI.

    `t` is 0/1. The standard error is unpooled: each arm keeps its own variance.
    Returns (effect, ci_low, ci_high).
    """
    y, t = np.asarray(y, dtype=float), np.asarray(t)
    treated, control = y[t == 1], y[t == 0]
    if len(treated) < 2 or len(control) < 2:
        raise ValueError("each arm needs at least 2 customers")
    effect = treated.mean() - control.mean()
    se = math.sqrt(treated.var(ddof=1) / len(treated) + control.var(ddof=1) / len(control))
    z = norm.ppf(1 - alpha / 2)
    return effect, effect - z * se, effect + z * se


def cuped_adjust(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    """CUPED: remove from the outcome `y` the part predictable from the pre-experiment covariate `x`.

    theta = cov(x, y) / var(x), computed on ALL customers (both arms together, so it cannot
    absorb a treatment effect); y_adjusted = y - theta * (x - mean(x)). Returns (y_adjusted, theta).
    """
    y, x = np.asarray(y, dtype=float), np.asarray(x, dtype=float)
    if x.var() == 0:
        raise ValueError("the covariate is constant (variance 0): theta is undefined")
    x_centred = x - x.mean()
    theta = np.mean(x_centred * (y - y.mean())) / x.var()  # cov and var both with ddof=0, so they are consistent
    return y - theta * x_centred, theta


def attach_history(train: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Left-join purchase-history features onto the training table WITHOUT dropping anyone.

    Customers with no purchases before the campaign keep their row, with n_transactions = 0,
    total_spend = 0, log_spend = 0 and has_history = False. Dropping them would change the sample
    analysed in notebook 02. `validate="1:1"` fails loudly if either table repeats a client_id.
    """
    out = train.merge(features, on="client_id", how="left", validate="1:1")
    out["n_transactions"] = out["n_transactions"].fillna(0).astype(int)
    out["total_spend"] = out["total_spend"].fillna(0.0)
    out["log_spend"] = out["log_spend"].fillna(0.0)
    out["has_history"] = out["has_history"].fillna(False).astype(bool)
    return out
