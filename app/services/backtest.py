from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, ReviewStat, StructureEvent, TradeSignal
from app.services.pipeline import run_pipeline


def run_backtest(session: Session, settings: Settings) -> dict[str, float]:
    result = run_pipeline(session, settings)
    signals = list(session.scalars(select(TradeSignal)))
    positions = list(session.scalars(select(Position)))
    structures = list(session.scalars(select(StructureEvent)))
    wins = [position for position in positions if position.current_r > 0]
    losses = [position for position in positions if position.current_r <= 0]
    stats = {
        "signal_count": float(len(signals)),
        "position_count": float(len(positions)),
        "structure_count": float(len(structures)),
        "win_rate": len(wins) / len(positions) if positions else 0.0,
        "avg_r": sum(position.current_r for position in positions) / len(positions) if positions else 0.0,
        "loss_count": float(len(losses)),
    }
    for metric, value in stats.items():
        session.add(ReviewStat(subject_type="SYSTEM", subject_id=0, metric=metric, value=value))
    session.commit()
    stats["pipeline_states"] = float(result["states"])
    return stats

