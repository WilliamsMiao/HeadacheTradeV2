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


@dataclass(frozen=True)
class EntryTriggerConfig:
    breakout_lookback_bars: int = 8
    histogram_improvement_bars: int = 3
    minimum_volume_ratio: float = 0.65
    maximum_stop_distance_pct: float = 0.08
    maximum_stop_distance_atr: float = 4.0
    script_version: str = "macd-15m-trigger-v1"


@dataclass(frozen=True)
class CorrectionConfig:
    signal_expiry_bars: int = 4
    trigger_failure_bars: int = 5
    maximum_entry_deviation_pct: float = 0.03


STRUCTURE_CONFIG = StructureConfig()
ENTRY_TRIGGER_CONFIG = EntryTriggerConfig()
CORRECTION_CONFIG = CorrectionConfig()
