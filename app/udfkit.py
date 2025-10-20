# app/udfkit.py
from __future__ import annotations
from typing import Any, Callable, Dict, Optional, Type, Literal, List
from pydantic import BaseModel, Field
from enum import Enum
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Body
from concurrent.futures import ThreadPoolExecutor
import threading
import os
import logging, time
from typing import Any

logger = logging.getLogger("udfkit")
def _summarize_val(v: Any) -> Any:
    """Résumé compact et sûr pour les logs (évite d'inonder/PII).
    - list/tuple: taille + 1ers éléments
    - dict: clés + tailles
    - pydantic model: dict() résumé
    """
    try:
        from pydantic import BaseModel
    except Exception:
        BaseModel = tuple()  # type: ignore

    try:
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        if isinstance(v, (list, tuple)):
            n = len(v)
            head = v[:5] if n else []
            return {"type": type(v).__name__, "len": n, "head": head}
        if isinstance(v, dict):
            return {"type": "dict", "keys": list(v.keys())[:10]}
        if "numpy" in type(v).__module__.lower():
            # numpy array
            try:
                import numpy as np  # noqa
                shape = getattr(v, "shape", None)
                return {"type": "ndarray", "shape": shape}
            except Exception:
                return {"type": "ndarray"}
        if BaseModel and isinstance(v, BaseModel):  # type: ignore[truthy-bool]
            d = v.model_dump()
            return {k: _summarize_val(d[k]) for k in d}
        # fallback
        return {"type": type(v).__name__}
    except Exception:
        return {"type": type(v).__name__}
    
# =========================================================
# Types & schémas communs
# =========================================================

class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"

class JobSubmitResponse(BaseModel):
    job_id: str = Field(..., description="Identifiant du job")
    status: JobStatus = Field(..., description="État du job")

class JobGetBase(BaseModel):
    job_id: str
    status: JobStatus
    result: dict | None = None   # réponse générique (compatible Swagger)
    error: str | None = None

# =========================================================
# Registry des UDFs
# =========================================================

class _UDFMeta(BaseModel):
    name: str
    mode: Literal["sync", "async"]
    request_model: Type[BaseModel]
    response_model: Type[BaseModel]
    func: Callable[[BaseModel], BaseModel]
    tags: Optional[List[str]] = None
    version: Optional[str] = None
    description: Optional[str] = None

_REGISTRY: Dict[str, _UDFMeta] = {}

def udf(
    name: Optional[str] = None,
    *,
    mode: Literal["sync", "async"] = "sync",
    request_model: Type[BaseModel],
    response_model: Type[BaseModel],
    tags: Optional[List[str]] = None,
    version: Optional[str] = None,
    description: Optional[str] = None,
):
    """
    Décorateur d'enregistrement d'une UDF.

    Example:
        @udf("npv", mode="sync", request_model=Req, response_model=Resp)
        def npv(req: Req) -> Resp: ...

        @udf("scenario", mode="async", request_model=Req, response_model=Resp)
        def scenario(req: Req) -> Resp: ...
    """
    def _wrap(func: Callable[[BaseModel], BaseModel]):
        fn_name = name or func.__name__
        if fn_name in _REGISTRY:
            raise ValueError(f"UDF '{fn_name}' déjà enregistrée")

        meta = _UDFMeta(
            name=fn_name,
            mode=mode,
            request_model=request_model,
            response_model=response_model,
            func=func,
            tags=tags,
            version=version,
            description=description or (func.__doc__ or "").strip() or fn_name,
        )
        _REGISTRY[fn_name] = meta
        return func
    return _wrap

# =========================================================
# Store & exécution de jobs (POC: en mémoire)
# =========================================================

_MAX = max(2, (os.cpu_count() or 2) - 1)
_EXECUTOR = ThreadPoolExecutor(max_workers=min(_MAX, 8))
_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

def _set_job(job_id: str, **updates):
    with _LOCK:
        _JOBS[job_id].update(updates)

def _run_job(job_id: str, meta: _UDFMeta, req_obj: BaseModel):
    t0 = time.perf_counter()
    try:
        _set_job(job_id, status=JobStatus.running)
        logger.info(
            "udf.async.start",
            extra={"udf": meta.name, "job_id": job_id},
        )
        result = meta.func(req_obj)
        _set_job(job_id, status=JobStatus.done, result=result, error=None)
        dt = time.perf_counter() - t0
        logger.info(
            "udf.async.done",
            extra={"udf": meta.name, "job_id": job_id, "elapsed_s": round(dt, 4)},
        )
    except Exception as e:
        _set_job(job_id, status=JobStatus.error, error=str(e))
        dt = time.perf_counter() - t0
        logger.exception(
            "udf.async.error",
            extra={"udf": meta.name, "job_id": job_id, "elapsed_s": round(dt, 4)},
        )

# =========================================================
# Montage des routes sur une app FastAPI
# =========================================================

def attach_to_app(
    app,
    *,
    base_udf_path: str = "/udf",
    base_jobs_path: str = "/jobs",
    security_dep: Optional[Callable[..., Any]] = None,
):
    udf_router = APIRouter()
    jobs_router = APIRouter()
    deps = [Depends(security_dep)] if security_dep else []

    # --------- GET /jobs/{job_id} générique (OK Swagger) ---------
    @jobs_router.get(f"{base_jobs_path}" + "/{job_id}", response_model=JobGetBase, dependencies=deps)
    def get_job(job_id: str):
        with _LOCK:
            data = _JOBS.get(job_id)
        if not data:
            raise HTTPException(status_code=404, detail="job not found")

        result_obj = data.get("result")
        if isinstance(result_obj, BaseModel):
            result_payload = result_obj.model_dump()
        elif isinstance(result_obj, dict):
            result_payload = result_obj
        else:
            try:
                result_payload = result_obj.dict()  # type: ignore[attr-defined]
            except Exception:
                result_payload = None

        return JobGetBase(
            job_id=job_id,
            status=data["status"],
            result=result_payload,
            error=data.get("error"),
        )

    # --------- Usines de fonctions pour endpoints ---------
    def make_sync_endpoint(meta: _UDFMeta, ReqModel: type[BaseModel]):
        try:
            ReqModel.model_rebuild()
            meta.response_model.model_rebuild()
        except Exception:
            pass

        async def endpoint(req: Any = Body(...)):
            t0 = time.perf_counter()
            try:
                # Validation explicite pour éviter tout ForwardRef
                obj = ReqModel.model_validate(req)
                logger.info(
                    "udf.sync.start",
                    extra={"udf": meta.name, "mode": meta.mode, "request": _summarize_val(obj)},
                )
                res = meta.func(obj)
                dt = time.perf_counter() - t0
                logger.info(
                    "udf.sync.done",
                    extra={"udf": meta.name, "elapsed_s": round(dt, 4)},
                )
                return res
            except Exception:
                dt = time.perf_counter() - t0
                logger.exception(
                    "udf.sync.error",
                    extra={"udf": meta.name, "elapsed_s": round(dt, 4)},
                )
                raise

        # ⚠️ Remplace l’annotation string par la vraie classe
        endpoint.__annotations__ = {'req': ReqModel}
        return endpoint

    def make_submit_endpoint(meta: _UDFMeta, ReqModel: type[BaseModel]):
        try:
            ReqModel.model_rebuild()
            meta.response_model.model_rebuild()
        except Exception:
            pass

        async def endpoint(req: Any = Body(...)):
            obj = ReqModel.model_validate(req)
            job_id = str(uuid4())
            with _LOCK:
                _JOBS[job_id] = {
                    "status": JobStatus.queued,
                    "result": None,
                    "error": None,
                    "udf_name": meta.name,
                }
            logger.info(
                "udf.async.submit",
                extra={"udf": meta.name, "job_id": job_id, "request": _summarize_val(obj)},
            )
            _EXECUTOR.submit(_run_job, job_id, meta, obj)
            return JobSubmitResponse(job_id=job_id, status=JobStatus.queued)

        endpoint.__annotations__ = {'req': ReqModel}
        return endpoint

    # --------- Création des routes pour chaque UDF enregistrée ---------
    for name, meta in _REGISTRY.items():
        ReqModel = meta.request_model
        RespModel = meta.response_model
        tags = meta.tags or [f"udf:{name}"]

        if meta.mode == "sync":
            udf_router.add_api_route(
                path=f"{base_udf_path}/{name}",
                endpoint=make_sync_endpoint(meta, ReqModel),
                response_model=RespModel,
                methods=["POST"],
                tags=tags,
                dependencies=deps,
                summary=meta.description or name,
            )
        else:
            jobs_router.add_api_route(
                path=f"{base_jobs_path}/{name}",
                endpoint=make_submit_endpoint(meta, ReqModel),
                response_model=JobSubmitResponse,
                methods=["POST"],
                tags=tags,
                dependencies=deps,
                summary=f"Submit job {name}",
            )

    app.include_router(udf_router)
    app.include_router(jobs_router)
