"""Shared OpenAI-compatible client pointed at the IBM ICA gateway."""
import os

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ICA_BASE_URL = os.environ["ICA_BASE_URL"]   # e.g. https://api.nextgen-beta.ica.ibm.com/ica/v1/chat-models
ICA_API_KEY  = os.environ["ICA_API_KEY"]
ICA_MODEL    = os.environ.get("ICA_MODEL", "claude-sonnet-4-5")

# The ICA chat endpoint is  <ICA_BASE_URL>/chat/completions
# OpenAI SDK appends  /chat/completions  automatically when base_url ends without it,
# but ICA's path is  /ica/v1/chat-models/chat/completions, so we pass the prefix directly.
client = OpenAI(
    api_key=ICA_API_KEY,
    base_url=ICA_BASE_URL,   # SDK will POST to  {base_url}/chat/completions
)
