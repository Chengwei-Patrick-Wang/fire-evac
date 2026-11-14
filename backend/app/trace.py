"""Tracer routes (spec 7.5), mounted under /api by main.py.

Placeholder until A8 puts the Gemini first pass behind it.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/trace/propose")
def post_trace_propose():
    raise HTTPException(501, "not implemented yet")
