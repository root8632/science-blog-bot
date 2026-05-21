import os
import sys
import logging
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ModelChecker")

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY environment variable is not set. Please set it before running this script.")
        sys.exit(1)
        
    logger.info("Initializing GenAI Client...")
    client = genai.Client(api_key=api_key)
    
    logger.info("=" * 60)
    logger.info("LISTING ALL AVAILABLE MODELS FOR YOUR API KEY:")
    logger.info("=" * 60)
    
    available_models = []
    try:
        models = client.models.list()
        for m in models:
            logger.info(f"- Model Name: '{m.name}' (Supported Actions: {m.supported_actions})")
            available_models.append(m.name)
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        
    logger.info("\n" + "=" * 60)
    logger.info("TESTING IMAGE GENERATION WITH AVAILABLE MODELS:")
    logger.info("=" * 60)
    
    test_prompt = "A simple red apple on a clean white background, minimalist style"
    
    # Common Imagen model candidates to test
    candidates = [
        "imagen-3.0-generate-002",
        "imagen-3.0-generate-001",
        "imagen-2.0-generate-002",
    ]
    
    # Add any models from list that contain 'imagen'
    for name in available_models:
        clean_name = name.replace("models/", "")
        if "imagen" in clean_name and clean_name not in candidates:
            candidates.append(clean_name)
            
    success_models = []
    
    for model_name in candidates:
        logger.info(f"Testing model: '{model_name}'...")
        try:
            result = client.models.generate_images(
                model=model_name,
                prompt=test_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="1:1"
                )
            )
            if result.generated_images:
                logger.info(f"🎉 SUCCESS! Model '{model_name}' successfully generated image!")
                success_models.append(model_name)
            else:
                logger.warning(f"⚠️ Model '{model_name}' returned empty images.")
        except Exception as e:
            logger.error(f"❌ Model '{model_name}' failed. Error: {e}\n")
            
    logger.info("=" * 60)
    logger.info("DIAGNOSTIC SUMMARY:")
    logger.info("=" * 60)
    if success_models:
        logger.info(f"Successfully verified working image models: {success_models}")
        logger.info("You can use one of these model names in config.py or GEMINI_POST_MODEL environment variable.")
    else:
        logger.error("No image generation models succeeded with your API key.")
        logger.error("If you are on the free tier, please check Google AI Studio to verify if Imagen 3 API is allowed for your account type/region.")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
