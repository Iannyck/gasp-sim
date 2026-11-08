"""Run the toy chatter model and print a short summary (example only, no scientific value).

Run from the root of the repository::

    uv run python -m examples.toy_chatter.run
"""

from examples.toy_chatter.model import ToyChatter, ToyParameters


def main(seed: int = 42, days: int = 5) -> None:
    """Run the toy model for ``days`` working days and print a summary."""
    model = ToyChatter(ToyParameters(), seed=seed)
    model.run_days(days)
    summary = model.summary()
    print("Toy chatter (example model, no scientific value)")
    print(f"  seed: {seed}, agents: {model.parameters.n_agents}, working days: {days}")
    print(f"  ticks: {summary.ticks}, consultations: {summary.consultations}")
    print(f"  messages: {summary.messages}")
    print(f"  mean participation per consultation round: {summary.mean_participation:.3f}")


if __name__ == "__main__":
    main()
