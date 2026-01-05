"""
Fraud Classification Service.

This module implements the FraudClassifier service which uses an LLM to classify
fraud attempts based on the official taxonomy and few-shot examples.
"""

import json
import yaml
import requests
from pathlib import Path
from typing import Optional, Protocol

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
except ImportError:
    vertexai = None
    GenerativeModel = None

from i4g.settings import PROJECT_ROOT, get_settings
from i4g.taxonomy.models import FraudClassificationResult, ScoredLabel
from i4g.classification.rules import detect_signals
from typing import Dict, List


class LLMClient(Protocol):
    """Protocol for LLM interactions."""
    def generate(self, prompt: str) -> str:
        """Generate text from a prompt."""
        ...


class OllamaClient:
    """Client for Ollama local LLM."""
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
        except requests.RequestException as e:
            raise ValueError(f"Ollama request failed: {e}")


class VertexAIClient:
    """Client for Google Vertex AI."""
    def __init__(self, project: str, location: str, model_name: str):
        if not vertexai:
            raise ImportError("vertexai module is not installed.")
        vertexai.init(project=project, location=location)
        self.model = GenerativeModel(model_name)

    def generate(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return response.text
        except Exception as e:
            raise ValueError(f"Vertex AI request failed: {e}")


class MockLLMClient:
    """Mock implementation for testing and development."""
    def generate(self, prompt: str) -> str:
        """Return a dummy valid JSON response."""
        return """
        {
          "intent": [
            {
              "label": "INTENT.IMPOSTER",
              "confidence": 0.95,
              "explanation": "Mock classification for testing."
            }
          ],
          "channel": [
            {
              "label": "CHANNEL.SMS",
              "confidence": 0.9,
              "explanation": "Mock classification for testing."
            }
          ],
          "techniques": [
            {
              "label": "SE.URGENCY",
              "confidence": 0.85,
              "explanation": "Mock classification for testing."
            }
          ],
          "actions": [
            {
              "label": "ACTION.CLICK_LINK",
              "confidence": 0.9,
              "explanation": "Mock classification for testing."
            }
          ],
          "persona": [
            {
              "label": "PERSONA.BANK",
              "confidence": 0.95,
              "explanation": "Mock classification for testing."
            }
          ],
          "taxonomy_version": "1.0"
        }
        """


class FraudClassifier:
    """Service for classifying fraud attempts using LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Initialize the classifier with resources and LLM client.
        
        Args:
            llm_client: Optional LLM client implementation. If None, selects based on settings.
        """
        if llm_client:
            self.llm_client = llm_client
        else:
            settings = get_settings()
            provider = settings.llm.provider
            
            if provider == "ollama":
                self.llm_client = OllamaClient(
                    base_url=settings.llm.ollama_base_url,
                    model=settings.llm.chat_model
                )
            elif provider == "vertex_ai":
                if not settings.llm.vertex_ai_project:
                    raise ValueError("Vertex AI project not configured.")
                
                # Prefer generic chat_model, fallback to legacy vertex_ai_model
                model_name = settings.llm.chat_model
                if model_name == "llama3" and settings.llm.vertex_ai_model:
                    # If chat_model is default but vertex_ai_model is set, use legacy
                    model_name = settings.llm.vertex_ai_model
                
                self.llm_client = VertexAIClient(
                    project=settings.llm.vertex_ai_project,
                    location=settings.llm.vertex_ai_location or "us-central1",
                    model_name=model_name
                )
            else:
                self.llm_client = MockLLMClient()

        self.definitions_path = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "definitions.yaml"
        self.examples_path = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "golden_examples.json"
        self.prompt_template_path = PROJECT_ROOT / "src" / "i4g" / "llm" / "prompts" / "fraud_classifier.md"
        
        self._load_resources()

    def _load_resources(self) -> None:
        """Load taxonomy definitions, examples, and prompt template."""
        if not self.definitions_path.exists():
            raise FileNotFoundError(f"Taxonomy definitions not found at {self.definitions_path}")
        
        with open(self.definitions_path, "r") as f:
            self.definitions = yaml.safe_load(f)
            
        # Build risk weight map
        self.risk_weights = {}
        for category in ["intents", "techniques", "actions"]:
            if category in self.definitions:
                for item in self.definitions[category]:
                    label = item.get("label")
                    weight = item.get("risk_weight", 0)
                    if label:
                        self.risk_weights[label] = weight

        if not self.examples_path.exists():
            raise FileNotFoundError(f"Golden examples not found at {self.examples_path}")

        with open(self.examples_path, "r") as f:
            self.examples = json.load(f)
            
        if not self.prompt_template_path.exists():
            raise FileNotFoundError(f"Prompt template not found at {self.prompt_template_path}")

        with open(self.prompt_template_path, "r") as f:
            self.prompt_template = f.read()

    def _calculate_risk_score(self, result: FraudClassificationResult) -> float:
        """Calculate risk score based on detected labels and their weights.
        
        Formula: Sum(label_confidence * label_risk_weight)
        Capped at 100.0.
        """
        total_score = 0.0
        
        # Collect all scored labels from relevant categories
        all_labels = []
        all_labels.extend(result.intent)
        all_labels.extend(result.techniques)
        all_labels.extend(result.actions)
        
        for item in all_labels:
            weight = self.risk_weights.get(item.label, 0)
            total_score += item.confidence * weight
            
        # Heuristic scaling: 
        # If we have a high-risk intent (weight 8-10) with high confidence (0.9), score is ~7-9.
        # If we have multiple techniques/actions, score adds up.
        # Example: Extortion (10 * 0.9 = 9) + Fear (9 * 0.8 = 7.2) + Send Money (9 * 0.9 = 8.1) = 24.3
        # This raw sum is low for a 0-100 scale.
        # Let's apply a multiplier to map it to 0-100.
        # A "max" case might be ~30-40 raw points.
        # Let's multiply by 2.5 to scale it up, then cap at 100.
        
        scaled_score = total_score * 2.5
        return min(100.0, round(scaled_score, 1))


    def _construct_prompt(self, user_input: str) -> str:
        """Construct the prompt by injecting resources and user input."""
        # Format definitions as YAML string
        definitions_str = yaml.dump(self.definitions, sort_keys=False)
        
        # Format examples as JSON string
        examples_str = json.dumps(self.examples, indent=2)
        
        prompt = self.prompt_template.replace("{{ taxonomy_definitions }}", definitions_str)
        prompt = prompt.replace("{{ few_shot_examples }}", examples_str)
        prompt = prompt.replace("{{ user_input }}", user_input)
        
        return prompt

    def classify(self, text: str) -> FraudClassificationResult:
        """Classify the input text using the LLM.
        
        Args:
            text: The fraud attempt text to classify.
            
        Returns:
            FraudClassificationResult: The structured classification result.
            
        Raises:
            ValueError: If the LLM response cannot be parsed or validated after retries.
        """
        # 1. Run deterministic rules
        signals = detect_signals(text)

        # 2. Run LLM classification
        prompt = self._construct_prompt(text)
        
        max_retries = 3
        last_error = None
        result = None
        
        for attempt in range(max_retries):
            try:
                response_text = self.llm_client.generate(prompt)
                result = self._parse_response(response_text)
                break
            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                # In a real scenario, we might append the error to the prompt for the next attempt
                continue
        
        if result is None:
            raise ValueError(f"Failed to classify text after {max_retries} attempts. Last error: {last_error}")

        # 3. Merge signals into result
        self._merge_signals(result, signals)

        # 4. Recalculate risk score
        result.risk_score = self._calculate_risk_score(result)
        return result

    def _merge_signals(self, result: FraudClassificationResult, signals: Dict[str, List[ScoredLabel]]) -> None:
        """Merge deterministic signals into the classification result."""
        # Helper to merge a list of signals into a list of existing labels
        def merge_list(existing_labels: List[ScoredLabel], new_signals: List[ScoredLabel]):
            existing_map = {item.label: item for item in existing_labels}
            
            for signal in new_signals:
                if signal.label in existing_map:
                    # Boost confidence to 1.0 if it exists
                    existing_map[signal.label].confidence = 1.0
                    # Append explanation
                    if signal.explanation:
                        current_expl = existing_map[signal.label].explanation or ""
                        existing_map[signal.label].explanation = f"{current_expl} [Signal: {signal.explanation}]".strip()
                else:
                    # Add new label
                    existing_labels.append(signal)

        if "actions" in signals:
            merge_list(result.actions, signals["actions"])
        
        if "channel" in signals:
            merge_list(result.channel, signals["channel"])

    def _parse_response(self, response_text: str) -> FraudClassificationResult:
        """Parse and validate the LLM response."""
        try:
            # Basic cleanup of markdown code blocks if present
            cleaned_response = response_text.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            elif cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            
            cleaned_response = cleaned_response.strip()
                
            data = json.loads(cleaned_response)

            # Handle case where LLM returns a list of results (common with some models)
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                else:
                    raise ValueError(f"LLM returned a list, but it was empty or invalid: {data}")

            if not isinstance(data, dict):
                raise ValueError(f"Expected a dictionary or list of dictionaries, got {type(data)}")

            return FraudClassificationResult(**data)
        except (json.JSONDecodeError, ValueError) as e:
            # In a real implementation, we would implement retry logic here
            # For now, we raise the error to be handled by the caller
            raise ValueError(f"Failed to parse LLM response: {e}. Response was: {response_text}")
