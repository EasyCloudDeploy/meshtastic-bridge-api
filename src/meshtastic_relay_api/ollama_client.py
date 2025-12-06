"""Ollama client for message summarization."""

import logging
from typing import Optional

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for interacting with Ollama API."""

    def __init__(self, settings: Settings):
        """
        Initialize Ollama client.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.base_url = settings.ollama_server.rstrip("/") if settings.ollama_server else None
        self.model = settings.ollama_model or "llama3.2"
        self.timeout = settings.ollama_timeout
        self.enabled = self.base_url is not None

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """
        Test connection to Ollama server and verify model is available.

        Returns:
            Tuple of (is_available, error_message)
        """
        if not self.enabled:
            return False, "Ollama server URL not configured"

        try:
            # Test if Ollama server is reachable and check if model is available
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                models_data = response.json()
                available_models = [model.get("name", "") for model in models_data.get("models", [])]

                # Check if the specified model exists
                if self.model not in available_models:
                    model_list = ", ".join(available_models[:5])
                    if len(available_models) > 5:
                        model_list += f" (and {len(available_models) - 5} more)"
                    return False, f"Model '{self.model}' not found. Available models: {model_list}"

            return True, None

        except httpx.TimeoutException:
            return False, f"Timeout connecting to Ollama server at {self.base_url}"
        except httpx.ConnectError:
            return False, f"Cannot connect to Ollama server at {self.base_url}"
        except httpx.HTTPStatusError as e:
            return False, f"Ollama server returned error: {e.response.status_code}"
        except Exception as e:
            return False, f"Error testing Ollama connection: {str(e)}"

    def summarize(self, text: str) -> Optional[str]:
        """
        Summarize text using Ollama.

        Args:
            text: Text to summarize

        Returns:
            Summarized text, or None if summarization fails
        """
        if not self.enabled:
            logger.warning("Ollama is not enabled, cannot summarize")
            return None

        if not text or len(text.strip()) < 200:
            # Don't summarize if text is too short
            return None

        try:
            prompt = f"""Please provide a concise summary of the following message. 
Keep it under 200 characters and preserve the most important information:

{text}

Summary:"""

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "max_tokens": 150,
                        },
                    },
                )
                response.raise_for_status()
                result = response.json()
                summary = result.get("response", "").strip()

                if summary:
                    # Ensure summary doesn't exceed max message length
                    if len(summary) > self.settings.max_message_length:
                        summary = summary[: self.settings.max_message_length - 3] + "..."
                    logger.info(f"Summarized message from {len(text)} to {len(summary)} characters")
                    return summary
                else:
                    logger.warning("Ollama returned empty summary")
                    return None

        except httpx.TimeoutException:
            logger.error(f"Timeout while summarizing with Ollama (model: {self.model})")
            return None
        except httpx.ConnectError:
            logger.error(f"Cannot connect to Ollama server at {self.base_url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama server returned error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error summarizing with Ollama: {e}", exc_info=True)
            return None

