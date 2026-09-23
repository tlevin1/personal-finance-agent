from pathlib import Path

CATEGORIES = [
    "Food",
    "Transportation",
    "Shopping",
    "Entertainment",
    "Healthcare",
    # "Home" comes from expenses.csv's own labels (hardware, furnishings);
    # "Housing" is for rent/mortgage, which otherwise lands in "Transfer"
    # because the payment rail (Zelle) is all the description reveals.
    "Home",
    "Housing",
    "Health",
    "Insurance",
    "Utilities",
    "Income",
    "Transfer",
    "Uncategorized",
]

# Assigned only by deterministic ingest logic (never offered to the LLM as a
# choice) for transfers between the person's own accounts, so it can never be
# confused with money that actually left their control.
INTERNAL_TRANSFER_CATEGORY = "Internal Transfer"

MAX_AGENT_STEPS = 8
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_RECORDING_PATH = Path("llm_recordings/run.json")
