# app/routes/discovery.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import date, datetime
import pandas as pd
import os

router = APIRouter()

DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "synthetic_discovery_dataset.csv"
)

class Timeline(BaseModel):
    start: date
    end: date

class OptionalAttributes(BaseModel):
    style: Optional[str] = None
    colors: Optional[List[str]] = None
    patterns: Optional[List[str]] = None

class DiscoveryRequest(BaseModel):
    gender: str
    garment_type: str
    timeline: Timeline
    optional: Optional[OptionalAttributes] = None

@router.post("/run")
def run_discovery(req: DiscoveryRequest) -> Dict:
    print(f"Received request: {req.dict()}") # For debugging

    try:
        # Specify encoding to handle non-UTF-8 characters, typically 'latin-1' or 'cp1252'
        df = pd.read_csv(DATASET_PATH, encoding='latin-1') 
        # FIX 1: Make date parsing robust. It should be 'DD-MM-YYYY' based on your CSV.
        df["timestamp"] = pd.to_datetime(df["timestamp"], format='%d-%m-%Y', errors='coerce')
        df.dropna(subset=['timestamp'], inplace=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Failed to process dataset: {str(e)}"})

    # --- Initial Filtering ---
    start_date = pd.to_datetime(req.timeline.start)
    end_date = pd.to_datetime(req.timeline.end)

    mask = (
        (df["gender"].str.lower() == req.gender.lower()) &
        (df["garment_type"].str.lower() == req.garment_type.lower()) &
        (df["timestamp"] >= start_date) &
        (df["timestamp"] <= end_date)
    )
    
    # NEW CODE (More robust handling of empty lists for filtering)
    if req.optional:
        # Check if colors list has content before applying filter
        colors_to_filter = [c.lower() for c in req.optional.colors if c] if req.optional.colors else []
        if colors_to_filter:
            mask &= df["color"].str.lower().isin(colors_to_filter)
            
        # Check if patterns list has content before applying filter
        patterns_to_filter = [p.lower() for p in req.optional.patterns if p] if req.optional.patterns else []
        if patterns_to_filter:
            mask &= df["pattern"].str.lower().isin(patterns_to_filter)
            
    filtered_df = df[mask].copy()

    print(f"Found {len(filtered_df)} items after filtering.") # For debugging

    # --- Grouping and Aggregation Logic ---
    if filtered_df.empty:
        return {"results": [], "dataset_url": None}

    grouping_fields = ['timestamp', 'influence_identifier', 'pattern', 'color']
    grouped = filtered_df.groupby(grouping_fields)
    results = []
    for name, group in grouped:
        avg_engagement = group['engagement_metric'].mean()
        items_in_group = group.to_dict(orient="records")
        for item in items_in_group:
            item["image_url"] = f"/images/{item['image_path']}"
        results.append({
            "group_key": name,
            "timestamp": name[0].isoformat(),
            "items": items_in_group,
            "engagement_metric_avg": avg_engagement,
            "item_count": len(items_in_group)
        })
    
    print(f"Returning {len(results)} groups to the frontend.")

    # --- CSV Generation ---
    dataset_url = None
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    os.makedirs(STATIC_DIR, exist_ok=True)
    filename = f"discovery_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    filepath = os.path.join(STATIC_DIR, filename)
    filtered_df.to_csv(filepath, index=False)
    dataset_url = f"/static/{filename}"
    
    return {"results": results, "dataset_url": dataset_url}