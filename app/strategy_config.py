from dataclasses import dataclass


@dataclass(frozen=True)
class StructureConfig:
    lookback_bars: int = 30
    confirmation_bars: int = 8
    minimum_history_bars: int = 40
    near_low_ratio: float = 1.03
    near_high_ratio: float = 0.97
    minimum_volume_ratio: float = 0.65
    structure_expiry_days: int = 14
    script_version: str = "macd-structure-v1"


STRUCTURE_CONFIG = StructureConfig()
