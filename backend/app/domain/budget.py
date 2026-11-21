"""Conservative request reservation; no provider credentials or database imports."""
import json
from decimal import Decimal as D, ROUND_CEILING


def reserve_cost(messages: list, input_rate: D, output_rate: D, max_output=2048) -> D:
    if any(not rate.is_finite() or rate <= 0 for rate in (input_rate,output_rate)):
        raise ValueError('尚未配置已核对的人民币最高档计费价格，拒绝付费调用')
    # UTF-8 byte count is a conservative token bound, with a fixed envelope
    # allowance. No tools, images, thinking or unbounded output are enabled.
    upper_input = len(json.dumps(messages,ensure_ascii=False).encode())+2048
    return ((D(upper_input)*input_rate+D(max_output)*output_rate)/D(1000000)).quantize(D('.00000001'),rounding=ROUND_CEILING)
