from pydantic import BaseModel, Field
import numpy as np
from app.udfkit import udf

class NPVRequest(BaseModel):
    cashflows: list[float]
    rate: float

class NPVResponse(BaseModel):
    npv: float
    per_period: list[float]

@udf("npv", mode="sync", request_model=NPVRequest, response_model=NPVResponse)
def npv(req: NPVRequest) -> NPVResponse:
    cf = np.array(req.cashflows, dtype=float)
    r = float(req.rate)
    t = np.arange(len(cf))
    pv = cf / (1 + r) ** t
    return NPVResponse(npv=float(pv.sum()), per_period=pv.tolist())

class ScenarioRequest(BaseModel):
    cashflows: list[float]
    rate: float
    n_sims: int = 1000
    mu: float = 0.0
    sigma: float = 0.1

class ScenarioResponse(BaseModel):
    npv_mean: float
    npv_std: float

@udf("scenario", mode="async", request_model=ScenarioRequest, response_model=ScenarioResponse)
def scenario(req: ScenarioRequest) -> ScenarioResponse:
    cf = np.array(req.cashflows, dtype=float)
    r = req.rate
    t = np.arange(len(cf))
    discounts = 1 / (1 + r) ** t
    rng = np.random.default_rng(42)
    shocks = rng.normal(req.mu, req.sigma, (req.n_sims, len(cf)))
    pv_sims = (cf * (1 + shocks)) * discounts
    npvs = pv_sims.sum(axis=1)
    return ScenarioResponse(npv_mean=float(npvs.mean()), npv_std=float(npvs.std(ddof=1)))

class DurationRequest(BaseModel):
    cashflows: list[float]
    rate: float

class DurationResponse(BaseModel):
    npv: float
    duration: float                 # Durée de Macaulay (en périodes)
    pv_per_period: list[float]      # Valeurs actualisées par période
    weights: list[float]            # Poids normalisés par période (PV_i / NPV)

@udf("duration", mode="sync", request_model=DurationRequest, response_model=DurationResponse)
def duration(req: DurationRequest) -> DurationResponse:
    cf = np.array(req.cashflows, dtype=float)
    r = float(req.rate)
    t = np.arange(len(cf), dtype=float)               # 0,1,2,...
    discounts = 1.0 / (1.0 + r) ** t
    pv = cf * discounts
    npv = float(pv.sum())

    if npv == 0.0:
        dur = 0.0
        weights = [0.0] * len(pv)
    else:
        w = pv / npv                                  # poids
        dur = float((t * w).sum())                    # Macaulay duration
        weights = w.tolist()

    return DurationResponse(
        npv=npv,
        duration=dur,
        pv_per_period=pv.tolist(),
        weights=weights,
    )
    
