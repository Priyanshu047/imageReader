import easyocr
import cv2
import numpy as np
import pytesseract
from PIL import Image
import re
from transformers import pipeline
import pandas as pd
import os
import requests
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

class OCRParameterModel:
    def __init__(self):
        self.easyocr_reader = easyocr.Reader(['en'])
        self.spell = pipeline("text2text-generation", model="oliverguhr/spelling-correction-english-base")
        self.configs = ['--psm 6', '--psm 11', '--psm 3']
        self.parameter_patterns = {
            'voltage': r'(\d+(?:\.\d+)?)\s*(?:v|volt|kV|mV)(?:s)?\b',
            'weight': r'(\d+(?:\.\d+)?)\s*(g|kg|lbs?|oz|mg)\b',
            'height': r'(\d+(?:\.\d+)?)\s*(cm|m|inch|ft|mm)\b',
            'volume': r'(\d+(?:\.\d+)?)\s*(ml|l|fl\s?oz|gal)\b',
            'wattage': r'(\d+(?:\.\d+)?)\s*(w|watt|mw)(?:s)?\b',
            'depth': r'(?:depth|d):\s*(\d+(?:\.\d+)?)\s*(cm|m|inch|ft|mm)\b',
            'width': r'(?:width|w):\s*(\d+(?:\.\d+)?)\s*(cm|m|inch|ft|mm)\b',
            'max_weight': r'(?:max(?:imum)?\s*weight|weight\s*capacity):\s*(\d+(?:\.\d+)?)\s*(kg|lbs?)\b'
        }

    def load_image(self, image_path):
        return cv2.imread(image_path)

    def preprocess_image(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def detect_text(self, image):
        easyocr_results = self.easyocr_reader.readtext(image)
        tesseract_results = pytesseract.image_to_string(image)
        return easyocr_results + [(None, text, None) for text in tesseract_results.split('\n') if text.strip()]

    def extract_parameter(self, text, parameter_type):
        pattern = self.parameter_patterns.get(parameter_type.lower())
        if not pattern:
            return None
        match = re.search(pattern, text.lower())
        if match:
            value, unit = match.groups() if len(match.groups()) == 2 else (match.group(1), "")
            return f"{value} {unit}".strip()
        return None

    def detect_parameters(self, text_results, params_to_find):
        parameters = {}
        for (_, text, _) in text_results:
            for param_type in params_to_find:
                result = self.extract_parameter(text, param_type)
                if result:
                    parameters[param_type] = result
        return parameters

    def predict(self, image_path, params_to_find):
        image = self.load_image(image_path)
        if image is None:
            return None
        preprocessed = self.preprocess_image(image)
        text_results = self.detect_text(preprocessed)
        return self.detect_parameters(text_results, params_to_find)

def download_image(image_url, save_dir):
    try:
        image_name = os.path.join(save_dir, os.path.basename(image_url))
        response = requests.get(image_url, stream=True, timeout=10)
        if response.status_code == 200:
            with open(image_name, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            return image_name
        else:
            return None
    except Exception as e:
        print(f"Failed to download {image_url}: {e}")
        return None

def process_image(model, image_url, image_dir, entity_name, entity_mapping):
    image_path = download_image(image_url, image_dir)
    if image_path:
        param_type = entity_mapping.get(entity_name, entity_name)
        image_predictions = model.predict(image_path, [param_type])
        if image_predictions:
            return list(image_predictions.values())[0]
    return 'No result'

def process_chunk(chunk, model, image_dir, entity_mapping):
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for _, row in chunk.iterrows():
            future = executor.submit(process_image, model, row['image_link'], image_dir, row['entity_name'], entity_mapping)
            futures.append(future)
        
        results = []
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing images"):
            results.append(future.result())
    
    chunk['predictions'] = results
    return chunk

def main():
    entity_mapping = {
        'item_weight': 'weight',
        'item_volume': 'volume',
        'max_weight_recommendation': 'max_weight',
        'height': 'height',
        'width': 'width',
        'voltage': 'voltage',
        'wattage': 'wattage',
        'depth': 'depth',
    }

    file_path = '/content/test.csv'
    image_dir = '/content/images/'
    os.makedirs(image_dir, exist_ok=True)
    chunk_size = 1000
    output_file = '/content/extracted_predictions.csv'

    model = OCRParameterModel()

    all_predictions = []

    for chunk in pd.read_csv(file_path, chunksize=chunk_size):
        processed_chunk = process_chunk(chunk, model, image_dir, entity_mapping)
        all_predictions.extend(processed_chunk['predictions'])

    # Save results to a CSV file
    result_df = pd.DataFrame({'predictions': all_predictions})
    result_df.to_csv(output_file, index=False)
    print(f"Data saved to {output_file}")

if __name__ == "__main__":
    main()
