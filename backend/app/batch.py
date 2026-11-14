"""Batch routes (spec 7.4, 7.5), mounted under /api by main.py.

Placeholder until A4 puts fire.batch.run_many behind them: every batch is the example batch
(contracts/batch.example.json, which carries "placeholder": true).
"""
import json

from fastapi import APIRouter, HTTPException, Response

from .store import BATCH_EXAMPLE

router = APIRouter()


def _example_batch() -> bytes:
    try:
        return BATCH_EXAMPLE.read_bytes()
    except OSError:
        raise HTTPException(404, "contracts/batch.example.json has not been generated yet")


@router.post("/batch")
def post_batch():
    return {"batchId": json.loads(_example_batch()).get("id", "example-batch")}


@router.get("/batch/{batch_id}")
def get_batch(batch_id: str):
    return Response(_example_batch(), media_type="application/json")
