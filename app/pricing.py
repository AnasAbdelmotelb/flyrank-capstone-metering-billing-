PRICING_VERSION = 'v1'
API_CALL_MICROUSD = 1000
INPUT_TOKEN_MICROUSD = 2
CACHED_TOKEN_MICROUSD = 1
OUTPUT_TOKEN_MICROUSD = 8


def calculate_cost(usage):
    return (
        API_CALL_MICROUSD
        + (usage.input_tokens - usage.cached_input_tokens) * INPUT_TOKEN_MICROUSD
        + usage.cached_input_tokens * CACHED_TOKEN_MICROUSD
        + usage.output_tokens * OUTPUT_TOKEN_MICROUSD
    )
