# Support chatbot: data (datasheet)

- **Model:** a third-party LLM with a system prompt written by Helios Bank's digital team; no
  fine-tuning. The FAQ answers come from the bank's public help pages (2026 edition).
- **Conversation logs:** 210,000 conversations, April-October 2026, 64% in Greek. Logs are kept 90
  days and are not used for training.
- **Evaluation set:** 120 hand-written test questions covering the FAQ intents; no adversarial or
  identity questions ("are you a bot?") were included.
- **Known biases:** none identified.
- No real customer data is included in this folder.
