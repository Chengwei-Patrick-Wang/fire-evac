"""Report route (spec 7.5), mounted under /api by main.py.

Placeholder until A7 puts the LLM report card behind it.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/report")
def post_report():
    raise HTTPException(501, "not implemented yet")
