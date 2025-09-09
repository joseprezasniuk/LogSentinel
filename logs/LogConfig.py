from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

import os

load_dotenv()

@dataclass 
class LogConfig:
    error_webhook: Optional[str] = None
    info_webhook: Optional[str] = None

    max_queue_size: int = 2000
    batch_interval: float = 5.0 
    max_retries: int = 3

    max_requests_per_window: int = 50
    rate_limit_window: int = 60
    emergency_cooldown: float = 300.0

    dedup_window: float = 30.0
    max_message_length: int = 1500

    def __post_init__(self):
        self.error_webhook = os.getenv("ERROR_HOOK", self.error_webhook)
        self.info_webhook = os.getenv("INFO_HOOK", self.info_webhook)


        self.max_queue_size = int(os.getenv("MAX_QUEUE_SIZE", self.max_queue_size))
        self.max_retries = int(os.getenv("MAX_RETRIES", self.max_retries))
        self.batch_interval = float(os.getenv("BATCH_INTERVAL", self.batch_interval))

        #:Carrega novas configurações do ambiente
        self.rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW", self.rate_limit_window))
        self.emergency_cooldown = float(os.getenv("EMERGENCY_COOLDOWN", self.emergency_cooldown))
        self.dedup_window = float(os.getenv("DEDUP_WINDOW", self.dedup_window))
