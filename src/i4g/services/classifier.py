"""
Fraud Classification Service.

This module implements the FraudClassifier service which uses an LLM to classify
fraud attempts based on the official taxonomy and few-shot examples.
"""

import json
import yaml
import logging
import requests
from typing import Protocol, Any

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
except ImportError:
    vertexai = None
    GenerativeModel = None

from i4g.settings import PROJECT_ROOT
from i4g.taxonomy.models import FraudClassificationResult, ScoredLabel
from i4g.classification.rules import detect_signals


LOGGER = logging.getLogger(__name__)


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
        payload = {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}
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
            response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
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

    def __init__(self, llm_client: LLMClient | None = None):
        """Initialize the classifier with resources and LLM client.

        Args:
            llm_client: Optional LLM client implementation. If None, selects based on settings.
        """
        if llm_client:
            self.llm_client = llm_client
        else:
            from i4g.llm.client import build_llm_client

            self.llm_client = build_llm_client()

        self.definitions_path = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "definitions.yaml"
        self.examples_path = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "golden_examples.json"
        self.prompt_template_path = PROJECT_ROOT / "src" / "i4g" / "llm" / "prompts" / "fraud_classifier.md"

        self._load_resources()

    def _load_resources(self) -> None:
        """Load taxonomy definitions, examples, and prompt template."""
        if not self.definitions_path.exists():
            raise FileNotFoundError(f"Taxonomy definitions not found at {self.definitions_path}")

        with open(self.definitions_path) as f:
            self.definitions = yaml.safe_load(f)

        # Build risk weight map keyed by taxonomy code (e.g. INTENT.IMPOSTER)
        self.risk_weights: dict[str, float] = {}
        for category in ["intents", "techniques", "actions"]:
            if category in self.definitions:
                for item in self.definitions[category]:
                    code = item.get("code")
                    weight = item.get("risk_weight", 0)
                    if code:
                        self.risk_weights[code] = weight

        if not self.examples_path.exists():
            raise FileNotFoundError(f"Golden examples not found at {self.examples_path}")

        with open(self.examples_path) as f:
            self.examples = json.load(f)

        if not self.prompt_template_path.exists():
            raise FileNotFoundError(f"Prompt template not found at {self.prompt_template_path}")

        with open(self.prompt_template_path) as f:
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

        # Sanitize user input to avoid breaking the prompt structure
        safe_input = user_input.replace('"""', '\\"\\"\\"')

        prompt = self.prompt_template.replace("{{ taxonomy_definitions }}", definitions_str)
        prompt = prompt.replace("{{ few_shot_examples }}", examples_str)
        prompt = prompt.replace("{{ user_input }}", safe_input)

        return prompt

    def _construct_batch_prompt(self, texts: list[str]) -> str:
        """Construct the prompt for batch classification."""
        # Format definitions as YAML string
        definitions_str = yaml.dump(self.definitions, sort_keys=False)

        # Format examples as JSON string
        examples_str = json.dumps(self.examples, indent=2)

        prompt = self.prompt_template.replace("{{ taxonomy_definitions }}", definitions_str)
        prompt = prompt.replace("{{ few_shot_examples }}", examples_str)

        # Inject batch instructions and data
        batch_input_json = json.dumps(texts, indent=2)
        batch_instructions = (
            "**BATCH MODE:**\n"
            "The input below is a JSON list of strings.\n"
            "You MUST return a JSON list of classification objects.\n"
            "You MUST return exactly one object for each input string.\n"
            "The order of the output list MUST match the order of the input list.\n"
            "If a text cannot be classified, return an empty object {} for that item.\n\n"
            "**Input Batch:**\n"
            f"{batch_input_json}"
        )
        # Using a marker or flexible replacement would be cleaner, but for now we replace the single-item section
        # We replace the entire Task section effectively
        prompt = prompt.replace('**Input Text:**\n"""\n{{ user_input }}\n"""', batch_instructions)

        if "{{ user_input }}" in prompt:
            LOGGER.error("Batch prompt replacement failed! '{{ user_input }}' placeholder still present.")
            # This means the template format does not match the replacement string exact characters.
            # We attempt a more aggressive replacement as fallback.
            snippet_start = prompt.find("**Input Text:**")
            if snippet_start != -1:
                # Replace everything from Input Text to end of potential block
                # This is risky without regex, but we can try to at least inject instructions.
                pass

            # For now, raising error is better than sending broken prompt
            raise ValueError("Batch prompt construction failed: Template mismatch.")

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

    def classify_batch(self, texts: list[str]) -> list[FraudClassificationResult | None]:
        """Classify a batch of texts using the LLM.

        Args:
            texts: List of strings to classify.

        Returns:
            List of results matching the input order. None means classification failed for that item.
        """
        if not texts:
            return []

        # 1. Run deterministic rules (local calculation, fast)
        signals_list = [detect_signals(text) for text in texts]

        # 2. Run LLM classification (batched)
        prompt = self._construct_batch_prompt(texts)

        max_retries = 3
        results: list[FraudClassificationResult | None] = [None] * len(texts)
        raw_list = []

        for attempt in range(max_retries):
            try:
                response_text = self.llm_client.generate(prompt)
                raw_list = self._parse_batch_response(response_text)

                if len(raw_list) != len(texts):
                    raise ValueError(f"Batch size mismatch: expected {len(texts)}, got {len(raw_list)}")

                # Convert dicts to Pydantic models
                for i, item_dict in enumerate(raw_list):
                    # If item_dict is empty (e.g. {}), it means "No classification / Unknown"
                    # We should NOT treat this as an error (None), but as a valid empty result.
                    if not item_dict:
                        # Defaults to empty lists for all fields
                        try:
                            results[i] = FraudClassificationResult()
                        except Exception as e:
                            LOGGER.warning(f"Failed to create empty result for item {i}: {e}")
                            results[i] = None
                    else:
                        try:
                            results[i] = FraudClassificationResult(**item_dict)
                        except Exception as e:
                            LOGGER.warning(f"Failed to parse item {i} in batch: {e}. Dict: {item_dict}")
                            results[i] = None
                break

            except (json.JSONDecodeError, ValueError) as e:
                LOGGER.warning(f"Batch classification attempt {attempt+1} failed: {e}")
                if attempt == max_retries - 1:
                    LOGGER.error(
                        f"Batch classification failed all retries. Falling back to serial classification. Error: {e}"
                    )
                    return self._classify_serial_fallback(texts)
                continue

        # 3. Merge signals and calculate scores
        final_results = []
        for i, res in enumerate(results):
            if res:
                self._merge_signals(res, signals_list[i])
                res.risk_score = self._calculate_risk_score(res)
                final_results.append(res)
            else:
                final_results.append(None)

        return final_results

    def _classify_serial_fallback(self, texts: list[str]) -> list[FraudClassificationResult | None]:
        """Fallback method to classify items one by one if batch fails."""
        results = []
        for i, text in enumerate(texts):
            try:
                # We reuse the single-item classify method which handles signals and scoring
                res = self.classify(text)
                results.append(res)
            except Exception as e:
                LOGGER.warning(f"Serial fallback failed for item {i}: {e}")
                results.append(None)
        return results

    def _merge_signals(self, result: FraudClassificationResult, signals: dict[str, list[ScoredLabel]]) -> None:
        """Merge deterministic signals into the classification result."""

        # Helper to merge a list of signals into a list of existing labels
        def merge_list(existing_labels: list[ScoredLabel], new_signals: list[ScoredLabel]):
            existing_map = {item.label: item for item in existing_labels}

            for signal in new_signals:
                if signal.label in existing_map:
                    # Boost confidence to 1.0 if it exists
                    existing_map[signal.label].confidence = 1.0
                    # Append explanation
                    if signal.explanation:
                        current_expl = existing_map[signal.label].explanation or ""
                        existing_map[signal.label].explanation = (
                            f"{current_expl} [Signal: {signal.explanation}]".strip()
                        )
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
            data = self._clean_and_parse_json(response_text)

            # Handle case where LLM returns a list of results (common with some models)
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                else:
                    raise ValueError(f"LLM returned a list, but it was empty or invalid: {data}")

            if not isinstance(data, dict):
                raise ValueError(f"Expected a dictionary, got {type(data)}")

            return FraudClassificationResult(**data)
        except (json.JSONDecodeError, ValueError) as e:
            # In a real implementation, we would implement retry logic here
            # For now, we raise the error to be handled by the caller
            raise ValueError(f"Failed to parse LLM response: {e}. Response was: {response_text}")

    def _parse_batch_response(self, response_text: str) -> list[dict[str, Any]]:
        """Parse and validate the LLM batch response."""
        data = self._clean_and_parse_json(response_text)

        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list, got {type(data)}")

        return data

    def _clean_and_parse_json(self, response_text: str) -> Any:
        """Common JSON cleanup logic."""
        cleaned_response = response_text.strip()

        # Try to find JSON block if wrapped in markdown
        if "```json" in cleaned_response:
            start = cleaned_response.find("```json") + 7
            end = cleaned_response.find("```", start)
            if end != -1:
                cleaned_response = cleaned_response[start:end]
        elif "```" in cleaned_response:
            # Basic markdown block without language tag
            start = cleaned_response.find("```") + 3
            end = cleaned_response.find("```", start)
            if end != -1:
                cleaned_response = cleaned_response[start:end]

        cleaned_response = cleaned_response.strip()

        # Heuristic: if it doesn't start with { or [, try to find them
        if not (cleaned_response.startswith("{") or cleaned_response.startswith("[")):
            start_brace = cleaned_response.find("{")
            start_bracket = cleaned_response.find("[")

            start = -1
            if start_brace != -1 and start_bracket != -1:
                start = min(start_brace, start_bracket)
            elif start_brace != -1:
                start = start_brace
            elif start_bracket != -1:
                start = start_bracket

            if start != -1:
                cleaned_response = cleaned_response[start:]

        # Heuristic: strip trailing non-json chars
        if cleaned_response:
            last_brace = cleaned_response.rfind("}")
            last_bracket = cleaned_response.rfind("]")

            end = -1
            if last_brace != -1 and last_bracket != -1:
                end = max(last_brace, last_bracket)
            elif last_brace != -1:
                end = last_brace
            elif last_bracket != -1:
                end = last_bracket

            if end != -1:
                cleaned_response = cleaned_response[: end + 1]

        return json.loads(cleaned_response)
