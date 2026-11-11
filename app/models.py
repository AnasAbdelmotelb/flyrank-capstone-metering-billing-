from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    input_tokens: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    cached_input_tokens: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    output_tokens: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    reasoning_tokens: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)

    @model_validator(mode='after')
    def subsets(self):
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError('cached_input_tokens must be a subset of input_tokens')
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError('reasoning_tokens must be a subset of output_tokens')
        return self
