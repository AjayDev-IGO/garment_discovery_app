# app/routes/predictor.py

from fastapi import APIRouter, HTTPException, File, UploadFile
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd
import os
import json

import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

import google.generativeai as genai
genai.configure(api_key='AIzaSyDZfD0wfWfy47ixo5ILvOWxJuMdaI25Clc')

router = APIRouter()

@router.post("/upload_dataset")
async def upload_dataset(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    # Assume single file for simplicity
    file = files[0]
    filename = f"uploaded_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    filepath = os.path.join(STATIC_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"dataset_url": f"/static/{filename}"}

class PredictionRequest(BaseModel):
    dataset_path: str
    prediction_date: str  # YYYY-MM-DD
    geography: str
    target_group: Optional[Dict[str, str]] = None

@router.post("/predict")
async def run_prediction(req: PredictionRequest) -> Dict:
    try:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        full_path = os.path.join(BASE_DIR, req.dataset_path.lstrip('/'))
        logger.debug(f"Loading dataset from: {full_path}")
        
        if not os.path.exists(full_path):
            logger.error(f"File not found: {full_path}")
            raise HTTPException(status_code=404, detail=f"Dataset file not found: {full_path}")

        df = pd.read_csv(full_path, encoding='latin-1')
        logger.debug(f"Dataset columns: {df.columns.tolist()}")
        
        required_columns = ['garment_type', 'color', 'pattern', 'fit', 'style', 'length', 'neckline', 'sleeve', 'fabric', 
                          'engagement_metric', 'engagement_likes', 'engagement_comments', 'engagement_views', 'timestamp']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing columns in dataset: {missing_columns}")
            raise HTTPException(status_code=400, detail=f"Dataset missing required columns: {missing_columns}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors='coerce')
        if df["timestamp"].isna().all():
            logger.error("All timestamps are invalid or missing")
            raise HTTPException(status_code=400, detail="All timestamps in dataset are invalid or missing")
        df.dropna(subset=['timestamp'], inplace=True)

        summary = df.groupby(['garment_type', 'color', 'pattern', 'fit', 'style', 'length', 'neckline', 'sleeve', 'fabric']).agg({
            'engagement_metric': 'mean',
            'engagement_likes': 'mean',
            'engagement_comments': 'mean',
            'engagement_views': 'mean',
            'timestamp': 'count'
        }).reset_index().rename(columns={'timestamp': 'count'})
        summary_str = summary.to_csv(index=False)
        logger.debug(f"Dataset summary:\n{summary_str}")

        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Analyze this historical garment trend data summary (CSV format):
        {summary_str}

        Predict near-future trends for date {req.prediction_date} in {req.geography}.
        Consider target group: {req.target_group if req.target_group else 'General'}.

        Output ONLY a JSON array of objects, each representing a predicted group:
        Each object has:
        - "timestamp": string (predicted date in YYYY-MM-DD) (different dates for different records)
        - "items": array of objects, each with:
          - "id": integer (unique, starting from 1)
          - "garment_type": string
          - "color": string (or comma-separated if multiple)
          - "pattern": string
          - "fit": string
          - "style": string
          - "length": string
          - "neckline": string
          - "sleeve": string
          - "fabric": string
          - "influence_type": string (e.g., "Celebrity")
          - "influence_identifier": string (e.g., "Celeb A")
          - "engagement_likes": integer
          - "engagement_comments": integer
          - "engagement_views": integer
          - "timestamp": string (same as group)
          - "image_url": null
        - "engagement_metric_avg": float
        - "item_count": integer

        Predict 5-10 diverse groups based on extrapolating trends from the data.
        """
        logger.debug("Sending prompt to Gemini API")
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith('```json'):
            text = text.strip('```json').strip('```')
        results = json.loads(text)
        logger.debug(f"Prediction results: {results}")
        
        return {"results": results, "dataset_url": None}
    except Exception as e:
        logger.error(f"Prediction error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

class GenerateImageRequest(BaseModel):
    description: str

from google.genai import types
from PIL import Image
from io import BytesIO
import base64

@router.post("/generate_image")
async def generate_image(req: GenerateImageRequest) -> dict:
    try:
        from google import genai
        # Initialize the client with the API key
        client = genai.Client(api_key='AIzaSyDZfD0wfWfy47ixo5ILvOWxJuMdaI25Clc')

        logger.debug(f"Generating image with prompt: {req.description}")
        response = client.models.generate_images(
            model='imagen-4.0-generate-001',
            prompt=req.description,
            config=types.GenerateImagesConfig(
                number_of_images=1,
            )
        )

        # Check if images were generated
        if not response.generated_images:
            logger.error("No images generated by the model")
            raise ValueError("Image generation returned no images")

        # Process the first generated image
        image_obj = response.generated_images[0].image
        if not image_obj:
            logger.error("No image object found in response")
            raise ValueError("No image object found")

        # Get the MIME type
        mime_type = getattr(image_obj, 'mime_type', 'unknown')
        logger.debug(f"Image 1 MIME type: {mime_type}")

        # Get the image bytes
        if hasattr(image_obj, 'image_bytes'):
            image_data = image_obj.image_bytes
        else:
            logger.error("No image_bytes attribute found")
            raise ValueError("No image_bytes attribute found")

        # Convert image_data to base64 string if needed
        if isinstance(image_data, bytes):
            try:
                base64_string = image_data.decode('utf-8')
                logger.debug(f"Image 1: Converted bytes to base64 string: {len(base64_string)} chars")
            except UnicodeDecodeError as e:
                logger.error(f"Image 1: Failed to decode bytes to string: {str(e)}")
                raise ValueError(f"Failed to decode image_bytes: {str(e)}")
        elif isinstance(image_data, str):
            base64_string = image_data
            logger.debug(f"Image 1: Using string as base64: {len(base64_string)} chars")
        else:
            logger.error(f"Image 1: image_bytes is not string or bytes, got {type(image_data)}")
            raise ValueError(f"image_bytes is not string or bytes, got {type(image_data)}")

        # Debug: Print first few characters of base64 string
        logger.debug(f"Image 1 base64 start: {base64_string[:10]}...")

        # Decode base64 string to raw PNG bytes
        try:
            binary_data = base64.b64decode(base64_string)
            logger.debug(f"Image 1 decoded base64: {len(base64_string)} chars -> {len(binary_data)} bytes")
        except Exception as e:
            logger.error(f"Image 1: Base64 decode failed: {str(e)}")
            raise ValueError(f"Base64 decode failed: {str(e)}")

        # Debug: Check size and PNG header
        logger.debug(f"Image 1 binary data size: {len(binary_data)} bytes")
        if len(binary_data) >= 8:
            logger.debug(f"Image 1 first 8 bytes: {binary_data[:8].hex()}")
            if binary_data[:8] == b'\x89PNG\r\n\x1a\n':
                logger.debug("Image 1: Valid PNG header detected.")
            else:
                logger.warning(f"Image 1: Invalid PNG header: {binary_data[:8].hex()}")
        else:
            logger.error(f"Image 1: Binary data too short for PNG header: {len(binary_data)} bytes")
            raise ValueError(f"Binary data too short: {len(binary_data)} bytes")

        # Set up file paths
        filename = f"generated_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.png"  # Changed to .png to match MIME type
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        IMAGE_DIR = os.path.join(BASE_DIR, "data", "images")
        os.makedirs(IMAGE_DIR, exist_ok=True)
        filepath = os.path.join(IMAGE_DIR, filename)

        # Save the binary data to disk
        with open(filepath, "wb") as f:
            f.write(binary_data)
        logger.debug(f"Image 1 saved to: {filepath}")

        # Verify with PIL
        try:
            img = Image.open(BytesIO(binary_data))
            # Optionally convert to JPEG if needed
            if mime_type == "image/png" and filename.endswith(".jpg"):
                img = img.convert("RGB")  # PNG may have alpha; convert to RGB for JPEG
                filepath = filepath.replace(".png", ".jpg")
                filename = filename.replace(".png", ".jpg")
                img.save(filepath, "JPEG", quality=95)
                logger.debug(f"Image 1 converted and saved as JPEG to: {filepath}")
            else:
                img.save(filepath, "PNG")
                logger.debug(f"Image 1 saved as PNG to: {filepath}")
        except Exception as e:
            logger.error(f"Image 1: Failed to process with PIL: {str(e)}")
            raise ValueError(f"Failed to process image with PIL: {str(e)}")

        # Alternative: Save using API's save method
        try:
            api_save_filename = f"api_save_{filename}"
            api_save_filepath = os.path.join(IMAGE_DIR, api_save_filename)
            image_obj.save(api_save_filepath)
            logger.debug(f"Image 1 saved via API to: {api_save_filepath}")
        except Exception as e:
            logger.warning(f"Image 1: Failed to save via API save method: {str(e)}")

        image_url = f"/images/{filename}"
        logger.debug(f"Image URL: {image_url}")
        return {"image_url": image_url}

    except Exception as e:
        logger.error(f"Image generation error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate image: {str(e)}")