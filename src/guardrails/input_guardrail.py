from src.guardrails.validators.empty_query import EmptyQueryValidator
from src.guardrails.validators.length import LengthValidator
from src.guardrails.validators.prompt_injection import (
    PromptInjectionValidator,
)
from src.guardrails.validators.character import (
    CharacterValidator,
)
from src.guardrails.validators.sensitive_info import (
    SensitiveInfoValidator,
)
from src.guardrails.validators.toxicity import (
    ToxicityValidator,
)
from src.guardrails.validators.normalizer import (
    QueryNormalizer,
)


class InputGuardrail:
    """
    Executes all input validation rules.
    """

    def __init__(self):

        self.validators = [

            EmptyQueryValidator(),

            LengthValidator(),

            CharacterValidator(),

            PromptInjectionValidator(),

            SensitiveInfoValidator(),

            ToxicityValidator(),

            QueryNormalizer(),

        ]

    def validate(self, state):

        state.setdefault("is_valid", True)
        state.setdefault("guardrail_reason", None)

        for validator in self.validators:

            state = validator.validate(state)

            if not state["is_valid"]:

                break

        return state